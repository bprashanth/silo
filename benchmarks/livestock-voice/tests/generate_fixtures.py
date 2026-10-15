"""Generate synthetic farmer WAVs locally; large audio remains on Seagate."""
import json, os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'tg-bridge'))
# Constrain ONNX threads to avoid contention with the live bot.
os.environ.setdefault('OMP_NUM_THREADS', '4')
import speech
import soundfile as sf
from kokoro_onnx import Kokoro
OUT = Path(os.environ.get('LIVESTOCK_FIXTURES', '/mnt/seagate/silo/livestock-voice/fixtures'))
OUT.mkdir(parents=True, exist_ok=True)
CASES = {
 'name': 'My name is Ramesh.',
 'missing': 'My cow is sick.',
 'out_of_order': 'My name is Ramesh. I live in Demo Village in Demo District. One cow is affected. She has not been eating and is very weak since yesterday.',
 'warning': 'She cannot stand up, and she is breathing very fast.',
 'unknown': 'I do not know when the symptoms started.',
 'correction': 'Sorry, I got that wrong. It started two days ago, not three days ago.',
 'treatment': 'There has been no previous treatment. I do not have a contact number to share.',
 'difficult': 'Um, my cow, she is, uh, not eating. I think it started yesterday. She is very weak.',
 'confirm': 'Yes, that summary is correct. Thank you.'
}
model = Kokoro(str(Path(speech.MODELS) / 'kokoro/kokoro-v1.0.onnx'), str(Path(speech.MODELS) / 'kokoro/voices-v1.0.bin'))
for name, text in CASES.items():
 if not (OUT / (name+'.wav')).exists():
  samples, rate = model.create(text, voice='am_adam', speed=1., lang='en-us')
  if name == 'difficult':
   import numpy as np
   rng=np.random.default_rng(41);samples=samples+rng.normal(0,.012,len(samples))
  sf.write(OUT / (name+'.wav'), samples, rate, subtype='PCM_16')
 print(name, flush=True)
(OUT / 'manifest.json').write_text(json.dumps({'kind':'synthetic Kokoro am_adam English, not human-spoken','cases':CASES}, indent=2)+'\n')
