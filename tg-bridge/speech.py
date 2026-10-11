"""Speech on the box, on the CPU: Whisper to listen, Kokoro to speak.

Both run on the CPU on purpose: the GPU's memory is shared with the model server and other
projects, and these two are small enough for the cores (chronology 2026-10-12T0000).

Env:
  MODELS_DIR     where the weights live (default ~/.local/share/idli-bridge/models):
                 kokoro/kokoro-v1.0.onnx, kokoro/voices-v1.0.bin, whisper/ (Hugging Face cache)
  WHISPER_MODEL  default large-v3-turbo
  TTS_VOICE      Kokoro voice (default af_heart); TTS_SPEED (default 1.0)
  SILO_CONFIG    glossary.txt there: names and words Whisper should expect, one per line
"""
import os
import re
import subprocess
import tempfile
import threading
import unicodedata

import numpy as np

MODELS = os.path.expanduser(os.environ.get("MODELS_DIR", "~/.local/share/idli-bridge/models"))
CFG = os.path.expanduser(os.environ.get("SILO_CONFIG", "~/.config/silo"))
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "large-v3-turbo")
VOICE = os.environ.get("TTS_VOICE", "af_heart")
SPEED = float(os.environ.get("TTS_SPEED", "1.0"))
MAX_SPOKEN = 1500  # characters; longer replies are cut, and the voice note says so

_whisper = _kokoro = None
_wlock, _klock = threading.Lock(), threading.Lock()


def _decode(data):
    """Any audio Telegram sends (OGG/Opus voice notes, mp3, m4a) -> 16 kHz mono float32."""
    p = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", "pipe:0", "-f", "f32le", "-ac", "1",
                        "-ar", "16000", "pipe:1"], input=data, capture_output=True, timeout=120)
    if p.returncode:
        raise ValueError(f"couldn't decode audio: {p.stderr.decode()[-200:]}")
    return np.frombuffer(p.stdout, np.float32)


def glossary():
    try:
        return [l.strip() for l in open(os.path.join(CFG, "glossary.txt")) if l.strip()]
    except OSError:
        return []


def transcribe(data, hints=()):
    """English speech -> text. hints (names, open todos) bias Whisper towards the user's words."""
    global _whisper
    with _wlock:
        if _whisper is None:
            from faster_whisper import WhisperModel
            _whisper = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8", cpu_threads=8,
                                    download_root=os.path.join(MODELS, "whisper"))
        words = ", ".join([*glossary(), *hints])[-800:]
        segs, _ = _whisper.transcribe(_decode(data), language="en", beam_size=1, vad_filter=True,
                                      initial_prompt=("Names and words: " + words) if words else None)
        return " ".join(s.text.strip() for s in segs).strip()


# ---- text to speech ---------------------------------------------------------------------

def indian_number(m):
    """19,080,600 -> '1 crore 90 lakh 80 thousand 600': how the team says large amounts."""
    digits = m.group(0).replace(",", "")
    n = int(digits)
    if n < 100_000:
        return m.group(0)
    parts = [(n // 10**7, "crore"), (n // 10**5 % 100, "lakh"), (n // 1000 % 100, "thousand"), (n % 1000, "")]
    return " ".join(f"{v} {w}".strip() for v, w in parts if v)


def speakable(text):
    """Strip what reads badly aloud: code and chart blocks, markdown, links, table pipes."""
    t = re.sub(r"```.*?```", " ", text, flags=re.S)
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)
    t = re.sub(r"https?://\S+", "", t)
    t = t.replace("→", " to ")
    # Emoji and symbols are read out by name ("heavy plus sign"); drop them.
    t = "".join(ch for ch in t if unicodedata.category(ch) not in ("So", "Sk", "Mn", "Cf") or ch == "₹")
    t = re.sub(r"[*_`#>]+", "", t)
    t = re.sub(r"^\s*\|?[-:| ]+\|?\s*$", "", t, flags=re.M)  # table rule lines
    t = t.replace("|", ", ")
    t = re.sub(r"(?:₹|Rs\.?|INR)\s?([\d,]+(?:\.\d+)?)", r"\1 rupees", t)
    t = re.sub(r"\b([\d,]+)\s?(?:INR)\b", r"\1 rupees", t)
    t = re.sub(r"(?<![\d.])\d{1,3}(?:,\d{2,3})+(?![\d.])|(?<![\d.,])\d{6,}(?![\d.,])", indian_number, t)
    t = re.sub(r"([^.!?:;,\s])[ \t]*\n", r"\1.\n", t)  # a line end is a pause
    t = re.sub(r"\n\s*\n+", ". ", t)
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"\s*([.,])(?:\s*[.,])+", r"\1", t)  # "rows.. , a" -> "rows. a"
    if len(t) > MAX_SPOKEN:
        t = t[:MAX_SPOKEN].rsplit(". ", 1)[0] + ". The rest is in the message."
    return t


def speak(text, voice=None):
    """Text -> OGG/Opus bytes for Telegram's sendVoice."""
    global _kokoro
    import soundfile as sf
    with _klock:
        if _kokoro is None:
            from kokoro_onnx import Kokoro
            d = os.path.join(MODELS, "kokoro")
            _kokoro = Kokoro(os.path.join(d, "kokoro-v1.0.onnx"), os.path.join(d, "voices-v1.0.bin"))
        audio, sr = _kokoro.create(speakable(text), voice=voice or VOICE, speed=SPEED, lang="en-us")
    with tempfile.TemporaryDirectory() as d:
        wav, ogg = os.path.join(d, "a.wav"), os.path.join(d, "a.ogg")
        sf.write(wav, audio, sr)
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", wav, "-c:a", "libopus", "-b:a", "32k", ogg],
                       check=True, timeout=120)
        return open(ogg, "rb").read()
