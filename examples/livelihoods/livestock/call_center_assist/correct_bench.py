"""Apply correct.py to a finished ASR run and rescore.  python correct_bench.py <run-tag>"""
import json, os, sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, str(Path(__file__).parent))
import asr_bench, correct
ART = Path(os.getenv('VR_ART', '/mnt/seagate/silo/voice-robust'))
tag = sys.argv[1]; rows = [json.loads(l) for l in open(ART / 'runs/asr' / (tag + '.jsonl'))]
def fix(r):
    c = correct.correct(r['hyp']); r = dict(r, raw_hyp=r['hyp'], hyp=c['text'], ms=r['ms'] + c['ms'], candidates=c['candidates'])
    r['key_hits'] = asr_bench.key_hits(r['keys'], r['hyp']); return r
with ThreadPoolExecutor(2) as ex: out = list(ex.map(fix, rows))
p = ART / 'runs/asr' / (tag + '+correct.jsonl'); p.write_text(''.join(json.dumps(r) + '\n' for r in out))
s = f'== {tag}+correct (Muse)\n' + asr_bench.summarize(out); p.with_suffix('.txt').write_text(s + '\n'); print(s)
changed = [r for r in out if r['hyp'] != r['raw_hyp']]
print(len(changed), 'changed'); [print(' ', r['raw_hyp'], '->', r['hyp']) for r in changed[:40]]
