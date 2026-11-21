"""Local home, chart views and script Minis. No model is used for privacy review."""
import csv
import json
import time
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import urllib.parse
import urllib.request
import uuid

from lib import privacy, filekit, muse
from lib.minimap import params_for, map_questions, plain  # noqa: F401  (light: the router uses them)

_SEND_LOCK = threading.Lock()


def inside(root, name, exists=True):
    root = Path(root).resolve()
    path = (root / name).resolve()
    if path == root or not path.is_relative_to(root) or (exists and not path.is_file()):
        raise ValueError('File must be inside its workspace folder')
    return path


def work_dir(data_dir=None):
    """Claude's folder of masked copies. A team (Start here > Teams) has its own, beside Drivey's (lib/teams.py)."""
    if os.environ.get('IDLI_CLAUDE_WORK'):
        return Path(os.environ['IDLI_CLAUDE_WORK']).expanduser().resolve()
    if data_dir is not None:
        from lib import teams
        team = teams.team_dir(data_dir)
        if team:
            return Path(teams.claude_work(team)).resolve()
    return Path('~/idli-insights/claude-masked').expanduser().resolve()


def allowed_path(data_dir, name):
    for root in (work_dir(data_dir), Path(data_dir).resolve()):
        try:
            return inside(root, name)
        except ValueError:
            pass
    raise ValueError('File must be inside the Claude work folder or data directory')


def write(path, obj):
    privacy._write(Path(path), obj)


def read(path):
    return json.loads(Path(path).read_text())


def update_state(data_dir, change):
    """Keep workspace records intact across the MCP, page server and download processes."""
    with privacy.session_lock(data_dir):
        path = inside(data_dir, '.idli/home.json', exists=False)
        state = read(path) if path.exists() else {}
        change(state)
        write(path, state)
        return state


def search(data_dir, query):
    from lib import driveindex
    results = []
    drive = Path(data_dir) / 'drive'
    for path in sorted(drive.rglob('*.xlsx')):
        if query.casefold() not in str(path.relative_to(drive)).casefold():
            continue
        try:
            rel = str(inside(data_dir, path).relative_to(Path(data_dir).resolve()))
        except ValueError:
            continue
        results.append({'title': path.stem, 'local': rel, 'folder': 'on this computer'})
    hits = driveindex.search(query, limit=12)
    for hit in hits.get('results', []):
        if hit.get('kind') not in ('sheet', 'spreadsheet', 'xlsx', 'application/vnd.google-apps.spreadsheet',
                                   'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'Google Sheets', 'Microsoft Excel'):
            continue
        results.append({'id': hit['id'], 'title': hit['name'], 'folder': hit.get('folder', ''),
                        'sheet': hit.get('kind') != 'Microsoft Excel'})
    return {'results': results[:24]}


def selected(data_dir, files, fetch=False):
    if not isinstance(files, list) or not files:
        raise ValueError('Choose at least one file')
    root = Path(data_dir).resolve()
    out = []
    for item in files:
        if item.get('local'):
            path = inside(root, item['local'])
            if not path.is_relative_to(root / 'drive') or path.suffix.lower() not in ('.xlsx', '.csv'):
                raise ValueError('Choose a spreadsheet in drive/')
        elif fetch and item.get('id'):
            from lib import drivefetch
            fid = str(item['id'])
            if not re.fullmatch(r'[\w-]+', fid):
                raise ValueError('Invalid Drive id')
            title = re.sub(r'[^\w .()-]+', '_', str(item.get('title') or fid)).strip(' .')[:80] or fid
            if title.lower().endswith('.xlsx'):
                title = title[:-5]
            path = inside(root, 'drive/' + title + '.xlsx', exists=False)
            if path.exists() and (not Path(str(path) + '.source.json').exists()
                                  or read(str(path) + '.source.json').get('id') != fid):
                path = inside(root, 'drive/' + title + '-' + fid[:12] + '.xlsx', exists=False)
                if path.exists() and (not Path(str(path) + '.source.json').exists()
                                      or read(str(path) + '.source.json').get('id') != fid):
                    raise ValueError('Another file already uses that download name')
            data = drivefetch.fetch(fid, item.get('sheet', True))
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
            try:
                tmp.write_bytes(data)
                os.replace(tmp, path)
            finally:
                tmp.unlink(missing_ok=True)
            write(str(path) + '.source.json', {'id': fid, 'url': ('https://docs.google.com/spreadsheets/d/' if item.get('sheet', True)
                                                       else 'https://drive.google.com/file/d/') + fid,
                                                   'sheet': item.get('sheet', True)})
        else:
            raise ValueError('Prepare these files before sending')
        rel = path.relative_to(root).as_posix()
        if not any(x['local'] == rel for x in out):
            out.append({'title': item.get('title') or path.stem, 'local': rel,
                        **({'id': item['id']} if item.get('id') else {})})
    return out


def _read_by_extension(data_dir, rel):
    """A table a team's reader made from a photo, recording or document (lib/teamcaps.py): its column names say
    little about what the columns hold, so every text column starts hidden (narrative/MODEL_TYPES.md)."""
    try:
        return bool(read(Path(data_dir) / (rel + '.source.json')).get('read_by'))
    except (OSError, ValueError):
        return False


def _marks_or_numbers(frame, column):
    """Numbers (92.8%, 1,236, Rs 500, 2005), or short marks such as P / A / Y / N, which are safe to leave visible.
    Up to three heading cells at the top of a column ("1990", "Non SC/ST") don't count against it."""
    try:
        values = [str(v).strip() for v in frame[column].tolist() if str(v).strip() not in ('', 'nan', 'None')]
    except KeyError:
        return False

    def number(v):
        if re.fullmatch(r'\+?\d[\d -]{7,}', v):  # phone, Aadhaar and other ID numbers are never "safe numbers"
            return False
        v = re.sub(r'^(?:rs\.?|inr|₹)\s*|\s*%$', '', v.lower()).replace(',', '').replace(' ', '')
        return bool(re.fullmatch(r'[-+]?\d+(?:\.\d+)?', v))

    def ok(v):
        return len(v) <= 2 or number(v)
    bad = [i for i, v in enumerate(values) if not ok(v)]  # heading cells may only sit in the first three rows
    return bool(values) and all(i < 3 for i in bad) and len(bad) * 2 < len(values)


def prepare(data_dir, files, question):
    chosen = selected(data_dir, files, fetch=True)
    with privacy.session_lock(data_dir):
        for item in chosen:
            rel = item['local']
            if privacy.get(data_dir, rel)['mode'] != 'mask':
                sheets, _ = filekit.raw_sheets(str(Path(data_dir) / rel))
                columns = {}
                strict = _read_by_extension(data_dir, rel)
                for tab in sheets:
                    for row in privacy.suggest(Path(data_dir) / rel, tab):
                        # A reader's table: text columns start hidden, and a column of plain numbers or marks stays
                        # visible even when its heading sounds like a person ("...of enterprise owner")
                        mask = (not _marks_or_numbers(sheets[tab], row['column'])) if strict else row['mask']
                        columns[row['column']] = columns.get(row['column'], False) or mask
                privacy.set(data_dir, rel, mode='mask', review='ask', columns=columns)
        # Seed all files before masking: the namespace and the question span every workbook.
        privacy.session_vault(data_dir)
        masked = str(question)
        reviews = []
        for item in chosen:
            rel, path = item['local'], Path(data_dir) / item['local']
            masked = privacy.mask_text(data_dir, rel, path, masked, active=True)['masked']
            sheets, _ = filekit.raw_sheets(str(path))
            reviews.append({**item, 'tabs': [privacy.review(data_dir, rel, path, tab) for tab in sheets]})
        result = {'files': chosen, 'reviews': reviews, 'masked_question': masked,
                  'warning': privacy.review_warning(data_dir, [x['local'] for x in chosen])}
    # Claude's folder gets masked copies of the reviewed files (never the real ones).
    from lib import maskcopy
    maskcopy.build(data_dir, work_dir(data_dir))
    return result


def rehydrate(data_dir, obj):
    """Real values for the person's own screen: every code in keys and string values."""
    vault = privacy.session_vault(data_dir)
    def walk(v):
        if isinstance(v, str):
            return vault.rehydrate(v)
        if isinstance(v, list):
            return [walk(x) for x in v]
        if isinstance(v, dict):
            return {walk(k): walk(x) for k, x in v.items()}
        return v
    return walk(obj)


def cli(*args):
    env = {k: v for k, v in os.environ.items() if not k.startswith('PASEO_') or k == 'PASEO_HOME'}
    r = subprocess.run([shutil.which('paseo') or 'paseo', *args], env=env, capture_output=True,
                       text=True, timeout=90, stdin=subprocess.DEVNULL)
    if r.returncode:
        raise ValueError('Paseo could not complete the request')
    return r.stdout


def chat_workspace():
    if os.environ.get('IDLI_WORKSPACE'):
        return os.environ['IDLI_WORKSPACE']
    agent = os.environ.get('PASEO_AGENT_ID')
    if agent:
        return _agent_workspace(agent)
    return None


_AGENT_WS = Path.home() / '.cache' / 'idli' / 'agent-workspaces.json'


def _agent_workspace(agent):
    """The Drivey workspace a left chat belongs to. Paseo's JSON omits labels and workspace ids for agents, but its
    label filter works: try each workspace that has a Claude terminal (newest first) and remember the answer."""
    try:
        known = json.loads(_AGENT_WS.read_text())
    except (OSError, ValueError):
        known = {}
    if known.get(agent):
        return known[agent]
    terminals = json.loads(cli('terminal', 'ls', '--all', '--json'))
    seen = []
    for t in reversed(terminals if isinstance(terminals, list) else []):
        w = t.get('workspaceId')
        if w and w not in seen and t.get('name') == 'Claude':
            seen.append(w)
    for w in seen:
        chats = json.loads(cli('ls', '--json', '--label', 'idli.ws=' + w))
        if isinstance(chats, dict):
            chats = chats.get('agents', [])
        if any((c.get('id') or c.get('agentId')) == agent for c in chats):
            known[agent] = w
            try:
                _AGENT_WS.parent.mkdir(parents=True, exist_ok=True)
                _AGENT_WS.write_text(json.dumps(known))
            except OSError:
                pass
            return w
    return None


LAUNCHER = Path(__file__).resolve().parent.parent / 'desktop' / 'claude-masked.sh'


def type_into(terminal, text):
    """Type one line into a terminal and press Enter (the person's Claude CLI)."""
    cli('terminal', 'send-keys', '-l', terminal, ' '.join(str(text).split()))
    cli('terminal', 'send-keys', '-l', terminal, '\r')


def left_chat(workspace):
    if not isinstance(workspace, str) or not re.fullmatch(r'[\w-]{1,80}', workspace):
        raise ValueError('Invalid workspace')
    chats = json.loads(cli('ls', '--json', '--label', 'idli.ws=' + workspace))
    if isinstance(chats, dict):
        chats = chats.get('agents', [])
    # Paseo has already filtered by workspace; older versions omit labels in JSON.
    left = next((c for c in chats if (c.get('labels') or {}).get('idli.left') == '1'), None) or next(
        (c for c in chats if str(c.get('provider', '')).startswith('t4gc-cowork')), None) or (chats[0] if chats else None)
    if not left:
        raise ValueError('No left chat in this workspace')
    return left.get('id') or left['agentId']


def claude_insert(data_dir, workspace, text):
    """Insert chart context into this workspace's existing Claude, leaving it unsubmitted."""
    from lib import uiswitch
    if not isinstance(workspace, str) or not re.fullmatch(r'[\w-]{1,80}', workspace):
        raise ValueError('Invalid workspace')
    if (not isinstance(text, str) or not text.strip() or len(text) > 16000
            or any(ord(c) < 32 or ord(c) == 127 for c in text)):
        raise ValueError('Supply one line of chart context')
    with _SEND_LOCK:
        tid = _claude_terminal(data_dir, workspace)
        if not tid:
            raise ValueError('No Claude terminal in this workspace')
        cli('terminal', 'send-keys', '-l', tid, text)
    shown = uiswitch.show_terminal(workspace, tid, 'right')
    return {'inserted': True, 'terminal': tid, 'focused': bool(shown.get('ok'))}


def _drivey_workspace(data_dir, workspace=''):
    workspaces = json.loads(cli('workspace', 'ls', '--json'))
    mine = [w for w in workspaces if Path(w.get('cwd') or '.').expanduser().resolve() == Path(data_dir).resolve()]
    if workspace and any(w.get('workspaceId') == workspace for w in mine):
        return workspace
    if workspace or not mine:
        raise ValueError('Open this chat in its Drivey workspace and try again.')
    return sorted(mine, key=lambda w: w.get('name') != 'Drivey')[0]['workspaceId']


def _claude_terminal(data_dir, wid):
    """The live Claude terminal recorded for this workspace, or None."""
    state_path = Path(data_dir) / '.idli/home.json'
    state = read(state_path) if state_path.exists() else {}
    tid = (state.get('terminals') or {}).get(wid) or (state.get('terminal') if state.get('workspace') == wid else None)
    terms = json.loads(cli('terminal', 'ls', '--all', '--json') or '[]')
    live = {t.get('id') or t.get('terminalId') for t in terms
            if (t.get('workspaceId') or t.get('workspace')) == wid}
    if tid in live:
        return tid
    # Drivey's "+" (Paseo P18) starts the Claude terminal itself: use that one
    return next((t.get('id') or t.get('terminalId') for t in terms
                 if (t.get('workspaceId') or t.get('workspace')) == wid and t.get('name') == 'Claude'), None)


def _remember(data_dir, wid, tid, **more):
    def change(state):
        state.setdefault('terminals', {})[wid] = tid
        state.update(terminal=tid, workspace=wid, **more)
    update_state(data_dir, change)


def _start_claude(wid, prompt=None):
    import shlex
    made = json.loads(cli('terminal', 'create', '--workspace', wid, '--name', 'Claude', '--json'))
    tid = made.get('id') or made.get('terminalId')
    if not tid:
        raise ValueError('Paseo did not create a terminal')
    cmd = 'IDLI_WORKSPACE=' + shlex.quote(wid) + ' exec ' + shlex.quote(str(LAUNCHER)) + (' ' + shlex.quote(prompt) if prompt else '')
    cli('terminal', 'send-keys', '-l', tid, cmd)
    cli('terminal', 'send-keys', '-l', tid, '\r')
    return tid


def ensure_claude(data_dir, workspace=''):
    """Idli home opened in a Drivey workspace: make sure the person's Claude CLI is running on the right (without
    taking focus from Idli home)."""
    from lib import uiswitch
    with _SEND_LOCK:
        wid = _drivey_workspace(data_dir, workspace)
        tid = _claude_terminal(data_dir, wid) or _start_claude(wid)
        _remember(data_dir, wid, tid)
    shown = uiswitch.show_terminal(wid, tid, 'right', focus=False)
    return {'terminal': tid, 'placed': bool(shown.get('ok'))}


def send(data_dir, files, question, workspace=''):
    """Hand the question to the person's Claude Code CLI in this Drivey workspace (desktop/claude-masked.sh, through
    the masking proxy), on the right with focus: typed into it, or started with it if it isn't running."""
    from lib import uiswitch
    chosen = selected(data_dir, files)
    if not str(question).strip():
        raise ValueError('Write a question first')
    if any(privacy.get(data_dir, x['local'])['mode'] != 'mask' for x in chosen):
        raise ValueError('Choose Mask for these files before sending to Claude')
    with _SEND_LOCK:
        wid = _drivey_workspace(data_dir, workspace)
        prompt = ('Files (masked by Idli): ' + ', '.join(x['local'] for x in chosen) + '. ' + ' '.join(str(question).split()))
        tid = _claude_terminal(data_dir, wid)
        if tid:
            type_into(tid, prompt)
        else:
            tid = _start_claude(wid, prompt)
        _remember(data_dir, wid, tid, files=chosen)
        update_state(data_dir, lambda state: state.setdefault('workspace_files', {}).update({wid: chosen}))
    shown = uiswitch.show_terminal(wid, tid, 'right')
    return {'terminal': tid, 'focused': bool(shown.get('ok')), 'message': 'Claude has it on the right'}


def object_path(data_dir, kind, ident):
    if not re.fullmatch(r'[\w-]{1,100}', str(ident)):
        raise ValueError('Invalid id')
    return inside(data_dir, f'{kind}/{ident}.json' if kind == 'views' else f'minis/{ident}/mini.json')


def minis(data_dir):
    out = []
    for path in sorted((Path(data_dir) / 'minis').glob('*/mini.json')):
        try:
            m = read(object_path(data_dir, 'minis', path.parent.name))
            # Minis saved before date/author were recorded: the file's date, and the same author rule Claude uses
            date = m.get('date') or time.strftime('%Y-%m-%d', time.localtime(path.stat().st_mtime))
            author = m.get('author')
            if not author:
                from lib import idli_mcp
                author = idli_mcp.mini_author()
            out.append({'id': path.parent.name, 'name': plain(m['name']), 'goal': plain(m['goal']),
                        'heading': plain(m.get('heading') or m['goal']), 'date': date,
                        'author': plain(author or ''), 'questions': len(m['questions'])})
        except (OSError, ValueError, KeyError):
            continue
    return out


def view(data_dir, ident):
    v = read(object_path(data_dir, 'views', ident))
    path = allowed_path(data_dir, v['data_csv'])
    if path.suffix.lower() != '.csv':
        raise ValueError('Charts require a CSV file')
    with path.open(newline='') as f:
        data = list(csv.DictReader(f))
    return {**v, 'id': ident, 'data': data}


def chart_sources(data_dir, sources=None):
    if sources is None:
        return []
    if not isinstance(sources, list) or any(not isinstance(s, str) for s in sources):
        raise ValueError('Sources must be a list of files in drive/')
    root = Path(data_dir).resolve()
    return list(dict.fromkeys(str(inside(root / 'drive', root / s).relative_to(root)) for s in sources))


def run_mini(data_dir, ident, qid, params):
    return run_manifest(data_dir, object_path(data_dir, 'minis', ident), qid, params)


def _sandbox(data_dir):
    try:
        return json.loads((Path(data_dir) / 'team.json').read_text()).get('kind') == 'sandbox'
    except (OSError, ValueError):
        return False


def run_manifest(data_dir, manifest, qid, params, preview=False):
    m = read(manifest)
    q = next((q for q in m['questions'] if q['id'] == qid), None)
    if not q:
        raise ValueError('Unknown Mini question')
    values = params_for(q, params)
    script = inside(manifest.parent, q['script'])
    if script.suffix != '.py':
        raise ValueError('Mini scripts must be Python files')
    args = [sys.executable, '-I', str(script)]
    for key, value in values.items():
        args.extend(['--' + key, str(value)])
    env = {k: v for k, v in os.environ.items() if not k.startswith('PASEO_')}
    # A sandbox's Mini may call its blocks (lib/blocks.py): it finds them through these
    env.update({'IDLI_COWORK': str(Path(__file__).resolve().parent.parent), 'IDLI_SANDBOX': str(Path(data_dir))})
    if (m.get('active') or {}).get('since'):  # turned on for an account from a day (lib/minitalk.py)
        env['IDLI_SINCE'] = str(m['active']['since'])
    if preview:  # a check before saving: an action Mini reads the accounts but writes nothing (lib/blocks.preview)
        env['IDLI_PREVIEW'] = '1'
        env.pop('IDLI_PREVIEW_LOG', None)
    # A sandbox's action Mini asks the private model about each reply (lib/blocks.nine_b): give it longer
    limit = 300 if _sandbox(data_dir) else 60
    try:
        r = subprocess.run(args, cwd=manifest.parent, env=env, capture_output=True, text=True, timeout=limit,
                           stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise ValueError(f'This question took longer than {limit // 60} minutes' if limit > 60 else
                         'This question took longer than 60 seconds') from None
    if r.returncode:
        raise ValueError('The Mini script failed. Ask Claude to check it.')
    lines = r.stdout.rstrip().splitlines()
    chart = None
    if lines:
        try:
            last = json.loads(lines[-1])
            if isinstance(last, dict) and isinstance(last.get('vega_lite'), dict) and isinstance(last.get('data'), list):
                chart = last
                lines.pop()
        except ValueError:
            pass
    return {'text': '\n'.join(lines), 'chart': chart, 'qid': qid, 'params': values, 'agent': m.get('agent'),
            'sources': chart_sources(data_dir, [f['local'] for f in m.get('files', []) if f.get('local')]),
            'script': str(script)}


def map_question(data_dir, ident, text):
    return map_questions(read(object_path(data_dir, 'minis', ident))['questions'], text)


def chart_markdown(data_dir, title, chart, agent=None, sources=None, script=None, workspace=None):
    """Save one computed chart as both a local SVG and an interactive view."""
    if not chart:
        return ''
    sources = chart_sources(data_dir, sources)
    script = str(allowed_path(data_dir, script)) if script else None
    import copy
    import vl_convert
    from lib import formserver
    ident = uuid.uuid4().hex
    title = plain(title)
    def clean(value):
        if isinstance(value, dict):
            return {plain(k): clean(v) for k, v in value.items() if k not in ('url', 'href', 'datasets')}
        if isinstance(value, list):
            return [clean(v) for v in value]
        return plain(value) if isinstance(value, str) else value
    spec = clean(copy.deepcopy(chart['vega_lite']))
    rows = clean(chart['data'])
    # Computed rows are authoritative. Never load external URLs from a Mini's spec.
    spec['data'] = {'values': rows}
    svg = vl_convert.vegalite_to_svg(json.dumps(spec))
    out = inside(data_dir, 'views/' + ident + '.svg', exists=False)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(svg)
    csv_path = out.with_suffix('.csv')
    keys = list(dict.fromkeys(k for row in rows for k in row))
    with csv_path.open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)
    write(out.with_suffix('.json'), {'title': title, 'spec': spec,
                                    'data_csv': str(csv_path), 'agent': agent, 'sources': sources, 'script': script,
                                    'workspace': workspace})
    port, token = formserver.ensure(str(data_dir))
    url = f'http://dashboard.localhost:{port}/view?' + urllib.parse.urlencode({'id': ident, 't': token})
    label = title.replace('[', '').replace(']', '').replace('\n', ' ')
    return f'![{label}]({out})\n[Open interactive]({url})'


BINDER_KINDS = {'Chart': 'view', 'Mini draft': 'mini-card', 'Run': None,  # Run: Sandbox Claude's script_try output
                'Try': None}  # Try: its two consent gates (lib/tries.py)


def binder_item(data_dir, kind, title, workspace=None, answer=None):
    """The newest chart or Mini draft from Claude with this title, as a page the left chat shows inline (its "binder":
    charts in order, each with Pin, then the editable Mini draft). kind "Try": a script_try's gates (lib/tries.py)."""
    from lib import journey
    if kind not in BINDER_KINDS:
        raise ValueError('Unknown item')
    if kind == 'Try':
        from lib import tries
        m = re.search(r'\[(\d{6,20})\]\s*$', str(title))
        return tries.left(data_dir, m[1] if m else str(title).strip(), answer)
    def key(t):
        return ' '.join(plain(str(t)).split())[:160]
    title = key(title)
    if kind == 'Run':  # a script Sandbox Claude ran: the real output, here only (Claude got it masked)
        from lib import minitalk
        for path in sorted((Path(data_dir) / '.idli/runs').glob('*.json'), key=lambda p: p.stat().st_mtime,
                           reverse=True):
            run = read(path)
            if key(run.get('title', '')) == title and (not workspace or run.get('workspace') in (workspace, None)):
                out = str(run.get('output') or '').strip() or '(no output)'
                lines = [f'**{title}**', '', '```', out[-5000:], '```']
                if run.get('error'):
                    lines += ['', 'It stopped with an error. Claude sees the error masked and can fix it.']
                items = minitalk._items_text(run.get('items') or [])
                if items:
                    lines += [items]
                lines += ['', minitalk.NOTHING_WRITTEN if run.get('preview') else
                          '_Run on your real accounts. Drafts wait in Gmail until you press Send._']
                return {'reply': '\n'.join(lines)}
        raise ValueError('That run is no longer here. Ask Claude to run it again.')
    if kind == 'Chart':
        found = None
        for path in sorted((Path(data_dir) / 'views').glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True):
            view = read(path)
            if key(view.get('title', '')) == title and (not workspace or view.get('workspace') in (workspace, None)):
                found = path.stem
                break
        if not found:
            raise ValueError('That chart is no longer here. Ask Claude to show it again.')
        url = journey.page_url(data_dir, 'view', id=found, embed='1', h='520')
        return {'reply': f'[{title}]({url})'}
    found = None
    for path in sorted((Path(data_dir) / '.idli/mini-drafts').glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            draft = journey.draft_data(data_dir, path.stem)
        except (OSError, ValueError):
            continue
        if key(draft.get('name', '')) == title and (not workspace or draft.get('workspace') == workspace):
            found = path.stem
            break
    if not found:
        raise ValueError('That draft is no longer here. Ask Claude to make it again.')
    url = journey.page_url(data_dir, 'mini-card', id=found, embed='1', h='900')
    return {'reply': f'Your Mini draft, as colleagues will see it. Click any text to change it, drag to reorder, then save.\n\n[{title}]({url})'}


def post_to_left(workspace, kind, title):
    """Put Claude's chart or Mini draft into this workspace's left chat. The line is short (no link or token): the chat
    asks Idli for the page itself."""
    if kind not in BINDER_KINDS:
        raise ValueError('Unknown item')
    cli('send', '--no-wait', left_chat(workspace), f'{kind} from Claude: ' + ' '.join(plain(str(title)).split())[:160])


def _human(key):
    t = re.sub(r'_inr$', ' (Rs)', str(key), flags=re.I)
    t = re.sub(r'_?1to10$', ' (1 to 10)', t, flags=re.I).replace('_', ' ').strip()
    return t[:1].upper() + t[1:]


def _indian(n):
    """3,50,000 style grouping for whole numbers."""
    neg, s = n < 0, str(abs(int(n)))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        head = ','.join([head[max(0, i - 2):i] for i in range(len(head), 0, -2)][::-1])
        s = head + ',' + tail
    return ('-' if neg else '') + s


def _nice_cell(v):
    v = v.strip()
    if re.fullmatch(r'-?\d{4,}', v):
        return _indian(int(v))
    if re.fullmatch(r'-?\d{4,}\.\d+', v):
        whole, frac = v.split('.')
        return _indian(int(whole)) + '.' + frac[:2]
    return v


def tidy_answer(text, max_rows=10):
    """A Mini script's printout made readable: table headings in words, grouped numbers, at most max_rows rows."""
    out, rows, header = [], 0, None
    for line in str(text).splitlines():
        cells = line.strip()
        if cells.startswith('|') and cells.endswith('|'):
            parts = [c for c in cells[1:-1].split('|')]
            if header is None:
                header = True
                out.append('| ' + ' | '.join(_human(c.strip()) for c in parts) + ' |')
            elif re.fullmatch(r'[\s:|-]+', cells):
                out.append(line)
            else:
                rows += 1
                if rows <= max_rows:
                    out.append('| ' + ' | '.join(_nice_cell(c) for c in parts) + ' |')
            continue
        if header and rows > max_rows:
            out.append(f'And {rows - max_rows} more rows.')
        header, rows = None, 0
        out.append(re.sub(r'\b\d{5,}\b', lambda m: _indian(int(m.group())), line))
    if header and rows > max_rows:
        out.append(f'And {rows - max_rows} more rows.')
    return '\n'.join(out)


def _option_words(key, desc):
    name = _human(key).lower()
    if desc.get('type') == 'choice':
        every = any(str(c) == 'All' for c in desc.get('choices', []))
        choices = [str(c) for c in desc.get('choices', []) if str(c) != 'All']
        if len(choices) <= 3:
            return name + ': ' + ' or '.join(choices + (['all'] if every else []))
        return f'{name}: any of {len(choices)}' + (' or all' if every else '')
    return name + ': a number'


def file_labels(files):
    """A Mini's source files for people: name, and the Drive folder it sits in."""
    out = []
    for x in files or []:
        parts = str(x.get('local') or x.get('title') or '').replace('drive/', '', 1).split('/')
        name = x.get('title') or re.sub(r'\.(xlsx|xls|csv)$', '', parts[-1])
        out.append({'name': plain(name), 'folder': plain(' / '.join(parts[:-1]))})
    return out


def mini_open(data_dir, ident, workspace=None):
    """Show what the author left: the story, the pinned charts (live), and what can be asked. No model, no scripts."""
    m = read(object_path(data_dir, 'minis', ident))
    if workspace:
        def change(state):
            state.setdefault('workspace_minis', {})[workspace] = ident
            state.setdefault('workspace_files', {})[workspace] = m.get('files', [])
        update_state(data_dir, change)
    from lib import journey
    # The Mini page: the same page the author arranged and saved (lib/mini-card.html), with live charts.
    lines = ['[' + plain(m['name']).replace('[', '').replace(']', '') + '](' + journey.page_url(
        data_dir, 'mini-card', mini=ident, embed=1, h=700, ws=workspace or '') + ')']
    charts = m.get('charts', [])
    from lib import minitalk
    actions = minitalk.is_action(data_dir, {**m, 'id': ident})
    # An action Mini is never run just by opening it: its run drafts and books (lib/minitalk.py)
    if not charts and m['questions'] and not actions:
        try:
            example = run_mini(data_dir, ident, m['questions'][0]['id'], {})
            if example['chart']:
                lines += ['', chart_markdown(data_dir, m['questions'][0]['question'], example['chart'], m.get('agent'),
                                             example['sources'], example['script'], workspace)]
        except ValueError:
            pass
    # can_query: questions outside the saved ones can go to the query service (lib/minisql.py).
    # A team set up without the outside service (Start here > Teams) leaves this file in its folder (lib/teams.py).
    can_query = not os.path.exists(os.path.join(data_dir, 'no-query-service'))
    # Yes at setup (query-service-always): no card each time; only masked data is sent, as with the card.
    query_auto = can_query and os.path.exists(os.path.join(data_dir, 'query-service-always'))
    if actions:  # an action Mini (accounts, not files): ask it, preview it, run it or turn it on (lib/minitalk.py)
        from lib import miniscope
        mm = {**m, 'id': ident}
        can = miniscope.uses(data_dir, mm)
        named = miniscope.steps(data_dir, mm)
        if can:
            lines += ['', 'It ' + ', '.join(can[:-1]) + (' and ' if len(can) > 1 else '') + can[-1] + '.']
        if named:
            lines += ['', 'Its steps: ' + '; '.join(f'{n}. {t}' for n, t in named) + '. Say "run step 2" to see one.']
        lines += ['', minitalk.state(m) + ' Ask how it works, or "show me what you would draft". Nothing is written '
                  'until you say "run it". To change it, press Fork on its card.']
    return {'id': ident, 'files': m.get('files', []), 'questions': m['questions'], 'can_query': can_query,
            **({'query_auto': True} if query_auto else {}), **({'actions': True} if actions else {}),
            'reply': plain('\n'.join(lines))}


QUERY_NOTE = ('_Asked an external service to write a query. It saw your question with private values as codes and '
              'the column names, not your data. The query ran on this computer._')


def mini_query_preview(data_dir, ident, question):
    """Before asking the query service: what it would get (masked question, first lines of the column list)."""
    from lib import minisql
    m = read(object_path(data_dir, 'minis', ident))
    files = [f['local'] for f in m.get('files', []) if f.get('local')]
    if not files:
        raise ValueError('This Mini has no files to query.')
    return {'question': question, 'consent': minisql.preview(data_dir, files, str(question)[:800])}


def mini_query(data_dir, ident, question, workspace=None):
    """A question the Mini's saved questions don't cover: a query written by the external service, run here."""
    from lib import minisql
    if os.path.exists(os.path.join(data_dir, 'no-query-service')):  # the team said No at setup: code refuses too
        raise ValueError('This team was set up without the outside query service.')
    m = read(object_path(data_dir, 'minis', ident))
    files = [f['local'] for f in m.get('files', []) if f.get('local')]
    if not files:
        raise ValueError('This Mini has no files to query.')
    r = minisql.answer(data_dir, files, str(question)[:800])
    if r['kind'] == 'clarify':
        return {'clarify': plain(r['text']), 'question': question,
                'options': [{'label': plain(o['label']), 'question': plain(o['question'])} for o in r['options']]}
    frame = r['frame']
    if frame.empty:
        table = 'No rows match.'
    else:
        shown = frame.head(15).astype(object).where(frame.head(15).notna(), '')
        cell = lambda v: str(v).replace('|', '/').replace('\n', ' ')
        md = ['| ' + ' | '.join(cell(c) for c in shown.columns) + ' |', '|' + '---|' * len(shown.columns)]
        md += ['| ' + ' | '.join(cell(v) for v in row) + ' |' for row in shown.itertuples(index=False)]
        table = tidy_answer('\n'.join(md), max_rows=15)
        if len(frame) > 15:
            table += f'\n\n{len(frame) - 15} more rows not shown.'
    lines = ['**' + plain(r['title']) + '**', '', table]
    if r['note']:
        lines += ['', plain(r['note'])]
    lines += ['', QUERY_NOTE]
    return {'question': question, 'reply': plain('\n'.join(lines)), 'rows': len(frame)}


def mini_ask(data_dir, ident, qid, params, workspace=None):
    m = read(object_path(data_dir, 'minis', ident))
    q = next(q for q in m['questions'] if q['id'] == qid)
    result = run_mini(data_dir, ident, qid, params)
    using = ', '.join(f'{_human(k).lower()} {v}' for k, v in result['params'].items())
    lines = ['_Answered with: ' + q['question'].rstrip('?') + (' (' + using + ')' if using else '') + '_', '',
             tidy_answer(result['text'])]
    if result['chart']:
        lines.append(chart_markdown(data_dir, q['question'], result['chart'], m.get('agent'),
                                    result['sources'], result['script'], workspace))
    return {**result, 'reply': plain('\n'.join(lines))}
