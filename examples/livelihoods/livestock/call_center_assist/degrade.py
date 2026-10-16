"""Make clean speech sound like a tired farmer on a cheap phone over a bad line.

Every condition is deterministic given (utterance id, condition), so a corpus can be
rebuilt bit-for-bit. Input and output are 16 kHz mono float32 numpy arrays.
"""
import hashlib, subprocess
import numpy as np

SR = 16000

def _rng(key):
    return np.random.default_rng(int(hashlib.sha256(key.encode()).hexdigest()[:8], 16))

def _ffmpeg(x, args_in, args_out):
    """Round-trip through an ffmpeg codec chain; returns 16 kHz float32."""
    pcm = (np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes()
    enc = subprocess.run(['ffmpeg', '-v', 'error', '-f', 's16le', '-ar', str(SR), '-ac', '1', '-i', 'pipe:0', *args_in],
                         input=pcm, capture_output=True, check=True).stdout
    dec = subprocess.run(['ffmpeg', '-v', 'error', '-i', 'pipe:0', *args_out, '-f', 's16le', '-ar', str(SR), '-ac', '1', 'pipe:1'],
                         input=enc, capture_output=True, check=True).stdout
    return np.frombuffer(dec, np.int16).astype(np.float32) / 32768

def gsm(x):
    """2G voice call: 300-3400 Hz band, 8 kHz, GSM full-rate codec (13 kbps)."""
    return _ffmpeg(x, ['-af', 'highpass=f=300,lowpass=f=3400', '-ar', '8000', '-c:a', 'libgsm', '-f', 'gsm', 'pipe:1'], [])

def opus_low(x):
    """WhatsApp/VoIP on a weak data link: narrowband Opus at 6 kbps."""
    return _ffmpeg(x, ['-c:a', 'libopus', '-b:a', '6k', '-application', 'voip', '-f', 'ogg', 'pipe:1'], [])

def drop_packets(x, key, rate=0.08, frame_ms=20, burst=3):
    """Lose ~rate of 20 ms frames in short bursts (zeroed, harsher than codec concealment)."""
    r = _rng(key + 'loss'); n = SR * frame_ms // 1000; y = x.copy(); i = 0
    while i < len(y) // n:
        if r.random() < rate / burst:
            k = r.integers(1, burst * 2); y[i * n:(i + k) * n] = 0; i += k
        else: i += 1
    return y

def noise(x, key, snr_db):
    """Rural background: brown (wind/rumble) + intermittent babble-like band noise."""
    r = _rng(key + 'noise')
    brown = np.cumsum(r.standard_normal(len(x))); brown -= np.convolve(brown, np.ones(400) / 400, 'same'); brown /= np.std(brown) + 1e-9
    band = r.standard_normal(len(x)); band = np.convolve(band, np.hanning(40), 'same')
    env = np.repeat(r.random(len(x) // 1600 + 1) > .5, 1600)[:len(x)] * .8 + .2
    n = brown * .6 + band / (np.std(band) + 1e-9) * env
    p_sig = np.mean(x[np.abs(x) > 1e-4] ** 2) if np.any(np.abs(x) > 1e-4) else 1e-6
    n *= np.sqrt(p_sig / (10 ** (snr_db / 10)) / (np.mean(n ** 2) + 1e-12))
    return x + n

def gain(x, db):
    return x * 10 ** (db / 20)

def clip(x, level=.25):
    return np.clip(x, -level, level) / level * .9

def gruff(x):
    """Lower, slower, tired voice: pitch down ~3 semitones with tempo kept near natural."""
    f = 2 ** (-3 / 12)
    pcm = (np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes()
    out = subprocess.run(['ffmpeg', '-v', 'error', '-f', 's16le', '-ar', str(SR), '-ac', '1', '-i', 'pipe:0',
                          '-af', f'asetrate={int(SR * f)},aresample={SR},atempo={1 / f * .92:.4f}', '-f', 's16le', 'pipe:1'],
                         input=pcm, capture_output=True, check=True).stdout
    return np.frombuffer(out, np.int16).astype(np.float32) / 32768

def normalize(x, peak=.9):
    m = np.max(np.abs(x)) or 1
    return x / m * peak

CONDITIONS = {
    'clean': lambda x, k: x,
    'gsm': lambda x, k: gsm(normalize(x)),
    'opus6k_loss': lambda x, k: drop_packets(opus_low(normalize(x)), k),
    # Quiet cheap mic, noisy yard, 2G codec, bursts of loss: the hard case.
    'farm_phone': lambda x, k: drop_packets(gsm(clip(noise(gain(normalize(x), -6), k, 5), .5)), k, .05) * 10 ** (-18 / 20),
}
