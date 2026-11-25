"""Independent shell turns on a frozen group snapshot. Store transcripts outside Git."""
import contextlib
import datetime as dt
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import urllib.request
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]/'core'))
from lib import idlicli as cli, recstore as rs, privacy, minisql

CASES = json.loads((HERE/'cases.json').read_text())
# Annotated private slots in benchmark inputs, used only at the network boundary.
SLOTS = [('Insight Out','org'),('Jam Buns','group'),('Young Birders’ Month','event'),
         ('DICE','org'),('Rainmatter','org'),('CC','org'),('Abhi','person_name'),
         ('Vidya','person_name'),('V','person_name')]
CLOCK = dt.datetime(2026,11,22,19,45,tzinfo=rs.TZ)


def main():
    root = Path(sys.argv[1]).resolve()
    os.umask(0o077)
    os.environ.update(IDLI_9B_URL='http://127.0.0.1:8291', IDLI_SCANNER='http://127.0.0.1:8899/scan', IDLI_CHIPS='1')
    cli.ACCOUNTS['me']='fixture@example.invalid'
    orig_menu=cli.menu
    orig_classify=cli.classify
    real_open=urllib.request.urlopen
    for arm in sys.argv[2:] or ['stock','source','remote']:
        box=root/arm
        box.mkdir()
        shutil.copyfile(root/'base/store.duckdb',box/'store.duckdb')
        os.environ['IDLI_SANDBOX']=str(box)
        vault=privacy._session_map(str(box))
        codes={v:vault.token(v,t) for v,t in SLOTS}
        privacy._save(vault)
        with tempfile.TemporaryDirectory(dir=root) as temp:
            control=rs.connect(temp)
            db=rs.connect(box)
            for name,kind,sql,about in db.execute('select * from views').fetchall():
                cols=db.execute(f'describe {name}').fetchall()
                control.execute(f'create table {name} ('+', '.join(f'"{r[0]}" {r[1]}' for r in cols)+')')
                control.execute('insert into views values (?,?,?,?)',[name,kind,sql,about])
            db.close()
            for case in CASES:
                q=case['q']
                safe=q
                for v,code in codes.items():
                    safe=re.sub(r'(?<!\w)'+re.escape(v)+r'(?!\w)',code,safe)
                requests=[]
                allowed=[]
                def guard(req,*args,**kwargs):
                    if req.full_url.startswith(('http://127.0.0.1:8291/','http://127.0.0.1:8899/')):
                        return real_open(req,*args,**kwargs)
                    payload=json.loads(req.data)
                    if req.full_url=='https://openrouter.ai/api/v1/systemone' and payload.get('state')==safe and set(payload['questions'])=={'kind'}:
                        requests.append('clef-kind')
                    elif req.full_url==minisql.URL and payload.get('messages')==allowed and allowed:
                        requests.append('remote-map')
                    else:
                        requests.append('withheld')
                        raise ValueError('Outside reviewed input')
                    return real_open(req,*args,**kwargs)
                def menu(*args,**kw):
                    m=orig_menu(*args,**kw)
                    return '\n'.join(l for l in m.splitlines() if l.startswith(('Views (','Today is'))) if arm=='source' else m
                with patch.object(rs,'now',return_value=CLOCK), patch.object(cli,'menu',menu):
                    if arm=='remote':
                        def inspect(system,user,*a):
                            if ('Request: '+safe not in user or any(re.search(r'(?<!\w)'+re.escape(v)+r'(?!\w)',user,re.I) for v in codes if v!='V') or 'fixture@example.invalid' in user):
                                return {'cannot':'Payload did not pass review'}
                            allowed.extend([dict(role='system',content=system),dict(role='user',content=user)])
                            return {'cannot':'Preflight'}
                        with patch.object(cli,'_remote',inspect):
                            cli.map_question(control,q,[],'remote',str(box))
                    with (patch.object(cli,'classify',lambda _:orig_classify(safe)),patch.object(urllib.request,'urlopen',guard),
                          (box/(case['id']+'.txt')).open('w') as out, contextlib.redirect_stdout(out)):
                        rc=cli.main(['ask','--new','--mapper','remote' if arm=='remote' else 'nine_compressed','--judge','clef',q])
                    if rc: raise RuntimeError(f'Failed turn {arm} {case["id"]}')
                    e=json.loads((box/'log.jsonl').read_text().splitlines()[-1])
                    item=dict(id=case['id'],requests=requests,event=e)
                    with (box/'turns.jsonl').open('a') as out: out.write(json.dumps(item)+'\n')
                    print(arm,case['id'],e.get('kind'),requests,flush=True)
            control.close()


if __name__=='__main__':
    main()
