"""SQLite state and private per-tester sandbox management for Silo alpha onboarding.

Implements the multi-user isolation guarantees from deployment/alpha/signal.md:
- Single-use, expiring setup tokens bound to an authenticated Signal ACI.
- Transactional invite redemption (replaying/forwarding never opens another tester's sandbox).
- Separate private 0700 sandbox directory per tester (DuckDB, credentials, profile.json, logs).
- Explicit Signal DM confirmation code required before activating a mailbox or chat store.
"""
import datetime as dt
import hashlib
import json
import os
import re
import secrets
import shutil
import sqlite3
from pathlib import Path

DRIVE_LINK_RE = re.compile(r'https?://(?:docs|drive)\.google\.com/[^\s<>()"\']+', re.I)

ROLE_EXAMPLES = [
    {
        'id': 'insights',
        'label': 'Insights team',
        'summary': 'Cross-doc & sheet analysis, data stories',
        'text': (
            'I plan to use AI to analyse connections across different docs, folders, and sheets — '
            'visualize and share data stories.'
        ),
    },
    {
        'id': 'partnerships',
        'label': 'Partnerships',
        'summary': 'Lead tracker, outreach & meeting scheduling',
        'text': (
            'I work on converting leads for my platform. Leads come in over many channels and I maintain '
            'them in the leads tracker. I mail these leads and when they reply I try and schedule a meeting with them.'
        ),
    },
    {
        'id': 'marketing',
        'label': 'Marketing',
        'summary': 'Event reels, LinkedIn content & reminders',
        'text': (
            'I work on making reels and LinkedIn content from our events. I do so according to a calendar '
            'stored in Drive here: https://drive.google.com/drive/folders/example-events-calendar. '
            'Remind me a day before and brainstorm the outline and setup for topics.'
        ),
    },
]


def _utc_now():
    return dt.datetime.now(dt.timezone.utc)


def _iso(t):
    return t.isoformat(timespec='seconds')


def _parse_iso(s):
    if not s:
        return None
    return dt.datetime.fromisoformat(s)


def extract_intent_signals(intended_use, available_folders=(), available_chats=()):
    """Deterministically detect Drive links and mentioned folder/group names from the user's
    intended-use text so onboarding can suggest relevant --in scopes without touching the 9B prompt."""
    text = (intended_use or '').strip()
    links = sorted(set(DRIVE_LINK_RE.findall(text)))
    low = text.lower()
    words = {w for w in re.findall(r'[a-z0-9]{4,}', low) if w not in {
        'plan', 'with', 'from', 'that', 'this', 'them', 'when', 'they', 'their', 'about',
        'have', 'work', 'into', 'over', 'many', 'also', 'here', 'there', 'using', 'different',
        'share', 'stored', 'drive', 'according', 'before', 'after', 'make', 'making',
    }}
    matched_folders = []
    for f in available_folders:
        name = f.get('name', '') if isinstance(f, dict) else str(f)
        ftoks = {w for w in re.findall(r'[a-z0-9]{4,}', name.lower())}
        if name.lower() in low or (ftoks and (ftoks & words)):
            matched_folders.append(name)
    matched_chats = []
    for c in available_chats:
        name = c.get('name', '') if isinstance(c, dict) else str(c)
        ctoks = {w for w in re.findall(r'[a-z0-9]{4,}', name.lower())}
        if name.lower() in low or (ctoks and (ctoks & words)):
            matched_chats.append(name)
    return {
        'drive_links': links,
        'suggested_folders': matched_folders[:8],
        'suggested_chats': matched_chats[:8],
    }


class OnboardStore:
    def __init__(self, state_dir):
        os.umask(0o077)
        self.state_dir = Path(state_dir).expanduser().resolve()
        self.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.sandboxes_dir = self.state_dir / 'testers'
        self.sandboxes_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db_path = self.state_dir / 'onboard.sqlite3'
        self._init_db()

    def _connect(self):
        con = sqlite3.connect(self.db_path, timeout=30)
        con.row_factory = sqlite3.Row
        con.execute('PRAGMA foreign_keys = ON')
        return con

    def _init_db(self):
        with self._connect() as con:
            con.executescript("""
                CREATE TABLE IF NOT EXISTS invites (
                    code TEXT PRIMARY KEY,
                    label TEXT DEFAULT '',
                    allowed_aci TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    redeemed_by_aci TEXT DEFAULT '',
                    redeemed_at TEXT DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS testers (
                    tester_id TEXT PRIMARY KEY,
                    signal_aci TEXT UNIQUE NOT NULL,
                    label TEXT DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'onboarding',
                    sandbox_dir TEXT NOT NULL,
                    google_email TEXT DEFAULT '',
                    google_scopes TEXT DEFAULT '[]',
                    sync_gmail INTEGER DEFAULT 1,
                    sync_calendar INTEGER DEFAULT 1,
                    wa_connected INTEGER DEFAULT 0,
                    wa_label TEXT DEFAULT '',
                    selected_drive_folders TEXT DEFAULT '[]',
                    selected_wa_chats TEXT DEFAULT '[]',
                    role TEXT DEFAULT '',
                    intended_use TEXT DEFAULT '',
                    detected_links TEXT DEFAULT '[]',
                    coverage_json TEXT DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    activated_at TEXT DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token TEXT PRIMARY KEY,
                    tester_id TEXT NOT NULL REFERENCES testers(tester_id) ON DELETE CASCADE,
                    signal_aci TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    oauth_state TEXT DEFAULT '',
                    pkce_verifier TEXT DEFAULT '',
                    confirm_code TEXT DEFAULT '',
                    confirm_expires_at TEXT DEFAULT '',
                    consumed_at TEXT DEFAULT ''
                );
            """)

    # ---- Invites ----

    def create_invite(self, label='', allowed_aci='', ttl_hours=72):
        code = secrets.token_urlsafe(8)
        now = _utc_now()
        exp = now + dt.timedelta(hours=ttl_hours)
        with self._connect() as con:
            con.execute(
                'INSERT INTO invites(code, label, allowed_aci, created_at, expires_at) VALUES (?,?,?,?,?)',
                (code, label.strip(), allowed_aci.strip(), _iso(now), _iso(exp)),
            )
        return code

    def redeem_invite(self, code, signal_aci):
        """Transactionally redeem a single-use invite for `signal_aci` and allocate their private tester row."""
        now = _utc_now()
        with self._connect() as con:
            con.execute('BEGIN IMMEDIATE')
            row = con.execute('SELECT * FROM invites WHERE code = ?', (code.strip(),)).fetchone()
            if not row:
                raise ValueError('Unknown invite code.')
            if row['redeemed_by_aci'] and row['redeemed_by_aci'] != signal_aci:
                raise ValueError('This invite has already been redeemed by another account.')
            if _parse_iso(row['expires_at']) < now and not row['redeemed_by_aci']:
                raise ValueError('This invite has expired. Ask the maintainer for a fresh one.')
            if row['allowed_aci'] and row['allowed_aci'] != signal_aci:
                raise ValueError('This invite is reserved for a different Signal account.')
            if not row['redeemed_by_aci']:
                con.execute(
                    'UPDATE invites SET redeemed_by_aci = ?, redeemed_at = ? WHERE code = ?',
                    (signal_aci, _iso(now), row['code']),
                )
            label = row['label']
        return self.ensure_tester(signal_aci, label=label)

    # ---- Testers & Sessions ----

    def get_tester_by_aci(self, signal_aci):
        with self._connect() as con:
            row = con.execute('SELECT * FROM testers WHERE signal_aci = ?', (signal_aci,)).fetchone()
            return self._row_to_tester(row) if row else None

    def get_tester(self, tester_id):
        with self._connect() as con:
            row = con.execute('SELECT * FROM testers WHERE tester_id = ?', (tester_id,)).fetchone()
            return self._row_to_tester(row) if row else None

    def ensure_tester(self, signal_aci, label=''):
        existing = self.get_tester_by_aci(signal_aci)
        if existing:
            return existing
        tester_id = 't_' + hashlib.sha256(f'{signal_aci}:{secrets.token_hex(8)}'.encode()).hexdigest()[:12]
        sbx = self.sandboxes_dir / tester_id
        sbx.mkdir(parents=True, exist_ok=True, mode=0o700)
        now = _iso(_utc_now())
        with self._connect() as con:
            con.execute(
                'INSERT INTO testers(tester_id, signal_aci, label, status, sandbox_dir, created_at, updated_at) '
                'VALUES (?,?,?,?,?,?,?)',
                (tester_id, signal_aci, label, 'onboarding', str(sbx), now, now),
            )
        return self.get_tester(tester_id)

    def create_setup_session(self, signal_aci, label='', ttl_minutes=60):
        tester = self.ensure_tester(signal_aci, label=label)
        token = secrets.token_urlsafe(24)
        oauth_state = secrets.token_urlsafe(16)
        pkce_verifier = secrets.token_urlsafe(32)
        now = _utc_now()
        exp = now + dt.timedelta(minutes=ttl_minutes)
        with self._connect() as con:
            con.execute(
                'INSERT INTO sessions(token, tester_id, signal_aci, created_at, expires_at, oauth_state, pkce_verifier) '
                'VALUES (?,?,?,?,?,?,?)',
                (token, tester['tester_id'], signal_aci, _iso(now), _iso(exp), oauth_state, pkce_verifier),
            )
        return token, tester

    def get_session(self, token, allow_expired=False):
        with self._connect() as con:
            row = con.execute('SELECT * FROM sessions WHERE token = ?', (token,)).fetchone()
            if not row:
                return None
            sess = dict(row)
            if not allow_expired and _parse_iso(sess['expires_at']) < _utc_now():
                return None
            sess['tester'] = self.get_tester(sess['tester_id'])
            return sess

    def get_session_by_oauth_state(self, state):
        if not state:
            return None
        with self._connect() as con:
            row = con.execute('SELECT * FROM sessions WHERE oauth_state = ?', (state,)).fetchone()
            if not row:
                return None
            sess = dict(row)
            if _parse_iso(sess['expires_at']) < _utc_now():
                return None
            sess['tester'] = self.get_tester(sess['tester_id'])
            return sess

    def update_tester(self, tester_id, **fields):
        allowed = {
            'status', 'google_email', 'google_scopes', 'sync_gmail', 'sync_calendar',
            'wa_connected', 'wa_label', 'selected_drive_folders', 'selected_wa_chats',
            'role', 'intended_use', 'detected_links', 'coverage_json', 'activated_at', 'label',
        }
        updates = {}
        for k, v in fields.items():
            if k not in allowed:
                continue
            if k in ('google_scopes', 'selected_drive_folders', 'selected_wa_chats', 'detected_links', 'coverage_json'):
                v = json.dumps(v, ensure_ascii=False)
            elif k in ('sync_gmail', 'sync_calendar', 'wa_connected'):
                v = 1 if v else 0
            updates[k] = v
        if not updates:
            return self.get_tester(tester_id)
        updates['updated_at'] = _iso(_utc_now())
        sets = ', '.join(f'{k} = ?' for k in updates)
        vals = list(updates.values()) + [tester_id]
        with self._connect() as con:
            con.execute(f'UPDATE testers SET {sets} WHERE tester_id = ?', vals)
        tester = self.get_tester(tester_id)
        self._write_profile(tester)
        return tester

    def issue_confirm_code(self, token, ttl_minutes=30):
        """Generate a 6-digit Signal DM confirmation code bound to this session & tester ACI."""
        sess = self.get_session(token)
        if not sess:
            raise ValueError('Setup link expired or invalid.')
        code = f'{secrets.randbelow(900000) + 100000:06d}'
        exp = _utc_now() + dt.timedelta(minutes=ttl_minutes)
        with self._connect() as con:
            con.execute(
                'UPDATE sessions SET confirm_code = ?, confirm_expires_at = ? WHERE token = ?',
                (code, _iso(exp), token),
            )
            con.execute(
                "UPDATE testers SET status = 'awaiting_confirm', updated_at = ? WHERE tester_id = ?",
                (_iso(_utc_now()), sess['tester_id']),
            )
        return code

    def confirm_from_signal(self, signal_aci, code):
        """Activate a tester ONLY when the matching confirmation code arrives from the same Signal ACI."""
        clean = re.sub(r'[^0-9]', '', code or '')
        if len(clean) != 6:
            return None, 'Confirmation code must be 6 digits (e.g. `confirm 482910`).'
        now = _utc_now()
        with self._connect() as con:
            row = con.execute(
                'SELECT * FROM sessions WHERE signal_aci = ? AND confirm_code = ? AND consumed_at = "" '
                'ORDER BY created_at DESC LIMIT 1',
                (signal_aci, clean),
            ).fetchone()
            if not row:
                return None, 'That confirmation code does not match your active setup session.'
            if row['confirm_expires_at'] and _parse_iso(row['confirm_expires_at']) < now:
                return None, 'That confirmation code has expired. Reopen your setup link to get a fresh one.'
            con.execute('UPDATE sessions SET consumed_at = ? WHERE token = ?', (_iso(now), row['token']))
            con.execute(
                "UPDATE testers SET status = 'active', activated_at = ?, updated_at = ? WHERE tester_id = ?",
                (_iso(now), _iso(now), row['tester_id']),
            )
        tester = self.get_tester(row['tester_id'])
        self._write_profile(tester)
        return tester, ''

    def disconnect_tester(self, tester_id, delete_data=False):
        tester = self.get_tester(tester_id)
        if not tester:
            return None
        with self._connect() as con:
            con.execute(
                "UPDATE testers SET status = 'disconnected', google_email = '', google_scopes = '[]', "
                "wa_connected = 0, updated_at = ? WHERE tester_id = ?",
                (_iso(_utc_now()), tester_id),
            )
            con.execute('UPDATE sessions SET consumed_at = ? WHERE tester_id = ? AND consumed_at = ""',
                        (_iso(_utc_now()), tester_id))
        if delete_data:
            sbx = Path(tester['sandbox_dir'])
            if sbx.exists() and self.sandboxes_dir in sbx.parents:
                shutil.rmtree(sbx)
                sbx.mkdir(parents=True, exist_ok=True, mode=0o700)
        return self.get_tester(tester_id)

    def _write_profile(self, tester):
        """Persist the tester's role, intended use, and --in scope choices privately in their sandbox.
        Kept strictly outside the 9B mapper prompt so it guides workflow triage without hurting CLI accuracy."""
        if not tester:
            return
        sbx = Path(tester['sandbox_dir'])
        sbx.mkdir(parents=True, exist_ok=True, mode=0o700)
        profile = {
            'tester_id': tester['tester_id'],
            'status': tester['status'],
            'google_email': tester['google_email'],
            'sync_gmail': tester['sync_gmail'],
            'sync_calendar': tester['sync_calendar'],
            'wa_connected': tester['wa_connected'],
            'selected_drive_folders': tester['selected_drive_folders'],
            'selected_wa_chats': tester['selected_wa_chats'],
            'role': tester['role'],
            'intended_use': tester['intended_use'],
            'detected_links': tester['detected_links'],
            'coverage': tester['coverage'],
            'updated_at': tester['updated_at'],
        }
        p = sbx / 'profile.json'
        p.write_text(json.dumps(profile, indent=2, ensure_ascii=False))
        os.chmod(p, 0o600)

    def _row_to_tester(self, row):
        d = dict(row)
        d['google_scopes'] = json.loads(d.get('google_scopes') or '[]')
        d['selected_drive_folders'] = json.loads(d.get('selected_drive_folders') or '[]')
        d['selected_wa_chats'] = json.loads(d.get('selected_wa_chats') or '[]')
        d['detected_links'] = json.loads(d.get('detected_links') or '[]')
        d['coverage'] = json.loads(d.get('coverage_json') or '{}')
        d['sync_gmail'] = bool(d.get('sync_gmail'))
        d['sync_calendar'] = bool(d.get('sync_calendar'))
        d['wa_connected'] = bool(d.get('wa_connected'))
        return d
