"""Farmer test utterances for the browser call (synthetic, 2G-line degraded) -> $VR_ART/fixtures/."""
import json, os, sys
from pathlib import Path
import numpy as np, soundfile as sf
sys.path.insert(0, str(Path(__file__).parent))
import sim

OUT = Path(os.getenv('VR_ART', '/mnt/seagate/silo/voice-robust')) / 'fixtures'; OUT.mkdir(parents=True, exist_ok=True)
LINES = [('opening', 'My buffalo is not eating from yesterday, she is very weak.'), ('stand_yes', 'Yes, she is standing.'),
         ('breath_yes', 'Yes, breathing is normal.'), ('one', 'Only one buffalo.'), ('treat_no', 'No, no treatment given.'),
         ('name', 'My name is Basavaraju.'), ('village', 'Kunigal.'), ('district', 'Tumakuru district.'),
         ('phone', 'Nine eight four five six, seven two three one zero.'), ('yes', 'Yes, that is correct.'),
         ('wait', 'One minute madam, wait.'), ('medicine', 'What medicine should I give her?'), ('since', 'From yesterday.')]
class _Sp:  # sim.Farmer only needs a lock
    import threading; lock = threading.Lock()
f = sim.Farmer(_Sp(), os.getenv('CONDITION', 'gsm'), False, 'fixtures')
index = []
for name, text in LINES:
    x = f.audio(text)
    sf.write(OUT / f'{name}.wav', np.clip(x, -1, 1), 16000, subtype='PCM_16')
    index.append({'label': name, 'file': f'{name}.wav', 'text': text})
(OUT / 'index.json').write_text(json.dumps(index, indent=1)); print(len(index), 'fixtures in', OUT)
