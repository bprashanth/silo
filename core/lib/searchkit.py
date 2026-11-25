"""Unified chat ingestion, deterministic entity/coverage resolution, DuckDB FTS BM25,
contextual conversation episodes, hybrid RRF, and optional local cross-encoder reranking.

Designed to keep core/lib/recstore.py and core/lib/idlicli.py clean and orthogonal across
Drive, Mail, Calendar, and Chat (WhatsApp, and later Slack/Mattermost via `provider`).
"""
import datetime as dt
import hashlib
import json
import math
import os
import re
import time
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

TZ = dt.timezone(dt.timedelta(hours=5, minutes=30))
HTTP_URL_RE = re.compile(r'https?://[^\s<>"\u200b]+', re.I)
CHAT_FILLER = {'group', 'chat', 'whatsapp', 'wa', 'the', 'my', 'our', 'in', 'on', 'from', 'channel'}

RERANK_URL = os.environ.get('IDLI_RERANK_URL', 'http://127.0.0.1:8294')
RERANK_MODEL = os.environ.get('IDLI_RERANK_MODEL', 'idli-rerank')
EPISODE_GAP_S = 900       # 15 minutes within the same chat
EPISODE_MAX_CHARS = 1500  # split very long bursts with 2-message overlap

LAST_TELEMETRY = {}


class EntityError(ValueError):
    """Raised when a chat or sender name cannot be uniquely resolved."""


class EntityNotFoundError(EntityError):
    """Raised when a requested chat or sender does not exist in the store."""


class EntityAmbiguousError(EntityError):
    """Raised when a chat or sender name matches multiple distinct entities."""


def stable_ref(raw_id):
    return hashlib.sha256(str(raw_id).encode()).hexdigest()[:20]


def _local(ts):
    if ts is None:
        return None
    if isinstance(ts, (int, float)):
        return dt.datetime.fromtimestamp(ts, TZ).replace(tzinfo=None)
    if isinstance(ts, dt.datetime):
        return ts.astimezone(TZ).replace(tzinfo=None) if ts.tzinfo else ts
    return ts


def _http_links(text):
    seen, out = set(), []
    for u in HTTP_URL_RE.findall(text or ''):
        u = u.rstrip('.,;!?)')
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return ' '.join(out)


def _tokens(text, drop_filler=False):
    toks = re.findall(r'[a-z0-9]+', (text or '').casefold())
    if drop_filler:
        kept = [t for t in toks if t not in CHAT_FILLER]
        return kept or toks
    return toks


def _stem_lite(tok):
    """Lightweight root normalizer for English derivational suffixes Porter leaves apart
    (e.g. birding/birders -> bird, rehearsing/rehearsals -> rehears)."""
    t = (tok or '').casefold()
    for suf in ('ations', 'ation', 'ments', 'ment', 'ings', 'ing', 'ers', 'er', 'ies', 'ied', 'als', 'al', 'ed', 'es', 's'):
        if len(t) - len(suf) >= 4 and t.endswith(suf):
            return t[:-len(suf)]
    return t


def _fuzzy_tok_score(qt, mt):
    if qt == mt:
        return 1.0
    if len(qt) >= 3 and mt.startswith(qt) and len(mt) <= len(qt) + 5:
        return 0.92
    if len(qt) >= 4 and len(mt) >= 4 and _stem_lite(qt) == _stem_lite(mt):
        return 0.94
    if abs(len(mt) - len(qt)) <= 3:
        jw = _jaro_winkler(qt, mt)
        if jw >= 0.85:
            return jw
    return 0.0


def _jaro_winkler(s1, s2):
    """Pure-Python Jaro-Winkler similarity in [0, 1] (no extra dependency)."""
    s1, s2 = (s1 or '').casefold(), (s2 or '').casefold()
    if s1 == s2:
        return 1.0
    if not s1 or not s2:
        return 0.0
    l1, l2 = len(s1), len(s2)
    dist = max(0, max(l1, l2) // 2 - 1)
    m1, m2 = [False] * l1, [False] * l2
    matches = 0
    for i in range(l1):
        lo, hi = max(0, i - dist), min(i + dist + 1, l2)
        for j in range(lo, hi):
            if not m2[j] and s1[i] == s2[j]:
                m1[i] = m2[j] = True
                matches += 1
                break
    if not matches:
        return 0.0
    t, k = 0, 0
    for i in range(l1):
        if m1[i]:
            while not m2[k]:
                k += 1
            if s1[i] != s2[k]:
                t += 1
            k += 1
    jaro = (matches / l1 + matches / l2 + (matches - t / 2) / matches) / 3.0
    prefix = 0
    for a, b in zip(s1[:4], s2[:4]):
        if a == b:
            prefix += 1
        else:
            break
    return jaro + 0.1 * prefix * (1.0 - jaro)


def ensure_fts(con):
    """Load DuckDB's built-in FTS extension if available. Returns True on success."""
    try:
        con.execute('LOAD fts')
        return True
    except Exception:
        try:
            con.execute('INSTALL fts; LOAD fts')
            return True
        except Exception:
            return False


def _fts_exists(con, table):
    try:
        r = con.execute(
            "SELECT 1 FROM information_schema.schemata WHERE schema_name = ?",
            [f'fts_main_{table}'],
        ).fetchone()
        return bool(r)
    except Exception:
        return False


def rebuild_message_fts(con):
    if not ensure_fts(con):
        return False
    n_msg = con.execute('SELECT count(*) FROM messages').fetchone()[0]
    if n_msg:
        con.execute(
            "PRAGMA create_fts_index('messages', 'id', 'body', 'link_preview', 'filename', 'sender', 'chat_name', "
            "stemmer='porter', stopwords='english', lower=1, overwrite=1)"
        )
    n_ep = con.execute('SELECT count(*) FROM message_episodes').fetchone()[0]
    if n_ep:
        con.execute(
            "PRAGMA create_fts_index('message_episodes', 'episode_id', 'context_text', "
            "stemmer='porter', stopwords='english', lower=1, overwrite=1)"
        )
    return True


def _format_msg_line(m, parent_map=None):
    ts = m['sent_at']
    stamp = ts.strftime('%d %b %H:%M') if isinstance(ts, dt.datetime) else str(ts)
    parts = [f"[{stamp} · {m['sender']} · ref {m['id']}]"]
    if parent_map and m.get('parent_id') and m['parent_id'] in parent_map:
        p = parent_map[m['parent_id']]
        pts = p['sent_at'].strftime('%d %b %H:%M') if isinstance(p['sent_at'], dt.datetime) else ''
        parts.append(f"(replying to {p['sender']} {pts}: \"{p['body'][:120]}\")")
    body = m['body'] or ''
    if m.get('link_preview'):
        body += f" [Preview: {m['link_preview'][:240]}]"
    if m.get('filename') and m['filename'] not in body:
        body += f" [File: {m['filename']}]"
    return ' '.join(parts) + ': ' + body


def build_message_episodes(con):
    """Deterministically group chat messages into contextual episodes using:
    (explicit parent_id reply links) U (same-chat consecutive gaps <= EPISODE_GAP_S).
    Zero LLM calls; splits oversized threads with 2-message overlap."""
    rows = con.execute(
        'SELECT id, chat_id, chat_name, sent_at, sender, body, link_preview, filename, parent_id '
        'FROM messages ORDER BY chat_id, sent_at, id'
    ).fetchall()
    by_chat = defaultdict(list)
    for r in rows:
        by_chat[r[1]].append({
            'id': r[0], 'chat_id': r[1], 'chat_name': r[2], 'sent_at': r[3],
            'sender': r[4] or 'Unknown', 'body': r[5] or '', 'link_preview': r[6] or '',
            'filename': r[7] or '', 'parent_id': r[8] or '',
        })
    episodes = []
    for chat_id, msgs in by_chat.items():
        idx = {m['id']: i for i, m in enumerate(msgs)}
        parent_uf = list(range(len(msgs)))

        def find(x):
            while parent_uf[x] != x:
                parent_uf[x] = parent_uf[parent_uf[x]]
                x = parent_uf[x]
            return x

        def union(a, b):
            ra, rb = find(a), find(b)
            if ra != rb:
                parent_uf[rb] = ra

        for i, m in enumerate(msgs):
            if i > 0 and m['sent_at'] and msgs[i - 1]['sent_at']:
                gap = (m['sent_at'] - msgs[i - 1]['sent_at']).total_seconds()
                if 0 <= gap <= EPISODE_GAP_S:
                    union(i - 1, i)
            if m['parent_id'] and m['parent_id'] in idx:
                union(idx[m['parent_id']], i)

        comps = defaultdict(list)
        for i in range(len(msgs)):
            comps[find(i)].append(msgs[i])

        msg_by_id = {m['id']: m for m in msgs}
        chat_name = msgs[0]['chat_name']

        def emit_window(win, seq_no):
            if not win:
                return
            # Include any referenced parent not already inside this window.
            win_ids = {m['id'] for m in win}
            extra_parents = []
            for m in win:
                pid = m.get('parent_id')
                if pid and pid in msg_by_id and pid not in win_ids:
                    extra_parents.append(msg_by_id[pid])
                    win_ids.add(pid)
            ordered = sorted(extra_parents + win, key=lambda x: (x['sent_at'] or dt.datetime.min, x['id']))
            speakers = list(dict.fromkeys(m['sender'] for m in ordered if m['sender']))
            start_at = ordered[0]['sent_at']
            end_at = ordered[-1]['sent_at']
            if start_at and end_at:
                span = (start_at.strftime('%d %b %Y') if start_at.date() == end_at.date()
                        else f"{start_at.strftime('%d %b')}–{end_at.strftime('%d %b %Y')}")
            else:
                span = ''
            head = f"Chat: {chat_name} | {span} | Speakers: {', '.join(speakers[:12])}"
            lines = [head] + [_format_msg_line(m, msg_by_id) for m in ordered]
            text = '\n'.join(lines)
            ep_id = stable_ref(f"{chat_id}:{ordered[0]['id']}:{ordered[-1]['id']}:{seq_no}")[:16]
            episodes.append((
                ep_id, chat_id, chat_name, start_at, end_at,
                json.dumps([m['id'] for m in ordered]),
                ', '.join(speakers), text,
            ))

        seq = 0
        for comp in comps.values():
            comp.sort(key=lambda m: (m['sent_at'] or dt.datetime.min, m['id']))
            cur, cur_chars = [], 0
            for m in comp:
                line_len = len(m['body']) + len(m['link_preview']) + 80
                if cur and cur_chars + line_len > EPISODE_MAX_CHARS:
                    seq += 1
                    emit_window(cur, seq)
                    # Keep 2-message overlap so cross-boundary follow-ups stay connected.
                    cur = cur[-2:]
                    cur_chars = sum(len(x['body']) + len(x['link_preview']) + 80 for x in cur)
                cur.append(m)
                cur_chars += line_len
            if cur:
                seq += 1
                emit_window(cur, seq)

    con.execute('DELETE FROM message_episodes')
    if episodes:
        con.executemany(
            'INSERT OR REPLACE INTO message_episodes '
            '(episode_id, chat_id, chat_name, start_at, end_at, message_ids, speakers, context_text, vec) '
            'VALUES (?,?,?,?,?,?,?,?,NULL)',
            episodes,
        )
    return len(episodes)


def embed_message_episodes(con, embed_fn, progress=None):
    """Embed episodes missing a vector using the local embedding service."""
    todo = con.execute(
        'SELECT episode_id, context_text FROM message_episodes WHERE vec IS NULL ORDER BY start_at DESC'
    ).fetchall()
    if not todo:
        return 0
    t0 = time.time()
    vecs = embed_fn([r[1] for r in todo], query=False)
    con.executemany(
        'UPDATE message_episodes SET vec = ? WHERE episode_id = ?',
        [[v, r[0]] for r, v in zip(todo, vecs)],
    )
    if progress:
        progress(len(todo), len(todo), 0, time.time() - t0, 'embedding chat episodes')
    return len(todo)


def default_whatsapp_snapshot():
    env = os.environ.get('IDLI_WHATSAPP_SNAPSHOT')
    if env:
        return Path(env).expanduser()
    cand = Path.home() / '.local/share/silo-owner-pilot/whatsmeow-smoke/snapshot.json'
    if cand.is_file():
        return cand
    return None


def _chat_matches_selector(chat_name, selector):
    q = (selector or '').strip()
    if not q:
        return True
    name_low = (chat_name or '').casefold()
    q_low = q.casefold()
    if q_low in name_low:
        return True
    q_toks = _tokens(q, drop_filler=True)
    ctoks = _tokens(chat_name, drop_filler=False)
    if not q_toks or not ctoks:
        return False
    if all(any(ct == qt or (len(qt) >= 3 and ct.startswith(qt)) for ct in ctoks) for qt in q_toks):
        return True
    if len(q_toks) == 1 and 2 <= len(q_toks[0]) <= 4:
        if ''.join(t[0] for t in ctoks).startswith(q_toks[0]):
            return True
    return False


def sync_whatsapp(con, snapshot_path=None, days=None, only_chats=None, embed_fn=None, progress=None, on_item=None):
    """Ingest a WhatsApp JSON snapshot (WA-JS `fresh.json` or whatsmeow `snapshot.json`)
    into first-class `chats`, `messages`, `chat_members`, and `message_episodes` tables,
    plus DuckDB FTS and optional embeddings.
    `only_chats`: optional list of chat/group name selectors (e.g. ['Jam Buns', 'Royal Enfield'])
    so testers can scope sync to specific groups only."""
    path = Path(snapshot_path).expanduser() if snapshot_path else default_whatsapp_snapshot()
    if not path or not path.is_file():
        checked = f' (checked {path})' if path else ''
        raise ValueError(
            f'No WhatsApp snapshot found{checked}. Run `./bridges/whatsapp/start.sh` first to pair WhatsApp '
            'and capture snapshot.json, or pass `--from-snapshot PATH`.'
        )
    t0 = time.time()
    snap = json.loads(path.read_text())
    provider = snap.get('provider') or 'whatsapp'
    raw_chats = list(snap.get('groups') or []) + list(snap.get('dms') or [])
    selectors = []
    for item in (only_chats or []):
        for part in str(item).split(','):
            if part.strip():
                selectors.append(part.strip())
    if selectors:
        matched_chats = [
            c for c in raw_chats
            if any(_chat_matches_selector(str(c.get('name') or c.get('id') or ''), sel) for sel in selectors)
        ]
        if not matched_chats:
            avail = ', '.join(str(c.get('name') or c.get('id')) for c in raw_chats[:10])
            raise ValueError(f'No chats in snapshot matched --in {selectors}. Sample chats: {avail}')
        raw_chats = matched_chats
    cutoff = None
    if days is not None and days > 0:
        all_ts = [r['t'] for c in raw_chats for r in (c.get('rows') or []) if r.get('t')]
        if all_ts:
            cutoff = max(all_ts) - int(days) * 86400

    now_local = _local(dt.datetime.now(TZ))
    chat_rows, msg_rows = [], []
    member_counts = Counter()
    member_last = {}
    reply_counts = Counter()

    for c in raw_chats:
        chat_id = str(c.get('id') or stable_ref(c.get('name', '')))
        chat_name = str(c.get('name') or chat_id).strip()
        is_group = bool(c.get('is_group', True if c in (snap.get('groups') or []) else False))
        # Map optional WA-JS `relations` array by raw message id.
        rels = {}
        for rel in c.get('relations') or []:
            if rel.get('id'):
                rels[rel['id']] = rel

        c_msgs = []
        for r in c.get('rows') or []:
            ts = r.get('t')
            if cutoff is not None and ts is not None and ts < cutoff:
                continue
            raw_id = r.get('id') or f"{chat_id}|{r.get('stanza_id')}|{ts}"
            ref = stable_ref(raw_id)
            rel = rels.get(raw_id) or {}
            raw_parent = r.get('parent') or rel.get('parent') or ''
            parent_ref = stable_ref(raw_parent) if raw_parent else ''
            body = str(r.get('body') or '')
            preview = str(r.get('preview') or '')
            filename = str(r.get('filename') or rel.get('filename') or '')
            source_type = str(r.get('source_type') or ('document' if filename and not body else 'text'))
            sender = str(r.get('sender') or 'Unknown').strip() or 'Unknown'
            is_from_me = bool(r.get('is_from_me') or sender.casefold() == 'me')
            sender_id = str(r.get('sender_id') or ('me' if is_from_me else stable_ref(sender.casefold())[:12]))
            sent_at = _local(ts)
            links = _http_links(body)
            c_msgs.append((
                ref, raw_id, provider, chat_id, chat_name, sent_at, sender_id, sender,
                is_from_me, source_type, body, links, preview, filename, parent_ref,
            ))
            if parent_ref:
                reply_counts[parent_ref] += 1
            mkey = (chat_id, sender_id, sender)
            member_counts[mkey] += 1
            if mkey not in member_last or (sent_at and (member_last[mkey] is None or sent_at > member_last[mkey])):
                member_last[mkey] = sent_at

        if not c_msgs:
            continue
        ts_list = [m[5] for m in c_msgs if m[5] is not None]
        earliest = min(ts_list) if ts_list else _local(c.get('earliest_at') or c.get('active_at'))
        latest = max(ts_list) if ts_list else _local(c.get('latest_at') or c.get('active_at'))
        active_at = _local(c.get('active_at')) or latest
        partial = bool(c.get('hit_cap') or (snap.get('cap') and (c.get('fetched') or 0) >= snap.get('cap')) or True)
        chat_rows.append((
            chat_id, provider, chat_name, is_group, active_at, earliest, latest,
            len(c_msgs), partial, now_local,
        ))
        msg_rows.extend(c_msgs)
        if on_item:
            on_item(chat_name, f'{len(c_msgs)} messages')

    con.execute('BEGIN')
    try:
        con.execute('DELETE FROM chats WHERE provider = ?', [provider])
        con.execute('DELETE FROM messages WHERE provider = ?', [provider])
        con.execute('DELETE FROM chat_members WHERE chat_id NOT IN (SELECT id FROM chats)')
        if chat_rows:
            con.executemany('INSERT OR REPLACE INTO chats VALUES (?,?,?,?,?,?,?,?,?,?)', chat_rows)
        if msg_rows:
            final_msgs = [
                (*m, int(reply_counts.get(m[0], 0)), now_local)
                for m in msg_rows
            ]
            con.executemany(
                'INSERT OR REPLACE INTO messages VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                final_msgs,
            )
        # Consolidate chat_members by (chat_id, sender_id) keeping the most common/latest display name.
        by_member = {}
        for (cid, sid, sname), cnt in member_counts.items():
            prev = by_member.get((cid, sid))
            last_t = member_last[(cid, sid, sname)]
            if prev is None or cnt > prev[1]:
                by_member[(cid, sid)] = (sname, cnt, last_t)
            else:
                by_member[(cid, sid)] = (prev[0], prev[1] + cnt, max(prev[2], last_t) if prev[2] and last_t else (prev[2] or last_t))
        if by_member:
            con.executemany(
                'INSERT OR REPLACE INTO chat_members VALUES (?,?,?,?,?)',
                [(cid, sid, sname, cnt, last_t) for (cid, sid), (sname, cnt, last_t) in by_member.items()],
            )
        con.execute('COMMIT')
    except Exception:
        con.execute('ROLLBACK')
        raise

    n_episodes = build_message_episodes(con)
    fts_ok = rebuild_message_fts(con)
    n_embedded = 0
    embed_err = None
    if embed_fn is not None:
        try:
            n_embedded = embed_message_episodes(con, embed_fn, progress=progress)
        except Exception as e:
            embed_err = type(e).__name__
    elapsed = round(time.time() - t0, 2)
    con.execute('INSERT INTO sync_log VALUES (?, ?, ?, ?, ?)',
                [provider, str(path.name), len(msg_rows), elapsed, now_local])
    return {
        'provider': provider, 'chats': len(chat_rows), 'messages': len(msg_rows),
        'episodes': n_episodes, 'embedded': n_embedded, 'embed_error': embed_err,
        'fts': fts_ok, 'seconds': elapsed,
    }


# ---- Deterministic entity & coverage resolution ----

def resolve_chat(con, query):
    """Resolve a natural/partial chat name (e.g. 'Jam Buns', 'Royal Enfield', 'RE')
    to a canonical row in `chats`. Distinguishes unique match, ambiguous match, and unknown."""
    q = (query or '').strip()
    if not q:
        raise EntityNotFoundError('No chat name given.')
    rows = con.execute(
        'SELECT id, name, provider, earliest_at, latest_at, msg_count FROM chats ORDER BY active_at DESC'
    ).fetchall()
    if not rows:
        raise EntityNotFoundError('No chats are synced in this store yet. Run `idli sync whatsapp` first.')

    q_low = q.casefold()
    # Tier 1: exact id or exact name match
    exact = [r for r in rows if r[0] == q or r[1].casefold() == q_low]
    if len(exact) == 1:
        return exact[0]

    q_toks = _tokens(q, drop_filler=True)
    if not q_toks:
        raise EntityNotFoundError(f'No chat matching "{q}".')

    # Tier 2: substring or all query tokens match whole/prefix tokens of chat name
    tok_hits = []
    for r in rows:
        name_low = r[1].casefold()
        ctoks = _tokens(r[1], drop_filler=False)
        if q_low in name_low:
            tok_hits.append((3, len(ctoks), r))
            continue
        if all(any(ct == qt or (len(qt) >= 3 and ct.startswith(qt)) for ct in ctoks) for qt in q_toks):
            tok_hits.append((2, len(ctoks), r))
            continue
        # Acronym match (e.g. 'RE' -> 'Royal Enfield ...')
        if len(q_toks) == 1 and 2 <= len(q_toks[0]) <= 4 and ctoks:
            acro = ''.join(t[0] for t in ctoks)
            if acro.startswith(q_toks[0]):
                tok_hits.append((1, len(ctoks), r))
    if tok_hits:
        best_tier = max(h[0] for h in tok_hits)
        top = [h[2] for h in tok_hits if h[0] == best_tier]
        if len(top) == 1:
            return top[0]
        # Prefer exact token-set match over longer superstrings if unique
        if best_tier == 3:
            tighter = [r for r in top if _tokens(r[1], True) == q_toks]
            if len(tighter) == 1:
                return tighter[0]
        names = ', '.join(f'"{r[1]}"' for r in top[:6])
        raise EntityAmbiguousError(f'Multiple chats match "{q}": {names}. Say which chat you mean.')

    # Tier 3: strict fuzzy token match (every query token must closely match a chat token)
    fuzzy = []
    for r in rows:
        ctoks = _tokens(r[1], drop_filler=False)
        if not ctoks:
            continue
        token_scores = [max(_jaro_winkler(qt, ct) for ct in ctoks) for qt in q_toks]
        if min(token_scores) >= 0.88:
            fuzzy.append((sum(token_scores) / len(token_scores), r))
    if len(fuzzy) == 1:
        return fuzzy[0][1]
    if len(fuzzy) > 1:
        fuzzy.sort(key=lambda x: -x[0])
        names = ', '.join(f'"{r[1]}"' for _, r in fuzzy[:6])
        raise EntityAmbiguousError(f'Multiple chats match "{q}": {names}. Say which chat you mean.')

    # Unknown chat: suggest only genuinely similar names, never silently return 0 rows
    suggestions = []
    for r in rows:
        ctoks = _tokens(r[1], drop_filler=False)
        if not ctoks:
            continue
        sc = sum(max(_jaro_winkler(qt, ct) for ct in ctoks) for qt in q_toks) / len(q_toks)
        overlap = len(set(q_toks) & set(ctoks))
        if sc >= 0.78 and overlap >= 1:
            suggestions.append((sc, r[1]))
    suggestions.sort(key=lambda x: -x[0])
    hint = f' Closest chats: {", ".join(repr(n) for _, n in suggestions[:3])}.' if suggestions else ''
    raise EntityNotFoundError(f'No chat named "{q}" was found in the synced chats.{hint}')


def resolve_sender(con, query, chat_id=None):
    """Resolve a sender name/nickname/initial against `chat_members` (scoped to `chat_id` if given).
    Returns (canonical_display_name, [matching_sender_ids]) or raises EntityNotFoundError / EntityAmbiguousError."""
    q = (query or '').strip().strip('.,!?;:')
    if not q:
        raise EntityNotFoundError('No sender name given.')
    if chat_id:
        rows = con.execute(
            'SELECT sender_id, sender, msg_count FROM chat_members WHERE chat_id = ? ORDER BY msg_count DESC',
            [chat_id],
        ).fetchall()
    else:
        rows = con.execute(
            'SELECT sender_id, arg_max(sender, msg_count) AS sender, sum(msg_count) AS n '
            'FROM chat_members GROUP BY sender_id ORDER BY n DESC'
        ).fetchall()
    if not rows:
        scope = 'this chat' if chat_id else 'your synced chats'
        raise EntityNotFoundError(f'No senders recorded in {scope}.')

    # Group by canonical display name (casefolded) so the same person across chats doesn't look ambiguous.
    by_person = {}
    for sid, sname, cnt in rows:
        key = (sname or sid).strip().casefold()
        if key not in by_person:
            by_person[key] = {'name': (sname or sid).strip(), 'ids': [sid], 'cnt': int(cnt or 0)}
        else:
            if sid not in by_person[key]['ids']:
                by_person[key]['ids'].append(sid)
            by_person[key]['cnt'] += int(cnt or 0)
    people = list(by_person.values())
    q_low = q.casefold()
    q_toks = _tokens(q)

    def pick(cands):
        if len(cands) == 1:
            return cands[0]['name'], cands[0]['ids']
        if len(cands) > 1:
            cands.sort(key=lambda p: (-p['cnt'], p['name']))
            opts = ', '.join(p['name'] for p in cands[:6])
            raise EntityAmbiguousError(f'Multiple people match "{q}": {opts}. Which person did you mean?')
        return None

    # Tier 1: exact name match
    r = pick([p for p in people if p['name'].casefold() == q_low])
    if r:
        return r
    # Tier 2: first token exact match (e.g. "Vidya" -> "Vidya S")
    if len(q_toks) == 1:
        r = pick([p for p in people if _tokens(p['name'])[:1] == q_toks])
        if r:
            return r
    # Tier 3: first token prefix match (e.g. "Abhi" -> "Abhiram", "V" -> all V* first names)
    if len(q_toks) == 1:
        qt = q_toks[0]
        r = pick([p for p in people if _tokens(p['name']) and _tokens(p['name'])[0].startswith(qt)])
        if r:
            return r
    # Tier 4: all query tokens prefix-match some token (for multi-word names or >=3 char nicknames)
    if len(q_toks) > 1 or len(q_low) >= 3:
        r = pick([
            p for p in people
            if all(any(pt.startswith(qt) for pt in _tokens(p['name'])) for qt in q_toks)
        ])
        if r:
            return r
    # Tier 5: fuzzy match for >=4 chars
    if len(q_low) >= 4:
        r = pick([
            p for p in people
            if any(_jaro_winkler(q_low, pt) >= 0.88 for pt in _tokens(p['name']))
        ])
        if r:
            return r
    scope = 'that chat' if chat_id else 'your synced chats'
    raise EntityNotFoundError(f'No sender matching "{q}" was found in {scope}.')


def chat_coverage_note(chat_row):
    _, name, _, earliest, latest, count = chat_row
    if earliest and latest:
        return f'In chat "{name}" (cached {earliest:%d %b %Y} to {latest:%d %b %Y}, {count} messages)'
    return f'In chat "{name}" ({count} messages)'


def check_date_coverage(con, chat_id, start_date, end_date):
    """Compare requested [start_date, end_date) against cached message timestamps.
    Returns (status, note) where status is 'covered' | 'partial' | 'outside'."""
    if chat_id:
        row = con.execute(
            'SELECT earliest_at, latest_at, name FROM chats WHERE id = ?', [chat_id]
        ).fetchone()
    else:
        row = con.execute(
            "SELECT min(earliest_at), max(latest_at), 'synced chats' FROM chats"
        ).fetchone()
    if not row or not row[0] or not row[1]:
        return 'covered', ''
    earliest, latest, label = row
    req_start = dt.datetime.combine(start_date, dt.time.min) if start_date else None
    req_end = dt.datetime.combine(end_date, dt.time.min) if end_date else None
    if req_end and req_end <= earliest:
        return 'outside', (
            f'Cached history for {label} only covers {earliest:%d %b %Y} to {latest:%d %b %Y}; '
            f'earlier dates are outside the cached window.'
        )
    if req_start and req_start < earliest and (not req_end or req_end > earliest):
        return 'partial', (
            f'Note: cached history for {label} starts on {earliest:%d %b %Y} '
            f'(earlier days in that period are not in the store).'
        )
    return 'covered', ''


# ---- Local Cross-Encoder Reranker ----

def _sigmoid(x):
    try:
        return 1.0 / (1.0 + math.exp(-float(x)))
    except OverflowError:
        return 0.0 if x < 0 else 1.0


def rerank(query, documents, timeout=20):
    """Call llama-server /v1/rerank endpoint (local DGX or via Cloudflare Access muse-access.json).
    Returns list of (doc_index, raw_score, prob) sorted descending, or None if unavailable/disabled."""
    if os.environ.get('IDLI_RERANK', '1') == '0' or not documents or not query:
        return None
    from lib import muse
    base, hdrs = muse.rerank_upstream()
    url = base.rstrip('/') + '/v1/rerank'
    body = {'model': RERANK_MODEL, 'query': query, 'documents': [d[:2000] for d in documents]}
    req = urllib.request.Request(
        url, json.dumps(body).encode(), {**hdrs, 'Content-Type': 'application/json'}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.load(resp)
        results = data.get('results') or []
        scored = [
            (int(item['index']), float(item['relevance_score']), round(_sigmoid(item['relevance_score']), 4))
            for item in results
        ]
        scored.sort(key=lambda x: -x[1])
        return scored
    except Exception:
        return None


# ---- Hybrid Message Search ----

def _message_search_context(row_map, mid, ordered_by_chat):
    """Build a compact contextual passage around one candidate message for reranking."""
    m = row_map[mid]
    parts = [f"Chat: {m['chat_name']} | {m['sent_at']:%d %b %Y %H:%M} | {m['sender']}"]
    pid = m.get('parent_id')
    if pid and pid in row_map:
        p = row_map[pid]
        parts.append(f"[Quoting {p['sender']} ({p['sent_at']:%d %b %H:%M}): {p['body'][:240]}]")
    body = m['body']
    if m.get('link_preview'):
        body += f" [Preview: {m['link_preview'][:240]}]"
    if m.get('filename') and m['filename'] not in body:
        body += f" [File: {m['filename']}]"
    parts.append(body[:600])
    # Include immediate same-chat ±1 neighbor if within 5 minutes so follow-up links carry context.
    seq = ordered_by_chat.get(m['chat_id']) or []
    pos = m.get('_pos')
    if pos is not None:
        for delta in (-1, 1):
            j = pos + delta
            if 0 <= j < len(seq):
                nb = seq[j]
                if nb['sent_at'] and m['sent_at'] and abs((nb['sent_at'] - m['sent_at']).total_seconds()) <= 300:
                    parts.append(f"[Nearby {nb['sender']} ({nb['sent_at']:%H:%M}): {nb['body'][:200]}]")
    return '\n'.join(parts)


def search_messages(con, query_text, base_ids, chat_name_hint=None, embed_fn=None, limit=12, intent_query=None):
    """Hybrid search over `messages` + `message_episodes` restricted to `base_ids`:
      1. Path A1: DuckDB FTS BM25 on individual messages (Porter stemming + IDF)
      2. Path A2: DuckDB FTS BM25 on contextualized episodes (cross-message keywords)
      3. Path A3: Jaro-Winkler + stem-lite fuzzy token fallback when lexical hits are sparse
      4. Path B:  Bi-encoder (Qwen3-Embedding-0.6B) cosine similarity on episode vectors
      5. Merge via RRF -> top ~35 candidates (or all messages when scope <= 35)
      6. Stage 3: Local Cross-Encoder Reranker (bge-reranker-v2-m3 on :8294, graceful fallback)
      7. Attach direct quoted parents and immediate same-sender follow-ups for top hits.
    When `intent_query` (the full user question from `ask`) is provided, BM25 runs on both
    `query_text` and `intent_query`, while Bi-encoder and Cross-encoder use the richer `intent_query`.
    Returns list of (message_id, found_label) ordered best-first, and populates LAST_TELEMETRY."""
    LAST_TELEMETRY.clear()
    if not base_ids:
        return []
    base_set = set(base_ids)
    t0 = time.time()

    def _strip_chat(text):
        s = (text or '').strip()
        if chat_name_hint and s:
            ctoks = set(_tokens(chat_name_hint, drop_filler=True))
            trimmed = ' '.join(w for w in s.split() if w.casefold().strip('?,.:;"\'!') not in ctoks)
            if trimmed:
                return trimmed
        return s

    topic = _strip_chat(query_text)
    sem_topic = _strip_chat(intent_query) if (intent_query and len(intent_query.strip()) > len(query_text.strip())) else topic

    # Load scoped messages (for fast in-memory metadata, fuzzy fallback, and context assembly).
    all_rows = con.execute(
        'SELECT id, chat_id, chat_name, sent_at, sender, body, links, link_preview, filename, parent_id, reply_count '
        'FROM messages ORDER BY chat_id, sent_at, id'
    ).fetchall()
    row_map = {}
    ordered_by_chat = defaultdict(list)
    replies_by_parent = defaultdict(list)
    for r in all_rows:
        m = {
            'id': r[0], 'chat_id': r[1], 'chat_name': r[2], 'sent_at': r[3], 'sender': r[4],
            'body': r[5] or '', 'links': r[6] or '', 'link_preview': r[7] or '',
            'filename': r[8] or '', 'parent_id': r[9] or '', 'reply_count': r[10] or 0,
        }
        m['_pos'] = len(ordered_by_chat[m['chat_id']])
        ordered_by_chat[m['chat_id']].append(m)
        row_map[m['id']] = m
        if m['parent_id']:
            replies_by_parent[m['parent_id']].append(m)

    # Load episodes that intersect base_set.
    ep_rows = con.execute(
        'SELECT episode_id, chat_id, message_ids, context_text, vec IS NOT NULL FROM message_episodes'
    ).fetchall()
    ep_msgs = {}
    scoped_eps = set()
    for ep_id, cid, mids_json, _, _ in ep_rows:
        mids = json.loads(mids_json or '[]')
        ep_msgs[ep_id] = mids
        if any(m in base_set for m in mids):
            scoped_eps.add(ep_id)

    # Path A1: DuckDB FTS BM25 on messages (filtered to base_set BEFORE LIMIT)
    fts_ok = ensure_fts(con)
    bm25_msg = []
    base_list = list(base_set)
    scoped_ep_list = list(scoped_eps)
    if fts_ok and _fts_exists(con, 'messages'):
        msg_scores = {}
        for q_str, w in ((topic, 1.0), (sem_topic, 0.7)):
            if not q_str or (w < 1.0 and q_str == topic):
                continue
            try:
                hits = con.execute(
                    'SELECT id, sc FROM ('
                    '  SELECT id, fts_main_messages.match_bm25(id, ?, conjunctive := false) AS sc '
                    '  FROM messages WHERE id IN (SELECT unnest(?::VARCHAR[]))'
                    ') WHERE sc IS NOT NULL ORDER BY sc DESC LIMIT 40',
                    [q_str, base_list],
                ).fetchall()
                for mid, sc in hits:
                    msg_scores[mid] = max(msg_scores.get(mid, 0.0), float(sc) * w)
            except Exception:
                pass
        bm25_msg = sorted(msg_scores.items(), key=lambda x: -x[1])[:30]

    # Path A2: DuckDB FTS BM25 on episodes (filtered to scoped_eps BEFORE LIMIT)
    bm25_ep = []
    if fts_ok and _fts_exists(con, 'message_episodes') and scoped_ep_list:
        ep_scores = {}
        for q_str, w in ((topic, 1.0), (sem_topic, 0.7)):
            if not q_str or (w < 1.0 and q_str == topic):
                continue
            try:
                hits = con.execute(
                    'SELECT episode_id, sc FROM ('
                    '  SELECT episode_id, fts_main_message_episodes.match_bm25(episode_id, ?, conjunctive := false) AS sc '
                    '  FROM message_episodes WHERE episode_id IN (SELECT unnest(?::VARCHAR[]))'
                    ') WHERE sc IS NOT NULL ORDER BY sc DESC LIMIT 25',
                    [q_str, scoped_ep_list],
                ).fetchall()
                for eid, sc in hits:
                    ep_scores[eid] = max(ep_scores.get(eid, 0.0), float(sc) * w)
            except Exception:
                pass
        bm25_ep = sorted(ep_scores.items(), key=lambda x: -x[1])[:20]

    # Path A3: Fuzzy + prefix + stem-lite token fallback when lexical hits are sparse
    fuzzy_msg = []
    q_toks = [t for t in _tokens(topic) if len(t) >= 3]
    if len(bm25_msg) < 5 and q_toks:
        for mid in base_set:
            m = row_map.get(mid)
            if not m:
                continue
            mtoks = set(_tokens(f"{m['body']} {m['link_preview']} {m['filename']} {m['sender']}"))
            if not mtoks:
                continue
            sc = 0.0
            matched = 0
            for qt in q_toks:
                best = max((_fuzzy_tok_score(qt, mt) for mt in mtoks), default=0.0)
                if best >= 0.85:
                    sc += best
                    matched += 1
            if matched:
                fuzzy_msg.append((mid, sc + matched * 0.5))
        fuzzy_msg.sort(key=lambda x: -x[1])
        fuzzy_msg = fuzzy_msg[:20]

    # Path B: Bi-encoder cosine similarity on message_episodes.vec (filtered to scoped_eps BEFORE LIMIT)
    sem_ep = []
    embed_err = None
    if embed_fn is not None and scoped_ep_list:
        has_vecs = con.execute('SELECT count(*) FROM message_episodes WHERE vec IS NOT NULL').fetchone()[0]
        if has_vecs:
            try:
                qvec = embed_fn([sem_topic], query=True)[0]
                hits = con.execute(
                    'SELECT episode_id, array_cosine_similarity(vec, ?::FLOAT[1024]) AS sc '
                    'FROM message_episodes WHERE vec IS NOT NULL AND episode_id IN (SELECT unnest(?::VARCHAR[])) '
                    'ORDER BY sc DESC LIMIT 25',
                    [qvec, scoped_ep_list],
                ).fetchall()
                sem_ep = [(eid, float(sc)) for eid, sc in hits]
            except Exception as e:
                embed_err = type(e).__name__

    # Stage 2: Reciprocal Rank Fusion into candidate message list
    rrf = Counter()
    sources = defaultdict(set)
    for rank, (mid, _) in enumerate(bm25_msg):
        rrf[mid] += 1.2 / (15 + rank + 1)
        sources[mid].add('bm25')
    for rank, (mid, _) in enumerate(fuzzy_msg):
        rrf[mid] += 0.9 / (20 + rank + 1)
        sources[mid].add('fuzzy')
    q_tok_set = set(_tokens(sem_topic)) | set(_tokens(topic))
    for ep_list, weight, tag in ((bm25_ep, 0.9, 'ep_bm25'), (sem_ep, 1.15, 'semantic')):
        for rank, (eid, _) in enumerate(ep_list):
            mids = [m for m in ep_msgs.get(eid, []) if m in base_set]
            if not mids:
                continue
            for mid in mids:
                m = row_map.get(mid)
                mtoks = set(_tokens(f"{m['body']} {m['sender']} {m['link_preview']}")) if m else set()
                bonus = 1.25 if (q_tok_set & mtoks) else 0.75
                rrf[mid] += (weight * bonus) / (15 + rank + 1)
                sources[mid].add(tag)

    fused = [mid for mid, _ in rrf.most_common(35)]
    # When the resolved scope itself is small (<= 35 messages), never drop any message before cross-encoder!
    if len(base_set) <= 35:
        seen_f = set(fused)
        for mid in sorted(base_set, key=lambda x: row_map[x]['sent_at'] or dt.datetime.min, reverse=True):
            if mid not in seen_f and mid in row_map:
                fused.append(mid)
                seen_f.add(mid)
                sources[mid].add('scope')

    # Stage 3: Optional Local Cross-Encoder Reranker on top ~35 fused candidates using full intent
    rerank_t0 = time.time()
    reranked = None
    rerank_scores = {}
    if fused:
        passages = [_message_search_context(row_map, mid, ordered_by_chat) for mid in fused]
        reranked = rerank(sem_topic, passages)
    rerank_ms = round((time.time() - rerank_t0) * 1000, 1)

    if reranked:
        ordered_hits = []
        for doc_idx, raw_sc, prob in reranked:
            mid = fused[doc_idx]
            rerank_scores[mid] = (raw_sc, prob)
            ordered_hits.append(mid)
        fallback = None
    else:
        ordered_hits = fused
        fallback = 'disabled' if os.environ.get('IDLI_RERANK', '1') == '0' else 'reranker_unavailable'

    # Expand top anchors with their direct quoted parent and immediate same-sender follow-up (<=3 min)
    # so multi-message answers (e.g. decline quoting invite + link 1 min later) stay together.
    final = []
    seen = set()

    def add_row(mid, label):
        if mid in seen or mid not in row_map or len(final) >= int(limit):
            return
        seen.add(mid)
        m = row_map[mid]
        tags = [label]
        if m.get('parent_id') and m['parent_id'] in row_map:
            tags.append(f"quoting {m['parent_id'][:8]}")
        if m.get('reply_count'):
            tags.append(f"+{m['reply_count']} replies")
        final.append((mid, '; '.join(tags)))

    for rank_i, mid in enumerate(ordered_hits):
        if len(final) >= int(limit):
            break
        src_tags = '+'.join(sorted(sources.get(mid, {'match'})))
        label = f"match ({src_tags})"
        add_row(mid, label)
        if rank_i < 4:
            m = row_map[mid]
            pid = m.get('parent_id')
            if pid and pid in row_map:
                add_row(pid, f"quoted parent of {mid[:8]}")
            seq = ordered_by_chat.get(m['chat_id']) or []
            pos = m.get('_pos')
            if pos is not None:
                for delta in (1, -1):
                    j = pos + delta
                    if 0 <= j < len(seq):
                        nb = seq[j]
                        if (nb['chat_id'] == m['chat_id'] and nb['sender'] == m['sender']
                                and nb['sent_at'] and m['sent_at']
                                and abs((nb['sent_at'] - m['sent_at']).total_seconds()) <= 180):
                            add_row(nb['id'], f"follow-up to {mid[:8]}" if delta == 1 else f"preceding {mid[:8]}")
                            if nb.get('parent_id') and nb['parent_id'] in row_map:
                                add_row(nb['parent_id'], f"quoted parent of {nb['id'][:8]}")
            for rep in replies_by_parent.get(mid, [])[:2]:
                if rep['chat_id'] == m['chat_id']:
                    add_row(rep['id'], f"reply to {mid[:8]}")

    top_prob = rerank_scores[ordered_hits[0]][1] if (ordered_hits and ordered_hits[0] in rerank_scores) else None
    LAST_TELEMETRY.update({
        'query': topic,
        'intent_query': sem_topic if sem_topic != topic else None,
        'scoped_messages': len(base_set),
        'bm25_msg_hits': len(bm25_msg),
        'bm25_ep_hits': len(bm25_ep),
        'fuzzy_hits': len(fuzzy_msg),
        'sem_ep_hits': len(sem_ep),
        'embed_error': embed_err,
        'fused_candidates': len(fused),
        'reranker_used': bool(reranked),
        'reranker_ms': rerank_ms if reranked else 0,
        'top_prob': top_prob,
        'fallback': fallback,
        'top_scores': [(mid[:8], rerank_scores[mid][1]) for mid in ordered_hits[:5] if mid in rerank_scores],
        'total_ms': round((time.time() - t0) * 1000, 1),
    })
    return final


def search_episodes(con, query_text, base_ids, chat_name_hint=None, embed_fn=None, limit=5, intent_query=None):
    """Return top-K full contextualized episodes (plus their member message rows) for `summarise messages`."""
    hits = search_messages(con, query_text, base_ids, chat_name_hint=chat_name_hint, embed_fn=embed_fn,
                           limit=20, intent_query=intent_query)
    if not hits:
        return []
    hit_ids = [mid for mid, _ in hits]
    # Find episodes containing these top hit messages, preserving rank order.
    ep_rows = con.execute(
        'SELECT episode_id, chat_name, start_at, end_at, message_ids, context_text FROM message_episodes'
    ).fetchall()
    msg_to_eps = defaultdict(list)
    ep_data = {}
    for ep_id, cname, start_at, end_at, mids_json, ctx_text in ep_rows:
        mids = json.loads(mids_json or '[]')
        ep_data[ep_id] = {
            'episode_id': ep_id, 'chat_name': cname, 'start_at': start_at, 'end_at': end_at,
            'message_ids': mids, 'context_text': ctx_text,
        }
        for mid in mids:
            msg_to_eps[mid].append(ep_id)
    picked, seen = [], set()
    for mid in hit_ids:
        for ep_id in msg_to_eps.get(mid, []):
            if ep_id not in seen:
                seen.add(ep_id)
                picked.append(ep_data[ep_id])
                if len(picked) >= int(limit):
                    return picked
    return picked
