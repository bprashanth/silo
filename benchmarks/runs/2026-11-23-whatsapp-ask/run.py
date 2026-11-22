"""Paired real ask turns; all fixture data, expected references and traces live outside Git."""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
from collections import Counter
import numpy as np

root = Path(__file__).resolve().parents[3]
sys.path.insert(0,str(root/'core'))
from lib import recstore as rs

fixture, trial = map(Path, sys.argv[1:3])
arm = sys.argv[3]
os.umask(0o077)
os.environ.update(IDLI_SANDBOX=str(trial/arm), IDLI_9B_URL='http://127.0.0.1:8291', IDLI_CHIPS='0')
groups = json.loads((fixture/'fresh.json').read_text())['groups']
rows, bursts, near, parents = [], [], {}, {}
for g in groups:
    ordered = sorted(g['rows'],key=lambda r:(r['t'],r['id']))
    offset = len(rows)
    for n,r in enumerate(ordered):
        i = offset+n
        rows.append(dict(r,group=g['name'],ref=hashlib.sha256(r['id'].encode()).hexdigest()[:20]))
        near[i] = list(range(offset+max(0,n-2),offset+min(len(ordered),n+3)))
        if n==0 or len(bursts[-1])>=5 or r['t']-ordered[n-1]['t']>300:
            bursts.append([])
        bursts[-1].append(i)
    parents.update({r['id']:r['parent'] for r in g['relations'] if r['parent']})
index = {r['id']:i for i,r in enumerate(rows)}
def words(s):
    return set(re.findall(r'\w+',s.casefold()))-rs.STOP
terms = [words(r['body']) for r in rows]
freq = Counter(w for term in terms for w in term)
if arm!='base':
    vectors=np.load(fixture/'messages.npy')
    burst_vectors=np.load(fixture/'bursts.npy')

def prepare(q):
    qw=words(q)
    # A unique longest group-name overlap of two or more tokens binds the group.
    scores=[(len(qw & words(g['name'])),g['name']) for g in groups]
    top=max(n for n,_ in scores)
    matches=[g for n,g in scores if n==top and n>=2]
    group=matches[0] if len(matches)==1 else None
    ids=[i for i,r in enumerate(rows) if not group or r['group']==group]
    text=' '.join(w for w in q.split() if not group or w.lower() not in group.lower().split()) or q
    vec=np.asarray(rs.embed([text],query=True)[0])
    sem=sorted(zip(vectors[ids]@vec,ids),reverse=True)
    query=words(text)
    lex=sorted(ids,key=lambda i:sum(math.log((1+len(rows))/(1+freq[w])) for w in query & terms[i]),reverse=True)
    bs=[n for n,b in enumerate(bursts) if not group or rows[b[0]]['group']==group]
    br=sorted(zip(burst_vectors[bs]@vec,bs),reverse=True)
    ranks=Counter()
    for seq in ([i for _,i in sem],lex,[i for _,b in br for i in bursts[b]]):
        for k,i in enumerate(seq[:40]):ranks[i]+=1/(10+k)
    hits=[i for i,_ in ranks.most_common(12)]
    selected=dict.fromkeys(hits,'match')
    for i in hits:
        parent=index.get(parents.get(rows[i]['id']))
        if parent is not None:selected.setdefault(parent,'quoted parent')
        for j in near[i]:selected.setdefault(j,'neighbor')
    con=rs.connect(trial/arm)
    con.execute('create or replace table wa_packet(rank integer, ref varchar, group_name varchar, sender varchar, body varchar, relation varchar, sent_at timestamp)')
    con.executemany("insert into wa_packet select ?,ref,group_name,sender,body,?,sent_at from wa_messages where ref=?",[(n,relation,rows[i]['ref']) for n,(i,relation) in enumerate(selected.items(),1)])
    con.execute("create or replace view wa_candidates as select * from wa_packet order by rank")
    con.execute("insert or replace into views values ('wa_candidates','message','select * from wa_packet order by rank','WhatsApp messages ranked for this request using words and meaning, including quoted and nearby messages. Read the matches with idli list wa_candidates --order rank --limit 12. Use wa_messages for counts.')")
    if arm=='guided':
        # Expose measured source availability and actual binding. Include no expected answers.
        counts = {table:con.execute(f'select count(*) from {table}').fetchone()[0]
                  for table in ('files','mail','events','wa_messages')}
        info = (f"Record counts {counts}. Ranked WhatsApp search already ran on this request"
                + (f" inside group {group!r}" if group else " across the captured groups")
                + ". Inspect using idli list wa_candidates --fields 'ref, sender, body' --order rank --limit 12"
                + " before applying any extra filters. Use wa_messages for exhaustive counts.")
        con.execute("update views set about=? where name='wa_candidates'",[info])
    con.close()
    return list(selected)

for n,case in enumerate(json.loads((trial/'bank.json').read_text())):
    path=trial/f'{arm}-{n:02}.json'
    if path.exists():continue
    packet=prepare(case['q']) if arm!='base' else []
    log=trial/arm/'log.jsonl'
    before=log.stat().st_size if log.exists() else 0
    result=subprocess.run([root/'core/idli','ask','--new','--mapper','nine_compressed','--judge','nine_compressed',case['q']],capture_output=True,text=True,timeout=240)
    with log.open('rb') as f:
        f.seek(before)
        events=[json.loads(l) for l in f if l.strip()]
    event=next(e for e in reversed(events) if e['verb']=='ask')
    shown=event.get('steps_shown') or ''
    # Only visible refs or an identifying body excerpt in tool results count.
    visible=[i for i,r in enumerate(rows) if r['ref'] in shown or (len(r['body'])>=28 and r['body'][:70] in shown)]
    path.write_text(json.dumps(dict(event=event,visible=visible,packet=packet,returncode=result.returncode)))
    print(arm,n,flush=True)
