"""`idli`: the record store on the command line, and `idli ask`, the left chat on top of it.

    idli sync [gmail|gcalendar|drive|all]           copy your Google account into this sandbox (read only); drive also
                                                    reads every document's text and makes a short card for each
    idli list RESOURCE [--where ..] [--since ..]    rows: mail, threads, calendar, files, folders, photos, sheets,
          [--search ..] [--count] [--group-by ..]   rows --sheet NAME, labels, definitions, or a view
    idli get RESOURCE REF [--text] [--outline]      one item in full; a file's text; its pages or a sheet's columns
    idli summarise file NAME | --search WORDS       one file's summary, or what your documents say about a topic
    idli help [RESOURCE]                            fields and examples (the manual page)
    idli define NAME --on mail|event|file|photo --ask "..." --answers yes,no
    idli judge RESOURCE --def NAME [--search ..]    label each row once per definition version (Clef by default)
    idli query "SELECT ..."                         any read-only SQL over the store
    idli view NAME --sql "SELECT ..."               save a query as a resource you can list
    idli draft mail --reply-to THREAD --ask "..."   a draft, previewed only (nothing is saved or sent)
    idli ask "question"                             ask in your own words; it picks the commands and answers
    -v, -vv, -vvv                                   show steps, then prompts and items, then every model call

--search: every word must appear; "words in quotes" are an exact phrase; most mentions first.
Nothing here changes your accounts. docs/goals.md explains the design.
"""
import argparse
import datetime as dt
from email.utils import getaddresses
import json
import os
import re
import shlex
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from lib import recstore as rs

ACCOUNTS = {'me': os.environ.get('IDLI_GOOGLE_ACCOUNT') or '87profligate@gmail.com', 'lead': '88profligate@gmail.com'}


def sandbox():
    return os.environ.get('IDLI_SANDBOX') or str(Path.home() / 'idli-insights' / 'scaffold')


def account(role=None):
    return ACCOUNTS.get(role or 'me', role or ACCOUNTS['me'])


class Result:
    def __init__(self, cols=None, rows=None, text='', kind='table', sql='', note='', chat=None, links=None, source=None):
        self.source = source
        self.links = links or []
        self.chat = chat
        self.cols, self.rows, self.text, self.kind, self.sql, self.note = cols or [], rows or [], text, kind, sql, note

    def render(self, max_rows=20):
        if self.kind == 'text':
            return self.text
        if not self.rows:
            return (self.note + '\n' if self.note else '') + 'Nothing matches.'
        out = []
        for i, r in enumerate(self.rows[:max_rows], 1):
            vals = []
            for col, v in zip(self.cols, r):
                cl = col.lower()
                lim = 0 if cl == 'links' else (450 if cl in ('body', 'found') else 160)
                vals.append(_fmt(v, limit=lim))
            out.append(f'{i}. ' + ' | '.join(v for v in vals if v != ''))
        more = f'\n... and {len(self.rows) - max_rows} more' if len(self.rows) > max_rows else ''
        head = f'{len(self.rows)} row{"s" if len(self.rows) != 1 else ""} ({", ".join(self.cols)})'
        return (self.note + '\n' if self.note else '') + head + '\n' + '\n'.join(out) + more


def source_link(resource, record_id):
    if not record_id:
        return ''
    key = urllib.parse.quote(str(record_id), safe='')
    if resource in ('mail', 'threads'):
        return f'https://mail.google.com/mail/#all/{key}'
    return f'https://drive.google.com/open?id={key}'


def gmail_account_hint(con, text):
    """Label Idli's thread links with the mailbox that supplied each thread."""
    prefix = 'https://mail.google.com/mail/#all/'
    links = {line: urllib.parse.unquote(line[len(prefix):]) for line in text.splitlines()
             if line.startswith(prefix) and line[len(prefix):] and not re.search(r'\s', line)}
    if not links:
        return text
    rows = con.execute("SELECT DISTINCT thread_id, account FROM mail WHERE thread_id IN "
                       "(SELECT unnest(?::VARCHAR[])) AND account IS NOT NULL ORDER BY account",
                       [list(links.values())]).fetchall()
    owners = {}
    for thread, mailbox in rows:
        owners.setdefault(thread, []).append(mailbox)
    if not owners:
        return text
    mailboxes = {mailbox for _, mailbox in rows}
    if len(mailboxes) == 1 and all(thread in owners for thread in links.values()):
        mailbox = next(iter(mailboxes))
        return text + f'\n\nIf Gmail opens to your inbox, switch to {mailbox} and open the link again.'
    lines = []
    for line in text.splitlines():
        lines.append(line)
        if line in links and links[line] in owners:
            lines.append('Open in Gmail as ' + ' or '.join(owners[links[line]]) + '.')
    return '\n'.join(lines)


def sheet_sources(con, sql):
    tables = sorted(con.get_table_names(sql))
    files = con.execute('SELECT DISTINCT name, file_id FROM sheets WHERE tbl IN '
                        '(SELECT unnest(?::VARCHAR[])) ORDER BY name, file_id', [tables]).fetchall()
    return '\n'.join(name + '\n' + source_link('sheets', fid) for name, fid in files)


def chat_result(result, question=""):
    text = _chat_body(result, question)
    return text + '\n' + result.source if result.source else text


def _chat_body(result, question):
    if result.chat is not None:
        return result.chat
    if result.kind == 'text':
        return result.text
    if not result.rows:
        return (result.note + '\n' if result.note else '') + 'I couldn’t find a match.'
    items = []
    is_msg = 'body' in result.cols and 'sender' in result.cols
    if is_msg:
        for row in result.rows[:5]:
            rec = {col: value for col, value in zip(result.cols, row)}
            who = _fmt(rec.get('sender', ''))
            when = _fmt(rec.get('sent_at', ''))
            chat_nm = _fmt(rec.get('chat_name', ''))
            body = _fmt(rec.get('body', ''), limit=320)
            ref = str(rec.get('id') or '')[:8]
            links = str(rec.get('links') or '').strip()
            meta = ' · '.join(filter(None, [who, when, chat_nm, f'ref {ref}' if ref else '']))
            line = f'• {body}\n  _{meta}_'
            if links and links not in body:
                line += f'\n  {links}'
            items.append(line)
        if len(result.rows) > 5:
            items.append(f'{len(result.rows) - 5} more matches.')
        if result.note:
            items.append(f'\n_{result.note}_')
        return '\n'.join(items)
    if 'found' in result.cols:
        found = result.cols.index('found')
        together = sum(str(row[found]).startswith(('phrase', 'mentioned', 'matched in name or folder')) for row in result.rows)
        if together:
            items.append(f'The words occur together in {together} of these files.\n')
        elif re.search(r'\bthe (?:pdf|document|file|invite|spreadsheet)\b', question, re.I):
            return 'I couldn’t identify the specific file. Do you remember its filename, the organizer or the date?'
        elif all(str(row[found]).startswith('similar meaning') for row in result.rows):
            items.append('I found related passages, but no exact text match in these results.\n')
        else:
            items.append('I found the words separately. Do you remember the filename, organizer or date?\n')
    for index, row in enumerate(result.rows[:6]):
        fields = {col: _fmt(value) for col, value in zip(result.cols, row) if value is not None and value != ''}
        if not fields:
            continue
        title = next((fields.pop(col) for col in ('name', 'subject', 'title') if col in fields), '')
        if title and 'found' in fields:
            # The match and its page are the useful evidence in a file search.
            evidence = fields['found'].split(': ...', 1)[0]
            if evidence.startswith('matched in name or folder'):
                evidence = 'matching name or folder'
            evidence = re.sub(r'phrase x(\d+)', r'phrase mentioned \1×', evidence)
            evidence = re.sub(r'similar meaning [\d.]+', 'related by meaning', evidence).replace('; p.', ', p. ')
            items.append(f'• {title} — {evidence}')
        else:
            details = ' · '.join(f'{col.replace("_", " ")}: {value}' for col, value in fields.items())
            items.append('• ' + ('\n  '.join(filter(None, [title, details]))))
        if result.links and result.links[index]:
            items.append(result.links[index])
    if len(result.rows) > 6:
        items.append(f'{len(result.rows) - 6} more matches.')
    return '\n'.join(items)


def _fmt(v, limit=160):
    if isinstance(v, dt.datetime):
        v = rs.local(v)
        return v.strftime('%a %d %b %Y %H:%M') if (v.hour, v.minute) != (0, 0) else v.strftime('%a %d %b %Y')
    if isinstance(v, float):
        return f'{v:.2f}'.rstrip('0').rstrip('.')
    s = '' if v is None else str(v)
    if not limit or len(s) <= limit:
        return s
    return s[:limit - 3] + '...'


# ---- what the person sees while things run: -v, -vv, -vvv (or -v 1..3), progress, the log ----
VERBOSE = int(os.environ.get('IDLI_VERBOSE') or 0)
TTY = sys.stderr.isatty()
MAPPER_CALLS = []  # this turn's mapper calls: the masked prompt sent and the plan returned (for -vv and the log)


def say(level, msg):
    """Print to stderr when -v is at least `level`. Level 1: steps and timings. 2: prompts, plans, every step's rows,
    every judged item. 3: full model calls, retries, library warnings."""
    if VERBOSE >= level:
        if TTY:
            print('\r\033[K', end='', file=sys.stderr)
        print(f'{time.strftime("%H:%M:%S")} {msg}', file=sys.stderr, flush=True)


def dim(text):
    return f'\033[2m{text}\033[0m' if sys.stdout.isatty() else text


def item_line(what):
    """At -vv, one line per item as it finishes: '12:01:03 read thorat.pdf: 5 pages, 25,610 characters, 1.2 s'."""
    return (lambda name, detail: say(2, f'  {what} {name}: {detail}')) if VERBOSE >= 2 else None


def progress_line(done, total, failed, elapsed, what='judging'):
    if not TTY or VERBOSE >= 2:  # at -vv every item prints its own line
        return
    left = (elapsed / done) * (total - done) if done else 0
    eta = (f', about {int(left // 60)} min {int(left % 60)} s left' if left >= 60 else f', about {int(left)} s left') \
        if done < total else ''
    print(f'\r\033[K{what} {done} of {total}' + (f', {failed} failed' if failed else '') + eta,
          end='' if done < total else '\n', file=sys.stderr, flush=True)


def take_verbosity(argv):
    """-v, -vv, -vvv, -v N or --verbose[=N] anywhere on the line. Returns argv without them."""
    global VERBOSE
    out, i = [], 0
    while i < len(argv):
        t = argv[i]
        if re.fullmatch(r'-v+', t):
            VERBOSE = max(VERBOSE, len(t) - 1)
            if i + 1 < len(argv) and argv[i + 1] in ('1', '2', '3'):
                VERBOSE = int(argv[i + 1]); i += 1
        elif t.startswith('--verbose'):
            VERBOSE = int(t.split('=', 1)[1]) if '=' in t else max(VERBOSE, 1)
        else:
            out.append(t)
        i += 1
    VERBOSE = min(VERBOSE, 3)
    return out


def log(entry):
    """One line per command in <sandbox>/log.jsonl. It holds real data, like the store, and goes with the sandbox."""
    try:
        entry = {'at': rs.local(rs.now()).isoformat(timespec='seconds'), **entry}
        with open(Path(sandbox()) / 'log.jsonl', 'a') as f:
            f.write(json.dumps(entry, default=str, ensure_ascii=False) + '\n')
    except OSError:
        pass


def store_context(con):
    """What the store held when a question was asked: counts, definitions, views (for the log and the dev bank)."""
    ctx = {'today': f'{rs.now():%Y-%m-%d}'}
    for t in ('mail', 'events', 'files', 'file_text', 'labels'):
        ctx[t] = con.execute(f'SELECT count(*) FROM {t}').fetchone()[0]
    ctx['definitions'] = [list(r) for r in con.execute(
        'SELECT name, max(version), arg_max(ask, version), arg_max(answers, version) FROM definitions GROUP BY name').fetchall()]
    ctx['views'] = [r[0] for r in con.execute('SELECT name FROM views').fetchall()]
    ctx['last_sync'] = {w: str(t) for w, t in con.execute('SELECT what, max(at_time) FROM sync_log GROUP BY what').fetchall()}
    return ctx


# ---- the parser: one grammar for people, scripts and the mapper ----

class Err(ValueError):
    pass


class P(argparse.ArgumentParser):
    def error(self, message):
        verb = self.prog.split()[-1]
        raise Err(f'{message}. Try `idli {"" if verb == "idli" else verb + " "}--help` or `idli help`.')


def parser():
    p = P(prog='idli', description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter, add_help=True)
    sub = p.add_subparsers(dest='verb', metavar='VERB')
    s = sub.add_parser('sync', help='copy your Google or WhatsApp data into this sandbox (read only)')
    s.add_argument('what', nargs='?', default='all', choices=['all', 'gmail', 'gcalendar', 'drive', 'whatsapp', 'mail', 'events', 'files', 'sheets'],
                   help='gmail, gcalendar, drive, whatsapp, or all')
    s.add_argument('--no-read', action='store_true', help='copy the file list only; read the text later')
    s.add_argument('--no-cards', action='store_true', help='read the text but make no summary cards now')
    s.add_argument('--no-embed', action='store_true', help='make no embeddings now (search then matches words only)')
    s.add_argument('--from-snapshot', dest='from_snapshot', help='WhatsApp JSON snapshot path to ingest')
    s.add_argument('--days', type=int, default=None, help='rolling window in days for chat sync (e.g. 14)')
    s.add_argument('--in', '--folder', dest='in_scopes', action='append',
                   help='only sync specific Drive folders or WhatsApp chats/groups (repeatable or comma-separated)')
    s.add_argument('--as', dest='role', default='me')
    for verb in ('list', 'count'):  # count is list --count; still accepted, not in the menu
        l = sub.add_parser(verb, help='rows of a resource' if verb == 'list' else argparse.SUPPRESS)
        l.add_argument('resource')
        l.add_argument('--where', action='append', help="filter, e.g. \"direction = 'in' and subject ~ 'visit'\" or \"label.urgent = 'yes'\"")
        l.add_argument('--since', help='today, yesterday, 7d, last week, monday, 2026-11-12')
        l.add_argument('--until')
        l.add_argument('--on', help='one day or range: yesterday, next monday, this week')
        l.add_argument('--search', action='append', help='words that must all appear; "in quotes" = an exact phrase. '
                       'Files: names, folders, every page of text and the cards; most mentions first')
        l.add_argument('--label', action='append', help='DEFINITION or DEFINITION=VALUE, e.g. urgent or funder=yes; '
                       'give it twice for both')
        l.add_argument('--all', dest='show_all', action='store_true', help='include empty files (hidden by default)')
        l.add_argument('--in', '--folder', dest='folder', help='Drive folder name (files, photos, folders)')
        l.add_argument('--sheet', help='which sheet, for rows')
        l.add_argument('--group-by', '--by', dest='by', help='count by these fields, e.g. kind or folder,kind')
        l.add_argument('--count', action='store_true', help='only how many match')
        l.add_argument('--fields', help='which fields to show')
        l.add_argument('--order', help='e.g. "date desc"')
        l.add_argument('--limit', type=int, default=50)
        l.add_argument('-o', dest='out', default='table', choices=['table', 'json'])
    g = sub.add_parser('get', help='one item in full')
    g.add_argument('resource', choices=['mail', 'thread', 'event', 'calendar', 'file', 'sheet', 'message', 'chat'])
    g.add_argument('ref', nargs='?', help='an id, or words from its name or subject')
    g.add_argument('--sheet', '--name', dest='ref2', help=argparse.SUPPRESS)  # models reach for these; same as REF
    g.add_argument('--text', action='store_true', help="a file's text")
    g.add_argument('--outline', action='store_true', help="a file's pages, or a sheet's columns with examples")
    g.add_argument('--chars', type=int, default=3000)
    for verb in ('help', 'explain'):  # explain: the old name, still accepted; people say "explain X" for topics
        e = sub.add_parser(verb, help='fields and examples (the manual page)' if verb == 'help' else argparse.SUPPRESS)
        e.add_argument('resource', nargs='?')
    for verb in ('describe', 'read'):  # now get file --outline / --text; still accepted, not in the menu
        d = sub.add_parser(verb, help=argparse.SUPPRESS)
        d.add_argument('what', choices=['file', 'sheet'] if verb == 'describe' else ['file'])
        d.add_argument('ref', help='a name (or words from it) or an id')
        if verb == 'read':
            d.add_argument('--chars', type=int, default=3000)
    d = sub.add_parser('summarise', help="the 9B's summary of one file, or what your documents or chats say about a topic")
    d.add_argument('what', nargs='?', choices=['file', 'files', 'messages', 'message'], default='files')
    d.add_argument('ref', nargs='?', help='one file: a name (or words from it) or an id')
    d.add_argument('--search', action='append', help='across documents or messages: the passages that discuss this most')
    d.add_argument('--in', '--folder', dest='folder')
    d.add_argument('--on')
    d.add_argument('--since')
    d.add_argument('--until')
    d.add_argument('--question', default='')
    d = sub.add_parser('define', help='your own category, applied by judge')
    d.add_argument('name')
    d.add_argument('--on', required=True, choices=['mail', 'event', 'file', 'photo', 'message'])
    d.add_argument('--ask', required=True, help='the question for each item')
    d.add_argument('--answers', default='yes,no')
    j = sub.add_parser('judge', help='label each row with a definition')
    j.add_argument('resource')
    j.add_argument('--def', dest='defn', required=True)
    j.add_argument('--where', action='append')
    j.add_argument('--in', '--folder', dest='folder', help='only files in this Drive folder')
    j.add_argument('--search', action='append', help='only rows that match, as in list --search')
    j.add_argument('--since')
    j.add_argument('--until')
    j.add_argument('--on', help='one day or range: yesterday, next week, next month')
    j.add_argument('--limit', type=int, default=300)
    j.add_argument('--judge', choices=JUDGES, help='who labels: clef (default; hosted Clef-flash, it sees real content: '
                                                   'test accounts only), nine_compressed (served 9B), nine (BF16 9B)')
    q = sub.add_parser('query', help='read-only SQL over the store')
    q.add_argument('sql')
    v = sub.add_parser('view', help='save a query as a resource')
    v.add_argument('name')
    v.add_argument('--sql', required=True)
    v.add_argument('--on', default='mail')
    v.add_argument('--about', default='')
    w = sub.add_parser('draft', help='a draft email, previewed only')
    w.add_argument('what', choices=['mail'])
    w.add_argument('--reply-to', help='thread id or words from its subject')
    w.add_argument('--to')
    w.add_argument('--subject', default='')
    w.add_argument('--ask', default='', help='what the draft should say')
    dd = sub.add_parser('date', help='what a date phrase means: next monday, last week, 7d')
    dd.add_argument('phrase', nargs='+')
    a = sub.add_parser('ask', help='ask in your own words')
    a.add_argument('question', nargs='+')
    a.add_argument('--mapper', default=os.environ.get('IDLI_MAPPER', 'nine_compressed'), choices=['remote', 'nine', 'nine_compressed'],
                   help='remote: idli-remote maps (masked). nine: the full 9B (BF16) maps and words the reply. '
                        'nine_compressed: the served 9B (Q5) does both')
    a.add_argument('--judge', choices=JUDGES, help='who labels rows when a judge step runs: clef by default '
                                                   '(hosted, sees real content: test accounts only)')
    a.add_argument('--output', choices=['shell', 'humanize'], default='shell', help='presentation for this conversation')
    a.add_argument('--new', action='store_true', help='start a new conversation')
    sub.add_parser('size', help="the store's size")
    return p


# ---- running a command ----

def run_argv(con, argv, chat=False, intent=None):
    if argv and argv[0] == 'idli':
        argv = argv[1:]
    # `--label people = 'yes'` arrives as three words: join them
    out = []
    for t in argv:
        if out and (t.startswith('=') or out[-1].endswith('=')) and len(out) >= 2 and out[-2] == '--label':
            out[-1] += t
        else:
            out.append(t)
    argv = out
    if not argv:
        return Result(kind='text', text=__doc__)
    a = parser().parse_args(argv)
    v = a.verb
    if v == 'sync':
        if a.what == 'whatsapp':
            t0 = time.time()
            say(1, '[sync whatsapp] ingesting chat snapshot ...')
            rw = rs.sync_whatsapp(con, snapshot_path=a.from_snapshot, days=a.days, only_chats=a.in_scopes,
                                  with_embed=not a.no_embed, progress=progress_line, on_item=item_line('chat'))
            emb = (f', {rw["embedded"]} episodes embedded' if rw['embedded']
                   else (f', embeddings skipped ({rw["embed_error"]})' if rw.get('embed_error') else ''))
            scope_s = f' (filtered by --in {", ".join(a.in_scopes)})' if a.in_scopes else ''
            return Result(kind='text', text=f'Synced whatsapp{scope_s}: {rw["chats"]} chats, {rw["messages"]} messages, '
                                            f'{rw["episodes"]} episodes{emb} in {rw["seconds"]} s.')
        acct, out = account(a.role), []
        whats = {'all': ['mail', 'events', 'files', 'sheets'], 'drive': ['files', 'sheets'], 'gmail': ['mail'],
                 'gcalendar': ['events']}.get(a.what, [a.what])
        start = {'mail': 'reading the last 60 days of mail', 'events': 'reading the calendar',
                 'files': 'listing Drive', 'sheets': 'reading spreadsheets changed since the last sync'}
        for what in whats:
            t0 = time.time()
            say(1, f'[sync {what}] {start[what]} ...')
            if what == 'mail':
                n = rs.sync_mail(con, acct, progress=progress_line, on_item=item_line('mail'))
                out.append(f'mail: {n} new')
            elif what == 'sheets':
                n = rs.sync_sheets(con, acct, progress=progress_line, on_item=item_line('sheet'))
                out.append(f'sheets: {n} read (unchanged ones skipped)')
            elif what == 'files':
                n = rs.sync_files(con, acct, only_folders=a.in_scopes)
                out.append(f'files: {n} listed' + (f' (in {", ".join(a.in_scopes)})' if a.in_scopes else ''))
            else:
                n = getattr(rs, f'sync_{what}')(con, acct)
                out.append(f'{what}: {n} listed')
            say(1, f'[sync {what}] {n} in {round(time.time() - t0, 1)} s')
        if 'files' in whats or 'sheets' in whats:
            rs.drop_orphans(con)
            if not a.no_read:
                todo = [r for r in rs.to_read(con, acct) if rs.readable(r[4], r[5], r[2])]
                if todo:
                    mb = sum(r[3] or 0 for r in todo) / 1e6
                    print(f'Reading {len(todo)} documents not read yet ({mb:.0f} MB to download, Google Docs not '
                          'counted). Ctrl+C keeps what was read; sync again to carry on.', file=sys.stderr)
                    say(1, f'[read] {len(todo)} documents, four at a time, newest first ...')
                    rr = rs.read_texts(con, acct, progress=progress_line, on_item=item_line('read'))
                    out.append(f'documents read: {rr["read"]} in {rr["seconds"]} s' +
                               (f', {rr["failed"]} could not be read ({rr["failed_examples"][0]})' if rr['failed'] else ''))
                else:
                    out.append('documents: all read already')
                todo = [] if a.no_cards else rs.to_card(con)
                if todo:
                    print(f'Making a short card for {len(todo)} documents with the 9B (about '
                          f'{max(1, round(len(todo) * 5 / 60))} min; measured 5 s each). Ctrl+C keeps what was made; '
                          '--no-cards skips this.',
                          file=sys.stderr)
                    say(1, f'[cards] {len(todo)} documents ...')
                    rc = rs.make_cards(con, progress=progress_line, on_item=item_line('card'))
                    out.append(f'cards made: {rc["made"]} in {rc["seconds"]} s' +
                               (f', {rc["failed"]} failed ({rc["failed_examples"][0]})' if rc['failed'] else ''))
                if not a.no_embed:
                    files_, cards_ = rs.to_embed(con)
                    if files_ or cards_:
                        say(1, f'[embed] {len(files_)} documents and {len(cards_)} cards ...')
                        print(f'Embedding {len(files_)} documents and {len(cards_)} cards, so search also finds the '
                              'same meaning in other words (about 2 s a document). --no-embed skips this.', file=sys.stderr)
                        try:
                            re_ = rs.make_embeddings(con, progress=progress_line, on_item=item_line('embed'))
                            out.append(f'embedded: {re_["files"]} documents ({re_["chunks"]} passages), {re_["cards"]} '
                                       f'cards in {re_["seconds"]} s')
                        except Exception as e:  # the embedding server is down: search still works by words
                            out.append(f'embeddings skipped ({type(e).__name__}); search matches words only')
        return Result(kind='text', text='Synced ' + acct + '. ' + '; '.join(out) + '.')
    if v in ('list', 'count'):
        resource = rs.resource_name(a.resource)
        link_key = {'files': 'id', 'folders': 'id', 'photos': 'id', 'sheets': 'file_id',
                    'mail': 'thread_id', 'threads': 'thread_id'}.get(resource)
        fields = a.fields
        with_links = chat and link_key and v == 'list' and not (a.by or a.count) and a.out == 'table'
        if with_links:
            if fields:
                columns = [c.strip() for c in fields.split(',')]
                fields = ', '.join(c for c in columns if c.lower() not in ('link', 'url', 'webviewlink'))
            fields = fields or ', '.join(rs.RESOURCES[resource]['show'])
            # Arbitrary SQL projections can aggregate rows and have no single source.
            with_links = bool(re.fullmatch(r'\w+(?:\s*,\s*\w+)*', fields))
            if with_links:
                fields = link_key + ', ' + fields
        cols, rows, sql = rs.select(con, a.resource, where=a.where, since=a.since, until=a.until, on=a.on,
                                    search=a.search, label=a.label, folder=a.folder, sheet=a.sheet, by=a.by,
                                    count=(v == 'count' or a.count), fields=fields, order=a.order, limit=a.limit,
                                    show_all=a.show_all, intent=intent)
        sel_note = rs.LAST_SELECT_NOTE
        source = sheet_sources(con, sql) if chat and resource == 'rows' else None
        links = []
        if with_links and cols[0] == link_key:
            links = [source_link(resource, row[0]) for row in rows]
            cols, rows = cols[1:], [row[1:] for row in rows]
        if getattr(a, 'out', 'table') == 'json':
            return Result(kind='text', text=json.dumps([dict(zip(cols, map(_fmt, r))) for r in rows], ensure_ascii=False))
        if (v == 'count' or a.count) and not a.by:
            n = rows[0][0] if rows else 0
            resource = rs.resource_name(a.resource)
            noun = {'mail': 'emails', 'calendar': 'calendar events'}.get(resource, resource)
            if n == 1:
                noun = noun.removesuffix('s')
            prefix = (sel_note + '\n') if sel_note else ''
            return Result(kind='text', text=f'{prefix}Count: {n} {resource} match.', sql=sql,
                          chat=f'I found {n} {noun}.' + (f'\n_{sel_note}_' if sel_note else ''), source=source)
        if a.search and rs.resource_name(a.resource) == 'files' and rows and cols[-1] == 'found':
            ph = sum(1 for r in rows if str(r[-1]).startswith(('phrase', 'mentioned', 'matched in name or folder')))
            apart = sum(1 for r in rows if str(r[-1]).startswith('words apart'))
            note = (f'{ph} have the words together; {apart} only have them apart (shown last).' if apart else '')
            return Result(cols, rows, sql=sql, note='\n'.join(filter(None, [sel_note, note])), links=links)
        return Result(cols, rows, sql=sql, note=sel_note, links=links, source=source)
    if v == 'get':
        a.ref = a.ref or a.ref2
        if not a.ref:
            raise Err(f'Say which one: idli get {a.resource} NAME')
        res = 'event' if a.resource == 'calendar' else a.resource
        if res in ('file', 'sheet') and a.outline:
            return describe(con, res, a.ref)
        if res == 'file' and a.text:
            fid, name = find_file(con, a.ref)
            t = rs.file_text(con, file_account(con, fid), fid)
            return Result(kind='text', text=f'{name} ({len(t)} characters):\n\n' + t[:a.chars],
                          source=source_link('files', fid))
        if res == 'sheet':
            name, tab, tbl, nrows, tabs, fid = find_sheet(con, a.ref)
            others = f'; other tabs: {", ".join(t for t in tabs if t != tab)}' if len(tabs) > 1 else ''
            if nrows <= 50 and not a.outline:  # small: every row, values in full
                cur = con.execute(f'SELECT * EXCLUDE (row_no) FROM "{tbl}"')
                return Result([d[0] for d in cur.description], cur.fetchall(), source=source_link('sheets', fid),
                              note=f'{name} / {tab} (all {nrows} rows{others})' if len(tabs) > 1 else f'{name} (all {nrows} rows)')
            return describe(con, 'sheet', a.ref)
        return get(con, res, a.ref)
    if v in ('help', 'explain'):
        return Result(kind='text', text=explain(con, a.resource))
    if v == 'describe':
        return describe(con, a.what, a.ref)
    if v == 'read':
        fid, name = find_file(con, a.ref)
        t = rs.file_text(con, file_account(con, fid), fid)
        return Result(kind='text', text=f'{name} ({len(t)} characters):\n\n' + t[:a.chars],
                          source=source_link('files', fid))
    if v == 'summarise':
        if a.search:
            q_intent = a.question or intent or ''
            if a.what in ('messages', 'message'):
                return summarise_messages(con, a.search, chat=a.folder, on=a.on, since=a.since, until=a.until, question=q_intent)
            n_files = con.execute('SELECT count(*) FROM files').fetchone()[0]
            n_msgs = con.execute('SELECT count(*) FROM messages').fetchone()[0]
            if n_files == 0 and n_msgs > 0:
                return summarise_messages(con, a.search, chat=a.folder, on=a.on, since=a.since, until=a.until, question=q_intent)
            return summarise_search(con, a.search, a.folder, q_intent)
        if not a.ref:
            raise Err('Say which file (idli summarise file NAME), or a topic (idli summarise --search "border effects")')
        return summarise(con, a.ref, a.question)
    if v == 'define':
        name, ver = rs.define(con, a.name, a.on, a.ask, a.answers)
        return Result(kind='text', chat=f'I’ll use “{name}” for this question: {a.ask}', text=f'Definition "{name}" version {ver}: {a.ask} ({a.answers}). '
                                        f'Next: idli judge {"photos" if a.on == "photo" else {"mail": "mail", "event": "events", "file": "files", "message": "messages"}[a.on]} --def {name}')
    if v == 'judge':
        res = {'mail': 'mail', 'event': 'events'}.get(a.resource, a.resource)
        r = rs.judge(con, res, a.defn, where=a.where, since=a.since, limit=a.limit, account=account(), folder=a.folder,
                     search=a.search, until=a.until, on=a.on,
                     progress=progress_line, on_item=(lambda n, lab, why: say(2, f'  {n}: {lab or "FAILED"} ({why})'))
                     if VERBOSE >= 2 else None)
        labels = [f'• {label}: {count}' for label, count in sorted(r['counts'].items())]
        chat = f'Here’s what I found for “{a.defn}”.' if labels else 'I couldn’t label any items.'
        if r.get('failed'):
            labels.append(f'I couldn’t check {r["failed"]} items.')
        return Result(kind='text', text=judge_summary(r, a.defn, res), note=json.dumps(r, default=str),
                      chat='\n'.join([chat, *labels]))
    if v == 'query':
        cols, rows = rs.query(con, a.sql)
        return Result(cols, rows, sql=a.sql, source=sheet_sources(con, a.sql) if chat else None)
    if v == 'view':
        rs.query(con, a.sql, limit=1)
        if not re.fullmatch(r'[a-z][a-z0-9_]{1,40}', a.name) or a.name in rs.RESOURCES:
            raise Err('A view name is a short lower-case word (leads, from_leads) and not a resource name.')
        con.execute(f'CREATE OR REPLACE VIEW "{a.name}" AS {a.sql}')  # so other commands can use it: IN (SELECT ...)
        con.execute('INSERT OR REPLACE INTO views VALUES (?,?,?,?)', [a.name, a.on, a.sql, a.about])
        return Result(kind='text', chat=f'I saved the list “{a.name}”.', text=f'Saved view "{a.name}". List it with: idli list {a.name}')
    if v == 'draft':
        return draft(con, a)
    if v == 'date':
        ph = ' '.join(a.phrase)
        x, y = rs.day_range(ph)
        y = y - dt.timedelta(days=1)
        return Result(kind='text', text=f'{ph} = {x:%A %d %B %Y}' + ('' if x == y else f' to {y:%A %d %B %Y}') +
                      f' (today is {rs.now():%A %d %B %Y}).')
    if v == 'size':
        return Result(kind='text', text=json.dumps(rs.size_report(sandbox(), con)))
    raise Err('Try `idli --help`.')


def judge_summary(r, defn, res):
    head = 'Stopped. Kept' if r.get('stopped') else 'Judged'
    lines = [f'{head} {r["judged_now"]} now by {r["judge"]} ({r["already"]} already judged), {r["seconds"]} s. '
             'Labels: ' + (', '.join(f'{k} {n}' for k, n in sorted(r['counts'].items())) or 'none yet') + '.']
    for lab, names in r.get('examples', {}).items():
        n = r['counts'].get(lab, 0)
        lines.append(f'  {lab} ({n}): ' + '; '.join(str(x) for x in names) + (' ...' if n > len(names) else ''))
    if r.get('examples'):
        labs = list(r['examples'])
        lab = next((x for x in labs if x not in ('unsure', 'no')), labs[0])
        lines.append(f'  All of them: idli list {res} --label {defn}={lab}')
    if r.get('stopped'):
        lines.append(f'  {r["to_judge"] - r["judged_now"] - r["failed"]} not judged yet: run the same command to carry on.')
    if r.get('failed'):
        lines.append(f'  {r["failed"]} could not be judged (run judge again to retry): {r["failed_examples"][0]}')
    return '\n'.join(lines)


def file_account(con, fid):
    r = con.execute('SELECT account FROM files WHERE id = ?', [fid]).fetchone()
    return r[0] if r else account()


def find_file(con, ref, kinds=None):
    r = con.execute('SELECT id, name FROM files WHERE id = ?', [ref]).fetchone()
    if r:
        return r
    words = [w for w in re.split(r'\s+', ref.strip()) if w]
    cond = ' AND '.join(f"(name || ' ' || path) ILIKE '%{w.replace(chr(39), '')}%'" for w in words)
    k = f" AND kind IN ({','.join(repr(x) for x in kinds)})" if kinds else " AND kind != 'folder'"
    rows = con.execute(f'SELECT id, name, path FROM files WHERE {cond}{k} ORDER BY modified DESC').fetchall()
    if not rows:
        raise Err(f'No file matching "{ref}". Try `idli list files --search "{words[0] if words else ""}"`.')
    if len(rows) > 1 and not any(r[1].lower() == ref.lower() for r in rows):
        exact = [r for r in rows if all(w.lower() in r[1].lower() for w in words)]
        rows = exact or rows
    return rows[0][0], rows[0][1]


def get(con, what, ref):
    if what == 'file':
        fid, _ = find_file(con, ref, kinds=None)
        cols = rs.columns(con, 'files')
        r = con.execute('SELECT * FROM files WHERE id = ?', [fid]).fetchone()
        out = '\n'.join(f'{c}: {_fmt(x)}' for c, x in zip(cols, r) if x not in (None, ''))
        c = rs.card(con, fid)
        if c:
            out += f'\nsummary: {c[0]}\nkey terms: {", ".join(c[1])}'
        return Result(kind='text', text=out, source=source_link('files', fid))
    if what == 'event':
        r = con.execute("SELECT * FROM events WHERE id = ? OR title ILIKE ? ORDER BY start LIMIT 1",
                        [ref, f'%{ref}%']).fetchone()
        if not r:
            raise Err(f'No event matching "{ref}". Try `idli list calendar --search "{ref}"`.')
        cols = rs.columns(con, 'events')
        return Result(kind='text', text='\n'.join(f'{c}: {_fmt(x)}' for c, x in zip(cols, r) if x not in (None, '')))
    if what == 'chat':
        from lib import searchkit as sk
        crow = sk.resolve_chat(con, ref)
        cid, cname, provider, earliest, latest, count = crow
        speakers = con.execute(
            'SELECT sender, msg_count FROM chat_members WHERE chat_id = ? ORDER BY msg_count DESC LIMIT 8', [cid]
        ).fetchall()
        recent = con.execute(
            'SELECT id, sent_at, sender, body FROM messages WHERE chat_id = ? ORDER BY sent_at DESC LIMIT 8', [cid]
        ).fetchall()
        lines = [
            f'Chat: {cname} ({provider})',
            sk.chat_coverage_note(crow),
            'Top speakers: ' + ', '.join(f'{s} ({n})' for s, n in speakers),
            '', 'Recent messages:',
        ]
        for mid, ts, sender, body in reversed(recent):
            lines.append(f'  [{mid}] {_fmt(ts)} {sender}: {_fmt(body, limit=240)}')
        return Result(kind='text', text='\n'.join(lines))
    if what == 'message':
        from lib import searchkit as sk
        key = ref.strip()
        target = con.execute(
            'SELECT id, chat_id, chat_name, sent_at, sender, body, links, link_preview, filename, parent_id '
            'FROM messages WHERE id = ?', [key]
        ).fetchone()
        if not target and re.fullmatch(r'[0-9a-f]{6,20}', key, re.I):
            hits = con.execute(
                'SELECT id, chat_id, chat_name, sent_at, sender, body, links, link_preview, filename, parent_id '
                'FROM messages WHERE id LIKE ? ORDER BY sent_at DESC LIMIT 5', [key.lower() + '%']
            ).fetchall()
            if len(hits) == 1:
                target = hits[0]
            elif len(hits) > 1:
                raise Err(f'Multiple messages start with "{key}": ' + ', '.join(h[0] for h in hits))
        if not target:
            target = con.execute(
                'SELECT id, chat_id, chat_name, sent_at, sender, body, links, link_preview, filename, parent_id '
                'FROM messages WHERE body ILIKE ? ORDER BY sent_at DESC LIMIT 1', [f'%{key}%']
            ).fetchone()
        if not target:
            raise Err(f'No message matching "{ref}". Try `idli list messages --search "{ref}"`.')
        tid, cid, cname = target[0], target[1], target[2]
        # Gather full chat sequence to extract +/-3 neighbors, parent chain (up to 3 hops), and direct replies.
        seq = con.execute(
            'SELECT id, sent_at, sender, body, links, link_preview, filename, parent_id '
            'FROM messages WHERE chat_id = ? ORDER BY sent_at, id', [cid]
        ).fetchall()
        by_id = {r[0]: r for r in seq}
        pos = next((i for i, r in enumerate(seq) if r[0] == tid), None)
        picked = {}
        # 1. Parent chain (can be hours or days older)
        cur_pid = target[9]
        for _ in range(3):
            if cur_pid and cur_pid in by_id and cur_pid not in picked:
                picked[cur_pid] = 'quoted parent'
                cur_pid = by_id[cur_pid][7]
            else:
                break
        # 2. Target + +/-3 neighbors
        if pos is not None:
            for j in range(max(0, pos - 3), min(len(seq), pos + 4)):
                r = seq[j]
                picked.setdefault(r[0], 'target' if r[0] == tid else 'nearby')
                # Also pull the quoted parent of an immediate neighbor if present (DICE pattern).
                if abs(j - pos) <= 1 and r[7] and r[7] in by_id:
                    picked.setdefault(r[7], 'quoted parent of neighbor')
        # 3. Direct replies to target
        for r in seq:
            if r[7] == tid:
                picked.setdefault(r[0], 'reply')
        ordered = [r for r in seq if r[0] in picked]
        crow = con.execute('SELECT id, name, provider, earliest_at, latest_at, msg_count FROM chats WHERE id = ?', [cid]).fetchone()
        lines = [sk.chat_coverage_note(crow) if crow else f'Chat: {cname}', '']
        for r in ordered:
            mid, ts, sender, body, links, preview, fname, pid = r
            role = picked[mid]
            mark = '>>> ' if mid == tid else '    '
            rel = f' (replying to {pid[:8]})' if pid and pid in by_id else ''
            tag = f' [{role}]' if role != 'nearby' else ''
            extra = ''
            if preview:
                extra += f'\n      Link preview: {preview[:300]}'
            if fname and fname not in (body or ''):
                extra += f'\n      File: {fname}'
            lines.append(f'{mark}[{mid}] {_fmt(ts)} {sender}{rel}{tag}:\n      {body}{extra}')
        return Result(kind='text', text='\n'.join(lines))
    if what == 'thread':
        tid = con.execute('SELECT thread_id FROM mail WHERE thread_id = ? OR id = ? OR subject ILIKE ? '
                          'ORDER BY date DESC LIMIT 1', [ref, ref, f'%{ref}%']).fetchone()
        if not tid:
            raise Err(f'No thread matching "{ref}". Try `idli list threads --search "{ref}"`.')
        rows = con.execute('SELECT date, direction, from_name, from_addr, subject, substr(body_text, 1, 600) FROM mail '
                           'WHERE thread_id = ? ORDER BY date', [tid[0]]).fetchall()
        return Result(kind='text', text='\n\n'.join(f'{_fmt(d)} {"me" if dr == "out" else (n or a)}: {s}\n{b}'
                                                     for d, dr, n, a, s, b in rows), source=source_link('threads', tid[0]))
    r = con.execute("SELECT date, direction, from_name, from_addr, to_addrs, subject, body_text, thread_id FROM mail "
                    "WHERE id = ? OR subject ILIKE ? ORDER BY date DESC LIMIT 1", [ref, f'%{ref}%']).fetchone()
    if not r:
        raise Err(f'No email matching "{ref}". Try `idli list mail --search "{ref}"`.')
    return Result(kind='text', text=f'{_fmt(r[0])} from {r[2]} <{r[3]}> to {r[4]}\nSubject: {r[5]}\nThread: {r[7]}\n\n'
                                    f'{(r[6] or "")[:3000]}', source=source_link('mail', r[7]))


def find_sheet(con, ref):
    """A sheet or one of its tabs: "Leads (test)", "Leads (test) / Contacts", a tab name or a table name.
    Returns (name, tab, table, rows, every tab of that file)."""
    r = con.execute("SELECT name, tab, tbl, nrows, file_id FROM sheets WHERE (name || ' / ' || tab) ILIKE ? OR tab ILIKE ? "
                    "OR name ILIKE ? OR tbl = ? ORDER BY (tbl = ?) DESC, ((name || ' / ' || tab) ILIKE ?) DESC, "
                    "(name ILIKE ?) DESC, tab_index", [f'%{ref}%', ref, f'%{ref}%', ref, ref, f'%{ref}%', ref]).fetchall()
    if not r:
        raise Err(f'No sheet matching "{ref}". `idli list sheets` shows them.')
    tabs = [x[0] for x in con.execute('SELECT tab FROM sheets WHERE file_id = ? ORDER BY tab_index', [r[0][4]]).fetchall()]
    return r[0][0], r[0][1], r[0][2], r[0][3], tabs, r[0][4]


def describe(con, what, ref):
    if what == 'sheet':
        name, tab, tbl, nrows, tabs, fid = find_sheet(con, ref)
        head = f'{name}' + (f' / {tab}' if len(tabs) > 1 else '') + f': {nrows} rows'
        if len(tabs) > 1:
            head += f'\nTabs: {", ".join(tabs)} (idli get sheet "{name} / TAB" for another)'
        return _describe_table(con, tbl, head, fid)
    fid, name = find_file(con, ref)
    f = con.execute('SELECT kind, mime, size, modified, path FROM files WHERE id = ?', [fid]).fetchone()
    head = f'{name} ({f[0]}, {f[2] or "?"} bytes, changed {_fmt(f[3])}, in {f[4] or "My Drive"})'
    if f[0] == 'sheet':
        t = con.execute('SELECT tbl, nrows, tab FROM sheets WHERE file_id = ? ORDER BY tab_index', [fid]).fetchall()
        if t:
            tabs = f'\nTabs: {", ".join(x[2] for x in t)}' if len(t) > 1 else ''
            return _describe_table(con, t[0][0], head + f'\n{t[0][1]} rows' + tabs, fid)
    if f[0] in ('pdf', 'doc'):
        t = rs.file_text(con, file_account(con, fid), fid)
        pages = con.execute('SELECT pages FROM file_text WHERE file_id = ?', [fid]).fetchone()[0]
        words = len(t.split())
        first = re.sub(r'\s+', ' ', t[:400])
        return Result(kind='text', text=head + f'\n{pages or "?"} pages, about {words} words read.\nStarts: {first}', source=source_link('files', fid))
    return Result(kind='text', text=head, source=source_link('files', fid))


def _describe_table(con, tbl, head, fid):
    cols = [c for c in rs.columns_of(con, f'"{tbl}"') if c != 'row_no']
    lines = [head, f'{len(cols)} columns:']
    for c in cols[:40]:
        r = con.execute(f'SELECT count(DISTINCT "{c}"), count(*) FILTER (WHERE "{c}" != \'\'), '
                        f'string_agg(DISTINCT "{c}", \', \') FILTER (WHERE "{c}" != \'\') FROM (SELECT "{c}" FROM "{tbl}" LIMIT 500)').fetchone()
        ex = (r[2] or '')[:80]
        lines.append(f'- {c}: {r[1]} filled, {r[0]} different (e.g. {ex})')
    if len(cols) > 40:
        lines.append(f'... and {len(cols) - 40} more columns')
    return Result(kind='text', text='\n'.join(lines), source=source_link('files', fid))


def summarise(con, ref, question=''):
    fid, name = find_file(con, ref)
    kind = con.execute('SELECT kind FROM files WHERE id = ?', [fid]).fetchone()[0]
    if kind == 'sheet':
        return describe(con, 'file', fid)
    t = rs.file_text(con, file_account(con, fid), fid)
    if not t.strip():
        return Result(kind='text', text=f'{name} has no text I can read (it may be a scan).')
    chunks = [t[i:i + 7000] for i in range(0, min(len(t), 35000), 7000)]
    schema = {'type': 'object', 'properties': {'summary': {'type': 'string'}}, 'required': ['summary']}
    import concurrent.futures as cf
    def part(c):
        return rs._nine([{'role': 'user', 'content': f'Summarise this part of "{name}" in 3 sentences'
                          + (f', focusing on: {question}' if question else '') + f'.\n\n{c}'}], schema,
                        max_tokens=300)['summary']
    with cf.ThreadPoolExecutor(4) as ex:  # the parts at once: a 96-page report took over a minute one by one
        parts = list(ex.map(part, chunks))
    if len(parts) > 1:
        final = rs._nine([{'role': 'user', 'content': f'Combine these notes on "{name}" into one summary of 4-6 '
                           f'sentences{", focusing on: " + question if question else ""}. Keep only what the notes say.'
                           '\n\n' + '\n'.join(parts)}], schema, max_tokens=400)['summary']
    else:
        final = parts[0]
    return Result(kind='text', text=f'{name}: {final}\n(Read {min(len(t), 35000)} of {len(t)} characters.)', source=source_link('files', fid))


def summarise_search(con, search, folder=None, question='', docs=5, chars=9000):
    """What the documents say about a topic: the pages that mention it most, read by the 9B, with file and page."""
    phrases, words, rank = rs.parse_search(search)
    _, rows, _ = rs.select(con, 'files', search=search, folder=folder, fields='id, name', limit=docs, plain=True)
    rows = [r[:2] for r in rows]  # a search adds its "found" column
    by_meaning = []
    if not phrases and rs.embeddings_ready(con):  # passages that say it in other words
        topic = rs._search_text(search) + (f'. {question}' if question else '')
        hits = rs.semantic_chunks(con, topic, k=8)
        best = hits[0][3] if hits else 0
        by_meaning = [h for h in hits if h[3] >= max(rs.SEMANTIC_FLOOR, best - rs.SEMANTIC_BAND)] \
            if best >= rs.SEMANTIC_TOP else []
    if (not rows and not by_meaning) or not rank:
        return Result(kind='text', chat='I couldn’t find that topic in your documents. Try another name or phrase.', text='No document mentions that. Try other words, or `idli list files --search`.')
    rx = rs._phrase_re(rank)
    cited_files = {}
    excerpts, used = [], 0
    for fid, name in rows:
        pages = con.execute(f"SELECT page, text, len(regexp_extract_all(lower(text), '{rx}')) n FROM file_pages "
                            f"WHERE file_id = ? ORDER BY n DESC, page LIMIT 2", [fid]).fetchall()
        if not any(n for _, _, n in pages):  # the words, but not together: the pages with most of them
            like = ' + '.join(f"(lower(text) LIKE '%{w.lower().replace(chr(39), '')}%')::INT" for w in rank)
            pages = con.execute(f'SELECT page, text, {like} n FROM file_pages WHERE file_id = ? ORDER BY n DESC, page '
                                f'LIMIT 2', [fid]).fetchall()
        for page, text, n in pages:
            if not n:
                continue
            hit = re.search(rx, text.lower()) or re.search(re.escape(rank[0].lower()), text.lower())
            i = max(0, (hit.start() if hit else 0) - 700)
            piece = re.sub(r'\s+', ' ', text[i:i + 1800])
            cited_files[fid] = name
            excerpts.append(f'[{name}, page {page}]\n{piece}')
            used += len(piece)
            if used > chars:
                break
        if used > chars:
            break
    names = dict(con.execute('SELECT id, name FROM files').fetchall())
    seen = {e.split(']')[0] for e in excerpts}
    for fid, page, text, sc in by_meaning:  # literal passages first, then the closest in meaning
        key = f'[{names.get(fid, fid)}, page {page}'
        if key in seen or used > chars:
            continue
        cited_files[fid] = names.get(fid, fid)
        excerpts.append(f'{key}]\n{text}')
        seen.add(key)
        used += len(text)
    topic = ' '.join(rank)
    if not excerpts:
        return Result(kind='text', chat=f'I found those words, but no passage explaining “{topic}”. Which file should I look in?', text=f'I found files with those words but no passage about "{topic}" to read. '
                      'Try fewer words, or `idli summarise file NAME` for one file.')
    schema = {'type': 'object', 'properties': {'answer': {'type': 'string'}}, 'required': ['answer']}
    ans = rs._nine([{'role': 'system', 'content': 'Explain a topic to the person using only the excerpts from their '
                     'documents. 4 to 6 plain sentences. After each point, name the file and page in brackets, as given. '
                     'If the excerpts disagree or are thin, say so. Never add facts that are not in the excerpts.'},
                    {'role': 'user', 'content': f'Topic: {topic}' + (f'\nTheir question: {question}' if question else '') +
                     '\n\n' + '\n\n'.join(excerpts)}], schema, max_tokens=600, timeout=240)['answer']
    srcs = sorted({e.split(']')[0][1:] for e in excerpts})
    return Result(kind='text', text=f'{ans.strip()}\n\nFrom {len(excerpts)} passages in: ' +
                  '; '.join(sorted({s.rsplit(", page", 1)[0] for s in srcs})),
                  chat=ans.strip(), source='\n'.join(name + '\n' + source_link('files', fid)
                                                     for fid, name in cited_files.items()))


def summarise_messages(con, search, chat=None, on=None, since=None, until=None, question='', limit=5):
    """What your chat conversations say about a topic: top ranked contextualized episodes read by the 9B,
    grounded with dates, speakers, message refs and verbatim source receipts."""
    from lib import searchkit as sk
    _, base, _ = rs.select(con, 'messages', folder=chat, on=on, since=since, until=until,
                           fields='id', limit=100000, order='id', plain=True)
    scope_note = rs.LAST_SELECT_NOTE
    base_ids = [r[0] for r in base]
    topic = rs._search_text(search)
    if not base_ids:
        msg = (scope_note + '\n' if scope_note else '') + 'No messages in that scope to summarise.'
        return Result(kind='text', text=msg, chat=msg)
    eps = sk.search_episodes(con, topic, base_ids, chat_name_hint=chat, embed_fn=rs.embed, limit=limit,
                             intent_query=question or None)
    tel = dict(sk.LAST_TELEMETRY)
    weak_in_chat = (
        chat and 'outside the cached window' not in scope_note
        and (
            (tel.get('reranker_used') and (tel.get('top_prob') or 0.0) < 0.05)
            or (not tel.get('reranker_used') and tel.get('bm25_msg_hits', 0) == 0 and tel.get('fuzzy_hits', 0) == 0)
        )
    )
    if weak_in_chat:
        _, all_base, _ = rs.select(con, 'messages', on=on, since=since, until=until,
                                   fields='id', limit=100000, order='id', plain=True)
        all_ids = [r[0] for r in all_base]
        if len(all_ids) > len(base_ids):
            g_eps = sk.search_episodes(con, topic, all_ids, chat_name_hint=None, embed_fn=rs.embed, limit=limit,
                                       intent_query=question or None)
            gtel = dict(sk.LAST_TELEMETRY)
            strong_global = (
                (gtel.get('reranker_used') and (gtel.get('top_prob') or 0.0) >= 0.25)
                or (not gtel.get('reranker_used') and gtel.get('bm25_msg_hits', 0) > 0)
            )
            if g_eps and strong_global:
                eps = g_eps
                scope_note = f'No strong match inside "{chat}"; showing matches across all synced chats.'
            else:
                sk.LAST_TELEMETRY.clear()
                sk.LAST_TELEMETRY.update(tel)
    if not eps:
        msg = (scope_note + '\n' if scope_note else '') + f'No chat messages matched "{topic}".'
        return Result(kind='text', text=msg, chat=msg)
    excerpts, used, refs = [], 0, []
    for ep in eps:
        piece = ep['context_text'][:2200]
        if used + len(piece) > 9500 and excerpts:
            break
        excerpts.append(piece)
        used += len(piece)
        refs.extend(ep['message_ids'])
    schema = {'type': 'object', 'properties': {'answer': {'type': 'string'}}, 'required': ['answer']}
    today = rs.now().strftime('%A %d %B %Y')
    ans = rs._nine([
        {'role': 'system', 'content': (
            f'Answer the person using ONLY the chat excerpts below. Today is {today} (IST). '
            'Write 2 to 5 concise sentences. Cite speaker, date and message ref in brackets where relevant. '
            'Anchor relative words inside old messages ("today", "tomorrow") to that message\'s timestamp, never to today. '
            'Distinguish proposals or suggestions from confirmed decisions; if confirmation is not shown, say so. '
            'Include exact URLs, numbers and names from the excerpts; never invent facts.'
        )},
        {'role': 'user', 'content': (
            f'Topic: {topic}' + (f'\nQuestion: {question}' if question else '') +
            (f'\nScope: {scope_note}' if scope_note else '') + '\n\n' + '\n\n---\n\n'.join(excerpts)
        )},
    ], schema, max_tokens=500, timeout=240)['answer'].strip()
    receipts = '\n\nSources:\n' + '\n\n'.join(excerpts[:3])
    head = (scope_note + '\n\n' if scope_note else '')
    return Result(kind='text', text=head + ans + receipts,
                  chat=ans + (f'\n\n_{scope_note}_' if scope_note else ''))


def draft(con, a):
    """A draft, previewed only. --reply-to must match one conversation (all its words in the sender or subject);
    a new email to someone with no conversation needs --to ADDRESS."""
    to, subject, context = a.to or '', a.subject, ''
    if a.reply_to:
        ref = a.reply_to.strip()
        if ' | ' in ref:  # a row pasted from a listing: "1. Fri 20 Nov 09:58 | name | addr | subject | in"
            parts = [x.strip() for x in re.sub(r'^\d+\.\s*', '', ref).split(' | ')]
            ref = max((x for x in parts if '@' not in x and x not in ('in', 'out')), key=len, default=ref)
        r = con.execute('SELECT thread_id, subject, from_addr, from_name, body_text FROM mail WHERE thread_id = ? OR id = ? '
                        'ORDER BY date DESC LIMIT 1', [ref, ref]).fetchone()
        if not r:
            # words only: subjects carry curly quotes, colons and question marks that the ref may not
            words = [w for w in re.findall(r"[^\W_]{2,}", ref) if w.lower() not in ('re', 'fwd', 'fw')][:12]
            cond = ' AND '.join(f"(coalesce(from_name, '') || ' ' || from_addr || ' ' || subject) ILIKE '%{w}%'" for w in words)
            r = con.execute(f"SELECT thread_id, subject, from_addr, from_name, body_text FROM mail WHERE direction = 'in' "
                            f"AND {cond} ORDER BY date DESC LIMIT 1").fetchone()
        if not r:
            if not to:
                raise Err(f'No conversation with "{ref}". For a new email, give --to ADDRESS (for example from the leads '
                          'sheet) and --subject.')
        else:
            to = to or r[2]
            subject = subject or ('Re: ' + r[1] if not r[1].lower().startswith('re:') else r[1])
            context = f'Their last email ({r[3] or r[2]}):\n{(r[4] or "")[:1500]}'
    if not to:
        raise Err('Say who the draft is to: --reply-to a conversation, or --to ADDRESS.')
    schema = {'type': 'object', 'properties': {'body': {'type': 'string'}}, 'required': ['body']}
    body = rs._nine([{'role': 'user', 'content': f'Write a short, polite email body (no subject line) from me to {to}. '
                      f'{a.ask}\n{context}\nSign off as "Me".'}], schema, max_tokens=400)['body']
    return Result(kind='text', text=f'Would draft (not saved):\nTo: {to}\nSubject: {subject or "(none)"}\n\n{body}')


# ---- explain: the man page, with real dates ----

def explain(con, resource=None):
    today = rs.now().date()
    lw = rs.day_range('last week')
    if not resource:
        lines = ['What you can list (idli list RESOURCE), one row per item:']
        for k, r in rs.RESOURCES.items():
            lines.append(f'- {k}: {r["about"]}')
        lines.append('- rows --sheet NAME: the rows of one spreadsheet (`idli list sheets` shows the names)')
        views = con.execute('SELECT name, about FROM views').fetchall()
        for n, ab in views:
            lines.append(f'- {n}: your view. {ab}')
        lines += ['', 'Examples:',
                  f'  idli list mail --since yesterday --where "direction = \'in\' and not is_bulk"',
                  f'  idli list files --count --in "NDSA fixity study"',
                  f'  idli list files --group-by kind',
                  f'  idli list files --search \'"border effects"\'   (names, text and cards; most mentions first)',
                  f'  idli summarise --search \'"border effects"\'   (what your documents say, with file and page)',
                  f'  idli list calendar --on "next monday"   (= {rs.day_range("next monday")[0]})',
                  '  idli define urgent --on mail --ask "Does this email ask me to act soon?" --answers yes,no',
                  '  idli judge mail --def urgent --where "not is_bulk"   then   idli list threads --label urgent',
                  'More: idli help mail (or any resource).']
        return '\n'.join(lines)
    if resource == 'rows':
        return 'rows --sheet NAME: the rows of one spreadsheet. `idli get sheet NAME` lists its columns.'
    resource = rs.resource_name(resource)
    if resource not in rs.RESOURCES:
        raise Err(f'No resource "{resource}". `idli help` lists them.')
    r = rs.RESOURCES[resource]
    cols = rs.columns(con, resource)
    ex = {
        'mail': [f'idli list mail --since "last week" --where "direction = \'in\' and not is_bulk"   (last week = {lw[0]} to {lw[1] - dt.timedelta(days=1)})',
                 "idli list mail --search \"reading programme\"",
                 "idli list mail --since 7d --group-by is_bulk,is_calendar_notice",
                 "idli list mail --where \"from_addr ~ 'linkedin'\""],
        'threads': ["idli list threads --where \"last_direction = 'in' and not is_bulk\"",
                    "idli list threads --label urgent    (after define and judge)"],
        'calendar': [f'idli list calendar --on yesterday   (= {today - dt.timedelta(days=1)})',
                     "idli list calendar --since today --where \"guests ~ '@'\"",
                     "idli list calendar --where \"my_response = 'declined'\"   (my_response: Google's RSVP, or organizer)"],
        'files': ['idli list files --in "NDSA fixity study"', 'idli list files --count --in "Strategy Classics" --where "kind = \'pdf\'"',
                  'idli list files --group-by kind', "idli list files --search caste",
                  'idli list files --search \'"border effects"\'   (exact phrase; names, every page of text, cards)',
                  'idli get file wincoop --outline   (pages and the summary card)'],
        'folders': ['idli list folders', "idli list folders --where \"path ~ 'Strategy'\""],
        'photos': ['idli list photos', 'idli define has_people --on photo --ask "Are there people in this photo?"'],
        'sheets': ['idli list sheets', 'idli get sheet "Leads (test)"', 'idli list rows --sheet "Leads (test)"'],
        'chats': ['idli list chats', 'idli get chat "Jam Buns"'],
        'messages': ['idli list messages --in "Jam Buns" --on "last week"',
                     'idli list messages --in "Jam Buns" --search "birding"',
                     'idli list messages --count --in "Jam Buns" --where "links <> \'\'"',
                     'idli get message REF',
                     'idli summarise messages --search "session" --in "Royal Enfield"'],
    }.get(resource, [])
    notes = rs.FIELD_NOTES.get(resource, {})
    return (f'{resource}: {r["about"]}.\nFields: {", ".join(cols)}.\n' +
            ''.join(f'  {f}: {n}\n' for f, n in notes.items()) +
            f'Dates filter on {r["date"]}. --where takes SQL-like conditions; field ~ \'x\' means contains; '
            f"label.NAME = 'yes' uses your definitions.\nExamples:\n" + '\n'.join('  ' + e for e in ex))


# ---- ask: the left chat. The mapper picks commands; Idli runs them; the 9B words a short reply ----

GRAMMAR_HEAD = """You turn a person's request into `idli` commands that read their synced data from a local store.
Answer with JSON only: {"commands": ["idli ...", ...]} (add "continue": true to see results before the next
commands) or {"cannot": "<one sentence>", "needs": "<kind>"}.

Commands (read only unless said):
  idli list RESOURCE [--where COND] [--since D] [--until D] [--on D] [--search WORDS] [--label DEF[=VAL]]
                     [--in FOLDER|CHAT] [--sheet NAME] [--group-by FIELDS] [--count] [--fields F] [--order "F desc"] [--limit N]
  idli get mail|thread|calendar|file|sheet|message|chat REF [--text] [--outline]   one item in full (message shows
                                               quoted parent + replies + neighbors); --text: file text; --outline: pages/columns
  idli summarise file REF [--question Q]       a summary of one file
  idli summarise [files|messages] --search WORDS [--in FOLDER|CHAT] [--on D]   what documents or chats say about a topic
  idli define NAME --on mail|event|file|photo|message --ask "QUESTION" --answers a,b,c   the person's own category
  idli judge RESOURCE --def NAME [--where COND] [--search WORDS] [--in FOLDER|CHAT] [--since D] [--on D]   label rows (costly)
  idli query "SELECT ..."                      read-only SQL for joins and anything else
  idli draft mail --reply-to REF --ask "WHAT TO SAY"   preview only; nothing is saved or sent
  idli date PHRASE                             what "next monday", "last week" mean (for questions about dates)
Dates D: today, yesterday, tomorrow, 7d, last week, this week, next week, monday, next monday, YYYY-MM-DD.
COND is SQL over the resource's fields; field ~ 'x' means contains; label.NAME = 'yes' uses a definition.
--search WORDS: unquoted searches words and meaning; "in quotes" = exact phrase. On files: names, pages, cards.
On messages: bodies, captions, link previews, reply threads (use --in CHAT only if named). Use ONE --search flag.

Rules:
- Use only the resources and fields listed below (prefer populated ones over empty ones). Prefer list with flags; query only for joins.
- A category the person has in mind ("urgent", "about caste", "funder meeting", "photos with people") that is not
  a field: define it (a clear yes/no question), judge the relevant rows (narrow first with --where, --in or
  --since so fewer rows are judged), then list with --label. Reuse an existing definition when it fits; never
  define an existing name again. Word a new definition generally, as the person means the category, not from one
  document you just saw. The person is shown the wording and decides.
- A greeting, or "what can you do / what can you see": idli help (it lists what Idli can read).
- Use the person's own words: never add --search words, --in folders or --where conditions they didn't ask for.
- A field that already means the thing (newsletters: is_bulk; sent by me: direction = 'out'; declined:
  my_response = 'declined'; links: links <> ''): filter on it; don't define a category for it.
- A file the person names ("summarise wincoop", "what's in the leads sheet"): idli summarise file NAME, idli get
  sheet NAME, idli get file NAME.
- A question about a field (who owns, how big, who is invited): show it, e.g. --fields "name, owner".
- A group word that means people or things in the person's own data (leads, funders, donors, partners): if a
  sheet or rule clearly holds them, propose a view the person confirms, then use it: idli view leads --sql
  "SELECT Name, lower(Email) AS email FROM sheet_leads_test" --about "Name and Email from the Leads (test) sheet" ;
  idli list mail --where "from_addr IN (SELECT email FROM leads)". If nothing clearly holds them, cannot,
  needs "clarify". Reuse a view that exists.
- A named thing (term, phrase, person, place): --search (quote phrases of 2+ words only when exact). "How many
  emails/files/messages": list --count (for a number mentioned inside messages/files, use --search). "By X" or
  breakdown: --group-by (never for finding names/lists inside messages). "Explain X", "what did we discuss about X":
  summarise --search. Search first; define/judge only for a category no words capture, narrowed with --search/--in/--where.
- Follow-ups refer to the previous answer (shown below with its rows and ids): use the ids, or narrow the
  previous command.
- Moving, renaming, sending, booking, posting or deleting are not available: answer cannot, needs "new_write_action".
  Drafting an email reply is available as a preview.
- Slack, Mattermost, Canva, LinkedIn, Amazon, funder portals are not connected: cannot, needs "new_connector".
- If the data simply isn't there, cannot, needs "not_in_data". Prefer a reasonable reading of a vague request
  over asking back; use cannot, needs "clarify", only when no reading makes sense.
- When a later command needs a value from an earlier result (an id, a name, a thread), don't guess or write a
  placeholder: give only the earlier commands with "continue": true. You'll see their results and give the rest.
- A period ("yesterday", "last week", "next Monday") is --on PERIOD. --since D means from D until now.
- Time of day: hour(start) >= 13 (after lunch), hour(date) < 12 (morning). Booleans: not is_bulk, is_unread.
"""


def grammar():
    lw = rs.day_range('last week')
    return GRAMMAR_HEAD + f"""
Examples (today is {rs.now():%A %Y-%m-%d}):
  "emails I got last week" -> idli list mail --on "last week" --where "direction = 'in'"
  "how many PDFs in Strategy Classics" -> idli list files --count --in "Strategy Classics" --where "kind = 'pdf'"
  "meetings next monday" -> idli list calendar --on "next monday"
  "who emails me the most" -> idli list mail --where "direction = 'in'" --group-by from_addr --limit 5
  "which spreadsheet has the most rows" -> idli list sheets --order "nrows desc" --limit 1
  "docs that discuss border effects" -> idli list files --search '"border effects"'
  "explain border effects to me" -> idli summarise --search '"border effects"'
  "what did we discuss about Nadhi in Insight Out" -> idli list messages --in "Insight Out" --search "Nadhi"
  "how many messages with links in Jam Buns" -> idli list messages --count --in "Jam Buns" --where "links <> ''"
  "emails about the school visit" -> idli define school_visit --on mail --ask "Is this email about planning a school
                     visit?" --answers yes,no ; idli judge mail --def school_visit --where "direction = 'in' and not is_bulk" ;
                     idli list threads --label school_visit
  "which of those are really about it" (after a search) -> idli define NAME --on file --ask "..." ;
                     idli judge files --def NAME --search '"the same words"' ; idli list files --label NAME
  "leads who haven't replied" -> idli query "SELECT l.Name, l.Email FROM sheet_leads_x l WHERE lower(l.Email) NOT IN
                     (SELECT from_addr FROM mail WHERE direction = 'in')"
"""


MENU_INFO = {}  # what this turn's menu held: for the log, and to spot a miss
MENU_SHEETS_WITH_COLUMNS = 5
MENU_FOLDERS = 25


def relevant_sheets(con, question, history):
    """Sheet tables whose columns the mapper should see: named by a word in the question, close in meaning to it,
    or used in the last turn."""
    if not question:
        return set()
    words = {w for w in re.findall(r'[a-z0-9]{3,}', question.lower()) if w not in rs.STOP}
    rows = con.execute('SELECT tbl, file_id, name, tab, columns FROM sheets').fetchall()
    pick = []
    for tbl, fid, name, tab, cols in rows:  # by words: in the sheet's name, tab or columns
        text = f'{name} {tab} {" ".join(json.loads(cols or "[]"))}'.lower()
        if words & set(re.findall(r'[a-z0-9]{3,}', text)):
            pick.append(tbl)
    try:  # by meaning: the sheet's card
        if rs.embeddings_ready(con):
            ids = [r[1] for r in rows]
            for fid, sc in rs.semantic_cards(con, question, ids):
                pick += [r[0] for r in rows if r[1] == fid]
    except Exception:
        pass
    for h in history[-1:]:  # what the last turn used
        for c in h.get('commands') or []:
            pick += [r[0] for r in rows if r[0] in c or f'"{r[2]}' in c]
    out = []
    for t in pick:
        if t not in out:
            out.append(t)
    return set(out[:MENU_SHEETS_WITH_COLUMNS])


def menu(con, mask=None, question=None, history=()):
    m = mask or (lambda s: s)
    # The smaller menu is opt-in (IDLI_MENU_TRIM=1): on 2026-11-21 it gave fewer errors but 17 vs 26 correct on the dev
    # bank, mostly grader and 9B noise, so it isn't proven harmless (io: benchmarks/runs/2026-11-21-menu-regression)
    full = os.environ.get('IDLI_MENU_TRIM') != '1' or os.environ.get('IDLI_MENU_FULL') == '1'
    keep = relevant_sheets(con, question, list(history)) if question and not full else None
    MENU_INFO.clear()
    MENU_INFO.update(sheets_with_columns=sorted(keep) if keep is not None else 'all')
    lines = ['Resources and fields:']
    counts_by_res = {}
    for k, r in rs.RESOURCES.items():
        if k in ('labels',):
            continue
        try:
            wh = f" WHERE {r['filter']}" if r.get('filter') else ''
            counts_by_res[k] = con.execute(f'SELECT count(*) FROM "{r["table"]}"{wh}').fetchone()[0]
        except Exception:
            counts_by_res[k] = 0
    any_populated = any(v > 0 for k, v in counts_by_res.items() if k != 'definitions')
    empty_res = []
    for k, r in rs.RESOURCES.items():
        if k in ('labels',):
            continue
        nrows = counts_by_res.get(k, 0)
        if any_populated and nrows == 0 and k != 'definitions':
            empty_res.append(k)
            continue
        notes = rs.FIELD_NOTES.get(k, {})
        cnt_tag = f' ({nrows} rows)' if nrows else ''
        lines.append(f'- {k}{cnt_tag}: {r["about"]}. Fields: {", ".join(rs.columns(con, k))}' + _values(con, k) +
                     ('. Meanings: ' + '; '.join(f'{f} = {n}' for f, n in notes.items()) if notes else ''))
    if empty_res:
        lines.append('Empty (not synced, 0 rows — do not query): ' + ', '.join(empty_res))
    sheets = con.execute('SELECT name, tab, columns, nrows, tbl, file_id FROM sheets ORDER BY name, tab_index').fetchall()
    ntabs = {}
    for r in sheets:
        ntabs[r[5]] = ntabs.get(r[5], 0) + 1
    def sheet_line(n, tb, cs, nr, t, fid):
        name = f'"{m(n)}' + (f' / {m(tb)}' if ntabs[fid] > 1 else '') + '"'
        if keep is not None and t not in keep:  # columns only for the sheets this question seems to be about
            return f'{name} ({t}, {nr} rows)'
        return f'{name} (SQL table {t}, {nr} rows; columns: {", ".join(m(c) for c in json.loads(cs)[:8])})'
    if sheets:
        lines.append('- rows --sheet NAME (or "NAME / TAB" for another tab). Sheets (columns shown for the likely ones; '
                     'idli get sheet NAME --outline shows any): ' + '; '.join(sheet_line(*r) for r in sheets))
    folders = [f[0] for f in con.execute("SELECT path || CASE WHEN path = '' THEN '' ELSE '/' END || name FROM files "
                                         "WHERE kind = 'folder' ORDER BY 1").fetchall()]
    if folders:
        if len(folders) > MENU_FOLDERS and question:  # many: the ones the question names first, then the rest by name
            qw = set(re.findall(r'[a-z0-9]{3,}', question.lower()))
            named = [f for f in folders if qw & set(re.findall(r'[a-z0-9]{3,}', f.lower()))]
            folders = (named + [f for f in folders if f not in named])[:MENU_FOLDERS]
            extra = ' (more: idli list folders)'
        else:
            extra = ''
        MENU_INFO['folders_shown'] = len(folders)
        lines.append('Drive folders: ' + '; '.join(m(f) for f in folders) + extra)
    chats = con.execute('SELECT name, msg_count FROM chats ORDER BY active_at DESC').fetchall()
    if chats:
        if len(chats) > MENU_FOLDERS and question:
            qw = set(re.findall(r'[a-z0-9]{3,}', question.lower()))
            named = [c for c in chats if qw & set(re.findall(r'[a-z0-9]{3,}', c[0].lower()))]
            chats = (named + [c for c in chats if c not in named])[:MENU_FOLDERS]
            cextra = ' (more: idli list chats)'
        else:
            cextra = ''
        MENU_INFO['chats_shown'] = len(chats)
        lines.append('Synced chats (use --in "CHAT"): ' + '; '.join(f'{m(c[0])} ({c[1]})' for c in chats) + cextra)
    defs = con.execute('SELECT name, max(version), arg_max(on_kind, version), arg_max(ask, version), '
                       'arg_max(answers, version) FROM definitions GROUP BY name').fetchall()
    if defs:
        lines.append('Definitions already made (reuse them; never define these names again): ' + '; '.join(
            f'{n} (on {k}, answers {"/".join(json.loads(ans))}): {a}' for n, v, k, a, ans in defs))
    views = con.execute('SELECT name, about FROM views').fetchall()
    if views:
        def vcols(n):
            try:
                return ', '.join(r[0] for r in con.execute(f'DESCRIBE "{n}"').fetchall())
            except Exception:
                return '?'
        lines.append('Views (the person confirmed these meanings; reuse them, also inside SQL as tables): ' +
                     '; '.join(f'{n} (columns: {vcols(n)}): {a}' for n, a in views))
    lines.append(f'Today is {rs.now():%A %Y-%m-%d}, time zone Asia/Kolkata. All data is from my own account '
                 f'({account()}); "account" is always that.')
    return '\n'.join(lines)


def _values(con, resource):
    """The values of short, few-valued text fields (direction: in, out), so filters use real values."""
    r = rs.RESOURCES[resource]
    if r.get('filter') or resource in ('definitions', 'sheets'):
        return ''
    out = []
    for c, t in con.execute(f'SELECT column_name, column_type FROM (DESCRIBE SELECT * FROM "{r["table"]}")').fetchall():
        if t != 'VARCHAR' or c in ('id', 'thread_id', 'account', 'title', 'subject', 'name', 'description', 'snippet'):
            continue
        n, mx, tot = con.execute(f'SELECT count(DISTINCT "{c}"), max(length("{c}")), count(*) FROM "{r["table"]}"').fetchone()
        if n and n <= 10 and (mx or 0) <= 24 and tot >= 3 * n:  # a real set of values, not a few titles
            vals = [v[0] for v in con.execute(f'SELECT DISTINCT "{c}" FROM "{r["table"]}" ORDER BY 1').fetchall()]
            out.append(f'{c} is one of: {", ".join(repr(v) for v in vals)}')
    return ('. ' + '; '.join(out)) if out else ''


def _remote(system, user, max_tokens=5000):
    from lib import minisql
    import urllib.request
    # reasoning is capped: uncapped, it used all of 1500 tokens on workflow asks and the JSON came back cut off
    body = {'model': minisql.MODEL, 'temperature': 0, 'max_tokens': max_tokens, 'response_format': {'type': 'json_object'},
            'reasoning': {'effort': 'low'},
            'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}]}
    if 'openrouter.ai' in minisql.URL:
        body['provider'] = {'data_collection': 'deny'}
    req = urllib.request.Request(minisql.URL, json.dumps(body).encode(), {
        'Content-Type': 'application/json', 'Authorization': 'Bearer ' + minisql._key(), 'User-Agent': 'idli-scaffold/1'})
    for attempt in (0, 1):
        with urllib.request.urlopen(req, timeout=120) as r:
            txt = json.load(r)['choices'][0]['message']['content'] or ''
        m = re.search(r'\{.*\}', txt, re.S)
        txt = m.group(0) if m else txt
        for t in (txt, txt.replace("\\'", "'")):  # the model sometimes writes \' inside JSON strings
            try:
                return json.loads(t)
            except ValueError:
                pass
        log = os.environ.get('IDLI_MAPPER_LOG')
        if log:
            open(log, 'a').write(json.dumps({'bad_json': txt[:4000]}) + '\n')
    raise ValueError('The mapper did not answer in JSON twice.')


PLAN_SCHEMA = {'type': 'object', 'properties': {'commands': {'type': 'array', 'items': {'type': 'string'}},
                                                'continue': {'type': 'boolean'},
                                                'cannot': {'type': 'string'}, 'needs': {'type': 'string'}}}


def map_question(con, question, history, mapper='remote', data_dir=None, failed=None, so_far=None):
    """The plan: idli commands for this question. Remote mapping sees masked text only. `failed` is a repair
    round: the commands that failed and why, so the mapper corrects them."""
    ctx = []
    for h in history[-2:]:
        ctx.append(f'Earlier question: {h["q"]}\nCommands run: {json.dumps(h.get("commands", []))}\n'
                   f'Result shown:\n{h.get("shown", "")[:1500]}')
    note = rs.dates_note(question)
    user = (menu(con, question=question, history=history) + '\n\n' + ('\n\n'.join(ctx) + '\n\n' if ctx else '') +
            f'Request: {question}' + (f'\nDates in this request: {note}' if note else ''))
    if so_far:
        user += ('\n\nYou already ran these for this request; their results:\n' + so_far[:5000] +
                 '\nNow give the remaining commands (or none, as {"commands": []}, if the results already answer it).')
    if failed:
        user += ('\n\nYour commands for this request failed:\n' + '\n'.join(failed) +
                 '\nGive the full corrected list of commands (same JSON shape).')
    t0 = time.time()
    if mapper == 'remote':
        from lib import privacy
        user = privacy.mask_account_text(data_dir, user)  # once, over everything that leaves (0.2 s)
        raw = _remote(grammar(), user)
        from lib import home
        plan = home.rehydrate(data_dir, raw)
    else:
        msgs = [{'role': 'system', 'content': grammar()}, {'role': 'user', 'content': user}]
        try:
            raw = plan = rs._nine(msgs, PLAN_SCHEMA, max_tokens=500, timeout=180)
        except ValueError:  # cut off or not JSON: once more, asked to be brief with anti-loop penalty
            msgs[-1] = {'role': 'user', 'content': user + '\n\nAnswer with short JSON: 1 or 2 commands, at most ONE --search flag.'}
            raw = plan = rs._nine(msgs, PLAN_SCHEMA, max_tokens=500, timeout=180, repeat_penalty=1.08)
    kind = 'repair' if failed else ('continue' if so_far else 'first')
    MAPPER_CALLS.append({'kind': kind, 'mapper': mapper, 'sent': user, 'returned': raw, 'seconds': round(time.time() - t0, 2)})
    say(1, f'[mapper {mapper}, {kind}] {round(time.time() - t0, 1)} s')
    say(2, f'[sent to the mapper' + (' (masked)' if mapper == 'remote' else '') + f', {len(user)} characters]\n{user}')
    say(2, f'[the mapper returned]\n{json.dumps(raw, ensure_ascii=False)}')
    return plan, len(user)


STYLE = """You are Idli, answering the person in a chat. Write 1-3 short sentences that answer what they just said,
using only the result below. Rules:
- If they corrected you or pointed at something ("no, the one from...", "the second one"), acknowledge that first in
  a few words, then answer.
- Don't repeat the wording of your previous reply. Don't list the rows (they are shown under your words); mention
  at most two items by name.
- Don't mention how it was worked out (seconds, judging, definitions, commands) unless they asked. Never tell
  them to run a command. If a step failed, say in plain words what you couldn't find.
- Only use numbers that appear in the result. If the result is empty, say so plainly and suggest one next step.
- Talk like a colleague about their data ("4 files are in the fixity folder"), never about rows or results.
- Don't end with a question or an offer ("Would you like...") unless their request was unclear.
- Plain words, no headings, no bullet points, no "As an AI".
- A draft is only a preview: never say it was saved, sent, or put in a folder.
- Only state what the rows show. If they ask who owns something, its size or its guests and that field isn't
  in the rows, say you can't see it here; never guess it from a name. Your previous reply was about an earlier
  question: don't repeat it."""


NUM = re.compile(r'(?<![\w.])\d+(?:[.,]\d+)?(?![\w])')


def compose(question, shown, history, plan_note=''):
    prev = history[-1]['reply'] if history else ''
    schema = {'type': 'object', 'properties': {'reply': {'type': 'string'}}, 'required': ['reply']}
    today = f'Today is {rs.now():%A %d %B %Y} (IST). Anchor words like "today" or "tomorrow" inside older messages to their message date.'
    msg = (f'{today}\n' +
           (f'Their previous question: {history[-1]["q"]}\nYour previous reply: {prev}\n\n' if history else '') +
           f'What they said now: {question}\n{plan_note}\nResult:\n{shown[:6000]}')
    try:
        reply = rs._nine([{'role': 'system', 'content': STYLE}, {'role': 'user', 'content': msg}], schema,
                         max_tokens=220)['reply'].strip()
    except Exception:
        return '', 'compose_failed'
    words = {'one': '1', 'two': '2', 'three': '3', 'four': '4', 'five': '5', 'six': '6', 'seven': '7', 'eight': '8',
             'nine': '9', 'ten': '10', 'eleven': '11', 'twelve': '12', 'single': '1'}
    said = NUM.findall(reply) + [words[w.lower()] for w in re.findall(r'\b(' + '|'.join(words) + r')\b', reply, re.I)]
    if re.search(r'Would draft \(not saved\)', shown) and re.search(r'\b(saved|sent|drafts? folder|unsent|outbox|ready in)\b', reply, re.I):
        return '', 'draft_claimed_saved'
    if 'Nothing matches' not in shown and re.match(r'\d+ rows?\b|Count: [1-9]', shown.strip()) and \
            re.search(r"\b(couldn't find|could not find|no (emails?|files?|documents?|results?|meetings?) (match|found)|nothing (matches|found))\b", reply, re.I):
        return '', 'says_nothing_but_rows_shown'
    if 'Nothing matches' in shown and said:  # an empty result has no count to word
        return '', 'number_on_empty_result:' + ','.join(said)
    body = re.sub(r'(?m)^\s*\d+\.\s', '', shown)  # "1. ", "2. ": list numbering, not numbers in the result
    allowed = set(NUM.findall(body)) | set(NUM.findall(question))
    m = re.match(r'(\d+) rows?\b', shown.strip())
    total = m.group(1) if m else None
    bad = [n for n in said if n not in allowed and n.replace(',', '') not in allowed]
    # "I found 19 documents", "three meetings": a count of the results must be the real count
    nouns = r'(emails?|messages?|meetings?|events?|files?|documents?|docs?|pdfs?|sheets?|spreadsheets?|rows?|items?|results?|threads?|people|leads?|photos?)'
    for w in re.findall(r'\b(\d+|' + '|'.join(words) + r')\s+(?:\w+\s+){0,2}?' + nouns + r'\b', reply, re.I):
        n = words.get(w[0].lower(), w[0])
        if total and n != total and n not in allowed:  # a count that is neither the total nor a value shown
            bad.append(f'{n} (shown: {total})')
    if bad:
        return '', 'number_not_in_result:' + ','.join(bad)
    return reply, ''


def _held(rec, plan, question, t0):
    """The plan stopped at a new meaning: ask the person, or say it was dropped."""
    if plan.get('pending'):
        rec.update(reply='Before I go on: ' + plan['pending']['card'] +
                   '\n\nTo keep it: idli ask yes\nTo use your own wording: idli ask "yes: <your question>"'
                   '\nAsking anything else drops it.', pending={'q': question, **plan['pending']})
    else:
        rec.update(reply='Okay, I did not make it, and nothing was judged. You can ask again in other words.')
    rec.update(shown='', commands=rec.get('commands', []), needs='meaning', total_s=round(time.time() - t0, 2))
    return rec


def sheet_distinct_count(con, question):
    """Answer simple distinct counts when the question names a synced workbook and tab."""
    text = question.strip().rstrip('?.!')
    match = re.fullmatch(r'in (.+?),\s*how many (?:distinct|unique|different) (.+?) are there', text, re.I)
    if match:
        scope, field = match.groups()
    else:
        match = re.fullmatch(r'how many (?:distinct|unique|different) (.+?) are (?:there )?in (.+)', text, re.I)
        if not match:
            return
        field, scope = match.groups()
    scope = scope.casefold()
    sheets = con.execute('SELECT name, tab, tbl, file_id FROM sheets').fetchall()
    matches = [(name, tab, table, fid) for name, tab, table, fid in sheets
               if name.casefold() in scope and tab.casefold() in scope]
    if len(matches) != 1:
        return
    name, tab, table, fid = matches[0]
    # Constrain the shortcut to an unfiltered count on the named source.
    remaining = scope.replace(name.casefold(), '').replace(tab.casefold(), '')
    if re.sub(r"""\b(?:of|the|tab|sheet|workbook|spreadsheet)\b|[\s'"/]+""", '', remaining):
        return
    ident = lambda value: '"' + value.replace('"', '""') + '"'
    cols = rs.columns_of(con, ident(table))
    fields = [c for c in cols if field.strip(' "`').casefold() in (c.casefold(), c.casefold() + 's')]
    if len(fields) != 1:
        return
    col = ident(fields[0])
    sql = f"SELECT count(DISTINCT {col}) FROM {ident(table)} WHERE trim(cast({col} AS VARCHAR)) <> ''"
    count, = con.execute(sql).fetchone()
    return (f'{tab} has {count} distinct nonblank values for {fields[0]}.\n{name}\n'
            + source_link('sheets', fid), qjoin(['idli', 'query', sql]))


def last_sent_reply(con, question, history):
    """Resolve a person against the synced mailbox before selecting their latest outgoing message."""
    match = re.fullmatch(r"(?:show me |what was |what’s |what's )?(?:what I (?:responded|replied) to (.+?) with last|"
                         r"(?:my |the )?(?:last|latest) (?:email|reply|message) to (.+?)|"
                         r"what did I last (?:send|say|write) to (.+?))[?.!]?", question.strip(), re.I)
    if match:
        person = next(group for group in match.groups() if group).strip()
        intent = "reply" if re.search(r"\b(?:responded|replied|reply)\b", question, re.I) else "sent"
    elif history and history[-1].get('clarify_recipient') and re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', question.strip()):
        person = question.strip()
        intent = history[-1]['clarify_recipient']
    else:
        return
    mailbox = account()
    sent = con.execute("SELECT to_addrs, date, subject, body_text, thread_id FROM mail "
                       "WHERE account=? AND direction='out' ORDER BY date DESC NULLS LAST, id DESC", [mailbox]).fetchall()
    recipients = [getaddresses([row[0] or '']) for row in sent]
    contacts = con.execute("SELECT DISTINCT from_name, from_addr FROM mail WHERE account=?", [mailbox]).fetchall()
    for addresses in recipients:
        contacts.extend(addresses)
    needle = person.casefold()
    def matches(name, addr):
        if '@' in needle:
            return needle == addr.casefold()
        return bool(re.search(r'(?<!\w)' + re.escape(needle) + r'(?!\w)',
                              (name or '').casefold() + ' ' + addr.split('@')[0].casefold()))
    choices = sorted({addr.casefold() for name, addr in contacts if addr and matches(name, addr)})
    if len(choices) > 1:
        return ('Which email address did you mean?\n' + '\n'.join('• ' + a for a in choices[:6]), intent)
    if not choices and '@' not in needle:
        return (f'I couldn’t identify {person} in your synced email. What email address should I check?', intent)
    prior = {}
    if choices and intent == 'reply':
        prior = dict(con.execute("SELECT thread_id, min(date) FROM mail WHERE account=? AND direction='in' "
                                 "AND lower(from_addr)=? GROUP BY thread_id", [mailbox, choices[0]]).fetchall())
    for row, addresses in zip(sent, recipients):
        _, date, subject, body, thread = row
        if not any(addr.casefold() in choices for _, addr in addresses):
            continue
        if intent == 'reply' and not (prior.get(thread) and date and prior[thread] <= date):
            continue
        label = 'reply' if intent == 'reply' else 'email'
        return (f'Your latest synced {label} to {choices[0]} was on {_fmt(date)}.\n{subject or "(no subject)"}\n\n'
                f'{(body or "").strip()[:3000]}\n{source_link("mail", thread)}'.strip(), False)
    label = 'reply' if intent == 'reply' else 'sent email'
    return (f'I couldn’t find a {label} to {person} in your synced mail.', False)


def ask(con, question, history, mapper='remote', data_dir=None, show_commands=True, resume=None, humanize=False):
    """One turn. Returns a dict with the reply and everything the bench needs. `resume` carries on a plan that
    stopped at a new meaning, after the person said yes."""
    t0 = time.time()
    rec = {'q': question, 'mapper': mapper}
    if humanize and not resume:
        metric = sheet_distinct_count(con, question)
        if metric:
            reply, command = metric
            return {**rec, 'reply': reply, 'shown': reply, 'commands': [command],
                    'total_s': round(time.time() - t0, 2)}
        latest = last_sent_reply(con, question, history)
        if latest:
            reply, clarify = latest
            return {**rec, 'reply': reply, 'shown': reply, 'commands': [],
                    'clarify_recipient': clarify, 'total_s': round(time.time() - t0, 2)}
    global SAID
    SAID = ' '.join([h.get('q') or '' for h in history] + [question])
    SEARCHED.clear()
    for h in history:
        for c in h.get('commands') or []:
            SEARCHED.update(_searches(c))
    if resume:
        plan, rec['resumed'] = {'commands': resume['commands']}, True
    else:
        try:
            plan, rec['prompt_chars'] = map_question(con, question, history, mapper, data_dir)
        except Exception as e:
            plan = {'cannot': f'I could not work out the steps ({type(e).__name__}).', 'needs': 'mapper_failed'}
    rec['map_s'] = round(time.time() - t0, 2)
    rec['plan'] = plan
    if not plan.get('commands'):
        needs = plan.get('needs', 'clarify')
        why = plan.get('cannot') or 'I am not sure what to look up.'
        nxt = {'new_connector': ' The Builder can ask for a connector for it; until then I only see your Google account.',
               'new_write_action': ' I can read and show previews (a draft reply, for example), but changing things '
                                   'in your accounts needs an action our team adds.'}.get(needs, '')
        why = why.rstrip()
        why += '' if not nxt or why.endswith(('.', '!', '?')) else '.'
        rec.update(reply=why + nxt, shown='', commands=[], needs=needs, total_s=round(time.time() - t0, 2))
        return rec
    chat_results = {} if humanize else None
    shown_parts, cmds, judge_s, errors = run_plan(con, plan, chat_results, question)
    if plan.get('pending') or plan.get('declined'):
        rec['commands'] = cmds
        return _held(rec, plan, question, t0)
    if errors:  # one repair round: the mapper sees what failed and why
        try:
            plan2, _ = map_question(con, question, history, mapper, data_dir, failed=errors)
            if plan2.get('commands'):
                rec['repaired'] = plan = plan2
                made = [c for c in cmds if re.match(r'(idli\s+)?(define|view|judge)\b', c)]  # already done
                shown_parts, cmds, judge_s2, errors = run_plan(con, plan2, chat_results, question)
                cmds = made + [c for c in cmds if c not in made]
                judge_s += judge_s2
                if plan.get('pending') or plan.get('declined'):
                    rec['commands'] = cmds
                    return _held(rec, plan, question, t0)
        except Exception:
            pass
    rounds = 0
    while plan.get('continue') and rounds < 2 and not errors:  # the mapper asked to see results first
        rounds += 1
        so_far = '\n'.join(f'$ {c}\n{p}' for c, p in zip(cmds, shown_parts))
        try:
            plan, _ = map_question(con, question, history, mapper, data_dir, so_far=so_far)
        except Exception:
            break
        if not plan.get('commands'):
            break
        more_parts, more_cmds, js, errors = run_plan(con, plan, chat_results, question)
        shown_parts += more_parts; cmds += more_cmds; judge_s += js
        if plan.get('pending') or plan.get('declined'):
            rec['commands'] = cmds
            return _held(rec, plan, question, t0)
    rec['rounds'] = rounds
    shown = '\n\n'.join(shown_parts)
    t1 = time.time()
    display_parts = shown_parts[-1:]
    reads = [(c, p) for c, p in zip(cmds, shown_parts) if not re.match(r'(idli\s+)?(define|judge|view)\b', c)]
    if 1 < len(reads) <= 3 and all(len(p.splitlines()) <= 6 for _, p in reads[:-1]):
        # "how many sheets, and which has the most rows": each part is an answer; show (and word) them all
        display_parts = [p for _, p in reads]
    final_rows = '\n\n'.join(display_parts)
    earlier = ('Earlier steps (not shown to the person; do not describe their rows): ' + ' ; '.join(cmds[:-1])) \
        if len(cmds) > 1 else ''
    chat_has_rows = humanize and any(
        chat_results.get(p) and chat_results[p].rows
        and ('found' not in chat_results[p].cols or 'body' in chat_results[p].cols)
        for p in display_parts
    )
    if humanize and not chat_has_rows:
        reply, why = '', 'chat_result'
    elif cmds and re.match(r'(idli\s+)?(summarise|explain|help)\b', cmds[-1]) and 'failed' not in final_rows[:40]:
        reply, why = '', 'prose_result'  # the result is already written for the person
    else:
        reply, why = compose(question, final_rows, history, plan_note=earlier)
    rec['compose_s'] = round(time.time() - t1, 2)
    rec['compose_fallback'] = why
    body = (reply + '\n\n' if reply else '') + (final_rows if final_rows else '')
    if final_rows and re.search(r'list files .*--search', cmds[-1] if cmds else '') and 'Nothing matches' not in final_rows:
        body += ('\n\nThese mention it; to check which ones are really about it, ask me to judge them '
                 '(it reads only these files).')
    if humanize:
        pieces = []
        for part in display_parts:
            result = chat_results.get(part)
            if result is None:
                pieces.append("I couldn’t complete that lookup.")
            else:
                pieces.append(chat_result(result, question))
        body = '\n\n'.join(pieces) or reply or "I couldn’t find an answer."
        if reply and chat_has_rows:
            body = reply + '\n\n' + body
    if show_commands:
        body += '\n\n(Ran: ' + ' ; '.join(cmds) + ')'
    rec.update(reply=body.strip(), words=reply, shown=shown, commands=cmds, errors=errors, judge_s=round(judge_s, 1),
               total_s=round(time.time() - t0, 2))
    return rec


PLACEHOLDER = re.compile(r'<[A-Za-z_][A-Za-z0-9_ .\-]{1,60}>|(?<![\w"\'-])(REF|NAME|WORDS|FOLDER|ID|THREAD)(?![\w"\'-])')
CONFIRM = None  # main sets it when someone can answer now: card -> True, False, or a better wording (str)
SECONDS_PER_ITEM = {'clef': 0.2, 'nine_compressed': 0.9, 'nine': 1.9}  # measured 2026-11-20, two at a time


def meaning_card(con, verb, a):
    """What the person is asked before a new category or saved list is made."""
    if verb == 'view':
        return (f'I would save "{a.name}" to mean: {a.about or "the rows of this query"}.\n'
                f'  The rule: {a.sql}')
    things = {'mail': ('emails', "SELECT count(*) FROM mail"), 'event': ('events', "SELECT count(*) FROM events"),
              'photo': ('pictures', "SELECT count(*) FROM files WHERE kind = 'image'"),
              'message': ('messages', "SELECT count(*) FROM messages"),
              'file': ('files', f"SELECT count(*) FROM files WHERE kind IN ('pdf', 'doc', 'sheet', 'other') "
                                f"AND NOT {rs.EMPTY_SQL}")}[a.on]
    n = con.execute(things[1]).fetchone()[0]
    secs = n * SECONDS_PER_ITEM.get(rs.JUDGE, 1)
    took = f'about {int(secs // 60)} min' if secs >= 90 else f'about {int(secs)} s'
    return (f'I would make a new category "{a.name}": {a.ask}\n'
            f'  Answers: {", ".join(a.answers.split(","))}.\n'
            f'  Judging all your {things[0]} with it reads up to {n} of them ({took} with {rs.JUDGE}); '
            f'it can be narrowed to fewer.')


def tty_confirm(card):
    print('\n' + card, file=sys.stderr)
    try:
        ans = input('Keep this? y = yes, n = no, or type a better wording: ').strip()
    except EOFError:
        return None
    if ans.lower() in ('y', 'yes'):
        return True
    if ans.lower() in ('', 'n', 'no'):
        return False
    return ans


SAID = ''  # the person's words this conversation (ask sets it): --search may only use these
SEARCHED = set()  # --search values already run this conversation: a judge may narrow to "those" only


def _searches(c):
    try:
        argv = shlex.split(c)
    except ValueError:
        return []
    return [argv[i + 1].strip('"\' ').lower() for i, t in enumerate(argv[:-1]) if t == '--search']


IN_FILLER = {'group', 'chat', 'whatsapp', 't4gc', 'the', 'my', 'our', 'active', 'speaking', 'event', 'by', 'for', 'of', 'at', 'in'}
DATE_CUE_RE = re.compile(
    r'\b(today|yesterday|tomorrow|week|weeks|month|months|year|years|day|days|morning|tonight|evening|'
    r'monday|tuesday|wednesday|thursday|friday|saturday|sunday|'
    r'jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|'
    r'sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?|'
    r'last|next|past|recent|latest|since|before|after|until|upcoming|earlier|ago|20\d{2}|\d+d)\b',
    re.I,
)


def own_words(c):
    """Drop --search values whose words the person never used, drop --in CHAT/FOLDER values
    that share zero words (or acronym) with what the person actually said, and drop
    hallucinated --since/--until/--on filters when the person gave no date or time cue."""
    if not SAID or not any(f in c for f in ('--search', '--in', '--folder', '--since', '--until', '--on')):
        return c, []
    try:
        argv = shlex.split(c)
    except ValueError:
        return c, []
    said = set(re.findall(r'[a-z0-9]+', SAID.lower()))
    stem = lambda w: (w[:-1] if len(w) >= 4 and w.endswith('s') and not w.endswith('ss') else w).replace('z', 's')
    said |= {stem(w) for w in said}
    has_date_cue = bool(DATE_CUE_RE.search(SAID))
    judging = 'judge' in argv[:2]
    out, dropped, i = [], [], 0
    while i < len(argv):
        if argv[i] == '--search':
            if i + 1 >= len(argv) or argv[i + 1].startswith('--'):
                dropped.append('')
                i += 1
                continue
            ws = re.findall(r'[a-z0-9]+', argv[i + 1].lower())
            not_said = ws and not all(w in said or stem(w) in said for w in ws)
            not_shown = judging and argv[i + 1].strip('"\' ').lower() not in SEARCHED  # judge narrows to a shown search
            if not ws or not_said or not_shown:
                dropped.append(argv[i + 1]); i += 2; continue
        elif argv[i] in ('--in', '--folder'):
            if i + 1 >= len(argv) or argv[i + 1].startswith('--'):
                dropped.append('')
                i += 1
                continue
            raw_in = argv[i + 1]
            in_toks = [w for w in re.findall(r'[a-z0-9]+', raw_in.lower()) if w not in IN_FILLER]
            if not in_toks:
                in_toks = re.findall(r'[a-z0-9]+', raw_in.lower())
            acro = ''.join(w[0] for w in in_toks) if len(in_toks) >= 2 else ''
            has_match = (
                not in_toks
                or any(w in said or stem(w) in said or (len(w) >= 3 and any(sw.startswith(w[:3]) or w.startswith(sw) for sw in said if len(sw) >= 3)) for w in in_toks)
                or (acro and acro in said)
            )
            if not has_match:
                dropped.append(f'--in {raw_in}')
                i += 2
                continue
        elif argv[i] in ('--since', '--until', '--on') and not has_date_cue:
            # Don't drop `--on` for `define --on mail|message`!
            if argv[i] == '--on' and 'define' in argv[:2]:
                out.append(argv[i]); i += 1; continue
            if i + 1 < len(argv):
                dropped.append(f'{argv[i]} {argv[i + 1]}')
                i += 2
                continue
        out.append(argv[i]); i += 1
    return (qjoin(out), dropped) if dropped else (c, [])


def qjoin(argv):
    """A command line as a person would type it: "double quotes" around anything with spaces or single quotes."""
    def q(a):
        if re.fullmatch(r'[\w./:@=,+-]+', a):
            return a
        return '"' + a.replace('\\', '\\\\').replace('"', '\\"') + '"' if '"' not in a or "'" in a else "'" + a + "'"
    return ' '.join(q(a) for a in argv)


def _merge_list_searches(cmds):
    """Merge consecutive `idli list <resource> --search <unquoted>` commands that share the exact same
    scope flags (--in, --where, --on, --since, --until, --fields) into a single combined --search
    command so earlier keywords aren't overwritten by the last command."""
    if len(cmds) < 2:
        return cmds

    def parse_list_search(c):
        try:
            argv = shlex.split(c)
        except ValueError:
            return None
        prefix = ['idli'] if argv[:1] == ['idli'] else []
        rest = argv[len(prefix):]
        if len(rest) < 3 or rest[0] != 'list':
            return None
        resource = rest[1]
        terms, scope_tokens, limit_val = [], [], None
        i = 2
        while i < len(rest):
            t = rest[i]
            if t == '--search' and i + 1 < len(rest):
                val = rest[i + 1]
                if '"' in val:  # keep exact quoted phrase searches separate
                    return None
                terms.append(val)
                i += 2
            elif t == '--limit' and i + 1 < len(rest):
                try:
                    limit_val = int(rest[i + 1])
                except ValueError:
                    return None
                i += 2
            elif t in ('--count', '--group-by', '--by'):
                return None
            else:
                scope_tokens.append(t)
                i += 1
        if not terms:
            return None
        return prefix, resource, tuple(scope_tokens), terms, limit_val

    out = []
    i = 0
    while i < len(cmds):
        p = parse_list_search(cmds[i])
        if not p:
            out.append(cmds[i])
            i += 1
            continue
        prefix, res, scope, all_terms, max_lim = p
        j = i + 1
        while j < len(cmds):
            p2 = parse_list_search(cmds[j])
            if p2 and p2[1] == res and p2[2] == scope:
                all_terms.extend(p2[3])
                if p2[4] is not None:
                    max_lim = max(max_lim or 0, p2[4])
                j += 1
            else:
                break
        if j - i > 1:
            merged_words = ' '.join(dict.fromkeys(w for t in all_terms for w in t.split()))
            argv = prefix + ['list', res] + list(scope) + ['--search', merged_words]
            if max_lim is not None:
                argv += ['--limit', str(max_lim)]
            out.append(qjoin(argv))
        else:
            out.append(cmds[i])
        i = j
    return out


def run_plan(con, plan, chat_results=None, question=None):
    shown_parts, cmds, judge_s, errors = [], [], 0.0, []
    seen_cmds = set()
    plan_cmds = _merge_list_searches(list(plan['commands'][:6]))
    for c in plan_cmds:
        if c.strip().lower() in ('continue', 'idli continue'):
            # The 9B occasionally emits "continue" inside commands[] instead of "continue": true.
            if not shown_parts:
                plan['continue'] = True
            continue
        if PLACEHOLDER.search(c):  # it needs a value from the results so far: stop here and ask for the rest
            plan['continue'] = True
            break
        c2, dropped = own_words(c)
        SEARCHED.update(_searches(c2)) if not re.match(r'(idli\s+)?judge\b', c2) else None
        if dropped:
            say(1, f'[own words] dropped {dropped}: not words the person used')
            plan.setdefault('dropped_search', []).extend(dropped)
            plan['commands'] = [c2 if x == c else x for x in plan['commands']]
            c = c2
        if c in seen_cmds:
            continue
        seen_cmds.add(c)
        try:
            argv = shlex.split(c)
        except ValueError:
            try:  # 'direction = \'in\'': a shell can't escape inside single quotes; read it as meant
                argv = shlex.split(re.sub(r"'((?:[^'\\]|\\')*)'", lambda m: '"' + m.group(1).replace("\\'", "'") + '"', c))
            except ValueError:
                errors.append(f'{c}: could not read the command')
                continue
        verb = argv[1] if argv[:1] == ['idli'] and len(argv) > 1 else argv[0]
        if verb in ('define', 'view'):  # a new meaning: never made or changed without the person's yes
            try:
                pa = parser().parse_args(argv[1:] if argv[:1] == ['idli'] else argv)
            except Err as e:
                errors.append(f'{c}: {e}')
                continue
            tbl = 'definitions' if verb == 'define' else 'views'
            if con.execute(f'SELECT 1 FROM {tbl} WHERE name = ?', [pa.name]).fetchone():
                say(1, f'[step] {c}\n       skipped: "{pa.name}" already exists, so it is used as it is')
                plan.setdefault('kept', []).append(pa.name)
                continue
            card = meaning_card(con, verb, pa)
            ans = CONFIRM(card) if CONFIRM else None
            if ans is None:  # no one to ask right now: stop here, keep the rest for "idli ask yes"
                plan['pending'] = {'card': card, 'commands': plan['commands'][plan['commands'].index(c):]}
                break
            if ans is False:
                plan['declined'] = card
                break
            if isinstance(ans, str):  # the person's own wording
                pa.ask = ans
                argv = ['define', pa.name, '--on', pa.on, '--ask', ans, '--answers', pa.answers]
                c = shlex.join(['idli'] + argv)
        args = argv[1:] if argv[:1] == ['idli'] else argv
        if (chat_results is not None and args[:2] in (['list', 'calendar'], ['list', 'events'])
                and re.search(r"\b(?:my|our|the) next (?:meeting|appointment|event)\b", question or '', re.I)):
            argv.extend(['--where', f"start >= '{rs.local(rs.now()):%Y-%m-%d %H:%M:%S}'", '--order', 'start asc'])
            c = qjoin(argv)
        cmds.append(c)
        t0 = time.time()
        say(1, f'[step] {c}' + ('   (writes to the store)' if re.match(r'(idli\s+)?(define|judge|view)\b', c) else ''))
        try:
            r = run_argv(con, argv, chat=chat_results is not None, intent=question)
            say(1, f'       {round(time.time() - t0, 1)} s')
            say(2, r.render())
        except (Err, ValueError) as e:
            from lib import searchkit as sk
            if isinstance(e, sk.EntityNotFoundError) and '--in' in argv and '--search' in argv and '--count' not in argv:
                # If the mapper guessed a person/org name as --in CHAT alongside --search (and the user didn't call it a group/chat),
                # fall back to searching all chats for both terms rather than dead-ending.
                in_idx = argv.index('--in')
                missing_in = argv[in_idx + 1] if in_idx + 1 < len(argv) else ''
                explicit_group = bool(missing_in and re.search(re.escape(missing_in) + r'\s+(?:group|chat)\b', question or '', re.I))
                if missing_in and not explicit_group:
                    retry_argv = argv[:in_idx] + argv[in_idx + 2:] + ['--search', missing_in]
                    try:
                        r = run_argv(con, retry_argv, chat=chat_results is not None, intent=question)
                        r.note = '\n'.join(filter(None, [f'No chat named "{missing_in}"; searched all synced chats instead.', r.note]))
                        rendered = r.render()
                        shown_parts.append(rendered)
                        if chat_results is not None:
                            chat_results[rendered] = r
                        say(1, f'       fallback without --in "{missing_in}": ok')
                        continue
                    except Exception:
                        pass
            if isinstance(e, sk.EntityError):
                # Entity not found / ambiguous is a user-facing clarification, not a syntax bug to retry blindly.
                r = Result(kind='text', text=str(e), chat=str(e))
                rendered = r.render()
                shown_parts.append(rendered)
                if chat_results is not None:
                    chat_results[rendered] = r
                say(1, f'       clarify: {e}')
                continue
            errors.append(f'{c}: {e}')
            shown_parts.append(f'(That step failed: {e})')
            say(1, f'       failed: {e}')
            continue
        except Exception as e:
            say(1, f'       failed: {type(e).__name__}: {e}')
            errors.append(f'{c}: {type(e).__name__}: {e}')
            shown_parts.append(f'(That step failed: {type(e).__name__})')
            continue
        if argv[1:2] == ['judge'] or argv[:1] == ['judge']:
            try:
                judge_s += json.loads(r.note)['seconds']
            except Exception:
                pass
        rendered = r.render()
        shown_parts.append(rendered)
        if chat_results is not None:
            chat_results[rendered] = r
    return shown_parts, cmds, judge_s, errors


JUDGES = ['nine', 'nine_compressed', 'clef']


def use_models(mapper=None, judge=None):
    """Set which 9B maps and words replies, and who judges. The judge follows the mapper unless given. With the
    remote mapper the judge stays the served 9B: judging reads real content, and idli-remote only sees masked text.
    Clef is never the default: hosted, it sees real content (test accounts only)."""
    rs.NINE = 'nine' if mapper == 'nine' else 'nine_compressed'
    rs.JUDGE = judge or os.environ.get('IDLI_JUDGE') or 'clef'  # owner's choice 2026-11-21 (test accounts: hosted)


def _session_path():
    return Path(sandbox()) / 'session.json'


def menu_miss(con, rec):
    """A command or error that involves a sheet whose columns weren't in the menu: the smaller menu may have caused
    it. Logged on every turn, so the trimming can be judged on evidence (owner, 2026-11-21)."""
    kept = MENU_INFO.get('sheets_with_columns')
    if kept == 'all' or kept is None:
        return None
    text = ' '.join(rec.get('commands') or []) + ' ' + ' '.join(rec.get('errors') or [])
    used = []
    low = text.lower()
    for tbl, name in con.execute('SELECT tbl, name FROM sheets').fetchall():
        as_sheet = name and re.search(r'(--sheet|get sheet)\s+["\']?' + re.escape(name.lower()), low)
        if tbl in text or as_sheet:  # used as a sheet, not a folder that shares its name
            used.append(tbl)
    missed = [t for t in dict.fromkeys(used) if t not in kept]
    if not missed:
        return None
    return {'sheets_without_columns': missed, 'had_errors': bool(rec.get('errors')),
            'empty_result': 'Nothing matches' in (rec.get('shown') or '')}


# ---- what kind of ask, and did this turn struggle (owner, 2026-11-21) ----
KINDS = {
    'lookup': 'The answer is already in the data as it is: dates, senders, folders, counts, file names, or words in '
              'documents. Nothing has to be judged.',
    'judgement': 'Each item has to be read and judged against a category the person has in mind, like urgent, about '
                 'climate, sounds unhappy, asks for money.',
    'workflow': 'Several steps, joining different sources, or words that mean something particular in this '
                "person's work (leads, follow up, prep list, needs a reply from my partners).",
    'elsewhere': 'Needs a site that is not connected (Slack, LinkedIn) or an action that changes things '
                 '(send, post, book, move, delete).',
}
CHIP_MIN = 0.5
CHIP_COLOUR = {'lookup': 32, 'judgement': 33, 'workflow': 35, 'elsewhere': 34, 'struggled': 31}


def classify(question):
    """Clef labels the ask. Hosted Clef sees the question (test accounts; Clef runs locally later). Returns
    (label, probabilities), or (None, {}) when Clef can't be reached."""
    from lib import minisql
    body = {'model': 'cloudflare/clef-flash', 'state': question,
            'questions': {'kind': {'type': 'choice', 'instructions': 'What kind of request is this, for an assistant '
                                   "that reads the person's own email, calendar and files?", 'criteria': KINDS}},
            'provider': {'order': ['Cloudflare'], 'allow_fallbacks': False}}
    try:
        req = urllib.request.Request('https://openrouter.ai/api/v1/systemone', json.dumps(body).encode(), {
            'Content-Type': 'application/json', 'Authorization': 'Bearer ' + minisql._key(), 'User-Agent': 'idli-scaffold/1'})
        with urllib.request.urlopen(req, timeout=20) as r:
            a = json.load(r)['answers']['kind']
        probs = {k: round(v, 2) for k, v in a['probabilities'].items()}
        # measured 2026-11-21 on 91 labelled tasks: top >= 0.5, or >= 0.4 with a 0.15 lead: 70 chips, 70% agree,
        # workflow chips 10 of 13 right (io: benchmarks/runs/2026-11-21-kind-classifier)
        v = sorted(probs.values(), reverse=True)
        sure = v[0] >= CHIP_MIN or (v[0] >= 0.4 and v[0] - v[1] >= 0.15)
        return (a['choice'] if sure else None), probs
    except Exception:
        return None, {}


def _words(q):
    return set(re.findall(r'[a-z0-9]{3,}', (q or '').lower())) - rs.STOP


def struggle(rec, history):
    """Signs this turn went badly, from what happened inside it (never just an empty result)."""
    why = []
    if rec.get('repaired'):
        why.append('a step failed and was redone')
    if rec.get('errors'):
        why.append('a step failed')
    if rec.get('needs') == 'mapper_failed':
        why.append('I could not work out the steps')
    if any(re.match(r'(idli\s+)?query\b', c) and re.search(r'\bjoin\b|\bin\s*\(\s*select', c, re.I)
           for c in rec.get('commands') or []):
        why.append('I had to write my own join')
    q = _words(rec.get('q')) if not rec.get('resumed') else set()  # "yes" to a card re-runs the question
    for h in [h for h in history[-3:] if not h.get('pending')]:  # the person asking again: the last answer didn't help
        hw = _words(h.get('q'))
        if q and hw and len(q & hw) / len(q | hw) >= 0.6:
            why.append('you asked this again')
            break
    return why


def chips(kind, why):
    def chip(label, text=None):
        t = f'[{text or label}]'
        return f'\033[{CHIP_COLOUR[label]}m{t}\033[0m' if sys.stdout.isatty() else t
    out = [chip(kind)] if kind else []
    if why:
        out.append(chip('struggled', 'struggled: ' + '; '.join(dict.fromkeys(why))))
    return ' '.join(out)


def offer(kind, why, rec):
    """What to suggest next, from the kind of ask and whether it struggled."""
    if rec.get('pending'):
        return ''  # the yes card already asks
    if 'you asked this again' in why:
        return 'This does not seem to be working. idli-remote may do better (it sees your question masked): ' \
               'idli ask --mapper remote "..."'
    if kind == 'workflow':
        tail = ' For a reliable repeat, this could become a Mini.'
        return ('I did my best, but this looks like a workflow. idli-remote may do better: idli ask --mapper remote '
                '"..."' + tail) if why else ('This looks like a workflow.' + tail)
    if why and kind in ('lookup', None):
        return 'I struggled with this one. idli-remote may do better: idli ask --mapper remote "..."'
    return ''


def ran_block(cmds):
    marks = [c + ('   (writes to the store)' if re.match(r'(idli\s+)?(define|judge|view)\b', c) else '') for c in cmds]
    return dim('Ran:\n' + '\n'.join('  ' + m for m in marks)) if cmds else ''


def main(argv=None):
    argv = take_verbosity(sys.argv[1:] if argv is None else argv)
    import logging
    logging.getLogger('pypdf').setLevel(logging.WARNING if VERBOSE >= 3 else logging.ERROR)
    rs.TRACE = say
    if argv[:1] == ['sync'] and parser().parse_args(argv).what != 'whatsapp':
        from lib import google_api
        acct = account(parser().parse_args(argv).role)
        try:
            if not google_api.connected(acct):
                if not sys.stdin.isatty():
                    raise ValueError(f'Google consent needed for {acct}. Run this sync in a laptop terminal first.')
                import webbrowser

                def open_consent(url):
                    print(f'Authorize {acct} in a browser on this computer:\n{url}', file=sys.stderr, flush=True)
                    webbrowser.open(url)

                google_api.connect(acct, open_consent)
        except (ValueError, OSError) as e:
            print(f'idli: {e}', file=sys.stderr)
            return 2
    con = rs.connect(sandbox())
    t0 = time.time()
    try:
        if argv[:1] == ['judge']:
            use_models(None, parser().parse_args(argv).judge)
        if argv[:1] == ['ask']:
            a = parser().parse_args(argv)
            use_models(a.mapper, a.judge)
            say(1, f'[models] mapper {a.mapper}, wording {rs.NINE}, judge {rs.JUDGE}; sandbox {sandbox()}')
            sp = _session_path()
            hist = [] if a.new or not sp.exists() else json.loads(sp.read_text())
            MAPPER_CALLS.clear()
            ctx = store_context(con)
            q = ' '.join(a.question)
            global CONFIRM
            resume = None
            m = re.match(r'\s*(yes|y|ok|keep it)\b[\s:,]*(.*)$', q, re.I | re.S)
            if m and hist and hist[-1].get('pending'):  # the yes to the last turn's card
                resume, wording, used = hist[-1]['pending'], m.group(2).strip() or True, []
                q = resume['q']

                def CONFIRM(card):  # yes to the card already shown; a later new meaning stops again
                    if used:
                        return None
                    used.append(1)
                    return wording
            elif m:  # "yes" with no card waiting: nothing to agree to
                print('There’s nothing waiting for confirmation.' if a.output == 'humanize' else
                      'There is nothing waiting for a yes. Ask your question again and I will show you the card.')
                return 0
            elif a.output == 'shell' and sys.stdin.isatty() and sys.stderr.isatty():
                CONFIRM = tty_confirm
            import concurrent.futures as _cf
            _ex = _cf.ThreadPoolExecutor(1)
            kind_f = _ex.submit(classify, q) if a.output == 'shell' and os.environ.get('IDLI_CHIPS', '1') != '0' else None
            rec = ask(con, q, hist, a.mapper, data_dir=sandbox(), show_commands=False, resume=resume, humanize=a.output == 'humanize')
            if a.output == 'humanize' and rec.get('pending'):
                rec['reply'] = rec['pending']['card'] + '\n\nReply “yes” to go ahead, or “yes: …” to change the wording.'
            kind, kind_p = kind_f.result() if kind_f else (None, {})
            why = struggle(rec, hist)
            rec.update(kind=kind, kind_probs=kind_p, struggled=why)
            hist.append({k: rec.get(k) for k in ('q', 'commands', 'shown', 'reply', 'pending', 'clarify_recipient')})
            sp.write_text(json.dumps(hist[-6:], default=str))
            from lib import searchkit as _sk
            log({'verb': 'ask', 'q': rec['q'], 'mapper': a.mapper, 'wording': rs.NINE, 'judge': rs.JUDGE,
                 'new_conversation': a.new, 'earlier': [h['q'] for h in hist[:-1]], 'store': ctx,
                 'mapper_calls': MAPPER_CALLS, 'commands': rec.get('commands'), 'errors': rec.get('errors'),
                 'steps_shown': rec.get('shown'), 'words': rec.get('words'), 'reply': rec['reply'],
                 'wording_dropped': rec.get('compose_fallback'), 'needs': rec.get('needs'),
                 'pending': rec.get('pending'), 'resumed': rec.get('resumed'), 'menu': dict(MENU_INFO),
                 'search_telemetry': dict(_sk.LAST_TELEMETRY),
                 'kind': rec.get('kind'), 'kind_probs': rec.get('kind_probs'), 'struggled': rec.get('struggled'),
                 'menu_miss': menu_miss(con, rec),
                 'seconds': {k: rec.get(k) for k in ('map_s', 'compose_s', 'judge_s', 'total_s')}})
            if a.output == 'humanize':
                print(gmail_account_hint(con, rec['reply']))
                return 0
            line = chips(kind, why)
            if line:
                print(line)
            print(rec['reply'])
            nxt = offer(kind, why, rec)
            if nxt:
                print('\n' + nxt)
            if rec.get('commands'):
                print('\n' + ran_block(rec['commands']))
            return 0
        r = run_argv(con, argv)
        out = r.render(max_rows=50)
        log({'verb': argv[0] if argv else '', 'argv': argv, 'seconds': round(time.time() - t0, 2),
             'output': out[:2000]})
        print(out)
        return 0
    except rs.Stopped as st:  # Ctrl+C during judge: what was judged is kept
        res = {'mail': 'mail', 'event': 'events'}.get(argv[1], argv[1]) if len(argv) > 1 and argv[0] == 'judge' else 'files'
        print('\n' + judge_summary(st.result, st.result['definition'], res), file=sys.stderr)
        log({'verb': 'judge', 'argv': argv, 'stopped': True, 'result': st.result})
        sys.stderr.flush(); sys.stdout.flush()
        con.close()
        os._exit(130)  # don't wait for model calls still in flight
    except KeyboardInterrupt:
        print('\nStopped.', file=sys.stderr)
        con.close()
        os._exit(130)
    except (Err, ValueError) as e:
        print(f'idli: {e}', file=sys.stderr)
        log({'verb': argv[0] if argv else '', 'argv': argv, 'error': str(e)})
        return 2
    finally:
        try:
            con.close()
        except Exception:
            pass


if __name__ == '__main__':
    sys.exit(main())
