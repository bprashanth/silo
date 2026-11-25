"""Score end-to-end unmodified core/idli ask trials (evidence recall + all 4 controls + telemetry)."""
import json
import sys
from pathlib import Path
from statistics import median

bank_path = Path(sys.argv[1]).expanduser()
out_dir = Path(sys.argv[2]).expanduser()
arms = sys.argv[3:] or ['core_rrf', 'core_rerank']

bank = json.loads(bank_path.read_text())


def complete(gold, ids):
    return all(set(alts).intersection(ids) for alts in gold)


for arm in arms:
    print(f'=== {arm} ===')
    for prefix, label in (('', 'pass1'), ('_repeat', 'repeat')):
        by_stratum = {}
        for idx, case in enumerate(bank):
            p = out_dir / f'{arm}{prefix}-{idx:02}.json'
            if not p.exists():
                continue
            item = json.loads(p.read_text())
            ev = item['event']
            st = case.get('stratum') or 'pos'
            if case.get('gold'):
                ok = complete(case['gold'], item['visible'])
                tot_s = (ev.get('seconds') or {}).get('total_s') or 0
                tel = ev.get('search_telemetry') or {}
                by_stratum.setdefault(st, []).append((idx, ok, tot_s, ev.get('commands') or [], tel.get('reranker_ms', 0)))
        for st, rows in by_stratum.items():
            passed = sum(1 for r in rows if r[1])
            missed = [r[0] for r in rows if not r[1]]
            med_s = round(median(r[2] for r in rows), 2)
            print(f'  {label:6s} {st:14s}: {passed}/{len(rows)} complete evidence (median {med_s}s) missed={missed}')
    # Inspect controls (cases without gold)
    print('  controls:')
    for idx, case in enumerate(bank):
        if case.get('gold'):
            continue
        p = out_dir / f'{arm}-{idx:02}.json'
        if not p.exists():
            continue
        item = json.loads(p.read_text())
        ev = item['event']
        cmds = ev.get('commands') or []
        reply = (ev.get('reply') or '').replace('\n', ' | ')[:220]
        print(f'    [{idx:02}] cmds={cmds} -> {reply}')
