"""Operator-assist console: you play the helpline operator, Lakshmamma calls, the agent fills the care record live.

  ./assist/start.sh            # or: python assist/server.py
  open http://127.0.0.1:8776

Operator mic -> SmallWebRTC -> VAD + smart-turn -> Parakeet (live captions while you talk, then the turn)
  -> the farmer answers over the call: a recorded clip for the question you asked (rules, instant), or, live,
     an LLM on OpenRouter playing Lakshmamma from a case sheet (Kokoro voice, put through the bad-line condition)
  -> the farmer clip's ASR (as the bad line delivered it) and your words both go to the local LLM
  -> one case record: what you repeated counts as confirmed, what only the line heard is flagged.
After the call: QA checks, a full-transcript re-read by Muse, and the differences from the live record.
"""
import asyncio, json, os, re, sys, time, uuid, wave
from pathlib import Path
from contextlib import asynccontextmanager
import numpy as np, aiohttp
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from pipecat.frames.frames import InputAudioRawFrame, TTSAudioRawFrame, InterruptionFrame, StartFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.task import PipelineTask, PipelineParams
from pipecat.pipeline.runner import PipelineRunner
from pipecat.processors.frame_processor import FrameProcessor
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams, VADState
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
from pipecat.audio.turn.smart_turn.base_smart_turn import SmartTurnParams
from pipecat.audio.turn.base_turn_analyzer import EndOfTurnState

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent)); sys.path.insert(0, str(HERE))
import speech as speech_mod, nlu
import assist as assist_mod, farmer as farmer_mod, farmer_ai, degrade, protocol as protocol_mod

ART = Path(os.getenv('VR_ART', '/mnt/seagate/silo/voice-robust')) / 'assist'
STATE = Path(os.getenv('VR_ASSIST_STATE', Path.home() / '.local/share/silo-voice/assist'))
PORT = int(os.getenv('PORT', '8776'))
SR = 16000
GAP_S = float(os.getenv('FARMER_GAP_S', '0.8'))
NUDGE_S = float(os.getenv('FARMER_NUDGE_S', '6'))  # operator silent after a statement: the farmer says "Hello?"  # pause before the farmer answers, like a real person
SCENARIOS = {s['id']: s for s in json.loads((HERE / 'scenarios.json').read_text())}  # recorded clips
PERSONA, CASES = farmer_ai.load()  # Lakshmamma's cases, for the live farmer (and the recorded one where it has clips)
SP = None; SESSIONS = {}; CLIP_ASR = {}

def clip_topic(key):
    k = key.removeprefix('no_').removesuffix('_again')
    return k if k in assist_mod.REQUIRED else None

def load_clips(sid):
    """Each farmer clip, plus what the farmer-side ASR hears in it (computed once: same clip, same text)."""
    if sid in CLIP_ASR: return CLIP_ASR[sid]
    index = json.loads((ART / sid / 'index.json').read_text()); out = {}
    for key, meta in index.items():
        with wave.open(str(ART / sid / meta['file'])) as w: pcm = w.readframes(w.getnframes())
        out[key] = {'pcm': pcm, 'seconds': len(pcm) / 2 / SR, 'text': meta['text'],
                    'heard': SP.transcribe(pcm, clip_topic(key)), 'file': f'/clips/{sid}/{meta["file"]}'}
    CLIP_ASR[sid] = out; return out

class Session(FrameProcessor):
    def __init__(self, rec):
        super().__init__()
        self.rec = rec; self.ai = rec['mode'] == 'ai'; self.assist = assist_mod.Assist(); self.http = aiohttp.ClientSession()
        self.protocol = protocol_mod.Protocol() if protocol_mod.ENABLED else None
        if self.ai:
            self.case = CASES[rec['case']]; self.truth = self.case['truth']; self.farmer = farmer_ai.AIFarmer(PERSONA, self.case); self.n_said = 0
        else:
            self.sc = SCENARIOS[rec['scenario']]; self.truth = self.sc['truth']; self.clips = load_clips(rec['scenario'])
            self.farmer = farmer_mod.ScriptedFarmer(self.sc)
        self.vad = SileroVADAnalyzer(sample_rate=SR, params=VADParams(confidence=.5, start_secs=.15, stop_secs=.3, min_volume=.1))
        self.turn = LocalSmartTurnAnalyzerV3(sample_rate=SR, params=SmartTurnParams(stop_secs=1.2))
        self.vad.set_sample_rate(SR); self.turn.set_sample_rate(SR)
        self.t0 = time.monotonic(); self.buf = bytearray(); self.inbuf = b''; self.pre = []; self.in_speech = False
        self.partial = ''; self.partial_at = 0; self.last_voice = 0; self.started = asyncio.Event()
        self.farmer_until = 0.0; self.farmer_job = None; self.lock = asyncio.Lock(); self.metrics = []; self.ended = False
        self.audio_dir = STATE / rec['id']
        self.carry = ''; self.last_text = ''; self.farmer_scheduled_until = 0.0; self.nudge = None; self.op_chain = None

    def now(self): return round(time.monotonic() - self.t0, 3)
    def farmer_speaking(self): return time.monotonic() < self.farmer_until

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if isinstance(frame, InputAudioRawFrame):
            self.inbuf += frame.audio
            while len(self.inbuf) >= 640:
                f, self.inbuf = self.inbuf[:640], self.inbuf[640:]
                await self.feed(f)
            return
        await self.push_frame(frame, direction)
        if isinstance(frame, StartFrame): self.started.set()

    async def feed(self, f):
        if self.ended: return
        state = await self.vad.analyze_audio(f); speaking = state in (VADState.SPEAKING, VADState.STARTING)
        if state == VADState.SPEAKING and not self.in_speech:
            self.in_speech = True; self.buf = bytearray(b''.join(self.pre)); self.speech_start = time.monotonic()
            # Still talking (a pause between sentences), and the farmer hasn't started: hold the farmer's reply,
            # and let the next fragment decide it together with this one.
            if self.nudge: self.nudge.cancel()
            if self.farmer_job and not self.farmer_job.done() and not self.farmer_speaking() and self.farmer_until == self.farmer_scheduled_until:
                self.farmer_job.cancel(); self.carry = self.last_text; self.farmer.undo()
        if self.in_speech:
            self.buf.extend(f)
            if speaking: self.last_voice = time.monotonic()
            # Talking over the farmer for a moment: the farmer stops, as people do.
            if self.farmer_speaking() and time.monotonic() - self.speech_start > .5:
                await self.push_frame(InterruptionFrame()); self.farmer_until = 0
                if self.assist.transcript and self.assist.transcript[-1]['role'] == 'farmer': self.assist.transcript[-1]['interrupted'] = True
            if time.monotonic() - self.partial_at > .8 and len(self.buf) > SR:  # live caption while the operator talks
                self.partial_at = time.monotonic(); pcm = bytes(self.buf)
                asyncio.create_task(self._partial(pcm))
            eot = self.turn.append_audio(f, speaking)
            if eot != EndOfTurnState.COMPLETE and state == VADState.QUIET: eot, _ = await self.turn.analyze_end_of_turn()
            if eot == EndOfTurnState.COMPLETE or len(self.buf) > SR * 2 * 40:
                self.in_speech = False; pcm = bytes(self.buf); self.buf.clear(); self.turn.clear(); self.pre = []
                if len(pcm) > SR * 2 * .3: asyncio.create_task(self.operator_turn(pcm, self.last_voice))
        self.pre = (self.pre + [f])[-25:]

    async def _partial(self, pcm):
        text = await asyncio.to_thread(SP.transcribe, pcm, self.assist.asking)
        if self.in_speech: self.partial = text

    async def operator_turn(self, pcm, speech_end):
        """ASR and the farmer's reply happen under the lock (fast); the LLM's reading is applied later, in order."""
        async with self.lock:
            m = {'turn': len(self.metrics) + 1, 'speech_end_s': round(speech_end - self.t0, 3)}; self.metrics.append(m)
            t = time.monotonic(); text = await asyncio.to_thread(SP.transcribe, pcm, self.assist.asking)
            m['asr_ms'] = round((time.monotonic() - t) * 1000); self.partial = ''
            if not text: m['dropped'] = 'empty'; return
            m['heard'] = text
            self.audio_dir.mkdir(parents=True, exist_ok=True)
            with wave.open(str(self.audio_dir / f'operator{m["turn"]:02d}.wav'), 'wb') as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes(pcm)
            entry = {'role': 'operator', 'text': text, 't': m['speech_end_s']}; self.assist.transcript.append(entry)
            # Like a person, the farmer answers a question, and waits through statements ("Tumakuru." ... "What number?").
            whole = (self.carry + ' ' + text).strip(); self.last_text = whole
            last = assist_mod.last_sentence(text)
            asking = assist_mod.asked_slot(last) or ('summary' if assist_mod.asked_slot(whole) == 'summary' else None)
            reply = assist_mod.is_question(last) or asking in ('greeting', 'summary') or re.search(r'\b(good ?bye|bye)\b', text, re.I)
            if not assist_mod.is_question(last) and asking not in ('greeting', 'summary'): asking = None
            if self.ai:  # the live farmer hears every turn and decides herself whether to answer
                self.carry = ''; m['asked'] = asking
                if self.nudge: self.nudge.cancel()
                self.farmer_scheduled_until = self.farmer_until
                self.farmer_job = asyncio.create_task(self.ai_says(whole, speech_end, m, asking))
            elif reply:
                key = self.farmer.reply(asking, assist_mod.operator_rules(whole), whole); self.carry = ''
                m['asked'] = asking; m['farmer_clip'] = key
                if key: self.farmer_scheduled_until = self.farmer_until; self.farmer_job = asyncio.create_task(self.farmer_says(key, speech_end, m))
            else:
                self.carry = whole; m['asked'] = None; m['farmer_clip'] = '(waits)'
                if self.nudge: self.nudge.cancel()
                self.nudge = asyncio.create_task(self._nudge())
            last_farmer = next((x['text'] for x in reversed(self.assist.transcript) if x['role'] == 'farmer'), '')
            task = asyncio.create_task(assist_mod.interpret_operator(text, last_farmer))
            self.op_chain = asyncio.create_task(self._apply(task, self.op_chain, text, entry, asking, m))

    async def _apply(self, task, prev, text, entry, asking, m):
        op = await task
        if prev: await asyncio.wait([prev])
        op['asking'] = asking or op.get('asking'); m['op_ms'] = op['ms']; m['op_source'] = op['source']
        self.assist.on_operator(text, op, entry)
        if self.protocol:
            self.protocol.see(text, 'operator')
            last_farmer = next((x['text'] for x in reversed(self.assist.transcript) if x['role'] == 'farmer'), '')
            asyncio.create_task(self.protocol.extract(text, 'operator', last_farmer, self.http))

    async def _nudge(self):
        """The operator said something, then went quiet: after a while the farmer checks the line is alive."""
        await asyncio.sleep(NUDGE_S)
        if self.in_speech or self.farmer_speaking() or self.ended or (self.farmer_job and not self.farmer_job.done()): return
        if self.ai: self.farmer_job = asyncio.create_task(self.ai_says(None, time.monotonic() - GAP_S, {})); return
        key = self.farmer.reply(None, assist_mod.operator_rules(self.carry), self.carry); self.carry = ''
        if key: self.farmer_job = asyncio.create_task(self.farmer_says(key, time.monotonic() - GAP_S, {}))

    def render(self, text, n, asking=None):
        """Lakshmamma's words -> her voice (Kokoro), down the same bad line as the recorded clips -> int16 PCM, and what the line lets ASR hear."""
        import torch, librosa
        with SP.lock: a = torch.cat([r.audio for r in SP.tts(text, voice=PERSONA['voice'], speed=PERSONA['speed'])]).numpy()
        x = librosa.resample(a.astype(np.float32), orig_sr=24000, target_sr=SR)
        x = np.concatenate([np.zeros(1600, np.float32), x, np.zeros(1600, np.float32)])
        x = degrade.CONDITIONS[PERSONA['condition']](x, f'{self.rec["id"]}{n}')
        pcm = (np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes()
        self.audio_dir.mkdir(parents=True, exist_ok=True); name = f'farmer{n:02d}.wav'
        with wave.open(str(self.audio_dir / name), 'wb') as w: w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes(pcm)
        return {'pcm': pcm, 'seconds': len(pcm) / 2 / SR, 'text': text, 'heard': SP.transcribe(pcm, asking or self.assist.asking),
                'file': f'/api/sessions/{self.rec["id"]}/audio/{name}'}

    async def ai_says(self, text, speech_end, m, asking=None):
        r = await self.farmer.reply(text, self.http)
        m['farmer_llm_ms'] = r['ms']; m['farmer_clip'] = r['say'] or '(quiet)'
        if not r['say']:
            if r['hangup']: await self.finish()
            elif text is not None: self.nudge = asyncio.create_task(self._nudge())
            return
        self.n_said += 1
        c = await asyncio.to_thread(self.render, r['say'], self.n_said, asking)
        await self.farmer_says(None, speech_end, m, c, hangup=r['hangup'], topic=asking)

    async def farmer_says(self, key, speech_end, m, c=None, hangup=False, topic=None):
        c = c or self.clips[key]
        await asyncio.sleep(max(0, speech_end + GAP_S - time.monotonic()))
        if self.in_speech: await asyncio.sleep(.1)
        start = max(time.monotonic(), self.farmer_until)
        await self.push_frame(TTSAudioRawFrame(audio=c['pcm'], sample_rate=SR, num_channels=1))
        self.farmer_until = start + c['seconds']; m['farmer_starts_after_s'] = round(start - speech_end, 3)
        await asyncio.sleep(c['seconds'])
        if self.farmer_until == 0: return  # the operator talked over the farmer
        topic = (key and clip_topic(key)) or topic or self.assist.asking
        r = await nlu.interpret(c['heard'], topic if topic in assist_mod.REQUIRED else None, {}, '', 'muse')
        self.assist.on_farmer(c['heard'], r, c['file'])
        if self.protocol:
            opened = self.protocol.see(c['heard'], 'farmer')
            last_op = next((x['text'] for x in reversed(self.assist.transcript) if x['role'] == 'operator'), '')
            asyncio.create_task(self.protocol.extract(c['heard'], 'farmer', last_op, self.http, opened=opened))
        self.assist.transcript[-1].update(t=round(start - self.t0, 3), clip=key, said=c['text'])
        if key == 'bye' or hangup: await self.finish()

    async def finish(self):
        if self.ended: return
        self.ended = True; self.rec['status'] = 'reviewing'
        rv = await assist_mod.review(self.assist.transcript)
        live = self.assist.record()
        self.rec['review'] = {'qa': self.assist.qa(), 'offline': rv, 'differences': assist_mod.differences(live, rv['record']),
                              'truth_check': truth_check(live, self.truth), 'truth': self.truth}
        if self.protocol:
            self.rec['review']['qa'] += self.protocol.qa(live, self.assist.transcript)
            self.rec['review']['handoff'] = self.protocol.handoff(live, self.assist.transcript)
            self.rec['review']['protocol_log'] = self.protocol.extract_log
        if self.ai: self.rec['review']['case'] = {k: self.case[k] for k in ('title', 'story', 'reveal_only_if_asked', 'source')}
        self.rec['status'] = 'ended'; save(self.rec)
        await self.http.close()

def truth_check(live, truth):
    """Only possible in role-play: the scripted farmer's real answers vs what the call recorded."""
    return {k: bool(live.get(k) not in (None, []) and farmer_mod.right(k, live[k], v)) for k, v in truth.items()}

def public(rec):
    s = rec.get('_s'); out = {k: v for k, v in rec.items() if not k.startswith('_')}
    if s:
        out.update(transcript=sorted(s.assist.transcript, key=lambda x: x.get('t', 1e9)), partial=s.partial, record=s.assist.record(), help=s.assist.suggestions(),
                   metrics=s.metrics, farmer_speaking=s.farmer_speaking(), asking=s.assist.asking,
                   protocol=None)
        if s.protocol: out['protocol'] = s.protocol.view(out['record'], s.assist.transcript)
    return out

def save(rec):
    STATE.mkdir(parents=True, exist_ok=True); os.chmod(STATE, 0o700)
    p = STATE / (rec['id'] + '.json'); p.write_text(json.dumps(public(rec), indent=1, default=str)); p.chmod(0o600)

@asynccontextmanager
async def lifespan(app):
    global SP
    SP = await asyncio.to_thread(speech_mod.Speech)
    for sid in SCENARIOS:
        if (ART / sid / 'index.json').exists(): await asyncio.to_thread(load_clips, sid)
    yield

app = FastAPI(lifespan=lifespan)

@app.get('/api/config')
async def config():
    recorded = {k for k in SCENARIOS if (ART / k / 'index.json').exists()}
    return {'farmer': PERSONA['name'], 'llm': farmer_ai.MODEL, 'ai': farmer_ai.KEY_FILE.exists(),
            'cases': [{'id': c['id'], 'opening': c['opening'], 'recorded': c.get('recorded') in recorded} for c in CASES.values()],  # not the title: it gives the case away
            'recorded_only': {k: SCENARIOS[k]['title'] for k in recorded if k not in {c.get('recorded') for c in CASES.values()}},
            'asr': speech_mod.ASR_ENGINE, 'ready': SP is not None, 'protocol': protocol_mod.ENABLED}

@app.post('/api/sessions')
async def create(req: Request):
    """{case, mode: 'ai' | 'recorded'}; or {scenario} for a recorded scenario directly (the automated test)."""
    b = await req.json(); mode = b.get('mode', 'recorded'); case = b.get('case'); sid = b.get('scenario')
    if mode == 'ai' and case not in CASES: raise HTTPException(400, 'unknown case')
    if mode == 'recorded':
        sid = sid or CASES.get(case, {}).get('recorded')
        if sid not in SCENARIOS: raise HTTPException(400, 'no recording for this case')
    ident = time.strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:6]
    SESSIONS[ident] = {'id': ident, 'mode': mode, 'case': case, 'scenario': sid, 'fixture': bool(b.get('fixture')),
                       'status': 'connecting', 'created': time.time()}
    return public(SESSIONS[ident])

@app.post('/api/offer')
async def offer(req: Request, session_id: str):
    rec = SESSIONS.get(session_id)
    if not rec: raise HTTPException(404)
    body = await req.json(); conn = SmallWebRTCConnection(ice_servers=[])
    await conn.initialize(sdp=body['sdp'], type=body['type'])
    transport = SmallWebRTCTransport(conn, TransportParams(audio_in_enabled=True, audio_out_enabled=True,
                                     audio_in_sample_rate=SR, audio_out_sample_rate=SR))
    s = Session(rec)
    task = PipelineTask(Pipeline([transport.input(), s, transport.output()]), params=PipelineParams(audio_in_sample_rate=SR, audio_out_sample_rate=SR))
    @transport.event_handler('on_client_connected')
    async def connected(t, client): rec['status'] = 'on call'
    @transport.event_handler('on_client_disconnected')
    async def disconnected(t, client): await task.cancel()
    rec.update(_conn=conn, _task=task, _s=s, _runner=asyncio.create_task(PipelineRunner(handle_sigint=False).run(task)))
    return conn.get_answer()

@app.get('/api/sessions/{ident}')
async def state(ident: str):
    if ident not in SESSIONS: raise HTTPException(404)
    return public(SESSIONS[ident])

@app.post('/api/sessions/{ident}/edit')
async def edit(ident: str, req: Request):
    """{field, value}: the operator types a value where recognition failed ('' clears the edit). Record or card fields."""
    rec = SESSIONS.get(ident); s = rec and rec.get('_s')
    if not s: raise HTTPException(404)
    b = await req.json(); k = b.get('field')
    try:
        if k in s.assist.fields: s.assist.edit(k, b.get('value'))
        elif s.protocol and k in s.protocol.fields:
            f = s.protocol.fields[k]; f.edited = assist_mod.parse_edit(k, b.get('value'), s.protocol.meta[k]['type'])
            f.evidence.append({'side': 'operator', 'heard': '(edited)'})
        else: raise HTTPException(400, 'unknown field')
    except ValueError as e: raise HTTPException(400, f'expects {e}')
    if rec['status'] == 'ended': save(rec)
    return public(rec)

@app.get('/api/sessions/{ident}/audio/{name}')
async def audio(ident: str, name: str):
    from fastapi.responses import FileResponse
    p = STATE / ident / name
    if ident not in SESSIONS or not re.fullmatch(r'farmer\d+\.wav', name) or not p.exists(): raise HTTPException(404)
    return FileResponse(p, media_type='audio/wav')

@app.post('/api/sessions/{ident}/end')
async def end(ident: str):
    rec = SESSIONS.get(ident)
    if not rec: raise HTTPException(404)
    s = rec.get('_s')
    if s and not s.ended:
        if s.lock.locked():  # let the operator's last turn land in the record
            async with s.lock: pass
        await s.finish()
    if rec.get('_conn'): await rec['_conn'].disconnect()
    if rec.get('_task'): await rec['_task'].cancel()
    rec['status'] = 'ended'; save(rec)
    return public(rec)

app.mount('/clips', StaticFiles(directory=ART, check_dir=False), name='clips')
app.mount('/base', StaticFiles(directory=HERE.parent / 'static'), name='base')
app.mount('/', StaticFiles(directory=HERE / 'static', html=True), name='static')

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host=os.getenv('HOST', '0.0.0.0'), port=PORT)
