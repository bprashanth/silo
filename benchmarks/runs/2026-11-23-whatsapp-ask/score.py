"""Score only complete returned evidence on positive cases. Controls need separate inspection."""
import json
from pathlib import Path
import sys
from statistics import median

run = Path(sys.argv[1])
bank = json.loads((run/'bank.json').read_text())
for arm in ('base','hybrid','guided','preview'):
    results = []
    for n, case in enumerate(bank):
        if not case['gold']: continue
        item = json.loads((run/f'{arm}-{n:02}.json').read_text())
        event = item['event']
        def complete(ids):
            return all(set(alternatives).intersection(ids) for alternatives in case['gold'])
        results.append((case['stratum'],complete(item['packet']),complete(item['visible']),
                        any('wa_candidates' in c for c in event['commands']),event['seconds']['total_s']))
    for group in ('prior','new'):
        subset=[r for r in results if r[0]==group]
        if not subset: continue
        print(arm, group, 'n',len(subset),'packet, shown, used',*[sum(r[i] for r in subset) for i in (1,2,3)],
              'median ask seconds',median(r[-1] for r in subset))
