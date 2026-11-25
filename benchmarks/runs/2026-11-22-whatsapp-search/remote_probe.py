"""Inspect the real masked mapper prompt locally. Release only a verified, fresh schema-only turn."""
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import shutil
import tempfile
from unittest.mock import patch
import urllib.request

from shell_trials import CLOCK, GENERIC, idlicli, rs
from lib import home, minisql, privacy

os.umask(0o077)
run = Path(sys.argv[1]).resolve()
os.environ.update(IDLI_SCANNER='http://127.0.0.1:8899/scan', IDLI_CHIPS='0', IDLI_9B_URL='http://127.0.0.1:8291')
idlicli.ACCOUNTS['me'] = 'fixture@example.invalid'
cases = {c['id']:c for c in json.loads((Path(__file__).with_name('cases.json')).read_text())}
box = run/'nov10'
con = rs.connect(box)
empty = tempfile.TemporaryDirectory(dir=run)
control = rs.connect(empty.name)
for name, kind, about in con.execute('select name,on_kind,about from views').fetchall():
    # Only the public column names/types and hand-authored view description enter the control.
    columns = con.execute(f'describe {name}').fetchall()
    control.execute(f'create table {name} (' + ', '.join(f'"{r[0]}" {r[1]}' for r in columns) + ')')
    control.execute('insert into views values (?,?,?,?)',[name,kind,'',about])
assert idlicli.menu(control) == idlicli.menu(con)
group, sender, url = con.execute("select group_name,sender,links from wa_messages where sender ilike '%rinj%' and links <> '' limit 1").fetchone()
msg = con.execute("select body from wa_messages where sender ilike '%rinj%' and body ilike 'include %' limit 1").fetchone()[0]
proposal_names = re.search(r'include (\w+) and (\w+)',msg,re.I).groups()


def capture(db, q, folder, hist=()):
    captured = []
    def intercept(system, user, *rest):
        captured.append((system,user))
        return {'cannot':'dry run'}
    with patch.object(idlicli,'_remote',intercept):
        idlicli.map_question(db,q,hist,'remote',str(folder))
    return captured[0]


def live_if_exact(task, q, clock):
    sandbox = run/{'generic':'sandbox','meeting':'nov10','seeded':'seeded'}[task]
    target = rs.connect(sandbox)
    os.environ['IDLI_SANDBOX'] = str(sandbox)
    with clock:
        expected = capture(target,q,sandbox)
        reference = capture(control,q,sandbox)
        assert expected == reference, 'Live private store changed the prompt relative to an empty schema'
        text = expected[1].casefold()
        forbidden = [group,sender,url,'fixture@example.invalid','rinj','jam buns',*proposal_names]
        if task!='generic':
            forbidden.append('CC')
        if any(re.search(r'(?<!\w)'+re.escape(v.casefold())+r'(?!\w)', text) for v in forbidden):
            print(task,'withheld: identity still present')
            return
        if task == 'seeded':
            # The only identity-bearing request literals must be the two reviewed local codes.
            safe_query=q.replace('Rinj', seed_codes['Rinj']).replace('CC', seed_codes['CC'])
            if 'Request: '+safe_query not in expected[1]:
                print(task, 'withheld: masked question differs from approved template')
                return
        approved = json.dumps(expected).encode()
        external = []
        original = urllib.request.urlopen
        def checked(req,*args,**kwargs):
            if req.full_url.startswith(('http://127.0.0.1:8291/', 'http://127.0.0.1:8899/')):
                return original(req,*args,**kwargs)
            data = json.loads(req.data)
            actual = tuple(m['content'] for m in data['messages'])
            if req.full_url != minisql.URL or json.dumps(actual).encode() != approved:
                raise ValueError('Follow-up prompt outside reviewed payload')
            external.append(hashlib.sha256(approved).hexdigest())
            return original(req,*args,**kwargs)
        target.close()
        with patch.object(urllib.request,'urlopen',checked), (run/f'remote-{task}.txt').open('w') as out, contextlib.redirect_stdout(out):
            rc = idlicli.main(['ask','--new','--mapper','remote','--judge','nine_compressed',q])
        event = json.loads((sandbox/'log.jsonl').read_text().splitlines()[-1])
        (run/f'remote-{task}.json').write_text(json.dumps(event))
        print(task,'live requests',len(external),'exit',rc,'needs',event.get('needs'),
              'commands',len(event.get('commands',[])),'errors',len(event.get('errors') or []))


if '--only-seeded' not in sys.argv:
    with patch.object(rs,'now',return_value=CLOCK):
        probe = run/'dry-vault'
        probe.mkdir(exist_ok=True)
        hist = [{'q':cases['meeting']['question'],'commands':[], 'shown':msg+' '+url+' '+group+' '+sender}]
        _, masked = capture(con, cases['meeting']['question'],probe,hist)
        for label, real in [('nickname','Rinj'),('group',group),('sender',sender),('shared URL',url),
                            ('full proposal text',msg),('proposal name 1',proposal_names[0]),('proposal name 2',proposal_names[1]),
                            ('account email','fixture@example.invalid')]:
            print('history probe',label,'visible' if real.casefold() in masked.casefold() else 'obscured')
        canary = 'Reach tester.q91@example.org or call +91 98765 43210.'
        masked = privacy.mask_account_text(str(probe),canary)
        print('canary email hidden','tester.q91@example.org' not in masked,'phone hidden','98765' not in masked,
              'rehydration exact',home.rehydrate(str(probe),masked)==canary)
    for task,q,clock in [('generic',GENERIC,contextlib.nullcontext()),
                         ('meeting',cases['meeting']['question'],patch.object(rs,'now',return_value=CLOCK))]:
        if 'idli ask --mapper remote' in (run/(task+'-repeat.txt')).read_text():
            live_if_exact(task,q,clock)
con.close()
if 'idli ask --mapper remote' in (run/'meeting-repeat.txt').read_text():
    seedbox = run/'seeded'
    seedbox.mkdir()
    shutil.copyfile(box/'store.duckdb',seedbox/'store.duckdb')
    # Diagnostic for this verified, explicitly selected pair of aliases, in a new conversation.
    v = privacy._session_map(str(seedbox))
    seed_codes={label:v.token(label,typ) for label,typ in [('Rinj','person_name'),('CC','group')]}
    privacy._save(v)
    live_if_exact('seeded',cases['meeting']['question'],patch.object(rs,'now',return_value=CLOCK))
control.close()
empty.cleanup()
