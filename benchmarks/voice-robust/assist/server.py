"""Operator-assist console: you play the helpline operator, a scripted farmer answers, the agent helps live.

  ./assist/start.sh            # or: python assist/server.py
  open http://127.0.0.1:8776

Operator mic -> SmallWebRTC -> VAD + smart-turn -> Parakeet (live captions while you talk, then the turn)
  -> which question you asked (rules, instant) -> the scripted farmer's clip plays back over the call
  -> the farmer clip's ASR (as the bad line delivered it) and your words both go to the local LLM
  -> one case record: what you repeated counts as confirmed, what only the line heard is flagged.
After the call: QA checks, a full-transcript re-read by Muse, and the differences from the live record.
"""
import asyncio, json, os, re, sys, time, uuid, wave
from pathlib import Path
from contextlib import asynccontextmanager
import numpy as np
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
import assist as assist_mod, farmer as farmer_mod

ART = Path(os.getenv('VR_ART', '/mnt/seagate/silo/voice-robust')) / 'assist'
STATE = Path(os.getenv('VR_ASSIST_STATE', Path.home() / '.local/share/silo-voice/assist'))
PORT = int(os.getenv('PORT', '8776'))
SR = 16000
GAP_S = float(os.getenv('FARMER_GAP_S', '0.8'))
NUDGE_S = float(os.getenv('FARMER_NUDGE_S', '6'))  # operator silent after a statement: the farmer says "Hello?"  # pause before the farmer answers, like a real person
SCENARIOS = {s['id']: s for s in json.loads((HERE / 'scenarios.json').read_text())}
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
        self.rec = rec; self.sc = SCENARIOS[rec['scenario']]; self.clips = load_clips(rec['scenario'])
        self.assist = assist_mod.Assist(); self.farmer = farmer_mod.ScriptedFarmer(self.sc)
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
            if reply:
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

    async def _nudge(self):
        """The operator said something, then went quiet: after a while the farmer checks the line is alive."""
        await asyncio.sleep(NUDGE_S)
        if self.in_speech or self.farmer_speaking() or self.ended or (self.farmer_job and not self.farmer_job.done()): return
        key = self.farmer.reply(None, assist_mod.operator_rules(self.carry), self.carry); self.carry = ''
        if key: self.farmer_job = asyncio.create_task(self.farmer_says(key, time.monotonic() - GAP_S, {}))

    async def farmer_says(self, key, speech_end, m):
        c = self.clips[key]
        await asyncio.sleep(max(0, speech_end + GAP_S - time.monotonic()))
        if self.in_speech: await asyncio.sleep(.1)
        start = max(time.monotonic(), self.farmer_until)
        await self.push_frame(TTSAudioRawFrame(audio=c['pcm'], sample_rate=SR, num_channels=1))
        self.farmer_until = start + c['seconds']; m['farmer_starts_after_s'] = round(start - speech_end, 3)
        await asyncio.sleep(c['seconds'])
        if self.farmer_until == 0: return  # the operator talked over the farmer
        topic = clip_topic(key) or self.assist.asking
        r = await nlu.interpret(c['heard'], topic if topic in assist_mod.REQUIRED else None, {}, '', 'muse')
        self.assist.on_farmer(c['heard'], r, c['file'])
        self.assist.transcript[-1].update(t=round(start - self.t0, 3), clip=key, said=c['text'])
        if key == 'bye': await self.finish()

    async def finish(self):
        if self.ended: return
        self.ended = True; self.rec['status'] = 'reviewing'
        rv = await assist_mod.review(self.assist.transcript)
        live = self.assist.record()
        self.rec['review'] = {'qa': self.assist.qa(), 'offline': rv, 'differences': assist_mod.differences(live, rv['record']),
                              'truth_check': truth_check(live, self.sc['truth'])}
        self.rec['status'] = 'ended'; save(self.rec)

def truth_check(live, truth):
    """Only possible in role-play: the scripted farmer's real answers vs what the call recorded."""
    return {k: bool(live.get(k) not in (None, []) and farmer_mod.right(k, live[k], v)) for k, v in truth.items()}

def public(rec):
    s = rec.get('_s'); out = {k: v for k, v in rec.items() if not k.startswith('_')}
    if s:
        out.update(transcript=sorted(s.assist.transcript, key=lambda x: x.get('t', 1e9)), partial=s.partial, record=s.assist.record(), help=s.assist.suggestions(),
                   metrics=s.metrics, farmer_speaking=s.farmer_speaking(), asking=s.assist.asking)
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
    return {'scenarios': {k: v['title'] for k, v in SCENARIOS.items() if (ART / k / 'index.json').exists()},
            'asr': speech_mod.ASR_ENGINE, 'ready': SP is not None}

@app.post('/api/sessions')
async def create(req: Request):
    b = await req.json(); sid = b.get('scenario')
    if sid not in SCENARIOS: raise HTTPException(400, 'unknown scenario')
    ident = time.strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:6]
    SESSIONS[ident] = {'id': ident, 'scenario': sid, 'fixture': bool(b.get('fixture')), 'status': 'connecting', 'created': time.time()}
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
