"""Render the scripted farmers (and the test operator) to audio -> $VR_ART/assist/.

  python assist/make_scenarios.py

Farmer lines are synthetic (Kokoro), with a tired pause at each "...", then put through the scenario's
bad-line condition from degrade.py, so the operator hears what a 2G call sounds like and the farmer-side
ASR has to cope with it. Operator lines (for the automated test only) are left clean, like a headset.
"""
import json, os, sys
from pathlib import Path
import numpy as np, soundfile as sf, librosa
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import degrade

ART = Path(os.getenv('VR_ART', '/mnt/seagate/silo/voice-robust')) / 'assist'

def main():
    from kokoro import KPipeline
    tts = KPipeline(lang_code='a', repo_id='hexgrad/Kokoro-82M', device='cuda')
    def speak(text, voice, speed):
        out = []
        for p in [p for p in text.split('...') if p.strip()]:
            a = np.concatenate([r.audio.numpy() for r in tts(p.strip(), voice=voice, speed=speed)])
            out += [librosa.resample(a.astype(np.float32), orig_sr=24000, target_sr=16000), np.zeros(int(16000 * .9), np.float32)]
        return np.concatenate(out[:-1])
    for sc in json.loads((HERE / 'scenarios.json').read_text()):
        d = ART / sc['id']; d.mkdir(parents=True, exist_ok=True); index = {}
        for key, text in sc['lines'].items():
            x = speak(text, sc['voice'], sc['speed'])
            x = degrade.CONDITIONS[sc['condition']](np.concatenate([np.zeros(1600, np.float32), x, np.zeros(1600, np.float32)]), sc['id'] + key)
            sf.write(d / f'{key}.wav', np.clip(x, -1, 1).astype(np.float32), 16000, subtype='PCM_16')
            index[key] = {'file': f'{key}.wav', 'text': text, 'seconds': round(len(x) / 16000, 2)}
        (d / 'index.json').write_text(json.dumps(index, indent=1)); print(sc['id'], len(index), 'clips')
    op = json.loads((HERE / 'operator_script.json').read_text()); d = ART / 'operator'; d.mkdir(parents=True, exist_ok=True)
    for key, text in op['lines']:
        x = speak(text, op['voice'], 1.0)
        sf.write(d / f'{key}.wav', np.clip(x * .8, -1, 1).astype(np.float32), 16000, subtype='PCM_16')
    (d / 'index.json').write_text(json.dumps([{'label': k, 'file': f'{k}.wav', 'text': t} for k, t in op['lines']], indent=1))
    print('operator', len(op['lines']), 'clips')

if __name__ == '__main__':
    main()
