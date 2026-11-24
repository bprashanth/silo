"""Alpha multi-user onboarding web server for Silo.

Run locally:
    python3 -m bridges.onboard.server --state ~/.local/share/silo-onboard --port 18770 --demo

Production / alpha deployment (`deployment/alpha/signal.md`):
    Set IDLI_GOOGLE_CLIENT_ID, IDLI_GOOGLE_CLIENT_SECRET, IDLI_ONBOARD_PUBLIC_BASE,
    and optionally --wa-snapshot / --wa-pair-url for the read-only whatsmeow sidecar.
"""
import argparse
import base64
import hashlib
import html
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from bridges.onboard.store import OnboardStore, ROLE_EXAMPLES, extract_intent_signals

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / 'core' / 'idli'

GOOGLE_AUTH_URL = 'https://accounts.google.com/o/oauth2/v2/auth'
GOOGLE_TOKEN_URL = 'https://oauth2.googleapis.com/token'
GOOGLE_SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/calendar.readonly',
    'https://www.googleapis.com/auth/drive.readonly',
    'openid',
    'email',
]

DEMO_DRIVE_FOLDERS = [
    {'name': 'Strategy Classics', 'path': 'Strategy Classics', 'files': 14, 'hint': 'Papers, PDFs & research notes'},
    {'name': 'Leads & Partnerships', 'path': 'Leads & Partnerships', 'files': 9, 'hint': 'Leads tracker sheet & outreach drafts'},
    {'name': 'Events & Content Calendar', 'path': 'Events & Content Calendar', 'files': 11, 'hint': 'Event schedules, reels & LinkedIn briefs'},
    {'name': 'Insights & Data Stories', 'path': 'Insights & Data Stories', 'files': 18, 'hint': 'Program sheets, dashboards & reports'},
    {'name': 'Finance & Ops (Private)', 'path': 'Finance & Ops (Private)', 'files': 23, 'hint': 'Budgets & admin records'},
    {'name': 'Personal Archive', 'path': 'Personal Archive', 'files': 41, 'hint': 'Unrelated personal files'},
]


def _pkce_challenge(verifier):
    digest = hashlib.sha256(verifier.encode('ascii')).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b'=').decode('ascii')


def list_snapshot_chats(snapshot_path):
    """Read chat names and message counts from a whatsmeow/wa-js snapshot JSON."""
    if not snapshot_path:
        return []
    p = Path(snapshot_path).expanduser()
    if not p.is_file():
        return []
    try:
        data = json.loads(p.read_text())
    except Exception:
        return []
    out = []
    for kind, key in (('group', 'groups'), ('dm', 'dms')):
        for item in data.get(key) or []:
            name = (item.get('name') or '').strip()
            if not name:
                continue
            rows = item.get('rows') or item.get('messages') or []
            cnt = int(item.get('fetched') or len(rows))
            if cnt <= 0:
                continue
            out.append({
                'name': name,
                'kind': kind,
                'messages': cnt,
                'active_at': item.get('active_at') or '',
            })
    out.sort(key=lambda x: (0 if x['kind'] == 'group' else 1, -x['messages'], x['name'].lower()))
    return out


def list_sandbox_folders(sandbox_dir):
    """Read Drive folder names and file counts from an existing DuckDB sandbox (if available)."""
    if not sandbox_dir:
        return []
    db_file = Path(sandbox_dir).expanduser() / 'store.duckdb'
    if not db_file.is_file():
        return []
    try:
        import duckdb
        con = duckdb.connect(str(db_file), read_only=True)
        try:
            rows = con.execute("""
                SELECT CASE WHEN path = '' THEN name ELSE path || '/' || name END AS full_path, name
                FROM files WHERE kind = 'folder' ORDER BY 1
            """).fetchall()
            all_files = con.execute("SELECT path FROM files WHERE kind <> 'folder'").fetchall()
        finally:
            con.close()
        out = []
        for full_path, name in rows:
            cnt = sum(1 for (fp,) in all_files if (fp or '') == full_path or (fp or '').startswith(full_path + '/'))
            out.append({'name': full_path, 'path': full_path, 'files': cnt, 'hint': ''})
        return out
    except Exception:
        return []


class OnboardConfig:
    def __init__(
        self,
        store,
        public_base='http://127.0.0.1:18770',
        demo=False,
        demo_google_sandbox=None,
        wa_snapshot=None,
        wa_pair_url=None,
        skip_embed=False,
    ):
        self.store = store
        self.public_base = public_base.rstrip('/')
        self.demo = demo
        self.demo_google_sandbox = demo_google_sandbox
        self.wa_snapshot = wa_snapshot
        self.wa_pair_url = (wa_pair_url or '').rstrip('/')
        self.skip_embed = skip_embed
        self.google_client_id = os.environ.get('IDLI_GOOGLE_CLIENT_ID', '').strip()
        self.google_client_secret = os.environ.get('IDLI_GOOGLE_CLIENT_SECRET', '').strip()

    @property
    def oauth_configured(self):
        return bool(self.google_client_id and self.google_client_secret)

    def available_drive_folders(self):
        if self.demo_google_sandbox:
            real = list_sandbox_folders(self.demo_google_sandbox)
            if real:
                return real
        return list(DEMO_DRIVE_FOLDERS)

    def available_wa_chats(self):
        real = list_snapshot_chats(self.wa_snapshot)
        if real:
            return real
        return [
            {'name': 'Jam Buns @ T4GC', 'kind': 'group', 'messages': 139, 'active_at': ''},
            {'name': 'Internal Core Group for Acumen @ T4GC', 'kind': 'group', 'messages': 48, 'active_at': ''},
            {'name': 'Events & Marketing Team', 'kind': 'group', 'messages': 64, 'active_at': ''},
            {'name': 'Partnerships & Leads', 'kind': 'group', 'messages': 52, 'active_at': ''},
            {'name': 'Family Chat (Private)', 'kind': 'group', 'messages': 210, 'active_at': ''},
        ]

    def wa_live_status(self):
        if not self.wa_pair_url:
            return None
        try:
            with urllib.request.urlopen(self.wa_pair_url + '/status', timeout=3) as r:
                return json.load(r)
        except Exception:
            return None

    def run_scoped_sync(self, tester):
        """Run real `--in` scoped sync into this tester's isolated sandbox directory."""
        sbx = Path(tester['sandbox_dir'])
        sbx.mkdir(parents=True, exist_ok=True, mode=0o700)
        coverage = {
            'drive_folders': list(tester['selected_drive_folders']),
            'wa_chats': list(tester['selected_wa_chats']),
            'wa_synced_chats': 0,
            'wa_synced_messages': 0,
            'drive_synced_folders': len(tester['selected_drive_folders']),
            'gmail_enabled': bool(tester['sync_gmail'] and tester['google_email']),
            'calendar_enabled': bool(tester['sync_calendar'] and tester['google_email']),
            'notes': [],
        }

        # 1. Real WhatsApp --in sync when a snapshot is available and chats are selected
        if tester['wa_connected'] and tester['selected_wa_chats'] and self.wa_snapshot and Path(self.wa_snapshot).is_file():
            cmd = [str(CLI), 'sync', 'whatsapp', '--from-snapshot', str(Path(self.wa_snapshot).expanduser())]
            if self.skip_embed:
                cmd.append('--no-embed')
            for chat_name in tester['selected_wa_chats']:
                cmd.extend(['--in', chat_name])
            env = {
                **os.environ,
                'IDLI_SANDBOX': str(sbx),
                'IDLI_CHIPS': '0',
                'IDLI_9B_URL': os.environ.get('IDLI_9B_URL', 'http://127.0.0.1:8291'),
                'IDLI_EMBED_URL': os.environ.get('IDLI_EMBED_URL', 'http://127.0.0.1:8293'),
                'IDLI_RERANK_URL': os.environ.get('IDLI_RERANK_URL', 'http://127.0.0.1:8294'),
            }
            proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=240)
            if proc.returncode != 0:
                raise RuntimeError(f'WhatsApp scoped sync failed: {(proc.stderr or proc.stdout).strip()[:240]}')
            m = re.search(r'(\d+)\s+chats,\s+(\d+)\s+messages', proc.stdout)
            if m:
                coverage['wa_synced_chats'] = int(m.group(1))
                coverage['wa_synced_messages'] = int(m.group(2))
            coverage['notes'].append(proc.stdout.strip())
        elif tester['wa_connected'] and tester['selected_wa_chats']:
            # Preview mode without a live snapshot file: record selected scope cleanly
            chats_map = {c['name']: c['messages'] for c in self.available_wa_chats()}
            coverage['wa_synced_chats'] = len(tester['selected_wa_chats'])
            coverage['wa_synced_messages'] = sum(chats_map.get(c, 0) for c in tester['selected_wa_chats'])
            coverage['notes'].append(
                f"Preview scope saved for {coverage['wa_synced_chats']} WhatsApp chats "
                f"(~{coverage['wa_synced_messages']} messages)."
            )

        # 2. Drive scope (real sync if OAuth token exists for this tester; otherwise preview/recorded scope)
        if tester['google_email'] and tester['selected_drive_folders']:
            folders_map = {f['name']: f['files'] for f in self.available_drive_folders()}
            coverage['drive_synced_files'] = sum(folders_map.get(f, 0) for f in tester['selected_drive_folders'])
            coverage['notes'].append(
                f"Drive scoped to {len(tester['selected_drive_folders'])} folder(s): "
                + ', '.join(tester['selected_drive_folders'])
            )

        return coverage


def _render_setup_html(token, cfg):
    esc_token = html.escape(token)
    examples_json = json.dumps(ROLE_EXAMPLES, ensure_ascii=False)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Idli — Private Workspace Setup</title>
<style>
  :root {{
    --bg: #f7f6f2;
    --card: #ffffff;
    --ink: #1a1917;
    --muted: #5c5852;
    --border: #e5e1d8;
    --accent: #1d5b4c;
    --accent-soft: #e7f3ef;
    --accent-hover: #16483c;
    --warn-bg: #fef7e6;
    --warn-ink: #7c5200;
    --danger: #b42318;
    --radius: 14px;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    background: var(--bg);
    color: var(--ink);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Roboto, sans-serif;
    line-height: 1.5;
    -webkit-font-smoothing: antialiased;
  }}
  .wrap {{ max-width: 820px; margin: 0 auto; padding: 24px 16px 64px; }}
  header {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 18px; }}
  .brand {{ display: flex; align-items: center; gap: 10px; }}
  .logo {{
    width: 36px; height: 36px; border-radius: 10px; background: var(--accent); color: #fff;
    display: grid; place-items: center; font-weight: 700; font-size: 18px; letter-spacing: -0.02em;
    flex-shrink: 0;
  }}
  h1 {{ font-size: 1.25rem; margin: 0; letter-spacing: -0.02em; }}
  .subtitle {{ color: var(--muted); font-size: 0.9rem; margin: 2px 0 0; }}
  .pill {{
    display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px;
    border-radius: 999px; font-size: 0.78rem; font-weight: 600;
    background: var(--accent-soft); color: var(--accent);
    white-space: nowrap; flex-shrink: 0;
  }}
  .pill.warn {{ background: var(--warn-bg); color: var(--warn-ink); }}
  .pill.muted {{ background: #ece9e1; color: var(--muted); }}
  .steps {{
    display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin-bottom: 20px;
  }}
  .step-tab {{
    background: var(--card); border: 1px solid var(--border); border-radius: 10px;
    padding: 8px 10px; font-size: 0.8rem; color: var(--muted); cursor: pointer;
    display: flex; align-items: center; gap: 8px; transition: all 0.15s ease;
  }}
  .step-tab .num {{
    width: 22px; height: 22px; border-radius: 999px; background: #ece9e1; color: var(--ink);
    display: grid; place-items: center; font-weight: 700; font-size: 0.75rem; flex-shrink: 0;
  }}
  .step-tab.active {{ border-color: var(--accent); color: var(--ink); font-weight: 600; background: #fff; }}
  .step-tab.active .num {{ background: var(--accent); color: #fff; }}
  .step-tab.done .num {{ background: var(--accent-soft); color: var(--accent); }}
  .card {{
    background: var(--card); border: 1px solid var(--border); border-radius: var(--radius);
    padding: 20px; margin-bottom: 16px; box-shadow: 0 1px 2px rgba(0,0,0,0.03);
  }}
  .card h2 {{ margin: 0 0 6px; font-size: 1.08rem; letter-spacing: -0.01em; }}
  .card p.desc {{ margin: 0 0 14px; color: var(--muted); font-size: 0.9rem; }}
  .trust-bar {{
    background: var(--accent-soft); border: 1px solid #cce3dc; color: var(--accent);
    border-radius: 10px; padding: 10px 14px; font-size: 0.85rem; margin-bottom: 18px;
    display: flex; flex-wrap: wrap; gap: 12px; align-items: center;
  }}
  .grid-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }}
  @media (max-width: 680px) {{
    .grid-2 {{ grid-template-columns: 1fr; }}
    .steps {{ grid-template-columns: repeat(2, 1fr); }}
  }}
  .source-box {{
    border: 1px solid var(--border); border-radius: 12px; padding: 16px;
    display: flex; flex-direction: column; justify-content: space-between; gap: 12px;
  }}
  .source-head {{ display: flex; justify-content: space-between; align-items: flex-start; gap: 8px; }}
  .source-title {{ font-weight: 700; font-size: 0.98rem; }}
  .source-meta {{ color: var(--muted); font-size: 0.83rem; margin-top: 2px; }}
  .btn {{
    appearance: none; border: 1px solid transparent; border-radius: 9px;
    padding: 9px 14px; font-size: 0.9rem; font-weight: 600; cursor: pointer;
    display: inline-flex; align-items: center; justify-content: center; gap: 6px;
    transition: background 0.15s ease, border-color 0.15s ease;
  }}
  .btn-primary {{ background: var(--accent); color: #fff; }}
  .btn-primary:hover {{ background: var(--accent-hover); }}
  .btn-primary:disabled {{ opacity: 0.55; cursor: not-allowed; }}
  .btn-outline {{ background: #fff; color: var(--ink); border-color: var(--border); }}
  .btn-outline:hover {{ border-color: #bbb5a8; background: #faf9f6; }}
  .btn-danger {{ background: #fff; color: var(--danger); border-color: #f3c6c3; }}
  .btn-sm {{ padding: 6px 10px; font-size: 0.82rem; border-radius: 8px; }}
  input[type="text"], textarea {{
    width: 100%; border: 1px solid var(--border); border-radius: 9px; padding: 9px 11px;
    font: inherit; font-size: 0.9rem; background: #fff; color: var(--ink);
  }}
  input[type="text"]:focus, textarea:focus {{ outline: 2px solid #b7dcd1; border-color: var(--accent); }}
  .picker-list {{
    max-height: 270px; overflow-y: auto; border: 1px solid var(--border);
    border-radius: 10px; margin-top: 10px; divide-y: 1px solid var(--border);
  }}
  .pick-row {{
    display: flex; align-items: flex-start; gap: 10px; padding: 10px 12px;
    border-bottom: 1px solid #f0ede6; cursor: pointer; transition: background 0.1s;
  }}
  .pick-row:last-child {{ border-bottom: none; }}
  .pick-row:hover {{ background: #faf9f5; }}
  .pick-row.suggested {{ background: #f1f9f6; }}
  .pick-row input {{ margin-top: 3px; accent-color: var(--accent); width: 16px; height: 16px; }}
  .pick-main {{ flex: 1; min-width: 0; }}
  .pick-name {{ font-weight: 600; font-size: 0.88rem; word-break: break-word; }}
  .pick-sub {{ font-size: 0.78rem; color: var(--muted); }}
  .role-pills {{ display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 14px; }}
  .role-pill {{
    border: 1px solid var(--border); background: #fff; color: var(--ink);
    padding: 7px 13px; border-radius: 999px; font-size: 0.86rem; font-weight: 600; cursor: pointer;
  }}
  .role-pill.selected {{ background: var(--accent); color: #fff; border-color: var(--accent); }}
  .examples {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin: 12px 0 14px; }}
  @media (max-width: 680px) {{ .examples {{ grid-template-columns: 1fr; }} }}
  .ex-card {{
    text-align: left; border: 1px solid var(--border); background: #fbfaf7;
    border-radius: 10px; padding: 11px 12px; cursor: pointer; transition: all 0.15s;
  }}
  .ex-card:hover {{ border-color: var(--accent); background: #f4faf8; }}
  .ex-title {{ font-weight: 700; font-size: 0.84rem; color: var(--accent); }}
  .ex-body {{ font-size: 0.8rem; color: var(--muted); margin-top: 4px; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }}
  .suggestion-box {{
    margin-top: 10px; padding: 10px 12px; border-radius: 10px;
    background: var(--accent-soft); border: 1px solid #cce3dc; font-size: 0.84rem;
    display: none; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap;
  }}
  .summary-strip {{
    background: #faf9f5; border: 1px solid var(--border); border-radius: 10px;
    padding: 12px 14px; margin-top: 14px; font-size: 0.86rem;
    display: flex; justify-content: space-between; align-items: center; gap: 10px; flex-wrap: wrap;
  }}
  .code-box {{
    background: #141918; color: #f6f8f7; border-radius: 12px; padding: 18px;
    text-align: center; margin: 14px 0;
  }}
  .code-val {{
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 1.75rem; font-weight: 700; letter-spacing: 0.14em; margin: 6px 0;
  }}
  .actions {{ display: flex; justify-content: space-between; align-items: center; gap: 10px; margin-top: 18px; }}
  .hidden {{ display: none !important; }}
  .toggle-row {{ display: flex; gap: 16px; flex-wrap: wrap; margin-top: 10px; font-size: 0.85rem; }}
  .toggle-row label {{ display: inline-flex; align-items: center; gap: 6px; cursor: pointer; }}
  .pair-inline {{
    margin-top: 10px; padding-top: 10px; border-top: 1px dashed var(--border);
    display: flex; flex-direction: column; gap: 8px;
  }}
  .pair-code {{
    font-family: monospace; font-size: 1.35rem; font-weight: 700; letter-spacing: 0.18em;
    background: #f4f3ee; padding: 8px; border-radius: 8px; text-align: center;
  }}
  .err {{ color: var(--danger); font-size: 0.86rem; margin-top: 8px; }}
  .footnote {{ color: var(--muted); font-size: 0.8rem; margin-top: 8px; }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="brand">
      <div class="logo">i</div>
      <div>
        <h1>Idli Private Workspace</h1>
        <div class="subtitle">Read-only assistant over only what you choose to share</div>
      </div>
    </div>
    <span id="mode-pill" class="pill">Private DGX</span>
  </header>

  <div class="trust-bar">
    <strong>Strictly read-only.</strong>
    <span>Never sends emails or WhatsApp messages. Stored in your own isolated sandbox on DGX. Revoke anytime.</span>
  </div>

  <nav class="steps" aria-label="Setup steps">
    <button type="button" class="step-tab active" data-step="1" onclick="goStep(1)"><span class="num">1</span> Connect</button>
    <button type="button" class="step-tab" data-step="2" onclick="goStep(2)"><span class="num">2</span> Pick scope</button>
    <button type="button" class="step-tab" data-step="3" onclick="goStep(3)"><span class="num">3</span> Your goals</button>
    <button type="button" class="step-tab" data-step="4" onclick="goStep(4)"><span class="num">4</span> Confirm</button>
  </nav>

  <!-- STEP 1: Connect Accounts -->
  <section id="step-1" class="card">
    <h2>1. Connect the accounts you want to search</h2>
    <p class="desc">Connect Google, WhatsApp, or both. You will pick the exact folders and groups in the next step — nothing is synced yet.</p>
    <div class="grid-2">
      <div class="source-box">
        <div>
          <div class="source-head">
            <div>
              <div class="source-title">Google Account</div>
              <div class="source-meta">Drive folders, Gmail &amp; Calendar (read-only)</div>
            </div>
            <span id="google-badge" class="pill muted">Not connected</span>
          </div>
          <div id="google-details" class="footnote" style="margin-top:10px"></div>
          <div id="google-toggles" class="toggle-row hidden">
            <label><input type="checkbox" id="chk-gmail" checked onchange="saveToggles()"> Include Gmail (read-only)</label>
            <label><input type="checkbox" id="chk-cal" checked onchange="saveToggles()"> Include Calendar (read-only)</label>
          </div>
        </div>
        <div>
          <button id="btn-google" type="button" class="btn btn-primary" style="width:100%" onclick="connectGoogle()">Connect Google (Read-Only)</button>
        </div>
      </div>

      <div class="source-box">
        <div>
          <div class="source-head">
            <div>
              <div class="source-title">WhatsApp</div>
              <div class="source-meta">Last 14 days · read-only linked device</div>
            </div>
            <span id="wa-badge" class="pill muted">Not linked</span>
          </div>
          <div id="wa-details" class="footnote" style="margin-top:10px">Link via QR code or 8-digit phone code (single-phone friendly).</div>
          <div id="wa-pair-panel" class="pair-inline hidden">
            <div style="display:flex;gap:6px">
              <input type="text" id="wa-phone" placeholder="919876543210 (country + number)">
              <button type="button" class="btn btn-outline btn-sm" onclick="requestWaCode()">Get code</button>
            </div>
            <div id="wa-code-out"></div>
          </div>
        </div>
        <div style="display:flex;gap:8px">
          <button id="btn-wa" type="button" class="btn btn-primary" style="flex:1" onclick="connectWhatsApp()">Link WhatsApp (Read-Only)</button>
        </div>
      </div>
    </div>
    <div id="err-1" class="err"></div>
    <div class="actions">
      <span class="footnote">You can disconnect and erase your sandbox at any time.</span>
      <button type="button" class="btn btn-primary" onclick="goStep(2)">Next: Pick folders &amp; groups &rarr;</button>
    </div>
  </section>

  <!-- STEP 2: Scope Picker (--in) -->
  <section id="step-2" class="card hidden">
    <h2>2. Choose only the folders &amp; groups you are comfortable sharing</h2>
    <p class="desc">Most testers start small (2–5 folders or groups). Only checked items are synced with <code>--in</code>; everything else stays untouched.</p>
    <div class="grid-2">
      <div class="source-box">
        <div>
          <div class="source-head">
            <div class="source-title">Google Drive Folders</div>
            <span id="drive-count" class="pill muted">0 selected</span>
          </div>
          <input type="text" id="filter-drive" placeholder="Filter folders..." style="margin-top:10px" oninput="renderPickers()">
          <div id="drive-list" class="picker-list"></div>
          <div style="display:flex;gap:6px;margin-top:8px">
            <input type="text" id="custom-drive" placeholder="Or add folder name / Drive link...">
            <button type="button" class="btn btn-outline btn-sm" onclick="addCustomDrive()">Add</button>
          </div>
        </div>
      </div>

      <div class="source-box">
        <div>
          <div class="source-head">
            <div class="source-title">WhatsApp Groups &amp; Chats</div>
            <span id="wa-count" class="pill muted">0 selected</span>
          </div>
          <input type="text" id="filter-wa" placeholder="Filter groups or chats..." style="margin-top:10px" oninput="renderPickers()">
          <div id="wa-list" class="picker-list"></div>
          <div class="footnote">Tip: Start with 1–3 work groups. Personal/family chats stay unchecked by default.</div>
        </div>
      </div>
    </div>

    <div class="summary-strip">
      <div id="scope-summary">Nothing selected yet — pick at least one folder or WhatsApp group.</div>
      <button type="button" class="btn btn-outline btn-sm" onclick="clearScope()">Clear all</button>
    </div>
    <div id="err-2" class="err"></div>
    <div class="actions">
      <button type="button" class="btn btn-outline" onclick="goStep(1)">&larr; Back</button>
      <button type="button" class="btn btn-primary" onclick="goStep(3)">Next: Your role &amp; goals &rarr;</button>
    </div>
  </section>

  <!-- STEP 3: Role & Intended Use -->
  <section id="step-3" class="card hidden">
    <h2>3. How do you plan to use AI in your role?</h2>
    <p class="desc">Optional, but super helpful. Tell us what workflows matter to you — click an example below or write your own.</p>

    <div class="role-pills" id="role-pills">
      <button type="button" class="role-pill" data-role="Insights" onclick="pickRole('Insights')">Insights</button>
      <button type="button" class="role-pill" data-role="Partnerships" onclick="pickRole('Partnerships')">Partnerships</button>
      <button type="button" class="role-pill" data-role="Marketing" onclick="pickRole('Marketing')">Marketing</button>
      <button type="button" class="role-pill" data-role="Operations" onclick="pickRole('Operations')">Operations</button>
      <button type="button" class="role-pill" data-role="Other" onclick="pickRole('Other')">Other</button>
    </div>

    <div class="examples" id="examples-wrap"></div>

    <label for="intended-use" style="font-weight:600;font-size:0.88rem;display:block;margin-bottom:6px">Describe your intended use of AI in your role</label>
    <textarea id="intended-use" rows="4" placeholder="e.g. I work on converting leads tracked in our Leads sheet, following up over email, and finding context in WhatsApp groups..." oninput="debouncedAnalyze()"></textarea>

    <div id="suggestion-box" class="suggestion-box">
      <span id="suggestion-text"></span>
      <button type="button" class="btn btn-outline btn-sm" onclick="applySuggestions()">Add suggested to scope</button>
    </div>

    <p class="footnote">
      Saved privately in your workspace profile (<code>profile.json</code>) to help match folders now and guide future workflow tools.
      It never alters core read-only search rules or triggers actions without your confirmation.
    </p>
    <div id="err-3" class="err"></div>
    <div class="actions">
      <button type="button" class="btn btn-outline" onclick="goStep(2)">&larr; Back</button>
      <button id="btn-sync" type="button" class="btn btn-primary" onclick="finishAndSync()">Sync selected items &amp; finish &rarr;</button>
    </div>
  </section>

  <!-- STEP 4: Confirm in Signal -->
  <section id="step-4" class="card hidden">
    <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap">
      <h2 style="margin:0">4. Confirm in Signal to activate</h2>
      <span id="final-status-pill" class="pill warn">Awaiting Signal confirmation</span>
    </div>
    <p class="desc" style="margin-top:6px">
      For security, a forwarded link can never activate your workspace. Reply with this code in your original Signal DM with Idli:
    </p>

    <div class="code-box">
      <div style="font-size:0.82rem;opacity:0.8">Send this message in Signal</div>
      <div id="confirm-code-val" class="code-val">confirm ------</div>
      <button type="button" class="btn btn-outline btn-sm" onclick="copyCode()" style="background:#26302d;color:#fff;border-color:#3b4945">Copy command</button>
    </div>

    <div id="coverage-card" class="summary-strip" style="flex-direction:column;align-items:flex-start;gap:6px"></div>

    <div class="actions">
      <button type="button" class="btn btn-outline" onclick="goStep(2)">Adjust shared folders/groups</button>
      <button type="button" class="btn btn-danger btn-sm" onclick="disconnectAll()">Disconnect &amp; delete data</button>
    </div>
  </section>
</div>

<script>
const TOKEN = {json.dumps(esc_token)};
const BASE = '/setup/' + TOKEN;
const EXAMPLES = {examples_json};
let STATE = null;
let SELECTED_DRIVE = new Set();
let SELECTED_WA = new Set();
let SUGGESTED = {{folders: [], chats: [], links: []}};
let CURRENT_ROLE = '';
let ANALYZE_TIMER = null;

function esc(s) {{
  return String(s || '').replace(/[&<>"']/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
}}

function goStep(n) {{
  for (let i = 1; i <= 4; i++) {{
    document.getElementById('step-' + i).classList.toggle('hidden', i !== n);
    const tab = document.querySelector('.step-tab[data-step="' + i + '"]');
    tab.classList.toggle('active', i === n);
    tab.classList.toggle('done', i < n);
  }}
}}

function renderExamples() {{
  const wrap = document.getElementById('examples-wrap');
  wrap.innerHTML = EXAMPLES.map(ex => `
    <button type="button" class="ex-card" onclick="useExample('${{ex.id}}')">
      <div class="ex-title">${{esc(ex.label)}}</div>
      <div class="ex-body">${{esc(ex.text)}}</div>
    </button>
  `).join('');
}}

function useExample(id) {{
  const ex = EXAMPLES.find(e => e.id === id);
  if (!ex) return;
  const roleMap = {{insights: 'Insights', partnerships: 'Partnerships', marketing: 'Marketing'}};
  if (roleMap[id]) pickRole(roleMap[id]);
  document.getElementById('intended-use').value = ex.text;
  analyzeIntent();
}}

function pickRole(role) {{
  CURRENT_ROLE = role;
  document.querySelectorAll('.role-pill').forEach(b => {{
    b.classList.toggle('selected', b.dataset.role === role);
  }});
}}

function renderState() {{
  if (!STATE) return;
  const t = STATE.tester;
  document.getElementById('mode-pill').textContent = STATE.demo ? 'Local Preview · DGX' : 'Private DGX';
  if (STATE.demo) document.getElementById('mode-pill').classList.add('warn');

  const gBadge = document.getElementById('google-badge');
  const gDet = document.getElementById('google-details');
  const gBtn = document.getElementById('btn-google');
  if (t.google_email) {{
    gBadge.textContent = 'Connected';
    gBadge.className = 'pill';
    gDet.textContent = 'Signed in as ' + t.google_email + ' (read-only).';
    gBtn.textContent = 'Reconnect Google';
    gBtn.className = 'btn btn-outline';
    document.getElementById('google-toggles').classList.remove('hidden');
    document.getElementById('chk-gmail').checked = !!t.sync_gmail;
    document.getElementById('chk-cal').checked = !!t.sync_calendar;
  }} else {{
    gBadge.textContent = 'Not connected';
    gBadge.className = 'pill muted';
    gDet.textContent = STATE.oauth_configured ? 'Uses Google OAuth PKCE with read-only scopes.' : 'Local preview mode — simulates Google sign-in with local folders.';
    gBtn.textContent = 'Connect Google (Read-Only)';
    gBtn.className = 'btn btn-primary';
  }}

  const wBadge = document.getElementById('wa-badge');
  const wDet = document.getElementById('wa-details');
  const wBtn = document.getElementById('btn-wa');
  if (t.wa_connected) {{
    wBadge.textContent = 'Linked (read-only)';
    wBadge.className = 'pill';
    wDet.textContent = t.wa_label || 'WhatsApp read-only snapshot ready.';
    wBtn.textContent = 'Linked ✓';
    wBtn.className = 'btn btn-outline';
    document.getElementById('wa-pair-panel').classList.add('hidden');
  }} else {{
    wBadge.textContent = 'Not linked';
    wBadge.className = 'pill muted';
    wBtn.textContent = STATE.wa_pair_url ? 'Link with phone code / QR' : 'Link WhatsApp (Read-Only)';
    wBtn.className = 'btn btn-primary';
  }}

  if (t.role) pickRole(t.role);
  if (t.intended_use && !document.getElementById('intended-use').value) {{
    document.getElementById('intended-use').value = t.intended_use;
  }}

  if (STATE.confirm_code) {{
    document.getElementById('confirm-code-val').textContent = 'confirm ' + STATE.confirm_code;
    renderCoverage(t);
  }}
  if (t.status === 'active') {{
    const p = document.getElementById('final-status-pill');
    p.textContent = 'Active in Signal ✓';
    p.className = 'pill';
    const box = document.querySelector('#step-4 .code-box');
    if (box) {{
      box.style.background = '#e7f3ef';
      box.style.color = '#1d5b4c';
      box.innerHTML = '<div style="font-weight:700;font-size:1.05rem">Workspace active in Signal ✓</div><div style="font-size:0.88rem;margin-top:4px">Return to your Signal DM with Idli to ask questions about your shared folders and chats.</div>';
    }}
  }}
  renderPickers();
}}

function renderPickers() {{
  if (!STATE) return;
  const df = (document.getElementById('filter-drive').value || '').toLowerCase();
  const wf = (document.getElementById('filter-wa').value || '').toLowerCase();

  const dList = document.getElementById('drive-list');
  const allFolders = [...STATE.available_folders];
  for (const name of SELECTED_DRIVE) {{
    if (!allFolders.some(f => f.name === name)) allFolders.unshift({{name, files: 0, hint: 'Added manually'}});
  }}
  dList.innerHTML = allFolders.filter(f => !df || f.name.toLowerCase().includes(df)).map(f => {{
    const checked = SELECTED_DRIVE.has(f.name) ? 'checked' : '';
    const sug = SUGGESTED.folders.includes(f.name);
    return `<label class="pick-row ${{sug ? 'suggested' : ''}}">
      <input type="checkbox" ${{checked}} data-name="${{esc(f.name)}}" onchange="toggleDrive(this.dataset.name, this.checked)">
      <div class="pick-main">
        <div class="pick-name">${{esc(f.name)}} ${{sug ? '<span class="pill" style="font-size:0.7rem;padding:1px 7px">suggested</span>' : ''}}</div>
        <div class="pick-sub">${{f.files ? f.files + ' files' : 'Drive folder'}}${{f.hint ? ' · ' + esc(f.hint) : ''}}</div>
      </div>
    </label>`;
  }}).join('') || '<div style="padding:12px;color:#777;font-size:0.85rem">No matching folders.</div>';

  const wList = document.getElementById('wa-list');
  wList.innerHTML = STATE.available_chats.filter(c => !wf || c.name.toLowerCase().includes(wf)).map(c => {{
    const checked = SELECTED_WA.has(c.name) ? 'checked' : '';
    const sug = SUGGESTED.chats.includes(c.name);
    return `<label class="pick-row ${{sug ? 'suggested' : ''}}">
      <input type="checkbox" ${{checked}} data-name="${{esc(c.name)}}" onchange="toggleWa(this.dataset.name, this.checked)">
      <div class="pick-main">
        <div class="pick-name">${{esc(c.name)}} ${{sug ? '<span class="pill" style="font-size:0.7rem;padding:1px 7px">suggested</span>' : ''}}</div>
        <div class="pick-sub">${{c.kind === 'group' ? 'Group' : 'DM'}} · ${{c.messages}} messages (last 14d)</div>
      </div>
    </label>`;
  }}).join('') || '<div style="padding:12px;color:#777;font-size:0.85rem">No matching chats.</div>';

  document.getElementById('drive-count').textContent = SELECTED_DRIVE.size + ' selected';
  document.getElementById('drive-count').className = SELECTED_DRIVE.size ? 'pill' : 'pill muted';
  document.getElementById('wa-count').textContent = SELECTED_WA.size + ' selected';
  document.getElementById('wa-count').className = SELECTED_WA.size ? 'pill' : 'pill muted';

  const sum = document.getElementById('scope-summary');
  if (SELECTED_DRIVE.size || SELECTED_WA.size) {{
    sum.innerHTML = `<strong>Sharing ${{SELECTED_DRIVE.size}} Drive folder(s) + ${{SELECTED_WA.size}} WhatsApp chat(s).</strong> Everything else stays untouched.`;
  }} else {{
    sum.textContent = 'Nothing selected yet — pick at least one folder or WhatsApp group.';
  }}
}}

function toggleDrive(name, on) {{ on ? SELECTED_DRIVE.add(name) : SELECTED_DRIVE.delete(name); renderPickers(); }}
function toggleWa(name, on) {{ on ? SELECTED_WA.add(name) : SELECTED_WA.delete(name); renderPickers(); }}
function clearScope() {{ SELECTED_DRIVE.clear(); SELECTED_WA.clear(); renderPickers(); }}

function addCustomDrive() {{
  const inp = document.getElementById('custom-drive');
  const val = inp.value.trim();
  if (!val) return;
  SELECTED_DRIVE.add(val);
  inp.value = '';
  renderPickers();
}}

async function connectGoogle() {{
  document.getElementById('err-1').textContent = '';
  if (STATE.oauth_configured) {{
    window.location.href = BASE + '/google/start';
    return;
  }}
  const r = await fetch(BASE + '/google/demo', {{method: 'POST'}});
  const d = await r.json();
  if (!r.ok) {{ document.getElementById('err-1').textContent = d.error || 'Failed'; return; }}
  STATE = d;
  renderState();
}}

async function saveToggles() {{
  await fetch(BASE + '/prefs', {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{
      sync_gmail: document.getElementById('chk-gmail').checked,
      sync_calendar: document.getElementById('chk-cal').checked,
    }})
  }});
}}

async function connectWhatsApp() {{
  document.getElementById('err-1').textContent = '';
  if (STATE.wa_pair_url && !(STATE.wa_live && STATE.wa_live.paired)) {{
    document.getElementById('wa-pair-panel').classList.remove('hidden');
    return;
  }}
  const r = await fetch(BASE + '/whatsapp/connect', {{method: 'POST'}});
  const d = await r.json();
  if (!r.ok) {{ document.getElementById('err-1').textContent = d.error || 'Failed'; return; }}
  STATE = d;
  renderState();
}}

async function requestWaCode() {{
  const phone = document.getElementById('wa-phone').value.trim();
  if (!phone) return;
  document.getElementById('wa-code-out').innerHTML = '<span class="footnote">Requesting 8-digit pairing code...</span>';
  const r = await fetch(BASE + '/whatsapp/pair-phone', {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{phone}})
  }});
  const d = await r.json();
  if (d.pair_code) {{
    document.getElementById('wa-code-out').innerHTML = '<div class="pair-code">' + esc(d.pair_code) + '</div><div class="footnote">Open WhatsApp &rarr; Linked Devices &rarr; Link with phone number instead.</div>';
  }} else {{
    document.getElementById('wa-code-out').innerHTML = '<div class="err">' + esc(d.pair_error || d.error || 'Could not request code') + '</div>';
  }}
}}

function debouncedAnalyze() {{
  clearTimeout(ANALYZE_TIMER);
  ANALYZE_TIMER = setTimeout(analyzeIntent, 250);
}}

async function analyzeIntent() {{
  const text = document.getElementById('intended-use').value;
  if (!text.trim()) {{
    document.getElementById('suggestion-box').style.display = 'none';
    SUGGESTED = {{folders: [], chats: [], links: []}};
    renderPickers();
    return;
  }}
  const r = await fetch(BASE + '/analyze-intent', {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{intended_use: text}})
  }});
  const d = await r.json();
  SUGGESTED = {{folders: d.suggested_folders || [], chats: d.suggested_chats || [], links: d.drive_links || []}};
  const bits = [];
  if (SUGGESTED.folders.length) bits.push('Drive: ' + SUGGESTED.folders.join(', '));
  if (SUGGESTED.chats.length) bits.push('WhatsApp: ' + SUGGESTED.chats.join(', '));
  if (SUGGESTED.links.length) bits.push(SUGGESTED.links.length + ' Drive link(s) detected');
  const box = document.getElementById('suggestion-box');
  if (bits.length) {{
    document.getElementById('suggestion-text').textContent = 'Matched from your description — ' + bits.join(' · ');
    box.style.display = 'flex';
  }} else {{
    box.style.display = 'none';
  }}
  renderPickers();
}}

function applySuggestions() {{
  SUGGESTED.folders.forEach(f => SELECTED_DRIVE.add(f));
  SUGGESTED.chats.forEach(c => SELECTED_WA.add(c));
  renderPickers();
  document.getElementById('suggestion-text').textContent = 'Added suggested folders & groups to your scope ✓';
}}

async function finishAndSync() {{
  const btn = document.getElementById('btn-sync');
  const err = document.getElementById('err-3');
  err.textContent = '';
  if (!SELECTED_DRIVE.size && !SELECTED_WA.size) {{
    err.textContent = 'Pick at least one Drive folder or WhatsApp group in Step 2 first.';
    return;
  }}
  btn.disabled = true;
  btn.textContent = 'Syncing selected items...';
  try {{
    const r = await fetch(BASE + '/sync', {{
      method: 'POST', headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{
        selected_drive_folders: Array.from(SELECTED_DRIVE),
        selected_wa_chats: Array.from(SELECTED_WA),
        role: CURRENT_ROLE,
        intended_use: document.getElementById('intended-use').value,
      }})
    }});
    const d = await r.json();
    if (!r.ok) {{
      err.textContent = d.error || 'Sync failed.';
      return;
    }}
    STATE = d;
    renderState();
    goStep(4);
  }} finally {{
    btn.disabled = false;
    btn.textContent = 'Sync selected items & finish →';
  }}
}}

function renderCoverage(t) {{
  const c = t.coverage || {{}};
  const lines = [];
  if (t.google_email) {{
    lines.push('<strong>Google:</strong> ' + esc(t.google_email) + ' · ' + (t.selected_drive_folders || []).length + ' folder(s)' + (t.sync_gmail ? ' · Gmail' : '') + (t.sync_calendar ? ' · Calendar' : ''));
  }}
  if (t.wa_connected) {{
    lines.push('<strong>WhatsApp:</strong> ' + (c.wa_synced_chats || (t.selected_wa_chats || []).length) + ' chat(s), ' + (c.wa_synced_messages || 0) + ' messages synced');
  }}
  if ((t.selected_drive_folders || []).length) {{
    lines.push('<strong>Shared Drive folders:</strong> ' + esc(t.selected_drive_folders.join(', ')));
  }}
  if ((t.selected_wa_chats || []).length) {{
    lines.push('<strong>Shared WhatsApp chats:</strong> ' + esc(t.selected_wa_chats.join(', ')));
  }}
  if (t.role || t.intended_use) {{
    lines.push('<strong>Saved profile:</strong> ' + esc(t.role || 'Custom role') + ' — saved privately to <code>profile.json</code>');
  }}
  document.getElementById('coverage-card').innerHTML = lines.map(l => '<div>' + l + '</div>').join('');
}}

function copyCode() {{
  const txt = document.getElementById('confirm-code-val').textContent;
  navigator.clipboard && navigator.clipboard.writeText(txt);
}}

async function disconnectAll() {{
  if (!confirm('Disconnect your accounts and delete your sandbox data?')) return;
  const r = await fetch(BASE + '/disconnect', {{method: 'POST'}});
  if (r.ok) {{
    document.querySelector('.wrap').innerHTML = '<div class="card"><h2>Disconnected</h2><p class="desc">Your accounts have been disconnected and your sandbox data was deleted. You can message Idli on Signal anytime to start fresh.</p></div>';
  }}
}}

async function load() {{
  renderExamples();
  const r = await fetch(BASE + '/state');
  if (!r.ok) {{
    document.querySelector('.wrap').innerHTML = '<div class="card"><h2>Link expired or invalid</h2><p class="desc">Send a message to Idli on Signal to get a fresh setup link.</p></div>';
    return;
  }}
  STATE = await r.json();
  (STATE.tester.selected_drive_folders || []).forEach(f => SELECTED_DRIVE.add(f));
  (STATE.tester.selected_wa_chats || []).forEach(c => SELECTED_WA.add(c));
  renderState();
  if (STATE.tester.status === 'awaiting_confirm' || STATE.tester.status === 'active') {{
    goStep(4);
  }}
}}
load();
</script>
</body>
</html>"""


def make_handler(cfg: OnboardConfig):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            if os.environ.get('IDLI_ONBOARD_QUIET') != '1':
                sys.stderr.write(f'[onboard] {self.address_string()} {fmt % args}\n')

        def _send_json(self, obj, status=HTTPStatus.OK):
            body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_html(self, text, status=HTTPStatus.OK):
            body = text.encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_json(self):
            n = int(self.headers.get('Content-Length') or 0)
            raw = self.rfile.read(n) if n > 0 else b'{}'
            return json.loads(raw.decode('utf-8') or '{}')

        def _state_payload(self, sess):
            tester = cfg.store.get_tester(sess['tester_id'])
            return {
                'demo': cfg.demo or not cfg.oauth_configured,
                'oauth_configured': cfg.oauth_configured,
                'wa_pair_url': bool(cfg.wa_pair_url),
                'wa_live': cfg.wa_live_status(),
                'tester': tester,
                'confirm_code': sess.get('confirm_code') or '',
                'available_folders': cfg.available_drive_folders(),
                'available_chats': cfg.available_wa_chats(),
            }

        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path

            if path == '/health':
                return self._send_json({'ok': True})

            if path == '/oauth/google/callback':
                return self._handle_google_callback(parsed)

            m = re.fullmatch(r'/setup/([A-Za-z0-9_-]+)(/.*)?', path)
            if not m:
                return self._send_html('<h1>Not found</h1>', HTTPStatus.NOT_FOUND)
            token, sub = m.group(1), (m.group(2) or '')
            sess = cfg.store.get_session(token)
            if not sess:
                return self._send_html(
                    '<!doctype html><body style="font-family:system-ui;max-width:480px;margin:3rem auto;padding:1rem">'
                    '<h2>Setup link expired</h2><p>Send a message to Idli on Signal to get a fresh link.</p></body>',
                    HTTPStatus.GONE,
                )

            if sub in ('', '/'):
                return self._send_html(_render_setup_html(token, cfg))
            if sub == '/state':
                return self._send_json(self._state_payload(sess))
            if sub == '/google/start':
                if not cfg.oauth_configured:
                    return self._send_json({'error': 'Google Web OAuth not configured'}, HTTPStatus.BAD_REQUEST)
                params = {
                    'client_id': cfg.google_client_id,
                    'redirect_uri': cfg.public_base + '/oauth/google/callback',
                    'response_type': 'code',
                    'scope': ' '.join(GOOGLE_SCOPES),
                    'access_type': 'offline',
                    'prompt': 'consent',
                    'state': sess['oauth_state'],
                    'code_challenge': _pkce_challenge(sess['pkce_verifier']),
                    'code_challenge_method': 'S256',
                }
                url = GOOGLE_AUTH_URL + '?' + urllib.parse.urlencode(params)
                self.send_response(HTTPStatus.FOUND)
                self.send_header('Location', url)
                self.end_headers()
                return
            return self._send_json({'error': 'Not found'}, HTTPStatus.NOT_FOUND)

        def _handle_google_callback(self, parsed):
            qs = urllib.parse.parse_qs(parsed.query)
            state = (qs.get('state') or [''])[0]
            code = (qs.get('code') or [''])[0]
            err = (qs.get('error') or [''])[0]
            sess = cfg.store.get_session_by_oauth_state(state)
            if not sess:
                return self._send_html('<h2>Invalid or expired OAuth state.</h2>', HTTPStatus.BAD_REQUEST)
            if err or not code:
                self.send_response(HTTPStatus.FOUND)
                self.send_header('Location', f"/setup/{sess['token']}?oauth_error={urllib.parse.quote(err or 'cancelled')}")
                self.end_headers()
                return
            # Exchange authorization code + PKCE verifier for tokens
            data = urllib.parse.urlencode({
                'code': code,
                'client_id': cfg.google_client_id,
                'client_secret': cfg.google_client_secret,
                'redirect_uri': cfg.public_base + '/oauth/google/callback',
                'grant_type': 'authorization_code',
                'code_verifier': sess['pkce_verifier'],
            }).encode()
            req = urllib.request.Request(GOOGLE_TOKEN_URL, data, {'Content-Type': 'application/x-www-form-urlencoded'})
            try:
                with urllib.request.urlopen(req, timeout=20) as resp:
                    tok = json.load(resp)
            except Exception as e:
                return self._send_html(f'<h2>Google token exchange failed: {html.escape(type(e).__name__)}</h2>', HTTPStatus.BAD_GATEWAY)
            # Fetch verified Google email from userinfo
            email = ''
            try:
                ureq = urllib.request.Request(
                    'https://openidconnect.googleapis.com/v1/userinfo',
                    headers={'Authorization': 'Bearer ' + tok.get('access_token', '')},
                )
                with urllib.request.urlopen(ureq, timeout=15) as uresp:
                    uinfo = json.load(uresp)
                    email = uinfo.get('email', '')
            except Exception:
                pass
            # Store token strictly inside this tester's private 0700 sandbox
            sbx = Path(sess['tester']['sandbox_dir'])
            cred_file = sbx / 'google_oauth_token.json'
            cred_file.write_text(json.dumps(tok, indent=2))
            os.chmod(cred_file, 0o600)
            cfg.store.update_tester(
                sess['tester_id'],
                google_email=email or 'google-user@verified',
                google_scopes=GOOGLE_SCOPES,
            )
            self.send_response(HTTPStatus.FOUND)
            self.send_header('Location', f"/setup/{sess['token']}")
            self.end_headers()

        def do_POST(self):
            parsed = urllib.parse.urlparse(self.path)
            m = re.fullmatch(r'/setup/([A-Za-z0-9_-]+)(/.*)', parsed.path)
            if not m:
                return self._send_json({'error': 'Not found'}, HTTPStatus.NOT_FOUND)
            token, sub = m.group(1), m.group(2)
            sess = cfg.store.get_session(token)
            if not sess:
                return self._send_json({'error': 'Setup link expired or invalid.'}, HTTPStatus.GONE)

            if sub == '/google/demo':
                if not cfg.demo and cfg.oauth_configured:
                    return self._send_json({'error': 'Demo mode disabled.'}, HTTPStatus.FORBIDDEN)
                label = sess['tester'].get('label') or 'tester'
                slug = re.sub(r'[^a-z0-9]+', '.', label.lower()).strip('.') or 'tester'
                cfg.store.update_tester(
                    sess['tester_id'],
                    google_email=f'{slug}@preview.local',
                    google_scopes=['drive.readonly', 'gmail.readonly', 'calendar.readonly'],
                )
                return self._send_json(self._state_payload(cfg.store.get_session(token)))

            if sub == '/prefs':
                body = self._read_json()
                cfg.store.update_tester(
                    sess['tester_id'],
                    sync_gmail=bool(body.get('sync_gmail', True)),
                    sync_calendar=bool(body.get('sync_calendar', True)),
                )
                return self._send_json({'ok': True})

            if sub == '/whatsapp/connect':
                live = cfg.wa_live_status()
                if live and live.get('paired'):
                    lbl = f"Connected ({live.get('groups', 0)} groups, {live.get('messages', 0)} messages in last {live.get('window_days', 14)}d)"
                elif cfg.wa_snapshot and Path(cfg.wa_snapshot).is_file():
                    chats = cfg.available_wa_chats()
                    lbl = f"Snapshot ready ({len(chats)} chats available to select)"
                else:
                    lbl = 'Linked (read-only preview · last 14 days)'
                cfg.store.update_tester(sess['tester_id'], wa_connected=True, wa_label=lbl)
                return self._send_json(self._state_payload(cfg.store.get_session(token)))

            if sub == '/whatsapp/pair-phone':
                body = self._read_json()
                if not cfg.wa_pair_url:
                    return self._send_json({'error': 'No live WhatsApp sidecar configured.'}, HTTPStatus.BAD_REQUEST)
                req = urllib.request.Request(
                    cfg.wa_pair_url + '/pair-phone',
                    json.dumps({'phone': body.get('phone', '')}).encode(),
                    {'Content-Type': 'application/json'},
                )
                try:
                    with urllib.request.urlopen(req, timeout=25) as r:
                        return self._send_json(json.load(r))
                except Exception as e:
                    return self._send_json({'error': f'Sidecar error: {type(e).__name__}'}, HTTPStatus.BAD_GATEWAY)

            if sub == '/analyze-intent':
                body = self._read_json()
                sig = extract_intent_signals(
                    body.get('intended_use', ''),
                    available_folders=cfg.available_drive_folders(),
                    available_chats=cfg.available_wa_chats(),
                )
                return self._send_json(sig)

            if sub == '/sync':
                body = self._read_json()
                folders = [str(x).strip() for x in (body.get('selected_drive_folders') or []) if str(x).strip()]
                chats = [str(x).strip() for x in (body.get('selected_wa_chats') or []) if str(x).strip()]
                role = str(body.get('role') or '').strip()
                intended_use = str(body.get('intended_use') or '').strip()
                if not folders and not chats:
                    return self._send_json({'error': 'Select at least one Drive folder or WhatsApp chat.'}, HTTPStatus.BAD_REQUEST)
                sig = extract_intent_signals(intended_use, cfg.available_drive_folders(), cfg.available_wa_chats())
                tester = cfg.store.update_tester(
                    sess['tester_id'],
                    selected_drive_folders=folders,
                    selected_wa_chats=chats,
                    role=role,
                    intended_use=intended_use,
                    detected_links=sig['drive_links'],
                )
                try:
                    coverage = cfg.run_scoped_sync(tester)
                except Exception as e:
                    return self._send_json({'error': str(e)}, HTTPStatus.INTERNAL_SERVER_ERROR)
                cfg.store.update_tester(sess['tester_id'], coverage_json=coverage)
                cfg.store.issue_confirm_code(token)
                return self._send_json(self._state_payload(cfg.store.get_session(token)))

            if sub == '/disconnect':
                cfg.store.disconnect_tester(sess['tester_id'], delete_data=True)
                return self._send_json({'ok': True})

            return self._send_json({'error': 'Not found'}, HTTPStatus.NOT_FOUND)

    return Handler


def start_server(cfg: OnboardConfig, host='127.0.0.1', port=18770):
    srv = ThreadingHTTPServer((host, port), make_handler(cfg))
    return srv


def main():
    p = argparse.ArgumentParser(description='Silo alpha onboarding web service')
    p.add_argument('--state', default='~/.local/share/silo-onboard', help='Private state directory (0700)')
    p.add_argument('--host', default='127.0.0.1')
    p.add_argument('--port', type=int, default=18770)
    p.add_argument('--public-base', default='')
    p.add_argument('--demo', action='store_true', help='Allow local preview mode without public Google OAuth callback')
    p.add_argument('--demo-google-sandbox', default='', help='Optional synced Google sandbox to list real Drive folders')
    p.add_argument('--wa-snapshot', default='', help='Optional whatsmeow snapshot.json to list real chats & run --in sync')
    p.add_argument('--wa-pair-url', default='', help='Optional live silo-wa-sync /pair/<token> base URL')
    p.add_argument('--no-embed', action='store_true', help='Pass --no-embed to WhatsApp sync for fast local testing')
    p.add_argument('--print-demo-url', action='store_true', help='Create and print a ready-to-open local setup URL')
    a = p.parse_args()

    public_base = a.public_base or os.environ.get('IDLI_ONBOARD_PUBLIC_BASE') or f'http://{a.host}:{a.port}'
    store = OnboardStore(a.state)
    cfg = OnboardConfig(
        store=store,
        public_base=public_base,
        demo=a.demo,
        demo_google_sandbox=a.demo_google_sandbox or None,
        wa_snapshot=a.wa_snapshot or None,
        wa_pair_url=a.wa_pair_url or None,
        skip_embed=a.no_embed,
    )
    if a.print_demo_url:
        tok, _ = store.create_setup_session('demo-local-aci', label='Local Tester')
        print(f'Demo setup URL: {public_base}/setup/{tok}', flush=True)
    srv = start_server(cfg, host=a.host, port=a.port)
    print(f'Onboarding server listening on http://{a.host}:{a.port}', flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


if __name__ == '__main__':
    main()
