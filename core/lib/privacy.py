"""Per-file privacy (engine and local review page).

What leaves: the configured HTTP scanner receives column sample windows and only
unmatched question text. Claude receives masked questions, form ids/labels,
masked filter choices and earlier masked question/spec pairs. No rows, answers,
SQL, workbook paths or vault are included in planner prompts. A final local
leak check refuses prompts containing known private values.
What never leaves: the vault and original workbook. Real samples on /privacy are
served only by the authenticated loopback formserver. Scanner failure is reported
as 'regex only'; names/places unknown to the vault may then be missed. Review=ask
is a setting for callers to enforce before invoking plan; plan itself sends.
"""
import builtins
import difflib
from contextlib import contextmanager
import functools
import inspect
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import urllib.request

from . import filekit as fk
from .privacy_engine.columns import classify_columns
from .privacy_engine.detect import regex_engine
from .privacy_engine.pseudonymize import PseudonymMap, TOKEN_RE, normalise, pseudonymise_frame, redact_text

_LOCK = threading.RLock()
_HELD = threading.local()


@contextmanager
def session_lock(data_dir):
    """Serialize vault read/modify/write across the proxy and the form server."""
    import fcntl
    root = Path(data_dir).resolve()
    with _LOCK:
        held = getattr(_HELD, 'roots', frozenset())
        if root in held:
            yield
            return
        folder = root / '.idli'
        folder.mkdir(parents=True, exist_ok=True)
        fd = os.open(folder / 'privacy.lock', os.O_CREAT | os.O_RDWR, 0o600)
        with os.fdopen(fd, 'a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            _HELD.roots = held | {root}
            try:
                yield
            finally:
                _HELD.roots = held


def locked(fn):
    directory = next(iter(inspect.signature(fn).parameters), None) == 'data_dir'
    @functools.wraps(fn)
    def call(*args, **kwargs):
        guard = session_lock(args[0] if args else kwargs['data_dir']) if directory else _LOCK
        with guard:
            return fn(*args, **kwargs)
    return call


def _key(data_dir, file):
    root = Path(data_dir).resolve()
    path = (root / file).resolve()
    if not path.is_relative_to(root) or path == root:
        raise ValueError('File must be inside the data directory')
    return path.relative_to(root).as_posix()


def _write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


@locked
def get(data_dir, file):
    key = _key(data_dir, file)
    path = Path(data_dir) / 'privacy.json'
    saved = json.loads(path.read_text()) if path.exists() else {}
    return {'mode': None, 'review': 'ask', 'columns': {}, **saved.get(key, {})}


@locked
def set(data_dir, file, **changes):
    if changes.keys() - {'mode', 'review', 'columns'}:
        raise ValueError('Unknown privacy setting')
    settings = {**get(data_dir, file), **changes}
    if settings['mode'] not in (None, 'fake', 'mask') or settings['review'] not in ('ask', 'auto'):
        raise ValueError('Invalid mode or review')
    if not isinstance(settings['columns'], dict) or any(
            not isinstance(k, str) or type(v) is not bool for k, v in settings['columns'].items()):
        raise ValueError('Columns must map names to booleans')
    path = Path(data_dir) / 'privacy.json'
    saved = json.loads(path.read_text()) if path.exists() else {}
    saved[_key(data_dir, file)] = settings
    _write(path, saved)
    return settings


def _vault(data_dir, file):
    _key(data_dir, file)  # retain the per-file path validation
    return _session_map(data_dir)


def _session_map(data_dir):
    """One code namespace for the directory, including existing per-file vaults.

    Conflicting legacy codes cannot be safely reinterpreted: refuse migration rather
    than silently restore a tool call to a different person's value.
    """
    path = Path(data_dir) / 'vault' / 'session.json'
    vault = PseudonymMap(path)
    if not path.exists():
        for old in sorted(path.parent.glob('*.json')):
            legacy = PseudonymMap(old)
            for code, real in legacy.display.items():
                key = normalise(real)
                if ((code in vault.display and normalise(vault.display[code]) != key)
                        or (key in vault.forward and vault.forward[key] != code)):
                    raise ValueError('Conflicting legacy vaults; use a new data directory')
                vault.display[code], vault.forward[key] = real, code
            for prefix, count in legacy.counters.items():
                vault.counters[prefix] = max(vault.counters.get(prefix, 0), count)
    return vault


@locked
def session_vault(data_dir):
    """Seed every selected cell in every mask-mode file into the shared vault."""
    vault = _session_map(data_dir)
    path = Path(data_dir) / 'privacy.json'
    settings = json.loads(path.read_text()) if path.exists() else {}
    for file, options in sorted(settings.items()):
        if options.get('mode') != 'mask':
            continue
        key = _key(data_dir, file)
        sheets, _ = fk.raw_sheets(str(Path(data_dir) / key))
        for frame in sheets.values():
            _code_frame(frame, options.get('columns', {}), vault)
    _save(vault)
    return vault


@locked
def active_vault(data_dir, vault=None):
    """Keep stable codes in storage, but stop masking cells explicitly switched off.

    Values still selected in another file/column stay private. Scanner-discovered values
    that are not cells also remain private.
    """
    import copy
    vault = copy.deepcopy(vault or session_vault(data_dir))
    path = Path(data_dir) / 'privacy.json'
    settings = json.loads(path.read_text()) if path.exists() else {}
    active, inactive = builtins.set(), builtins.set()
    for file, options in settings.items():
        if options.get('mode') != 'mask':
            continue
        sheets, _ = fk.raw_sheets(str(Path(data_dir) / _key(data_dir, file)))
        for frame in sheets.values():
            for column in frame.columns:
                dest = active if options.get('mode') == 'mask' and options.get('columns', {}).get(str(column)) else inactive
                dest.update(normalise(str(v)) for v in frame[column] if str(v).strip())
    excluded = inactive - active
    vault.display = {code: real for code, real in vault.display.items() if normalise(real) not in excluded}
    vault.forward = {normalise(real): code for code, real in vault.display.items()}
    vault.refresh()
    return vault


def _save(vault):
    _write(vault.path, {'forward': vault.forward, 'display': vault.display, 'counters': vault.counters})


UNIDENTIFYING = {'age', 'dob', 'date_of_birth', 'date', 'birth_date'}


class Scanner:
    def __init__(self):
        self.status = 'ok'

    def __call__(self, text):
        if self.status != 'ok':
            return []
        # Cloudflare (privacy.idli.cc) refuses Python's default User-Agent with a 403
        headers = {'Content-Type': 'application/json', 'User-Agent': 'idli-privacy/1'}
        token = os.environ.get('IO_PRIVACY_TOKEN')
        if token:
            headers['Authorization'] = 'Bearer ' + token
        req = urllib.request.Request(os.environ.get('IDLI_SCANNER', 'https://privacy.idli.cc/scan'),
                                     json.dumps({'text': text}).encode(), headers)
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                spans = json.load(r)['spans']
            # An age or a date found in running text identifies no one ("All six scripts" was tagged as an age, and
            # today's date as a birth date). Ages and birth dates in a sheet are hidden by their column instead.
            return [(int(a), int(b), str(c), float(d)) for a, b, c, d in spans
                    if 0 <= int(a) < int(b) <= len(text) and float(d) >= .7
                    and str(c).casefold().replace(' ', '_') not in UNIDENTIFYING]
        except (OSError, ValueError, KeyError, TypeError):
            self.status = 'regex only'
            return []


LAND = re.compile(r'(^|_)(species|spp\w*|sp|taxon|genus|plants?|trees?|crops?|birds?|animals?|habit)($|_)')
ABOUT_A_PERSON = re.compile(r'owner|farmer|worker|recorder|collector|observer|surveyor|enumerator|head|member|person|'
                            r'staff|contact')


def _about_land(column):
    """A heading about plants, animals or crops ("Species name expanded"), not about a person who recorded them."""
    c = re.sub(r'[^a-z0-9]+', '_', str(column).casefold()).strip('_')
    return bool(LAND.search(c)) and not ABOUT_A_PERSON.search(c)


def _class(column):
    c = str(column).casefold()
    people = r'beneficiary|employee|(^|_|\s)head($|_|\s)|owner|respondent|farmer|guardian|father|mother|spouse|husband|wife|contact_person'
    if re.search(people, c):
        return 'person_name'
    if _about_land(column):
        return 'value'
    # A district_name or organisation_name is a contextual label, not a person's name.
    if re.search(r'ward|village|town|place|district|block|organi[sz]ation|programme|program|scheme|categor|company|institution|agency', c):
        return 'village'
    for pattern, cls in [(r'name', 'person_name'), (r'address', 'address'),
                         (r'phone|mobile', 'phone'), (r'email', 'email')]:
        if re.search(pattern, c):
            return cls
    return 'value'


def column_class(column, series=None):
    """Reveal policy, independent of the person's masking switches. Unknowns stay personal."""
    c = re.sub(r'[^a-z0-9]+', '_', str(column).casefold()).strip('_')
    if re.search(r'phone|mobile|email|address|aadhaar|aadhar|voter|account|ifsc|upi|(^|_)(pan|ration|bank|id|lat|latitude|lon|lng|longitude|gps|coordinates?)($|_)', c):
        return 'personal'
    # Plants, animals and crops are about the land, not about people ("Species name expanded" is not a person's
    # name), unless the heading is about a person who recorded or owns them.
    if _about_land(column):
        return 'contextual'
    if _class(c) == 'person_name':
        return 'personal'
    if re.search(r'ward|village|district|block|town|place|organi[sz]ation|programme|program|scheme|categor|company|institution|agency', c):
        return 'contextual'
    # This also covers the names backstop. No unrecognised column is revealable.
    return 'personal'


@locked
def code_index(data_dir, vault=None):
    """Derive provenance from source cells in mask-mode files. Any personal use wins across files."""
    vault = vault or session_vault(data_dir)
    path = Path(data_dir) / 'privacy.json'
    settings = json.loads(path.read_text()) if path.exists() else {}
    out, rank = {}, {}
    for file, options in sorted(settings.items()):
        if options.get('mode') != 'mask':
            continue
        sheets, _ = fk.raw_sheets(str(Path(data_dir) / _key(data_dir, file)))
        for frame in sheets.values():
            for column in frame.columns:
                info = {'file': file, 'column': str(column), 'class': column_class(column, frame[column])}
                # A column without a heading (column_22) says nothing about what it holds: a named column decides.
                # Among named columns personal wins.
                named = not re.fullmatch(r'column_\d+|unnamed(: ?\d+)?|\d+', str(column).strip().casefold())
                info['named'] = named
                r = (2 if info['class'] == 'personal' else 1) if named else 0
                heading = normalise(str(column))
                for value in frame[column]:
                    if normalise(str(value)) == heading:
                        continue  # the heading repeated inside the sheet
                    code = vault.forward.get(normalise(str(value)))
                    if code and (code not in out or r > rank[code]):
                        out[code], rank[code] = info, r
    for code, info in list(out.items()):
        # Identifier codes are personal wherever they sit. NAME_ too, except in a column about plants or animals: an
        # older rule coded "Species name expanded" as names. Copy, since one record is shared by a column's codes.
        if (re.match(r'^(PHONE|EMAIL|AADHAAR|PAN|VOTER|RATION|ACCOUNT|IFSC|UPI|ADDRESS|GPS)_', code)
                or (code.startswith('NAME_') and not _about_land(info['column']))):
            out[code] = {**info, 'class': 'personal'}
    return out


@locked
def code_info(data_dir, code):
    vault = session_vault(data_dir)
    if code not in vault.display:
        return None
    info = code_index(data_dir, vault).get(code, {'file': '', 'column': '', 'class': 'personal'})
    return {k: info[k] for k in ('file', 'column', 'class')}


@locked
def reveals(data_dir):
    path = Path(data_dir) / '.idli/reveals.json'
    return json.loads(path.read_text()) if path.exists() else []


@locked
def revealed_values(data_dir, vault=None, index=None):
    vault = vault or session_vault(data_dir)
    index = index if index is not None else code_index(data_dir, vault)
    return {r['code']: vault.display[r['code']] for r in reveals(data_dir)
            if r.get('kind', 'unmask') == 'unmask' and r.get('code') in vault.display
            and index.get(r['code'], {}).get('class') == 'contextual'
            and r.get('value') == vault.display[r['code']]}


def heading_codes(data_dir, vault, index):
    """VALUE_ codes that only ever stood for a hidden column's own heading (or turn up only in columns without one). Older versions coded a header row
    repeated inside the sheet ("sppnam" under sppnam) as a private value, and every heading then reached Claude as a
    code (laptop, 2026-11-15). A code also found in a real cell, or with a name, phone or ID prefix, is kept."""
    path = Path(data_dir) / 'privacy.json'
    settings = json.loads(path.read_text()) if path.exists() else {}
    # (privacy.set is this module's own function, so no set() here)
    headings = {normalise(c) for options in settings.values() if options.get('mode') == 'mask'
                for c, on in options.get('columns', {}).items() if on}
    # Seen elsewhere only in columns without a heading (a side table's own header, a note in a Read me): still a
    # heading word.
    return {c for c, v in vault.display.items()
            if c.startswith('VALUE_') and normalise(v) in headings and not index.get(c, {}).get('named')}


@locked
def proxy_vault(data_dir, full=None):
    """Reveals can exempt contextual values only. Personal values remain guarded even if switched off."""
    full = full or session_vault(data_dir)
    index = code_index(data_dir, full)
    active = active_vault(data_dir, full)
    allowed = revealed_values(data_dir, full, index)
    junk = heading_codes(data_dir, full, index)
    active.display.update({c: v for c, v in full.display.items()
                           if index.get(c, {}).get('class', 'personal') == 'personal' and c not in junk})
    active.display = {c: v for c, v in active.display.items() if c not in allowed and c not in junk}
    active.forward = {normalise(v): c for c, v in active.display.items()}
    active.refresh()
    return active, allowed


def _frame(path, tab):
    sheets, _ = fk.raw_sheets(str(path))
    tab = tab or next(iter(sheets))
    if tab not in sheets:
        raise ValueError('Unknown workbook tab')
    return sheets[tab]


def _code_frame(frame, columns, vault):
    # Explicit choices always code the entire cell, including numbers, dates and GPS.
    classes = {c: _class(c) for c in frame.columns if columns.get(str(c), False)}
    # A header repeated inside the sheet ("sppnam" in the sppnam column) is the column's name, not a private value.
    repeats = {}
    for c in classes:
        hit = frame[c].astype(str).map(normalise) == normalise(str(c))
        if hit.any():
            repeats[c] = hit
    if repeats:
        frame = frame.copy()
        for c, hit in repeats.items():
            frame.loc[hit, c] = ''
    result = pseudonymise_frame(frame, classes, vault)
    for c, hit in repeats.items():
        result.loc[hit, c] = str(c)
    return result


ID_HEADING = re.compile(r'\b(id|ids|phone|mobile|contact|aadha?r|pan|account|acct|ifsc|pin|pincode|no|number|ration|voter|card)\b|_id\b', re.I)


NAME_LIKE = re.compile(r"^[A-Z][a-z'.-]+(?: [A-Z][a-z'.-]*){1,3}$")


def _looks_like_names(series):
    """A backstop when the name scanner can't be reached: most values are two to four capitalised words."""
    values = [str(v).strip() for v in series.head(200) if str(v).strip() not in ('', 'nan', 'None')]
    if len(values) < 3:
        return False
    return sum(bool(NAME_LIKE.match(v)) for v in values) / len(values) >= .6


_SUGGESTED = {}
_SUGGEST_CACHE = Path.home() / '.cache' / 'idli' / 'suggest'


def suggest(path, tab):
    """Column suggestions, cached per file version and tab (scanning every column takes seconds). Only answers from
    a reachable scanner are kept, so a scanner outage is never remembered. The cache stays on this computer (0600)."""
    import hashlib
    try:
        st = os.stat(path)
        key = hashlib.sha256(f'{os.path.realpath(path)}|{st.st_mtime_ns}|{st.st_size}|{tab}'.encode()).hexdigest()
    except OSError:
        return _suggest(path, tab)
    if key in _SUGGESTED:
        return json.loads(_SUGGESTED[key])
    disk = _SUGGEST_CACHE / (key + '.json')
    try:
        rows = json.loads(disk.read_text())
        _SUGGESTED[key] = json.dumps(rows)
        return rows
    except (OSError, ValueError):
        pass
    rows = _suggest(path, tab)
    if not any('scanner unavailable' in r.get('reason', '') for r in rows):
        _SUGGESTED[key] = json.dumps(rows)
        try:
            _SUGGEST_CACHE.mkdir(parents=True, exist_ok=True, mode=0o700)
            fd = os.open(disk, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, 'w') as f:
                f.write(_SUGGESTED[key])
        except OSError:
            pass
    return rows


@locked
def _suggest(path, tab):
    frame = _frame(path, tab)
    scanner = Scanner()
    classes = classify_columns(frame, scanner)
    vault = PseudonymMap()
    choices, reasons = {}, {}
    for c in frame.columns:
        info = classes[str(c)]
        mask = info['class'] not in ('none', 'age', 'record_id_non_pii')
        reason = info['rule']
        if info['rule'] in ('no-model', 'span-coverage', 'categorical') and _class(c) != 'value':
            mask, reason = True, 'identifier column heading'
        values = frame[c].replace('', None).dropna()
        import pandas as pd
        numbers = pd.to_numeric(values, errors='coerce')
        if len(values) and numbers.notna().mean() >= .95:
            if re.search(r'income|amount|salary|revenue|expense|price|cost|balance', str(c), re.I):
                mask, reason = False, 'numeric measure'
            elif ID_HEADING.search(str(c)):
                mask, reason = True, 'identifier column heading'
            elif (
                  not any(matched_in_text(str(v)) for v in values.astype(str).head(500))):
                mask, reason = False, 'counts or measures (small numbers)'
        if not mask and _looks_like_names(frame[c]):
            mask, reason = True, 'looks like people\'s names'
        choices[str(c)] = mask
        reasons[str(c)] = reason
    coded = _code_frame(frame, choices, vault)
    return [{'column': str(c), 'mask': choices[str(c)],
             'reason': reasons[str(c)] + ('; scanner unavailable — regex only' if scanner.status != 'ok' else ''),
             'samples': frame[c].head(3).astype(str).tolist(),
             'as_sent': coded[c].head(3).astype(str).tolist()} for c in frame.columns]


@locked
def masked_frame(data_dir, file, path, tab):
    vault = _vault(data_dir, file)
    frame = _code_frame(_frame(path, tab), get(data_dir, file)['columns'], vault)
    _save(vault)
    return frame


@locked
def _seed(data_dir, file, path):
    # All chosen cells, across tabs, before matching any question (not just samples).
    vault = _vault(data_dir, file)
    sheets, _ = fk.raw_sheets(str(path))
    for frame in sheets.values():
        _code_frame(frame, get(data_dir, file)['columns'], vault)
    _save(vault)
    return vault


SEP = r'(?:\s+|_|\+|-|%20)'
URL = re.compile(r'https?://[^\s"\'<>)\]\\]+')
# The product's own words are never private, even if a scanner tags them (a tool named mcp__idli__idli_show went out
# as mcp__NAME_032__NAME_032_show on the DGX, 2026-11-15).
NEVER_PRIVATE = {'idli', 'claude', 'drivey', 'paseo', 'mini', 'minis', 'anthropic', 'codex'}


def matched_in_text(value):
    """Whether a known value is looked for in free text (messages, scripts, script output, other cells).

    A short number (up to three digits, like 6, 52 or 4.5) is not: it is common, says nothing about a person on its
    own, and masking it everywhere turns counts into codes, so Claude can't read its own results. Numbers with four or
    more digits (amounts, phones, Aadhaar, PIN codes) and precise decimals (GPS: four or more places) still are. Cells
    of a column the person chose to hide are coded whatever they hold."""
    v = value.strip()
    if not v or v.casefold() in NEVER_PRIVATE:
        return False
    if re.fullmatch(r'(?:19|20)\d\d', v):  # a year (1990, 2005) says nothing about a person
        return False
    v = re.sub(r'\s*%$', '', v)  # a percentage counts like its number: 92.6% is as common as 92.6
    m = re.fullmatch(r'[+-]?(\d+)(?:\.(\d+))?', v)
    if not m:
        return True
    return len(m[1]) + len(m[2] or '') >= 4 or len(m[2] or '') >= 4


def _value_pattern(value):
    """A known value as a whole word; decimals also with trailing zeros (73.7354 printed as 73.73540)."""
    if re.fullmatch(r'[+-]?\d+(?:\.\d+)?', value):
        return r'(?<![\w.])' + re.escape(value) + ('0*' if '.' in value else '') + r'(?!\w|\.\d)'
    return r'(?<!\w)' + re.escape(value) + r'(?!\w)'


def _url_pattern(value):
    """Inside a web link a value can be joined by _ + - or %20 (/wiki/Satpur_Kamil): DGX wire audit 2026-11-15."""
    if re.fullmatch(r'[+-]?\d+(?:\.\d+)?', value):
        return _value_pattern(value)
    return r'(?<![^\W_])' + SEP.join(re.escape(part) for part in value.split()) + r'(?![^\W_])'


def _code_for(vault, found):
    """The code for a matched variant of a known value."""
    for key in (found, re.sub(SEP, ' ', found), found.rstrip('0').rstrip('.') if re.fullmatch(r'[+-]?\d+\.\d+', found) else None):
        if key is not None and normalise(key) in vault.forward:
            return vault.forward[normalise(key)]
    target = normalise(re.sub(SEP, ' ', found))
    for code, real in vault.display.items():
        if normalise(re.sub(SEP, ' ', real)) == target:
            return code
    raise KeyError(found)


def _known(text, vault):
    # Long numbers count, short plain numbers don't (matched_in_text); never match numbers inside code suffixes.
    values = sorted((v for v in vault.display.values() if matched_in_text(v)), key=len, reverse=True)
    if not values:
        return text, []
    pattern = re.compile('|'.join(_value_pattern(v) for v in values), re.I)
    in_url = re.compile('|'.join(_url_pattern(v) for v in values), re.I)
    found = []
    def sub(m):
        code = _code_for(vault, m.group())
        found.append({'real': m.group(), 'code': code, 'why': 'known value'})
        return code
    text = URL.sub(lambda u: in_url.sub(sub, u.group()), text)
    return pattern.sub(sub, text), found


GENERIC = {'ward', 'village', 'block', 'district', 'taluka', 'taluk', 'gram', 'nagar', 'colony', 'area', 'zone',
           'the', 'of'}


def _cores(vault):
    """Each known value, plus its distinctive part ('Yerawada Ward' -> 'Yerawada'), so a question that names a place
    the short way gets the same code as the file's value instead of a new one."""
    out = []
    for code, real in vault.display.items():
        out.append((code, real))
        core = ' '.join(w for w in re.findall(r'[^\W\d_]+', real) if w.casefold() not in GENERIC)
        if core and core.casefold() != real.casefold():
            out.append((code, core))
    return out


def _redact(text, vault, scanner):
    text, found = _known(text, vault)
    # Conservative edit-distance match against known words/phrases only; unique winner.
    words = list(re.finditer(r'\b[^\W\d_]+(?:[\s-]+[^\W\d_]+)*\b', text))
    spans = []
    for m in words:
        tokens = list(re.finditer(r'[^\W\d_]+', m.group()))
        for i in range(len(tokens)):
            for n in range(1, min(5, len(tokens) - i) + 1):
                a, b = m.start() + tokens[i].start(), m.start() + tokens[i+n-1].end()
                fragment = text[a:b]
                if len(fragment) < 5:
                    continue
                matches = []
                for code, real in _cores(vault):
                    if len(real) < 5 or abs(len(real) - len(fragment)) > 2:
                        continue
                    if not matched_in_text(real) or fragment.casefold() in NEVER_PRIVATE:
                        continue  # "claude" in Claude's own folder path became NAME_007-masked (laptop, 2026-11-15)
                    ratio = difflib.SequenceMatcher(None, fragment.casefold(), real.casefold()).ratio()
                    if ratio >= .85 and code not in [c for c, _ in matches]:
                        matches.append((code, real))
                if len(matches) == 1:
                    spans.append((a, b, *matches[0]))
    end = -1
    selected = []
    for a, b, code, real in sorted(spans, key=lambda x: (x[0], -(x[1]-x[0]))):
        if a >= end:
            selected.append((a, b, code))
            found.append({'real': text[a:b], 'code': code, 'why': 'close known value'})
            end = b
    for a, b, code in reversed(selected):
        text = text[:a] + code + text[b:]
    kept = {v.strip().casefold() for v in vault.display.values() if not matched_in_text(v)}
    text, events = redact_text(text, vault, regex_engine, kept=kept)
    found += [{'real': e['text'], 'code': e['token'], 'why': 'regex validator'} for e in events]
    # The scanner gets only the remaining text: blank out existing codes first.
    remaining = TOKEN_RE.sub(lambda m: ' ' * len(m.group()), text)
    spans = [s for s in scanner(remaining) if remaining[s[0]:s[1]].strip().casefold() not in NEVER_PRIVATE]
    text, events = redact_text(text, vault, lambda _: spans, kept=kept)
    found += [{'real': e['text'], 'code': e['token'], 'why': 'scanner'} for e in events]
    return text, found


@locked
def mask_text(data_dir, file, path, text, active=False):
    full = _seed(data_dir, file, path)
    vault = active_vault(data_dir, full) if active else full
    scanner = Scanner()
    masked, found = _redact(str(text), vault, scanner)
    if active:
        full.forward.update(vault.forward)
        full.display.update(vault.display)
        full.counters.update(vault.counters)
        _save(full)
    else:
        _save(vault)
    return {'masked': masked, 'found': found, 'scanner': scanner.status}


@locked
def unmask(data_dir, file, obj):
    vault = _vault(data_dir, file)
    def restore(v):
        if isinstance(v, str):
            return vault.rehydrate(v)
        if isinstance(v, list):
            return [restore(x) for x in v]
        if isinstance(v, dict):
            return {restore(k): restore(x) for k, x in v.items()}
        return v
    return restore(obj)


@locked
def leak_check(data_dir, file, outgoing):
    return known_leaks(outgoing, _vault(data_dir, file))


def known_leaks(outgoing, vault):
    # Decode JSON escapes as well, and remove codes so e.g. a masked '001' doesn't
    # match inside NAME_001. Fail closed for known values in labels or instructions.
    text = TOKEN_RE.sub('', outgoing)
    text = re.sub(r'\\u([0-9a-fA-F]{4})', lambda m: chr(int(m[1], 16)), text)
    urls = ' '.join(URL.findall(text))
    return [v for v in vault.display.values() if matched_in_text(v)
            and (re.search(_value_pattern(v), text, re.I) or re.search(_url_pattern(v), urls, re.I))]


def _shape(form, spec):
    if not isinstance(spec, dict):
        return 'Spec must be an object.'
    for key, available in [('measures', form['_measures']),
                           ('group_by', {g['id']: g for g in form['group_by']})]:
        vals = spec.get(key, [])
        if not isinstance(vals, list) or any(not isinstance(v, str) or v not in available for v in vals):
            return 'Invalid ' + key + ' ids or shape.'
    try:
        from . import formkit
        formkit.compile_spec(form, '_privacy_shape_check', spec)
    except Exception:
        return 'Invalid filter or preset shape.'
    return None


def _planner_env():
    """The person's own Claude, not Idli's: Idli's tools run with Idli's Claude config (CLAUDE_CONFIG_DIR, a base URL
    pointing at the private model), which would quietly send the 'Claude' plan to the private model instead."""
    return {k: v for k, v in os.environ.items()
            if k not in ('CLAUDE_CONFIG_DIR', 'ANTHROPIC_BASE_URL', 'ANTHROPIC_AUTH_TOKEN', 'ANTHROPIC_MODEL',
                         'ANTHROPIC_DEFAULT_HAIKU_MODEL', 'ANTHROPIC_DEFAULT_SONNET_MODEL',
                         'ANTHROPIC_DEFAULT_OPUS_MODEL', 'ANTHROPIC_SMALL_FAST_MODEL', 'CLAUDECODE')
            and not k.startswith('PASEO_')}


def _claude(prompt):
    with tempfile.TemporaryDirectory() as cwd:
        r = subprocess.run(['claude', '-p', prompt, '--model', os.environ.get('IDLI_PLANNER_MODEL', 'haiku'),
                            '--output-format', 'json', '--tools=', '--strict-mcp-config', '--mcp-config',
                            '{"mcpServers":{}}', '--setting-sources', ''],
                           cwd=cwd, capture_output=True, text=True, timeout=300, stdin=subprocess.DEVNULL,
                           env=_planner_env())
    if r.returncode:
        raise ValueError('Planner process failed')
    envelope = json.loads(r.stdout)
    if envelope.get('is_error'):
        raise ValueError('Planner returned an error')
    raw = envelope.get('result', '')
    match = re.search(r'\{.*\}', raw, re.S)
    return json.loads(match.group() if match else raw)


@locked
def plan(data_dir, file, path, tab, form, question, history, instructions=None):
    sent = ''
    attempts = []
    try:
        if get(data_dir, file)['mode'] != 'mask':
            raise ValueError('Choose mask mode before planning')
        vault = _seed(data_dir, file, path)
        scanner = Scanner()
        # Whitelist form metadata: no summary, SQL, numeric extrema, rows or answers.
        brief = {'measures': [{'id': k, 'label': v['label']} for k, v in form['_measures'].items()],
                 'group_by': [{k: g[k] for k in ('id', 'label')} for g in form['group_by']],
                 'filters': [{k: f[k] for k in ('column', 'label', 'kind', 'values') if k in f}
                             for f in form['filters']],
                 'columns': [{'id': k, 'label': (v.get('label') if isinstance(v, dict) else None) or k}
                             for k, v in (form.get('_kinds') or {}).items()],
                 'presets': [{k: p[k] for k in ('id', 'label') if k in p} for p in form.get('presets') or []]}
        thread = [{'question': h.get('question', h.get('q', '')), 'spec': h.get('spec', {})}
                  for h in (history or [])[-6:]]
        payload = {'form': brief, 'question': question, 'history': thread}
        # Preserve JSON types/structure; redact string leaves, including labels and ids.
        def clean(v):
            if isinstance(v, str):
                return _redact(v, vault, scanner)[0]
            if isinstance(v, list):
                return [clean(x) for x in v]
            if isinstance(v, dict):
                return {clean(k): clean(x) for k, x in v.items()}
            # Numeric literals in earlier specs may themselves be masked income values.
            if v is not None and normalise(str(v)) in vault.forward:
                return vault.forward[normalise(str(v))]
            return v
        payload = clean(payload)
        _save(vault)
        if instructions:
            prompt = instructions + '\n' + json.dumps(payload, ensure_ascii=False)
        else:
          prompt = ('Plan a local form query. Return JSON {"spec":{"measures":[ids],"group_by":[ids],'
                  '"filters":{column:[values]}}} or {"cannot":"reason"}. Use only supplied ids. '
                  'Keep codes exactly. Choice filters use lists or {"not":[values]}; number/date filters '
                  'use {"min":value,"max":value}; contains filters use strings. Never invent SQL.\n'
                  + json.dumps(payload, ensure_ascii=False))
        for attempt in range(2):
            if leak_check(data_dir, file, prompt):
                return {'spec': None, 'sent': sent, 'error': 'Refused: private values remain in the prompt'}
            sent = prompt  # on retry this is the exact final prompt; sent_attempts records both
            attempts.append(sent)
            got = _claude(sent)
            if got.get('cannot'):
                return {'spec': None, 'sent': sent, 'sent_attempts': attempts, 'error': 'Planner cannot express this question',
                        'why': unmask(data_dir, file, str(got['cannot']))[:300]}
            spec = unmask(data_dir, file, got.get('spec'))
            error = _shape(form, spec)
            if not error:
                return {'spec': spec, 'sent': sent, 'sent_attempts': attempts, 'error': None, 'scanner': scanner.status,
                        'note': str(got['note'])[:300] if got.get('note') else None}
            # One backtrack with a fixed shape-only message; never return local errors/data.
            prompt += ('\nPrevious spec: ' + json.dumps(got.get('spec'), ensure_ascii=False)
                       + '\nThe previous plan had an invalid shape: ' + error + ' Return a repaired JSON plan.')
        return {'spec': None, 'sent': sent, 'sent_attempts': attempts, 'error': error}
    except Exception as exc:
        return {'spec': None, 'sent': sent, 'error': 'Planner failed: ' + type(exc).__name__}


@locked
def review(data_dir, file, path, tab=None, columns=None):
    """Local-only preview, using the same stable vault and full-cell coding as export."""
    sheets, _ = fk.raw_sheets(str(path))
    tab = tab or next(iter(sheets))
    rows = suggest(path, tab)
    settings = get(data_dir, file)
    choices = {r['column']: settings['columns'].get(r['column'], r['mask']) for r in rows}
    if columns is not None:
        if not isinstance(columns, dict) or any(type(v) is not bool for v in columns.values()):
            raise ValueError('Columns must map names to booleans')
        choices.update(columns)
    vault = _vault(data_dir, file)
    coded = None
    for name, frame in sheets.items():
        preview = _code_frame(frame, choices, vault)
        if name == tab:
            coded = preview
    frame = sheets[tab]
    for row in rows:
        row['mask'] = choices[row['column']]
        # Show rows that hold something (a notes column is often blank at the top), and say when every cell is
        # blank or coded away: the page writes "<column> entirely withheld" (owner, 2026-11-18).
        col = row['column'] if row['column'] in coded.columns else next(
            (c for c in coded.columns if str(c) == row['column']), None)
        if col is None:
            row['as_sent'] = []
            continue
        filled = frame[col].astype(str).str.strip().replace({'nan': '', 'None': ''}) != '' if col in frame.columns \
            else coded[col].astype(str).str.strip() != ''
        idx = list(filled[filled].index[:3]) or list(coded.index[:3])
        row['samples'] = frame.loc[idx, col].astype(str).tolist() if col in frame.columns else row['samples']
        row['as_sent'] = coded.loc[idx, col].astype(str).tolist()
        # Whole cells of text (notes, remarks) each turned into one code: Claude gets none of it.
        whole = [a for a, b in zip(row['samples'], row['as_sent']) if a.strip() and len(a.split()) > 3 and
                 re.fullmatch(r'[A-Z][A-Z_]*_\d+', b.strip() or 'x')]
        row['withheld'] = bool(row['mask'] and (not filled.any() or whole and len(whole) == len(
            [a for a in row['samples'] if a.strip()])))
    return {**settings, 'columns': choices, 'tabs': list(sheets), 'tab': tab, 'suggestions': rows, 'warning': review_warning(data_dir)}


@locked
def review_warning(data_dir, files=None):
    """Count the mask-mode files in this question (or the proxy's active file set)."""
    path = Path(data_dir) / 'privacy.json'
    settings = json.loads(path.read_text()) if path.exists() else {}
    state = Path(data_dir) / '.idli/home.json'
    if files is None and state.exists():
        selected = json.loads(state.read_text()).get('files')
        if selected:
            files = [item['local'] for item in selected]
    chosen = builtins.set(files) if files is not None else builtins.set(settings)
    masked = [v for k, v in settings.items() if k in chosen and v.get('mode') == 'mask']
    if len(masked) > 10 and any(v.get('review', 'ask') == 'ask' for v in masked):
        return f'{len(masked)} files are masked for this question. Reviewing each one may take time. Consider switching review to Auto.'
    return ''


@locked
def mask_free_text(data_dir, text):
    """Mask text that isn't tied to one file (a request for the Builder) with this folder's known values, the regex
    rules and the name scanner. New codes are not saved: nothing else needs them back."""
    vault = active_vault(data_dir, _session_map(data_dir))
    masked, _ = _redact(str(text), vault, Scanner())
    return masked


def mask_account_text(data_dir, text):
    """Account content (an email, a calendar entry, a sheet row) for a sandbox's Claude: masked with this folder's
    known values, the regex rules and the name scanner, and the new codes saved, so Claude's replies show the person
    the real values again (narrative/SANDBOXES.md)."""
    full = _session_map(data_dir)
    vault = active_vault(data_dir, full)
    masked, _ = _redact(str(text), vault, Scanner())
    full.forward.update(vault.forward)
    full.display.update(vault.display)
    full.counters.update(vault.counters)
    _save(full)
    return masked

