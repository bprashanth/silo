"""Try first-class message metadata in an isolated CLI process with local models only."""
import contextlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
from unittest.mock import patch
from shell_trials import CLOCK, idlicli, rs

os.umask(0o077)
run = Path(sys.argv[1])
box = run/'registered'
box.mkdir()
shutil.copyfile(run/'nov10/store.duckdb',box/'store.duckdb')
os.environ.update(IDLI_SANDBOX=str(box), IDLI_9B_URL='http://127.0.0.1:8291', IDLI_CHIPS='0')
rs.RESOURCES['wa_messages'] = dict(table='wa_messages',date='sent_at',kind='message',id='ref',
    text=['body','sender','group_name','links'],show=['ref','sent_at','sender','body','links'],
    about='one text message or shared link from a WhatsApp group conversation')
con=rs.connect(box)
con.execute("delete from views where name='wa_messages'")
truth=con.execute("select body from wa_messages where sent_at::date='2026-11-06' and body ilike 'include % and %' and sender ilike '%rinj%'").fetchone()[0]
names=re.search(r'include (\w+) and (\w+)',truth,re.I).groups()
link=con.execute("select links from wa_messages where sent_at::date='2026-11-06' and sender ilike '%rinj%' and links<>''").fetchone()[0]
cases=json.loads(Path(__file__).with_name('cases.json').read_text())
with patch.object(rs,'now',return_value=CLOCK):
    direct=idlicli.run_argv(con,['list','wa_messages','--on','last week','--where',"sender ILIKE '%rinj%'",
                                '--search','include','--fields','body'])
    print('dated resource direct match',direct.rows==[(truth,)])
    for case in [c for c in cases if c['id'] in ('meeting','receipt','explicit','unknown')]:
        with (run/('resource-'+case['id']+'.txt')).open('w') as f, contextlib.redirect_stdout(f):
            idlicli.main(['ask','--new','--mapper','nine_compressed','--judge','nine_compressed',case['question']])
        e=json.loads((box/'log.jsonl').read_text().splitlines()[-1])
        print(case['id'],'used WhatsApp','wa_messages' in str(e['commands']), 'both people',all(n.casefold() in e['reply'].casefold() for n in names),
              'exact link',link in e['reply'], 'question mark','?' in e['reply'])
con.close()
