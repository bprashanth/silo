"""Verify person resolution, a direct CLI look-up, and a single-message extraction against the group source."""
import json
import os
from pathlib import Path
import re
import sys
from shell_trials import idlicli, rs, CLOCK

os.umask(0o077)
run = Path(sys.argv[1])
os.environ['IDLI_9B_URL'] = 'http://127.0.0.1:8291'
con = rs.connect(run/'nov10',read_only=True)
a,b=rs.day_range('last week',CLOCK.date())
period=f"sent_at >= '{a}' AND sent_at < '{b}'"
group="group_name ILIKE '%jam buns%'"
for nickname in ['rinj','rynzz']:
    matches=idlicli.run_argv(con,['list','wa_messages','--where',f"{group} AND {period} AND sender ILIKE '%{nickname}%'",
                                  '--group-by','sender'])
    print(nickname, 'candidate senders',len(matches.rows))
hits=idlicli.run_argv(con,['list','wa_messages','--search','include','--where',
                          f"{group} AND {period} AND sender ILIKE '%rinj%'",'--fields','ref,sent_at,sender,body'])
assert len(hits.rows)==1
ref,t,sender,body=hits.rows[0]
names=re.search(r'include (\w+) and (\w+)',body,re.I).groups()
schema={'type':'object','properties':{'quote':{'type':'string'},'status':{'type':'string','enum':['proposed','decided','unclear']}},
        'required':['quote','status']}
answer=rs._nine([{'role':'system','content':'Quote the source verbatim in full. Classify only what this speaker said in this message: proposing inclusion, a decision, or unclear.'},
                 {'role':'user','content':body}],schema)
print('narrow extraction exact quote',answer['quote'].strip()==body.strip(),'status',answer['status'])
links=idlicli.run_argv(con,['list','wa_messages','--where',f"{group} AND sent_at::date='2026-11-06' AND sender ILIKE '%rinj%' AND links <> ''",
                           '--fields','ref,sent_at,sender,links'])
assert len(links.rows)==1
raw=json.loads((run/'live.json').read_text())['groups'][0]['rows']
assert sum(r['body']==body and r['sender']==sender for r in raw)==1
assert any(links.rows[0][3] in r['body'] and r['sender']==sender for r in raw)
(run/'meeting-receipt.txt').write_text(f'{t} IST | {sender} | {ref}\n{body}\n\n'
    f'This is the suggested pair in the source. Subsequent discussion should be checked for a final decision.\n\n'
    f'Link posted by the same sender on November 6 (purpose unverified):\n{links.rows[0][3]}\n')
print('proposal and link verified against fresh raw source')
