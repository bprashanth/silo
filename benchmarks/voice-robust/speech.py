"""Speech in and out for the call engine: Parakeet (+ domain boosting) and Kokoro, both on the GPU.

ASR is `asr_engines.make(ASR_ENGINE)`. TTS is the PyTorch Kokoro on CUDA with an Indian voice;
every phrase is cached, and the fixed phrases (greeting, acks, fillers) are made at startup so
they play with no synthesis delay.
"""
import hashlib, os, re, threading, time
from pathlib import Path
import numpy as np

ASR_ENGINE = os.getenv('ASR_ENGINE', 'parakeet-v3-boost')
VOICE = os.getenv('TTS_VOICE', 'hf_alpha')
SPEED = float(os.getenv('TTS_SPEED', '0.95'))
OUT_SR = 24000

ACKS = ['Okay.', 'Achha, okay.', 'Hmm, okay.', 'Right.']
FILLERS = ['One second, writing it down.', 'Let me note that.', 'Just a second.', 'Hmm, one moment.']
Q_FILLERS = ['Hmm, let me see.', 'One moment.']
SORRY = 'Sorry, I could not hear you. The line is not clear.'

class Speech:
    def __init__(self):
        import torch, asr_engines
        from kokoro import KPipeline
        self.torch = torch
        self.asr = asr_engines.make(ASR_ENGINE)
        self.asr.transcribe([np.zeros(16000, np.float32)])
        self.tts = KPipeline(lang_code='a', repo_id='hexgrad/Kokoro-82M', device='cuda')
        self.cache, self.lock = {}, threading.Lock()
        for p in ACKS + FILLERS + Q_FILLERS + [SORRY]: self.say(p)

    def transcribe(self, pcm16):
        x = np.frombuffer(pcm16, np.int16).astype(np.float32) / 32768
        peak = np.max(np.abs(x)) if len(x) else 0
        if peak > 1e-3: x = x / peak * .9  # quiet cheap mics: normalize before recognition
        with self.lock:
            text = self.asr.transcribe([x])[0].strip()
        # Parakeet v3 is multilingual and can switch script on an unfamiliar name; keep Latin words only.
        if re.search(r'[^\x00-\x7F\u00C0-\u024F]', text):
            text = ' '.join(w for w in text.split() if not re.search(r'[^\x00-\x7F\u00C0-\u024F]', w))
        return text

    def say(self, text):
        """-> int16 PCM bytes at 24 kHz. Cached by text."""
        key = hashlib.sha1(f'{VOICE}{SPEED}{text}'.encode()).hexdigest()
        if key in self.cache: return self.cache[key]
        with self.lock:
            a = self.torch.cat([r.audio for r in self.tts(text, voice=VOICE, speed=SPEED)]).numpy()
        # Trim the long trailing silence Kokoro leaves, keep a short natural gap.
        nz = np.nonzero(np.abs(a) > 1e-3)[0]
        if len(nz): a = a[:min(len(a), nz[-1] + int(.12 * OUT_SR))]
        pcm = (np.clip(a, -1, 1) * 32767).astype(np.int16).tobytes()
        self.cache[key] = pcm
        return pcm
