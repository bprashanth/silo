"""Build the ASR robustness corpus: real accented speech plus synthetic farmer lines, each degraded.

  python build_corpus.py            # writes $VR_ART/corpus/{wav/,manifest.jsonl}

Sources:
  edacc     Edinburgh Intl. Accents of English, test split, Indian English speakers (real, conversational)
  svarah    AI4Bharat Svarah, Indian-accented English (real), if the gated download is available
  farmer    farmer_lines.json synthesized with Kokoro Indian voices, plus a lowered "gruff" variant
Each utterance x each condition in degrade.CONDITIONS.
"""
import glob, io, json, os, re, sys
from pathlib import Path
import numpy as np, soundfile as sf, librosa
sys.path.insert(0, str(Path(__file__).parent))
import degrade

HERE = Path(__file__).parent
ART = Path(os.getenv('VR_ART', '/mnt/seagate/silo/voice-robust'))
OUT = ART / 'corpus'; (OUT / 'wav').mkdir(parents=True, exist_ok=True)
MODELS = Path.home() / '.local/share/idli-bridge/models'
PER_SOURCE = int(os.getenv('PER_SOURCE', '60'))
SVARAH_TARGET = int(os.getenv('SVARAH_TARGET', '200'))

def load_bytes(b):
    x, sr = sf.read(io.BytesIO(b), dtype='float32', always_2d=True)
    x = x.mean(1)
    return librosa.resample(x, orig_sr=sr, target_sr=16000) if sr != 16000 else x

def edacc():
    import pyarrow.parquet as pq
    rows = []
    for f in sorted(glob.glob(str(ART / 'data/edacc/*.parquet'))):
        for r in pq.read_table(f).to_pylist():
            words = r['text'].split()
            if r['accent'] == 'Indian English' and 5 <= len(words) <= 40 and '<' not in r['text']:
                rows.append(r)
    # Spread across speakers: round-robin so a talkative speaker can't dominate.
    by = {}
    for r in rows: by.setdefault(r['speaker'], []).append(r)
    picked = []
    while len(picked) < PER_SOURCE and any(by.values()):
        for s in sorted(by):
            if by[s] and len(picked) < PER_SOURCE: picked.append(by[s].pop(len(by[s]) // 2))
    for i, r in enumerate(picked):
        yield f'edacc{i:03d}', load_bytes(r['audio']['bytes']), r['text'].lower(), {'speaker': r['speaker'], 'l1': r['l1'], 'gender': r['gender']}, []

def svarah():
    import pyarrow.parquet as pq

    def speaker_id_from_path(path):
        m = re.match(r'^(.*)_chunk_\d+\.wav$', path or '')
        return m.group(1) if m else (path or '')

    files = sorted(glob.glob(str(ART / 'data/svarah/**/*.parquet'), recursive=True))
    if not files:
        return
    rows = [r for f in files for r in pq.read_table(f).to_pylist()]
    if not rows:
        return
    text_key = next((k for k in ('text', 'transcript', 'sentence') if k in rows[0]), None)
    if not text_key:
        raise RuntimeError(f'Svarah schema lacks transcript field. Columns: {sorted(rows[0])}')

    valid = []
    for r in rows:
        audio = r.get('audio_filepath') or {}
        text = str(r.get(text_key, '')).strip()
        if not text or not isinstance(audio, dict) or 'bytes' not in audio:
            continue
        speaker = speaker_id_from_path(str(audio.get('path') or ''))
        if not speaker:
            continue
        words = text.split()
        if len(words) < 5 or len(words) > 60:
            continue
        rr = dict(r)
        rr['_speaker'] = speaker
        rr['_group'] = (
            str(r.get('primary_language') or 'UNKNOWN').strip() or 'UNKNOWN',
            str(r.get('native_place_state') or 'UNKNOWN').strip() or 'UNKNOWN',
        )
        valid.append(rr)

    rng = np.random.default_rng(0)
    by_group = {}
    for r in valid:
        g = r['_group']
        by_group.setdefault(g, {}).setdefault(r['_speaker'], []).append(r)
    for spk_map in by_group.values():
        for items in spk_map.values():
            rng.shuffle(items)

    group_speakers = {}
    for g, spk_map in by_group.items():
        speakers = list(spk_map)
        rng.shuffle(speakers)
        group_speakers[g] = speakers
    groups = list(group_speakers)
    rng.shuffle(groups)

    picked = []
    while len(picked) < SVARAH_TARGET and groups:
        progressed = False
        for g in list(groups):
            speakers = group_speakers[g]
            if not speakers:
                continue
            speaker = speakers.pop()
            picked.append(by_group[g][speaker][0])  # one clip per speaker for speaker balance
            progressed = True
            if len(picked) >= SVARAH_TARGET:
                break
        groups = [g for g in groups if group_speakers[g]]
        if not progressed:
            break

    picked = picked[:SVARAH_TARGET]
    print(
        f'svarah picked={len(picked)} seed=0 columns='
        f"{sorted([k for k in rows[0] if k != 'audio_filepath'])}",
        flush=True,
    )
    for i, r in enumerate(picked):
        meta = {k: r[k] for k in r if k not in ('audio_filepath', text_key, '_speaker', '_group') and isinstance(r[k], (str, int, float))}
        meta.update({
            'speaker': r['_speaker'],
            'sample_seed': 0,
            'sample_group_language': r['_group'][0],
            'sample_group_state': r['_group'][1],
        })
        yield f'svarah{i:03d}', load_bytes(r['audio_filepath']['bytes']), r[text_key], meta, []

def farmer():
    from kokoro_onnx import Kokoro
    k = Kokoro(str(MODELS / 'kokoro/kokoro-v1.0.onnx'), str(MODELS / 'kokoro/voices-v1.0.bin'))
    voices = ['hf_alpha', 'hf_beta', 'hm_omega', 'hm_psi']
    for i, line in enumerate(json.loads((HERE / 'farmer_lines.json').read_text())['lines']):
        v = voices[i % len(voices)]
        a, sr = k.create(line['text'], voice=v, speed=.95, lang='en-us')
        x = librosa.resample(a.astype(np.float32), orig_sr=sr, target_sr=16000)
        x = np.concatenate([np.zeros(4000, np.float32), x, np.zeros(4000, np.float32)])
        yield f"{line['id']}-{v}", x, line['text'], {'voice': v, 'tts': 'kokoro'}, line['keys']
        if v.startswith('hm'):
            yield f"{line['id']}-{v}-gruff", degrade.gruff(x), line['text'], {'voice': v + '+gruff', 'tts': 'kokoro'}, line['keys']

def main():
    sources = {'edacc': edacc, 'svarah': svarah, 'farmer': farmer}
    want = os.getenv('SOURCES', ','.join(sources)).split(',')
    man = open(OUT / 'manifest.jsonl', 'a')
    have = {json.loads(l)['id'] for l in open(OUT / 'manifest.jsonl')} if (OUT / 'manifest.jsonl').exists() else set()
    for name in want:
        n = 0
        for uid, x, text, meta, keys in sources[name]():
            for cond, fn in degrade.CONDITIONS.items():
                cid = f'{uid}.{cond}'
                if cid in have: continue
                y = fn(x, uid).astype(np.float32)
                sf.write(OUT / 'wav' / f'{cid}.wav', np.clip(y, -1, 1), 16000, subtype='PCM_16')
                man.write(json.dumps({'id': cid, 'utt': uid, 'source': name, 'condition': cond, 'text': text, 'keys': keys,
                                      'seconds': round(len(y) / 16000, 2), **meta}) + '\n')
            n += 1
        man.flush(); print(name, n, 'utterances', flush=True)

if __name__ == '__main__':
    main()
