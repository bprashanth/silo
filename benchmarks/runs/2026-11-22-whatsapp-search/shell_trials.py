"""Exercise the production CLI entry point. Keep raw commands, responses and logs on the DGX."""
import contextlib
import json
import os
from pathlib import Path
import sys
import subprocess
from datetime import datetime
from unittest.mock import patch
from urllib.parse import urlsplit
import urllib.request

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / 'core'))
from lib import idlicli, recstore as rs

CLOCK = datetime(2026, 11, 10, 12, tzinfo=rs.TZ)
GENERIC = 'How many captured WhatsApp messages contain a link?'


def main():
    run = Path(sys.argv[1]).resolve()
    os.umask(0o077)
    os.environ['IDLI_9B_URL'] = 'http://127.0.0.1:8291'
    os.environ['IDLI_GOOGLE_ACCOUNT'] = 'fixture@example.invalid'
    idlicli.ACCOUNTS['me'] = 'fixture@example.invalid'
    if not (run/'nov10').exists():
        # Remove later messages from the historical store, including the group's activity timestamp.
        sample = json.loads((run/'live.json').read_text())
        for group in sample['groups']:
            group['rows'] = [m for m in group['rows'] if m['t'] <= CLOCK.timestamp()]
            group['active_at'] = max(m['t'] for m in group['rows'])
            group['fetched'] = len(group['rows'])
        sample['as_of'] = CLOCK.isoformat()
        fixture = run/'nov10.json'
        fixture.write_text(json.dumps(sample))
        subprocess.run([sys.executable, str(HERE.parent/'2026-11-22-whatsapp-groups/import_snapshot.py'),
                        str(fixture), str(run/'nov10')], check=True)
    for item in json.loads((HERE/'cases.json').read_text()):
        past = item['clock'] == 'nov10'
        box = run / ('nov10' if past else 'sandbox')
        os.environ['IDLI_SANDBOX'] = str(box)
        os.environ['IDLI_CHIPS'] = '1' if item.get('clef') else '0'
        real_open = urllib.request.urlopen

        def guarded(req, *args, **kwargs):
            host = urlsplit(req.full_url).hostname
            if host != '127.0.0.1':
                if req.full_url != 'https://openrouter.ai/api/v1/systemone' or not item.get('clef'):
                    raise RuntimeError('Unexpected external call')
                if json.loads(req.data)['state'] != GENERIC:
                    raise RuntimeError('Unexpected classifier input')
            return real_open(req, *args, **kwargs)

        clock = patch.object(rs, 'now', return_value=CLOCK) if past else contextlib.nullcontext()
        with (clock, patch.object(urllib.request, 'urlopen', guarded),
              (run/(item['id']+'.txt')).open('w') as stream, contextlib.redirect_stdout(stream)):
            rc = idlicli.main(['ask', '--judge', 'nine_compressed', '--mapper', 'nine_compressed',
                               *([] if item.get('continue') else ['--new']), item['question']])
        if rc:
            raise RuntimeError(f"CLI failed in {item['id']}")
        event = json.loads((box/'log.jsonl').read_text().splitlines()[-1])
        (run/(item['id']+'.json')).write_text(json.dumps(event))
        output = (run/(item['id']+'.txt')).read_text()
        print(item['id'], 'chip', event['kind'], 'struggle', event['struggled'],
              'offered remote', 'idli ask --mapper remote' in output, flush=True)


if __name__ == '__main__':
    main()
