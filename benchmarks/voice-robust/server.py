"""Browser call for the robust livestock intake agent (isolated: port 8775, own state dir).

  ./start.sh            # or: python server.py
  open http://127.0.0.1:8775

Browser mic -> SmallWebRTC (Opus) -> [optional simulated 2G line] -> Call (VAD, smart-turn,
Parakeet, Muse/OpenRouter interpretation, Kokoro) -> browser speaker. The page polls the
call state for the live transcript, fields and per-turn timings.
"""
import asyncio, json, os, time, uuid
from pathlib import Path
import numpy as np
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from pipecat.frames.frames import InputAudioRawFrame, TTSAudioRawFrame, InterruptionFrame, StartFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.task import PipelineTask, PipelineParams
from pipecat.pipeline.runner import PipelineRunner
from pipecat.processors.frame_processor import FrameProcessor, FrameDirection
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
import call as call_mod, speech as speech_mod

HERE = Path(__file__).parent
STATE = Path(os.getenv('VR_STATE', Path.home() / '.local/share/silo-voice/calls'))
PORT = int(os.getenv('PORT', '8775'))
NLU_BACKENDS = {
    'muse': 'Local Muse 30B (private)',
    'or:deepseek/deepseek-v4-flash': 'OpenRouter DeepSeek V4 Flash (hosted text only, synthetic data)',
    'or:google/gemini-3.8-flash': 'OpenRouter Gemini 3.8 Flash (hosted text only, synthetic data)',
    'audio:google/gemini-3.5-flash-lite': 'OpenRouter Gemini 3.5 Flash-Lite hears the audio directly (NOT private)',
}
SP = None; CALLS = {}

class Line:
    """Simulated 2G phone line for testing with a real mic: 300-3400 Hz, 8 kHz mu-law, bursty loss, low level."""
    def __init__(self, seed=1):
        from scipy.signal import butter, sosfilt_zi
        self.sos = butter(4, [300, 3400], 'bandpass', fs=16000, output='sos'); self.zi = None
        self.rng = np.random.default_rng(seed); self.lose = 0
    def __call__(self, pcm):
        from scipy.signal import sosfilt, sosfilt_zi
        x = np.frombuffer(pcm, np.int16).astype(np.float32) / 32768
        if self.zi is None: self.zi = sosfilt_zi(self.sos) * 0
        x, self.zi = sosfilt(self.sos, x, zi=self.zi)
        x = x[::2]; mu = 255.0
        y = np.sign(x) * np.log1p(mu * np.abs(np.clip(x, -1, 1))) / np.log1p(mu)
        y = np.round(y * 127) / 127; x = np.sign(y) * ((1 + mu) ** np.abs(y) - 1) / mu
        x = np.repeat(x, 2) * 10 ** (-12 / 20)
        if self.lose > 0: self.lose -= 1; x[:] = 0
        elif self.rng.random() < .03: self.lose = int(self.rng.integers(1, 5)); x[:] = 0
        x += self.rng.standard_normal(len(x)) * 2e-3
        return (np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes()

class Bridge(FrameProcessor):
    """Pipecat <-> Call: mic frames in, agent audio out, InterruptionFrame on barge-in."""
    def __init__(self, record, nlu_backend, line):
        super().__init__()
        self.rec, self.line, self.buf = record, (Line() if line else None), b''
        self.call = call_mod.Call(SP, self, nlu_backend, on_event=self.event, audio_dir=str(STATE / record['id']))
        self.started = asyncio.Event()  # nothing may be pushed before the pipeline's StartFrame
    async def greet(self):
        await self.started.wait(); await self.call.start()
    def event(self, e):
        self.rec['status'] = {'agent': 'speaking', 'farmer': 'thinking', 'speech_start': 'listening', 'ended': 'ended'}.get(e['event'], self.rec['status'])
    async def play(self, pcm, meta):
        await self.push_frame(TTSAudioRawFrame(audio=pcm, sample_rate=speech_mod.OUT_SR, num_channels=1))
    async def stop(self):
        await self.push_frame(InterruptionFrame())
    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if isinstance(frame, InputAudioRawFrame):
            st = self.rec.setdefault('input', {'frames': 0, 'peak': 0, 'rate': frame.sample_rate})
            st['frames'] += 1; st['peak'] = max(st['peak'], int(np.abs(np.frombuffer(frame.audio, np.int16)).max(initial=0)))
            self.buf += frame.audio
            while len(self.buf) >= 640:
                f, self.buf = self.buf[:640], self.buf[640:]
                if self.line: f = self.line(f)
                await self.call.feed(f)
            return
        await self.push_frame(frame, direction)
        if isinstance(frame, StartFrame): self.started.set()

@asynccontextmanager
async def lifespan(app):
    global SP
    STATE.mkdir(parents=True, exist_ok=True); os.chmod(STATE, 0o700)
    SP = await asyncio.to_thread(speech_mod.Speech)
    yield
    for c in CALLS.values():
        if c.get('_conn'): await c['_conn'].disconnect()

app = FastAPI(lifespan=lifespan)

def public(c):
    b = c.get('_bridge')
    out = {k: v for k, v in c.items() if not k.startswith('_')}
    if b:
        r = b.call.record(); out.update(transcript=r['transcript'], metrics=r['metrics'], record=r['record'],
                                        asking=b.call.intake.asking, playing=b.call.playing())
        if b.call.ended: out['status'] = 'ended'
    return out

def save(c):
    p = STATE / (c['id'] + '.json'); p.write_text(json.dumps(public(c), indent=1, default=str)); p.chmod(0o600)

@app.get('/api/config')
async def config():
    return {'nlu': NLU_BACKENDS, 'asr': speech_mod.ASR_ENGINE, 'voice': speech_mod.VOICE, 'ready': SP is not None}

@app.post('/api/calls')
async def create(req: Request):
    b = await req.json(); nlu_backend = b.get('nlu', 'muse')
    if nlu_backend not in NLU_BACKENDS: raise HTTPException(400, 'unknown NLU backend')
    ident = time.strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:6]
    CALLS[ident] = {'id': ident, 'nlu': nlu_backend, 'line': bool(b.get('line')), 'fixture': bool(b.get('fixture')),
                    'status': 'connecting', 'created': time.time()}
    return public(CALLS[ident])

@app.post('/api/offer')
async def offer(req: Request, call_id: str):
    c = CALLS.get(call_id)
    if not c: raise HTTPException(404, 'no such call')
    body = await req.json()
    conn = SmallWebRTCConnection(ice_servers=[])
    await conn.initialize(sdp=body['sdp'], type=body['type'])
    transport = SmallWebRTCTransport(conn, TransportParams(audio_in_enabled=True, audio_out_enabled=True,
                                     audio_in_sample_rate=16000, audio_out_sample_rate=speech_mod.OUT_SR))
    bridge = Bridge(c, c['nlu'], c['line'])
    task = PipelineTask(Pipeline([transport.input(), bridge, transport.output()]),
                        params=PipelineParams(audio_in_sample_rate=16000, audio_out_sample_rate=speech_mod.OUT_SR))
    @transport.event_handler('on_client_connected')
    async def connected(t, client):
        c['status'] = 'listening'; asyncio.create_task(bridge.greet())
    @transport.event_handler('on_client_disconnected')
    async def disconnected(t, client): await task.cancel()
    c.update(_conn=conn, _task=task, _bridge=bridge, _runner=asyncio.create_task(PipelineRunner(handle_sigint=False).run(task)))
    return conn.get_answer()

@app.get('/api/calls/{ident}')
async def state(ident: str):
    if ident not in CALLS: raise HTTPException(404)
    return public(CALLS[ident])

@app.post('/api/calls/{ident}/end')
async def end(ident: str):
    c = CALLS.get(ident)
    if not c: raise HTTPException(404)
    b = c.get('_bridge')
    if b:
        b.call.ended = True
        if b.call.job and not b.call.job.done(): b.call.job.cancel()
        if b.call.silence_task: b.call.silence_task.cancel()
    if c.get('_conn'): await c['_conn'].disconnect()
    if c.get('_task'): await c['_task'].cancel()
    c['status'] = 'ended'; save(c)
    return public(c)

@app.post('/api/calls/{ident}/events')
async def browser_event(ident: str, req: Request):
    c = CALLS.get(ident)
    if c: c.setdefault('browser_events', []).append(await req.json())
    return {'ok': True}

app.mount('/fixtures', StaticFiles(directory=os.getenv('VR_FIXTURES', '/mnt/seagate/silo/voice-robust/fixtures'), check_dir=False), name='fixtures')
app.mount('/', StaticFiles(directory=HERE / 'static', html=True), name='static')

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host=os.getenv('HOST', '0.0.0.0'), port=PORT)
