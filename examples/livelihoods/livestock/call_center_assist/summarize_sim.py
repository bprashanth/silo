"""Table of simulated-call results:  python summarize_sim.py <run-dir>..."""
import json, sys, statistics as st
from pathlib import Path
import numpy as np

def loops(d):
    c = [t['text'] for t in d['transcript'] if t['role'] == 'agent' and t['kind'] == 'content']
    return any(c[j] == c[j + 1] == c[j + 2] for j in range(len(c) - 2))

for run in sys.argv[1:]:
    rows = [json.load(open(f)) for f in sorted(Path(run).glob('*.json')) if f.name != 'summary.json']
    if not rows: continue
    passed = total = 0; resp = []; first = []; nlu = []; done = 0
    print(f'\n### {Path(run).name}\n\n| scenario | line | checks | turns | first sound p50 | reply p50 | fillers | barge-ins | re-prompts | missed |\n|---|---|---|---|---|---|---|---|---|---|')
    for d in rows:
        d['checks']['no_loops'] = not loops(d)
        p = sum(d['checks'].values()); passed += p; total += len(d['checks'])
        resp += d['response_s']; first += d['first_audio_s']; done += d['record']['call_status'] == 'completed'
        nlu += [m['nlu_ms'] for m in d['metrics'] if m.get('nlu_ms')]
        print(f"| {d['scenario']} | {d['condition']} | {p}/{len(d['checks'])} | {d['turns']} | {st.median(d['first_audio_s']):.2f} s | "
              f"{st.median(d['response_s']):.2f} s | {d['fillers']} | {d['barge_ins']} | {d['reprompts']} | {', '.join(k for k, v in d['checks'].items() if not v) or '—'} |")
    q = lambda xs: ' / '.join(f'{np.percentile(xs, p):.2f}' for p in (50, 90, 95))
    print(f'\n{len(rows)} calls, {done} completed and confirmed, {passed}/{total} checks. First sound p50/p90/p95 {q(first)} s; '
          f'reply {q(resp)} s; interpretation p50 {st.median(nlu):.0f} ms (p95 {np.percentile(nlu, 95):.0f} ms).')
