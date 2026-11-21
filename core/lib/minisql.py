"""Questions a Mini's saved questions don't cover: an external service writes one SQL query from the masked question
and the column list, and Idli runs it on this computer.

What leaves this computer: the question with private values as codes, the sheet and column names, column types,
number ranges and a few example values of short text columns (as codes when private). Never rows. The query comes
back, Idli checks it is a single read-only SELECT, puts real values back into its string literals and runs it in an
in-memory DuckDB holding the Mini's files, with file access switched off. The service can instead ask back which of
two or three concrete questions was meant (a vague "big trees" becomes "girth over 100 cm" or "the tallest 10%").

The service is any OpenAI-compatible chat endpoint: IDLI_SQL_URL, IDLI_SQL_MODEL, IDLI_SQL_KEY (or the key in
~/.config/idlisseus/openrouter.json for the default endpoint).
"""
import json
import os
from pathlib import Path
import re
import urllib.request

import pandas as pd

from lib import filekit, privacy
from lib.privacy_engine.pseudonymize import TOKEN_RE

URL = os.environ.get('IDLI_SQL_URL', 'https://openrouter.ai/api/v1/chat/completions')
MODEL = os.environ.get('IDLI_SQL_MODEL', 'deepseek/deepseek-v4.1-flash')
MAX_ROWS = 200
# Cost bounds: one call per question (plus one per pick from an ask-back), a short reply, a capped column list and a
# daily limit per computer. Past the limit the person gets the Claude option instead.
MAX_REPLY_TOKENS = 700
MAX_SCHEMA_CHARS = 12000
DAILY_LIMIT = int(os.environ.get('IDLI_SQL_DAILY_LIMIT', '200'))
LIMIT_REACHED = "Today's limit of questions for the query service is used up. Claude can still answer this."
SERVICE = 'an external service'

SYSTEM = """You turn a person's question about their spreadsheets into one DuckDB SQL query.
You get the tables (one per sheet) with column names, types, number ranges and example values. You never see rows.
Private values appear as codes like VALUE_012 or PLACE_003: use them exactly as string literals ('VALUE_012').

Answer with JSON only, one of:
{"sql": "<one SELECT or WITH query>", "title": "<the question, made specific, as a short heading>",
 "note": "<one plain sentence on what the query counts or compares, including any threshold you chose>"}
{"clarify": "<one short question back>", "options": [{"label": "<2 to 5 words>", "question": "<a complete, specific question>"}, ...2 or 3 of these]}

Rules:
- Quote every table and column name with double quotes, exactly as given.
- Only SELECT/WITH. No files, no settings, no other statements.
- Return at most 50 rows; order the result so the answer is at the top. Round decimals to 1 or 2 places.
- Leave out rows where the measured column is blank, and rows that repeat the header.
- If the question is vague in a way that changes the answer (what counts as "big", which sheet, which measure),
  ask back with 2 or 3 options. Each option is a full question with a concrete threshold or choice based on the
  ranges you were given, so it can be answered without asking again. Otherwise just answer.
- Plain words in title, note and options. No jargon."""


def _key():
    if os.environ.get('IDLI_SQL_KEY'):
        return os.environ['IDLI_SQL_KEY']
    path = Path.home() / '.config/idlisseus/openrouter.json'
    return json.loads(path.read_text())['api_key']


def _table_name(sheet, taken):
    base = re.sub(r'[^a-z0-9]+', '_', sheet.casefold()).strip('_') or 'sheet'
    name, n = base, 2
    while name in taken:
        name, n = f'{base}_{n}', n + 1
    taken.add(name)
    return name


def _typed(frame):
    """raw_sheets gives text; make mostly-numeric columns numbers and drop repeated header rows."""
    frame = frame.copy()
    header_rows = frame.apply(lambda r: sum(str(v).strip().casefold() == str(c).strip().casefold()
                                            for c, v in r.items()) >= max(2, len(frame.columns) // 2), axis=1)
    frame = frame[~header_rows]
    for c in frame.columns:
        s = frame[c].replace('', pd.NA)
        num = pd.to_numeric(s, errors='coerce')
        if s.notna().sum() and num.notna().sum() >= .9 * s.notna().sum():
            frame[c] = num
        else:
            frame[c] = s
    return frame.reset_index(drop=True)


def load(data_dir, files, mask=lambda v: v):
    """{table: (sheet label, typed DataFrame of real values)} for the Mini's files. Table names are made from the
    masked sheet names, so a private value in a sheet name never reaches the service."""
    out, taken = {}, set()
    for rel in files:
        sheets, _ = filekit.raw_sheets(str(Path(data_dir) / rel))
        stem = Path(rel).stem
        for sheet, frame in sheets.items():
            label = sheet if len(files) == 1 else f'{stem} / {sheet}'
            out[_table_name(mask(sheet if len(files) == 1 else stem + ' ' + sheet), taken)] = (label, _typed(frame))
    return out


def schema(tables, mask):
    """The column list the service sees. Example values pass through `mask` (codes for private values)."""
    parts = []
    for name, (label, frame) in tables.items():
        lines = [f'Table "{name}" (sheet "{mask(label)}", {len(frame)} rows):']
        for c in frame.columns:
            s = frame[c].dropna()
            if pd.api.types.is_numeric_dtype(frame[c]):
                desc = f'number, {s.min():g} to {s.max():g}' if len(s) else 'number, empty'
            else:
                values = s.astype(str).unique()
                desc = f'text, {len(values)} different values'
                if 0 < len(values) <= 25:
                    desc += ': ' + ', '.join(mask(v) for v in sorted(values)[:25])
            blank = len(frame) - len(s)
            lines.append(f'  "{mask(str(c))}": {desc}' + (f', {blank} blank' if blank else ''))
        parts.append('\n'.join(lines))
    return '\n\n'.join(parts)


def _count_call(data_dir):
    """Count today's calls on this computer; refuse past DAILY_LIMIT."""
    import datetime as dt
    path = Path(data_dir) / '.idli' / 'query-usage.json'
    today = dt.date.today().isoformat()
    try:
        usage = json.loads(path.read_text())
    except (OSError, ValueError):
        usage = {}
    n = usage.get(today, 0)
    if n >= DAILY_LIMIT:
        raise ValueError(LIMIT_REACHED)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({today: n + 1}))


def ask_service(question, schema_text, call=None):
    body = {'model': MODEL, 'temperature': 0, 'max_tokens': MAX_REPLY_TOKENS, 'response_format': {'type': 'json_object'},
            'messages': [{'role': 'system', 'content': SYSTEM},
                         {'role': 'user', 'content': schema_text + '\n\nQuestion: ' + question}]}
    if 'openrouter.ai' in URL:
        body['provider'] = {'data_collection': 'deny'}  # only providers that don't keep or train on the prompt
    if call:
        return call(body)
    req = urllib.request.Request(URL, json.dumps(body).encode(), {
        'Content-Type': 'application/json', 'Authorization': 'Bearer ' + _key(), 'User-Agent': 'idli-minisql/1'})
    with urllib.request.urlopen(req, timeout=60) as r:
        text = json.load(r)['choices'][0]['message']['content']
    text = re.sub(r'^```(?:json)?\s*|\s*```$', '', text.strip())
    return json.loads(text)


FORBIDDEN = re.compile(r'\b(attach|copy|install|load|pragma|export|import|call|set|reset|create|insert|update|delete|'
                       r'drop|alter|checkpoint|vacuum|read_\w+|glob|httpfs|getenv|query_table|query)\b', re.I)


def check_sql(sql):
    import duckdb
    sql = sql.strip().rstrip(';').strip()
    statements = duckdb.extract_statements(sql)
    if len(statements) != 1 or statements[0].type != duckdb.StatementType.SELECT:
        raise ValueError('The query was not a single read-only question.')
    # String literals may hold anything (a species called "load"); check only the code around them.
    if FORBIDDEN.search(re.sub(r'"(?:[^"]|"")*"', '""', re.sub(r"'(?:[^']|'')*'", "''", sql))):
        raise ValueError('The query asked for something other than reading these sheets.')
    return sql


def put_back(sql, vault):
    """Codes inside string literals and quoted column names become real values (quotes doubled for SQL). A column
    heading can hold a private value; the service saw it as a code and names the column by that code."""
    def quoted(m):
        q = m.group()[0]
        return TOKEN_RE.sub(lambda c: vault.display.get(c.group(), c.group()).replace(q, q + q), m.group())
    return re.sub(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"", quoted, sql)


def run(tables, sql):
    import duckdb
    con = duckdb.connect(':memory:')
    try:
        for name, (_, frame) in tables.items():
            con.register(name + '_df', frame)
            con.execute(f'CREATE TABLE "{name}" AS SELECT * FROM "{name}_df"')
            con.unregister(name + '_df')
        con.execute("SET enable_external_access = false")
        con.execute("SET lock_configuration = true")
        return con.execute(f'SELECT * FROM ({sql}) AS answer LIMIT {MAX_ROWS}').df()
    finally:
        con.close()


def prepare(data_dir, files, question):
    """Exactly what would go to the service, built on this computer: the masked question and the column list.
    Shown to the person before anything is sent (preview), then sent unchanged (answer)."""
    with privacy.session_lock(data_dir):
        full = privacy.session_vault(data_dir)
        vault, _ = privacy.proxy_vault(data_dir, full)
        # Known values and validators (phones, IDs) always; from the scanner only what looks like a person or a
        # contact. It tagged "lantana" as a caste category, which hid the very word the question was about.
        scanner = privacy.Scanner()
        def people(text):
            return [s for s in scanner(text) if re.search(r'name|person|address|phone|email', s[2], re.I)]
        masked_q = privacy._redact(question, vault, people)[0]
        from lib import maskcopy
        mask = maskcopy._masker(vault)
        tables = load(data_dir, files, lambda v: mask(str(v)))
        text = schema(tables, lambda v: mask(str(v)))
        if len(text) > MAX_SCHEMA_CHARS:  # a very wide file: column names and types only
            text = re.sub(r'(: text, \d+ different values): [^\n]*', r'\1', text)[:MAX_SCHEMA_CHARS]
    if privacy.known_leaks(masked_q + '\n' + text, vault):
        raise ValueError('A private value was still in the question. Nothing was sent.')
    return {'masked_question': masked_q, 'schema': text, 'tables': tables, 'vault': vault, 'full': full}


def preview(data_dir, files, question, lines=14):
    """For the consent card: the masked question and the first lines of the column list, as the service gets them."""
    p = prepare(data_dir, files, question)
    rows = p['schema'].splitlines()
    # Columns that list their values first (the part that is data, as codes when private), in file order.
    valued = [i for i, r in enumerate(rows) if re.search(r': text, \d+ different values: ', r)]
    pick = sorted(set(valued[:lines]) | set(i for i in range(len(rows)) if rows[i].startswith('Table ')))
    pick = sorted(pick + [i for i in range(len(rows)) if i not in pick][:max(0, lines - len(pick))])
    shown = [rows[i][:160] + ('...' if len(rows[i]) > 160 else '') for i in pick]
    columns = sum(1 for r in rows if r.startswith('  "'))
    return {'masked_question': p['masked_question'], 'sample': '\n'.join(shown),
            'more': max(0, len(rows) - len(shown)), 'columns': columns, 'service': MODEL.split('/')[0]}


def answer(data_dir, files, question, call=None):
    """{'kind': 'table', title, note, frame, sql} or {'kind': 'clarify', text, options}; masked text only leaves."""
    p = prepare(data_dir, files, question)
    masked_q, text, tables, vault, full = p['masked_question'], p['schema'], p['tables'], p['vault'], p['full']
    def real(t):  # codes from the file, plus any the scanner gave to names typed in this question
        return full.rehydrate(vault.rehydrate(str(t)))
    _count_call(data_dir)
    reply = ask_service(masked_q, text, call)
    if reply.get('clarify'):
        options = []
        for o in reply.get('options', [])[:3]:
            o = o if isinstance(o, dict) else {'question': str(o)}
            q = real(o.get('question') or o.get('label') or '')
            if q:
                options.append({'label': real(o.get('label') or q)[:48], 'question': q})
        return {'kind': 'clarify', 'text': real(reply['clarify']), 'options': options,
                'masked_question': masked_q}
    sql = check_sql(str(reply.get('sql', '')))
    frame = run(tables, put_back(put_back(sql, vault), full))
    for c in frame.columns:  # sums come back as 1560.0; show whole numbers as whole numbers
        if pd.api.types.is_float_dtype(frame[c]) and frame[c].dropna().apply(float.is_integer).all():
            frame[c] = frame[c].astype('Int64')
    return {'kind': 'table', 'title': real(reply.get('title') or question),
            'note': real(reply.get('note') or ''), 'frame': frame, 'sql': sql,
            'masked_question': masked_q}
