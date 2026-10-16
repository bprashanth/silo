"""Score ASR engines on the degraded corpus.

  python asr_bench.py <engine> [--limit N] [--sources edacc,farmer] [--prompt domain]
Writes $VR_ART/runs/asr/<engine>[+prompt].jsonl (one row per clip) and prints a summary table.
Metrics: WER per source x condition (Whisper English normalizer), key-term recall on farmer lines
(the words an intake must get right), per-clip latency, and hallucinations on noise-only clips.
"""
import argparse, json, os, re, sys, time
from pathlib import Path
import numpy as np, soundfile as sf, jiwer
sys.path.insert(0, str(Path(__file__).parent))
import asr_engines, degrade

ART = Path(os.getenv('VR_ART', '/mnt/seagate/silo/voice-robust'))
from whisper_normalizer.english import EnglishTextNormalizer
_norm = EnglishTextNormalizer()

def norm(s):
    s = _norm(s or '')
    return re.sub(r'(?<=\d) (?=\d)', '', s).strip()

def key_hits(keys, hyp):
    h = ' ' + norm(hyp) + ' '
    return [(' ' + norm(k) + ' ') in h for k in keys]

def noise_clips():
    """Noise/silence with no speech: any output is a hallucination."""
    r = np.random.default_rng(3); out = []
    for i in range(6):
        x = np.zeros(16000 * 3, np.float32) + r.standard_normal(48000).astype(np.float32) * 1e-4
        y = degrade.CONDITIONS['farm_phone'](x + 0.02 * np.sin(np.arange(48000) / 9).astype(np.float32) * (i % 2), f'noise{i}')
        out.append({'id': f'noise{i}.farm_phone', 'source': 'noise', 'condition': 'farm_phone', 'text': '', 'keys': [], 'audio': y.astype(np.float32)})
    return out

def summarize(rows):
    groups = {}
    for r in rows: groups.setdefault((r['source'], r['condition']), []).append(r)
    lines = []
    for (src, cond), rs in sorted(groups.items()):
        if src == 'noise':
            lines.append(f'{src:7s} {cond:12s} n={len(rs):3d} hallucinated={sum(bool(norm(r["hyp"])) for r in rs)}'); continue
        wer = jiwer.wer([norm(r['text']) for r in rs], [norm(r['hyp']) or '-' for r in rs])
        keys = [h for r in rs for h in r['key_hits']]
        lat = np.percentile([r['ms'] for r in rs], [50, 95])
        lines.append(f'{src:7s} {cond:12s} n={len(rs):3d} WER={wer*100:5.1f}%' + (f' keys={np.mean(keys)*100:5.1f}%' if keys else ' ' * 12) + f'  p50={lat[0]:5.0f}ms p95={lat[1]:5.0f}ms')
    return '\n'.join(lines)

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('engine'); ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--sources', default='edacc,farmer,svarah'); ap.add_argument('--conditions', default='')
    ap.add_argument('--prompt', choices=['', 'domain'], default='')
    a = ap.parse_args()
    srcs = [s.strip() for s in a.sources.split(',') if s.strip()]
    src_tag = '-'.join(sorted(srcs))
    rows = [json.loads(l) for l in open(ART / 'corpus/manifest.jsonl')]
    rows = [r for r in rows if r['source'] in srcs and (not a.conditions or r['condition'] in a.conditions.split(','))]
    if a.limit:
        utts = list(dict.fromkeys(r['utt'] for r in rows))
        keep = {u for s in srcs for u in [u for u in utts if u.startswith(s)][:a.limit]}
        rows = [r for r in rows if r['utt'] in keep]
    rows += noise_clips()
    tag = a.engine.replace('/', '_').replace(':', '-') + ('+' + a.prompt if a.prompt else '')
    if src_tag and src_tag != 'edacc-farmer-svarah':
        tag += '__src_' + src_tag
    out_dir = ART / 'runs/asr'
    if src_tag == 'svarah':
        out_dir = out_dir / 'svarah'
    out = out_dir / (tag + '.jsonl'); out.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time(); eng = asr_engines.make(a.engine); load_s = time.time() - t0
    prompt = asr_engines.DOMAIN if a.prompt == 'domain' else None
    warm = sf.read(ART / 'corpus/wav' / (rows[0]['id'] + '.wav'), dtype='float32')[0]
    eng.transcribe([warm], prompt)
    done = []
    with open(out, 'w') as f:
        for r in rows:
            x = r.pop('audio', None)
            if x is None: x = sf.read(ART / 'corpus/wav' / (r['id'] + '.wav'), dtype='float32')[0]
            t = time.perf_counter(); hyp = eng.transcribe([x], prompt)[0]; ms = (time.perf_counter() - t) * 1000
            r.update(engine=a.engine, prompt=a.prompt, hyp=hyp, ms=round(ms, 1), key_hits=key_hits(r['keys'], hyp))
            f.write(json.dumps(r) + '\n'); done.append(r)
    cost = getattr(eng, 'cost', 0)
    head = f'== {tag}  load={load_s:.0f}s  clips={len(done)}' + (f'  cost=${cost:.4f}' if cost else '')
    s = head + '\n' + summarize(done)
    (out.with_suffix('.txt')).write_text(s + '\n'); print(s)

if __name__ == '__main__':
    main()
