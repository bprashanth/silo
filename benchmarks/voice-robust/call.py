"""One phone call: turn-taking, latency masking, barge-in and re-prompts around the Intake policy.

Transport-agnostic. Feed 16 kHz int16 mono frames with `await call.feed(frame)`; the call
speaks through `out`, an object with `async play(pcm24k_bytes, meta)` (queue audio, return
immediately) and `async stop()` (drop everything queued/playing). The Pipecat server and the
offline simulator both drive this same class.

Per farmer turn:
  speech ends -> Silero pause (0.25 s) -> smart-turn model says "finished?" (else wait, max STOP_S)
  -> Parakeet ASR (~50 ms) -> a cached ack plays at once ("Achha, okay.") while the LLM interprets
  -> if the LLM is still busy when the ack ends, a cached filler plays ("One moment, I am writing it down.")
  -> Intake decides the reply; it is synthesized (~60 ms on GPU) and played.
The farmer talking over the agent stops playback at once (barge-in); talking again before the
reply starts merges both fragments into one utterance, so a mid-sentence pause isn't a turn.
"""
import asyncio, os, random, time
import numpy as np
from rapidfuzz import fuzz
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams, VADState
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
from pipecat.audio.turn.smart_turn.base_smart_turn import SmartTurnParams
from pipecat.audio.turn.base_turn_analyzer import EndOfTurnState
import intake as intake_mod, nlu, speech as speech_mod

SR = 16000
STOP_S = float(os.getenv('TURN_STOP_S', '1.4'))       # max silence before a turn is over regardless
REPROMPT_S = float(os.getenv('REPROMPT_S', '8'))      # farmer silent after a question
HOLD_S = float(os.getenv('HOLD_S', '25'))             # after "wait a minute"
FILLER_AFTER_S = float(os.getenv('FILLER_AFTER_S', '0.6'))
BARGE_MIN_S = float(os.getenv('BARGE_MIN_S', '0.35'))  # speech this long while agent talks = interruption
MAX_REPROMPTS = 3
ECHO_FILTER = os.getenv('ECHO_FILTER') == '1'  # for speakerphone setups without echo cancellation
DIGIT_PAUSE_S = float(os.getenv('DIGIT_PAUSE_S', '0.9'))

class Call:
    def __init__(self, speech, out, nlu_backend='muse', on_event=None, audio_dir=None):
        self.sp, self.out, self.backend = speech, out, nlu_backend
        self.audio_dir = audio_dir  # each farmer turn saved here, so a human can re-listen to a name
        self.on_event = on_event or (lambda e: None)
        self.intake = intake_mod.Intake()
        self.vad = SileroVADAnalyzer(sample_rate=SR, params=VADParams(confidence=.5, start_secs=.15, stop_secs=.25, min_volume=.1))
        self.turn = LocalSmartTurnAnalyzerV3(sample_rate=SR, params=SmartTurnParams(stop_secs=STOP_S))
        self.vad.set_sample_rate(SR); self.turn.set_sample_rate(SR)
        self.t0 = time.monotonic()
        self.transcript, self.metrics, self.events = [], [], []
        self.buf, self.pre, self.in_speech = bytearray(), [], False
        self.speech_started_at = None; self.last_voice = None
        self.job, self.pending_pcm = None, None
        self.speaking_until = 0.0; self.speaking_text = ''
        self.silence_task = None; self.reprompts = 0
        self.agc = 1.0; self.floor = 50.0; self.ended = False; self.over_agent = False
        self.rng = random.Random(7)

    def now(self): return time.monotonic() - self.t0
    def log(self, event, **kw):
        e = {'t': round(self.now(), 3), 'event': event, **kw}; self.events.append(e); self.on_event(e)
    def playing(self): return time.monotonic() < self.speaking_until

    # ---------- output ----------
    async def speak(self, text, kind, metric=None):
        pcm = await asyncio.to_thread(self.sp.say, text)
        dur = len(pcm) / 2 / speech_mod.OUT_SR
        start = max(time.monotonic(), self.speaking_until)
        self.speaking_until = start + dur; self.speaking_text = text
        await self.out.play(pcm, {'text': text, 'kind': kind})
        entry = {'role': 'agent', 'text': text, 'kind': kind, 't': round(start - self.t0, 3), 'seconds': round(dur, 2)}
        self.transcript.append(entry); self.log('agent', text=text, kind=kind)
        if metric is not None and kind == 'content': metric.setdefault('first_content_audio_s', round(start - self.t0, 3))
        if metric is not None: metric.setdefault('first_audio_s', round(start - self.t0, 3))
        return entry

    async def stop_speaking(self, why):
        if self.playing():
            await self.out.stop(); self.speaking_until = 0.0
            for e in reversed(self.transcript):
                if e['role'] == 'agent': e['interrupted'] = True; break
            self.log('barge_in', why=why)

    async def start(self):
        await self.speak(intake_mod.GREETING, 'content')
        self.intake.asking = None
        self.arm_silence()

    # ---------- input ----------
    def gain(self, frame):
        """AGC ahead of the VAD, so a quiet cheap mic or a weak line still sounds like speech to it.
        Tracks a noise floor and the level of frames well above it; gain is capped so hiss isn't blown up."""
        x = np.frombuffer(frame, np.int16).astype(np.float32)
        rms = float(np.sqrt(np.mean(x ** 2)) + 1e-6)
        self.floor = min(rms, self.floor * 1.002 + 1e-3) if rms < self.floor * 4 else self.floor * 1.002
        if rms > max(self.floor * 4, 20):
            want = min(16.0, max(1.0, 4000 / rms)); self.agc += (want - self.agc) * (.2 if want < self.agc else .03)
        return np.clip(x * self.agc, -32768, 32767).astype(np.int16).tobytes()

    async def feed(self, frame):
        if self.ended: return
        frame = self.gain(frame)
        state = await self.vad.analyze_audio(frame)
        speaking = state in (VADState.SPEAKING, VADState.STARTING)
        if state == VADState.SPEAKING and not self.in_speech:
            self.in_speech = True; self.speech_started_at = time.monotonic()
            self.over_agent = self.playing()  # only speech that starts over our own voice can be an echo of it
            self.buf = bytearray(b''.join(self.pre))
            if self.silence_task: self.silence_task.cancel()
            # Farmer resumed before our real reply started (at most an ack was heard): it was a pause
            # mid-sentence, not the end of the turn. Drop the ack and hear the whole thing as one turn.
            if self.job and not self.job.done() and self.pending_pcm is not None:
                self.job.cancel(); self.buf = bytearray(self.pending_pcm) + self.buf; self.pending_pcm = None
                if self.playing(): await self.out.stop(); self.speaking_until = 0.0
                for j in range(len(self.transcript) - 1, -1, -1):  # the fragment's own entry (an ack may follow it)
                    if self.transcript[j]['role'] == 'farmer': self.transcript.pop(j); break
                self.log('merged_fragment')
            self.log('speech_start')
        if self.in_speech:
            self.buf.extend(frame)
            if speaking: self.last_voice = time.monotonic()
            # Barge-in once the farmer has clearly been talking over us for a moment.
            if self.playing() and time.monotonic() - self.speech_started_at > BARGE_MIN_S:
                if self.job and not self.job.done(): self.job.cancel()
                await self.stop_speaking('farmer spoke')
            eot = self.turn.append_audio(frame, speaking)
            if eot != EndOfTurnState.COMPLETE and state == VADState.QUIET:
                eot, _ = await self.turn.analyze_end_of_turn()
            # Numbers come in groups with pauses ("nine eight four five six ... seven two ..."): be patient.
            if eot == EndOfTurnState.COMPLETE and self.intake.asking == 'contact_details' \
                    and time.monotonic() - (self.last_voice or 0) < DIGIT_PAUSE_S:
                eot = EndOfTurnState.INCOMPLETE
            if eot == EndOfTurnState.COMPLETE or len(self.buf) > SR * 2 * 30:
                self.in_speech = False; pcm = bytes(self.buf); self.buf.clear(); self.turn.clear()
                self.pre = []  # pre-roll must not reach back into this turn, or a merged turn hears it twice
                if len(pcm) > SR * 2 * .3:
                    self.job = asyncio.create_task(self.respond(pcm, self.last_voice or time.monotonic()))
                else:
                    self.arm_silence()
        self.pre = (self.pre + [frame])[-50:]  # 1 s pre-roll: VAD fires late, don't clip the first syllable

    # ---------- one turn ----------
    async def respond(self, pcm, speech_end):
        m = {'turn': len(self.metrics) + 1, 'speech_end_s': round(speech_end - self.t0, 3),
             'eot_s': round(self.now(), 3), 'asking': self.intake.asking}
        self.metrics.append(m); self.pending_pcm = pcm
        try:
            t = time.monotonic()
            heard = await asyncio.to_thread(self.sp.transcribe, pcm)
            m['asr_ms'] = round((time.monotonic() - t) * 1000); m['heard'] = heard
            # Off by default: browser/phone echo cancellation handles echo, and this dropped a farmer repeating a read-back.
            echo = ECHO_FILTER and self.over_agent and self.speaking_text and fuzz.partial_ratio(heard.lower(), self.speaking_text.lower()) > 90 and len(heard) > 12
            if not heard or echo:
                m['dropped'] = 'empty' if not heard else 'echo of agent'
                self.pending_pcm = None; self.log('dropped', why=m['dropped'], heard=heard); self.arm_silence(); return
            entry = {'role': 'farmer', 'text': heard, 't': m['speech_end_s']}
            if self.audio_dir:
                import wave; os.makedirs(self.audio_dir, exist_ok=True)
                path = os.path.join(self.audio_dir, f'turn{m["turn"]:02d}.wav')
                with wave.open(path, 'wb') as w: w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes(pcm)
                entry['audio'] = path
            self.transcript.append(entry); self.log('farmer', text=heard)
            known = {k: s.value for k, s in self.intake.slots.items() if s.state == 'filled'}
            task = asyncio.create_task(nlu.interpret(heard, self.intake.asking, known, self.intake.last_said, self.backend, pcm16=pcm, prev_asking=self.intake.prev_asking))
            await self.speak(self.rng.choice(speech_mod.ACKS), 'ack', m)
            ack_ends = self.speaking_until
            while not task.done():
                if time.monotonic() > ack_ends + FILLER_AFTER_S - .25 and 'filler' not in m:
                    m['filler'] = True; await self.speak(self.rng.choice(speech_mod.Q_FILLERS if '?' in heard else speech_mod.FILLERS), 'filler', m)
                await asyncio.wait([task], timeout=.05)
            r = task.result(); m['nlu_ms'] = r['ms']; m['nlu_source'] = r['source']; m['intent'] = r['intent']; m['facts'] = r['facts']
            self.pending_pcm = None
            events = self.intake.update(r, heard, entry.get('audio'))
            reply = self.intake.next_turn(r, events)
            m['reply'] = reply['text']; m['now_asking'] = reply['asking']
            await self.speak(reply['text'], 'content', m)
            m['response_s'] = round(m['first_content_audio_s'] - m['speech_end_s'], 3)
            m['first_audio_after_s'] = round(m['first_audio_s'] - m['speech_end_s'], 3)
            if reply['end']: await self.finish(); return
            self.reprompts = 0; self.arm_silence(HOLD_S if reply.get('hold') else REPROMPT_S)
        except asyncio.CancelledError:
            m['cancelled'] = True; raise

    # ---------- silence ----------
    def arm_silence(self, after=None):
        if self.silence_task: self.silence_task.cancel()
        self.silence_task = asyncio.create_task(self._silence(after or REPROMPT_S))

    async def _silence(self, after):
        while self.playing(): await asyncio.sleep(.1)
        await asyncio.sleep(after)
        if self.in_speech or self.ended or (self.job and not self.job.done()): return
        self.reprompts += 1
        if self.reprompts > MAX_REPROMPTS:
            await self.speak('I cannot hear you. I have saved what you told me, and the vet team will call you back. Goodbye.', 'content')
            await self.finish(); return
        r = self.intake.reprompt(); self.log('reprompt', n=self.reprompts)
        await self.speak(r['text'], 'content')
        self.arm_silence()

    async def finish(self):
        while self.playing(): await asyncio.sleep(.1)
        self.ended = True; self.intake.phase = 'ended'; self.log('ended')

    def record(self):
        return {'record': self.intake.record(), 'transcript': self.transcript, 'metrics': self.metrics, 'events': self.events}
