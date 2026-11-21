"""File skills: how Idli recognises a spreadsheet it has been taught, and how it asks to be taught one.

A *file skill* lives in `file-skills/<id>/skill.json`. It is data, not code: what the columns mean,
how to clean them, which validations to run, and one parameterised DuckDB query per question taught.
Claude writes it in the Teach workspace from a mock of the file (junk values, same structure); Idli
runs it on the real file. Idli never computes numbers itself: every number comes from a query here.

Pieces:
  fingerprint / match   - recognise a file by its header set, whatever its name
  make_mock             - same sheets, headers, formats, blanks and messiness; every value junk;
                          plus a hidden `_idli_teach` sheet (the watermark Claude's teach-file skill reads)
  build_tables          - raw table (all text) + cleaned table (`skill.normalize`) in DuckDB
  check                 - run `skill.validations`, return problems, write "<name> - checked.xlsx"
  answer                - run a taught question with parameters

CLI (for the Teach workspace):
  python -m lib.filekit inspect <file>                 columns, types and messiness of a file or mock
  python -m lib.filekit test <skill_dir> [<mock>]      run the skill's tests.json against a mock
"""
import datetime as dt
import hashlib
import json
import os
import random
import re
import string
import sys

import pandas as pd

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILLS_DIR = os.environ.get("IDLI_FILE_SKILLS") or os.path.join(HERE, "file-skills")
TEACH_DIR = os.environ.get("IDLI_TEACH_DIR") or os.path.join(HERE, "teach", "inbox")
WATERMARK = "_idli_teach"


def slug(s):
    return re.sub(r"[^a-z0-9]+", "_", str(s).strip().lower()).strip("_") or "x"


# ---------------------------------------------------------------- reading
def raw_sheets(path):
    """{sheet: DataFrame of strings, header row applied}, plus {sheet: header_row_number (1-based)}."""
    if path.lower().endswith(".csv"):
        frames = {"csv": pd.read_csv(path, header=None, dtype=str, keep_default_na=False)}
    else:
        frames = pd.read_excel(path, sheet_name=None, header=None, dtype=object)
    out, hdr = {}, {}
    for name, df in frames.items():
        if name == WATERMARK:
            continue
        df = df.map(lambda v: "" if v is None or (isinstance(v, float) and pd.isna(v)) else _cell_text(v))
        df = df.loc[~(df == "").all(axis=1), ~(df == "").all(axis=0)]
        if df.empty:
            continue
        h = _header_index(df)
        header = [str(v).strip() or f"column_{j + 1}" for j, v in enumerate(df.iloc[h])]
        body = df.iloc[h + 1:]
        rows = [int(ix) + 1 for ix in body.index]  # real spreadsheet rows (blank rows were dropped above)
        cols = [int(c) for c in df.columns]        # real spreadsheet columns, 0 = A (blank columns dropped)
        body = body.reset_index(drop=True)
        body.columns = _unique(header)
        body.attrs["sheet_rows"], body.attrs["sheet_cols"] = rows, cols
        out[name] = body
        hdr[name] = int(df.index[h]) + 1
    return out, hdr


def sheet_row(df, i, header_row):
    """The spreadsheet row of data row i (blank rows in the sheet count, as people see them)."""
    rows = df.attrs.get("sheet_rows")
    return rows[i] if rows and i < len(rows) else header_row + 1 + i


def cell_ref(df, i, col, header_row):
    """'D54'-style address of data row i, column `col`, in the original sheet."""
    from openpyxl.utils import get_column_letter
    cols = df.attrs.get("sheet_cols")
    j = list(df.columns).index(col)
    return f"{get_column_letter((cols[j] if cols and j < len(cols) else j) + 1)}{sheet_row(df, i, header_row)}"


def _cell_text(v):
    if isinstance(v, (dt.datetime, dt.date, pd.Timestamp)):
        return v.strftime("%d/%m/%Y")
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def _unique(names):
    seen, out = {}, []
    for n in names:
        seen[n] = seen.get(n, 0) + 1
        out.append(n if seen[n] == 1 else f"{n} ({seen[n]})")
    return out


def _header_index(df):
    width = (df != "").sum(axis=1).max()
    for i, (_, row) in enumerate(df.iterrows()):
        vals = [v for v in row if v != ""]
        texts = [v for v in vals if not re.fullmatch(r"[\d.,/ :-]+", v)]
        if len(vals) >= max(2, 0.6 * width) and len(texts) >= 0.8 * len(vals):
            return i
    return 0


def main_sheet(sheets):
    return max(sheets, key=lambda s: len(sheets[s]) * max(1, sheets[s].shape[1]))


# ---------------------------------------------------------------- recognising a file
def header_set(df):
    """Slugged headers, ignoring the 'Check: ...' columns Idli adds to a '- checked' copy."""
    return sorted(slug(c) for c in df.columns if not str(c).lower().startswith("check:"))


def fingerprint(df):
    return hashlib.sha1("|".join(header_set(df)).encode()).hexdigest()[:10]


def load_skills():
    out = []
    if not os.path.isdir(SKILLS_DIR):
        return out
    for d in sorted(os.listdir(SKILLS_DIR)):
        p = os.path.join(SKILLS_DIR, d, "skill.json")
        try:
            with open(p) as f:
                s = json.load(f)
            s["_dir"] = os.path.dirname(p)
            out.append(s)
        except (OSError, ValueError):
            continue
    return out


def _overlap(a, b):
    """Share of headers that correspond, counting 'title_row_volunteer_name' ~ 'volunteer_name'."""
    hit, used = 0, set()
    for x in a:
        y = next((y for y in b if y not in used and (y == x or x.endswith("_" + y) or y.endswith("_" + x))), None)
        if y:
            hit += 1
            used.add(y)
    return hit / len(a | b - used) if (a or b) else 0.0


def match(df):
    """Best skill for this table: same header set (>= 80% overlap), whatever the file is called."""
    have = set(header_set(df))
    best, score = None, 0.0
    for s in load_skills():
        want = set(s.get("headers") or [])
        if not want:
            continue
        j = _overlap(have, want)
        if j > score:
            best, score = s, j
    return (best, round(score, 2)) if score >= 0.8 else (None, round(score, 2))


# ---------------------------------------------------------------- column kinds (for mocks and hints)
DATE_FORMATS = ["%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%y", "%m/%d/%Y", "%d %b %Y", "%d-%b-%Y", "%b %Y"]
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
PHONE = re.compile(r"^(\+?91[-\s]?)?[6-9]\d{4}[-\s]?\d{5}$")


def as_number(v):
    t = re.sub(r"(?i)(rs\.?|inr|₹|,|\s)", "", str(v))
    try:
        return float(t)
    except ValueError:
        return None


def date_format(vals):
    best, hits = None, 0
    for fmt in DATE_FORMATS:
        n = 0
        for v in vals:
            try:
                dt.datetime.strptime(v, fmt)
                n += 1
            except ValueError:
                pass
        if n > hits:
            best, hits = fmt, n
    return best, hits


def classify(series):
    vals = [v for v in series if v != ""]
    n = len(vals)
    info = {"blank": len(series) - n, "distinct": len(set(vals))}
    if not n:
        return {"kind": "empty", **info}
    fmt, hits = date_format(vals[:400])
    if hits >= 0.6 * min(n, 400):
        return {"kind": "date", "format": fmt, "bad": n - sum(1 for v in vals if _parses(v, fmt)), **info}
    emails = sum(1 for v in vals if EMAIL.match(v))
    if emails >= 0.6 * n:
        return {"kind": "email", "bad": n - emails, **info}
    phones = sum(1 for v in vals if PHONE.match(re.sub(r"[\s-]", "", v)) or PHONE.match(v))
    if phones >= 0.6 * n:
        return {"kind": "phone", "bad": n - phones, **info}
    nums = [as_number(v) for v in vals]
    good = [x for x in nums if x is not None]
    if len(good) >= 0.8 * n:
        styled = sum(1 for v in vals if re.search(r"(?i)rs|inr|₹|,", v))
        return {"kind": "number", "bad": n - len(good), "min": min(good), "max": max(good),
                "decimals": max((len(v.split(".")[1]) for v in vals if re.fullmatch(r"-?\d+\.\d+", v)), default=0),
                "styled": styled, **info}
    if info["distinct"] <= max(12, 0.2 * n):
        return {"kind": "category", **info}
    avg = sum(len(v) for v in vals) / n
    return {"kind": "longtext" if avg > 40 else "text", "avg_len": round(avg), **info}


def _parses(v, fmt):
    try:
        dt.datetime.strptime(v, fmt)
        return True
    except ValueError:
        return False


def _not_future(v, fmts):
    """True unless v parses (in one of fmts) to a date after today. Unparseable is left to the 'date' rule."""
    for f in fmts or ["%d/%m/%Y"]:
        try:
            return dt.datetime.strptime(v, f).date() <= dt.date.today()
        except ValueError:
            pass
    return True


# ---------------------------------------------------------------- mocks
WORDS = ("lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod tempor incididunt ut labore "
         "et dolore magna aliqua enim ad minim veniam quis nostrud").split()


def _variant(fake, real):
    """Give the fake value the real value's casing ('pune' -> 'district b', 'SATARA' -> 'DISTRICT C')."""
    if real.islower():
        return fake.lower()
    if real.isupper():
        return fake.upper()
    return fake


def _geo_kind(header, lo, hi):
    """'lat' / 'lon' for a coordinate column (by its name, within the valid range), else None."""
    h = re.sub(r"[^a-z]", " ", str(header).lower())
    if re.search(r"\b(lat|latitude|gps lat)\b", h) and -90 <= lo <= hi <= 90:
        return "lat"
    if re.search(r"\b(lon|lng|long|longitude|gps lon)\b", h) and -180 <= lo <= hi <= 180:
        return "lon"
    return None


def mock_column(series, header, rnd, keep_labels=False, shared=None):
    """`shared` maps a real value to its fake across every column and tab, so a name in Visits and the same
    name in Officers get the same fake, and lookups between tabs still join in the mock."""
    shared = {} if shared is None else shared
    info = classify(series)
    kind, out = info["kind"], []
    vals = list(series)
    real_variants = _variant_groups(vals) if kind == "category" else {}
    fixed = {}  # per ID length: positions where every ID has the same character (prefixes such as "T" or "R-2025-")
    for L in {len(str(v).strip()) for v in vals if _id_like(v)}:
        same = [str(v).strip() for v in vals if _id_like(v) and len(str(v).strip()) == L]
        if len(same) >= 3:
            fixed[L] = {i: c for i, c in enumerate(same[0]) if all(x[i] == c for x in same)}
    if kind == "date":  # fake dates stay inside the real column's range (no invented future dates)
        fmts = [info["format"]] + [f for f in DATE_FORMATS if f != info["format"]]
        ds = [dt.datetime.strptime(v, f).date() for v in vals if v for f in [next((f for f in fmts if _parses(v, f)), None)] if f]
        lo_d, hi_d = (min(ds), max(ds)) if ds else (dt.date(2026, 1, 1), dt.date(2026, 6, 30))
    cats = {}
    for i, v in enumerate(vals):
        if v == "":
            out.append("")
            continue
        if kind == "date":
            if _parses(v, info["format"]):
                d = lo_d + dt.timedelta(days=rnd.randint(0, max(0, (hi_d - lo_d).days)))
                out.append(d.strftime(info["format"]))
            else:  # another date format keeps its format (mixed formats are a real-world quirk); junk stays junk
                other = next((f for f in DATE_FORMATS if _parses(v, f)), None)
                d = lo_d + dt.timedelta(days=rnd.randint(0, max(0, (hi_d - lo_d).days)))
                out.append(d.strftime(other) if other else rnd.choice(["TBD", "31/02/2026", "next week", "2026"]))
        elif kind == "number":
            x = as_number(v)
            if x is None:
                out.append(rnd.choice(["n/a", "-", "approx 500", "pending"]))
                continue
            lo, hi = info["min"], info["max"]
            geo = _geo_kind(header, lo, hi)
            if geo:  # a real range of coordinates says where the people are: same spread, moved to nowhere (0, 0)
                half = (hi - lo) / 2
                y = round(rnd.uniform(-half, half), max(4, info["decimals"] or 0))
                out.append(str(y))
                continue
            if re.search(r"(?i)\b(pin|pincode|zip|postal|post code)\b", str(header)):
                out.append(str(rnd.randint(100000, 999999)))  # a postal code is a place: random, same shape
                continue
            y = rnd.uniform(lo, hi) if hi > lo else lo
            y = round(y, info["decimals"]) if info["decimals"] else int(round(y))
            s = str(y)
            if re.search(r"(?i)rs|inr|₹|,", v):  # keep the styling quirks, not the value
                s = rnd.choice(["Rs. {:,}", "₹{:,}", "{:,}", "{:,} INR"]).format(y)
            out.append(s)
        elif kind == "email":
            out.append(f"person{i + 1}@example.org" if EMAIL.match(v) else rnd.choice(["person at example", "n/a"]))
        elif kind == "phone":
            ok = PHONE.match(re.sub(r"[\s-]", "", v)) or PHONE.match(v)
            num = "9" + "".join(rnd.choice(string.digits) for _ in range(9))
            out.append((num if not re.search(r"[\s-]", v) else f"{num[:5]} {num[5:]}") if ok
                       else num[:rnd.randint(5, 8)])
        elif kind == "category" and keep_labels:
            out.append(v)  # the user agreed these labels (e.g. Approved / Pending) are not private
        elif kind == "category" and _id_like(v):
            key = "id:" + v.strip().upper()
            shared.setdefault(key, _same_shape(v.strip(), rnd, fixed.get(len(v.strip()))))
            out.append(shared[key])
        elif kind == "category":
            base = real_variants.get(v, v)
            key = re.sub(r"[^a-z0-9]", "", base.lower())
            if key in shared:
                cats.setdefault(base, shared[key])
            if base not in cats:
                cats[base] = f"{header} {_label(len(cats))}"
                shared[key] = cats[base]
            fake = cats[base]
            out.append(_variant(fake, v))
        elif kind == "longtext":
            n = max(3, len(v) // 6)
            out.append(" ".join(rnd.choice(WORDS) for _ in range(n)).capitalize())
        else:
            key = re.sub(r"[^a-z0-9]", "", v.lower())
            if key not in shared:
                if _id_like(v):
                    shared[key] = _same_shape(v.strip(), rnd, fixed.get(len(v.strip())))  # an ID (PAN, receipt no.): same pattern, so checks can be written
                else:
                    shared[key] = f"{header} {len([x for x in shared.values() if x.startswith(header + ' ')]) + 1}"
            out.append(shared[key] if _id_like(v) else _variant(shared[key], v))
    return out, info


def _id_like(v):
    """A code with digits and no spaces: PAN, receipt numbers, plot IDs."""
    v = str(v).strip()
    return bool(re.fullmatch(r"[A-Za-z0-9/._-]{4,24}", v) and re.search(r"\d", v) and re.search(r"[A-Za-z]", v))


def _same_shape(v, rnd, keep=None):
    """'ABCDE1234F' -> 'QWRTZ5821K': letters stay letters (same case), digits stay digits, separators stay, and
    characters every value shares at that position (`keep`) stay as they are."""
    keep = keep or {}
    return "".join(keep[i] if i in keep else rnd.choice(string.ascii_uppercase) if c.isupper() else
                   rnd.choice(string.ascii_lowercase) if c.islower() else rnd.choice(string.digits) if c.isdigit()
                   else c for i, c in enumerate(v))


def _label(k):
    s = ""
    k += 1
    while k:
        k, r = divmod(k - 1, 26)
        s = chr(65 + r) + s
    return s


def _variant_groups(vals):
    """value -> canonical value, for case/space spelling variants in a category column."""
    canon = {}
    for v in vals:
        if v == "":
            continue
        k = re.sub(r"[^a-z0-9]", "", v.lower())
        canon.setdefault(k, v)
    return {v: canon[re.sub(r"[^a-z0-9]", "", v.lower())] for v in vals if v != ""}


def scrub(text, sheets, keep=(), fakes=None):
    """Replace any real value from the file's text columns that appears in `text` (names, villages...).
    A value that has a fake in the mock (`fakes`, e.g. "Meena Kulkarni" -> "Person1 Surname1", "Meena" ->
    "Person1") is replaced by that fake, so the question still matches the mock; others by a placeholder."""
    fakes = fakes or {}
    vals = {}
    for df in sheets.values():
        for c in df.columns:
            info = classify(df[c])
            if info["kind"] in ("number", "date", "empty") or fk_slug_in(c, keep):
                continue
            for x in df[c]:
                if len(x) >= 3:
                    vals.setdefault(x, c)
    for v in sorted(vals, key=len, reverse=True):
        pat = r"(?i)(?<![\w<])" + re.escape(v) + r"(?![\w>])"
        if re.search(pat, text):
            fake = fakes.get(re.sub(r"[^a-z0-9]", "", v.lower()))
            text = re.sub(pat, (fake or f"<a value from '{vals[v]}'>").replace("\\", ""), text)
    return text


NAMEISH = re.compile(r"[A-Za-z][A-Za-z.'-]*(?: [A-Za-z][A-Za-z.'-]*){1,2}")
# Places that read like names ("Yerawada Ward", "Janata Vasahat") are not people (laptop 2026-11-12: wards became
# "Person27 Surname32" and Claude had to guess that a "person" was a ward)
PLACE_COL = re.compile(r"(?i)\b(ward|village|block|district|taluka?|tehsil|mandal|area|zone|region|location|place|"
                       r"locality|colony|basti|slum|settlement|town|city|panchayat|gram|habitation|hamlet|site|"
                       r"state|country|address|road|stretch)\b")
PLACE_WORD = re.compile(r"(?i)\b(ward|village|nagar|colony|basti|wadi|pada|vasahat|gaon|pur|abad|camp|road|"
                        r"block|district|taluka?|town|city|zone|area|sector|layout|chawl|peth|halli|palli)$")


def _name_fakes(sheets, share_labels=()):
    """Fakes for people's names that keep how names relate: "Meena Kulkarni" -> "Person1 Surname1", and a
    bare "Meena" in any name column -> "Person1". Without this, a first-name-only entry and the full name in
    another tab get unrelated fakes, and Claude can't test a first-name match on the mock."""
    cols = []
    for df in sheets.values():
        for c in df.columns:
            if fk_slug_in(c, share_labels):
                continue
            vals = [v.strip() for v in df[c] if v.strip()]
            if not vals or classify(df[c])["kind"] not in ("category", "text"):
                continue
            if PLACE_COL.search(str(c)) or sum(1 for v in vals if PLACE_WORD.search(v)) >= 0.5 * len(vals):
                continue
            if sum(1 for v in vals if NAMEISH.fullmatch(v) and (v.istitle() or v.isupper())) >= 0.6 * len(vals):
                cols.append(vals)
    firsts, out, n_full = {}, {}, 0
    for vals in cols:
        for v in vals:
            parts = v.split()
            if len(parts) >= 2 and NAMEISH.fullmatch(v):
                firsts.setdefault(parts[0].lower(), f"Person{len(firsts) + 1}")
    for vals in cols:
        for v in vals:
            key = re.sub(r"[^a-z0-9]", "", v.lower())
            if key in out:
                continue
            parts = v.split()
            if len(parts) >= 2 and parts[0].lower() in firsts:
                n_full += 1
                out[key] = f"{firsts[parts[0].lower()]} Surname{n_full}"
            elif len(parts) == 1 and v.lower() in firsts:
                out[key] = firsts[v.lower()]
    return out


def make_mock(path, question, title=None, caller_agent=None, seed=7, share_labels=(), missing=None, chart=None):
    """Write teach/inbox/<id>/mock.xlsx (+ request.json). Returns the request dict and a preview."""
    sheets, hdr = raw_sheets(path)
    if not sheets:
        raise ValueError("The file has no data.")
    rnd = random.Random(seed)
    main = main_sheet(sheets)
    fp = fingerprint(sheets[main])
    from lib import formkit  # late import: formkit builds on this module
    skill, score, _ = formkit.match_file(sheets)
    title = title or re.sub(r"\s*-\s*checked$", "", os.path.splitext(os.path.basename(path))[0])
    rid = f"{slug(title)[:40]}-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}"
    rdir = os.path.join(TEACH_DIR, rid)
    os.makedirs(rdir, exist_ok=True)
    mocks, kinds, layouts, shared = {}, {}, {}, _name_fakes(sheets, share_labels)
    for name, df in sheets.items():
        cols, k = {}, {}
        for c in df.columns:
            cols[c], info = mock_column(df[c], c, rnd, keep_labels=c in share_labels or fk_slug_in(c, share_labels),
                                        shared=shared)
            k[c] = {x: info[x] for x in ("kind", "format", "bad", "blank", "distinct") if x in info}
        mock = pd.DataFrame(cols)[list(df.columns)]
        from lib import fixkit
        lay = fixkit.layout_rows(df)  # rows that are layout, not data: Claude needs to see their shape
        heads = 0
        for i, kind in lay.items():
            if kind == "repeated_header":  # only column names, which are sent anyway
                mock.iloc[i] = df.iloc[i].values
            elif kind == "total":
                first = next(c for c in df.columns if str(df.iloc[i][c]).strip())
                mock.at[i, first] = "Total"
            elif kind == "subheading":
                heads += 1
                first = next(c for c in df.columns if str(df.iloc[i][c]).strip())
                mock.iloc[i] = ""
                mock.at[i, first] = f"Heading {heads}"
        layouts[name] = {kd: n for kd, n in __import__("collections").Counter(lay.values()).items()}
        mocks[name] = mock.head(300)
        kinds[name] = k
    clean_q = scrub(question, sheets, keep=share_labels, fakes=shared)  # real values -> the mock's own fakes
    req = {"kind": "idli-teach-request", "version": 1, "id": rid, "title": title, "fingerprint": fp,
           "main_sheet": main, "question": clean_q, "existing_skill": skill["id"] if skill else None,
           "missing": scrub(missing, sheets, keep=share_labels, fakes=shared) if missing else None,
           "layout": {t: v for t, v in layouts.items() if v},
           # a chart request: "" = suggest analyses for this file, text = the chart they asked for
           "chart": None if chart is None else (scrub(chart, sheets, keep=share_labels, fakes=shared) if chart else ""),
           "existing_version": skill.get("version") if skill else None, "caller_agent": caller_agent,
           "created": dt.datetime.now().isoformat(timespec="seconds"), "columns": kinds,
           "real_labels": sorted(c for df in sheets.values() for c in df.columns if fk_slug_in(c, share_labels))}
    mock_path = os.path.join(rdir, "mock.xlsx")
    with pd.ExcelWriter(mock_path, engine="openpyxl") as w:
        for name, df in mocks.items():
            df.to_excel(w, sheet_name=("Sheet1" if name == "csv" else str(name))[:31], index=False)
        pd.DataFrame([{"key": k, "value": json.dumps(v) if isinstance(v, (dict, list)) else v}
                      for k, v in req.items()]).to_excel(w, sheet_name=WATERMARK, index=False)
        w.book[WATERMARK].sheet_state = "hidden"
    with open(os.path.join(rdir, "request.json"), "w") as f:
        json.dump(req, f, indent=1)
    preview = {name: df.head(3).to_dict("records") for name, df in mocks.items()}
    return req, mock_path, preview


def fk_slug_in(c, cols):
    return slug(c) in {slug(x) for x in cols or ()}


def label_columns(path):
    """Category columns and their labels, so the user can choose which labels may be shared."""
    from lib import fixkit
    sheets, _ = raw_sheets(path)
    out = {}
    for df in sheets.values():
        lay = fixkit.layout_rows(df)  # repeated headings are not labels
        body = df.drop(index=[i for i in lay if i in df.index])
        for c in body.columns:
            vals = [v for v in body[c] if v]
            if not vals or sum(as_number(v) is not None for v in vals) > 0.6 * len(vals):
                continue  # numbers (a sparse DBH column) are not labels
            if classify(body[c])["kind"] == "category":
                out[c] = sorted(set(vals))[:12]
    return out


# ---------------------------------------------------------------- running a skill on a real file
def _lit(v):
    return "NULL" if v is None else "'" + str(v).replace("'", "''") + "'"


def build_tables(con, path, skill, base):
    """Register <base>_raw (text as in the file) and <base> (cleaned per skill.normalize)."""
    sheets, hdr = raw_sheets(path)
    sheet = skill.get("sheet") if skill.get("sheet") in sheets else main_sheet(sheets)
    df = sheets[sheet].copy()
    df.columns = [slug(c) for c in df.columns]
    con.register(base + "_raw", df)
    cols = skill.get("columns") or {}
    norm = skill.get("normalize") or {}
    sel = []
    for c in df.columns:
        spec, n = cols.get(c, {}), norm.get(c, {})
        expr = f'NULLIF(TRIM("{c}"), \'\')'
        if n.get("map"):
            cases = " ".join(f"WHEN lower(trim({expr})) = {_lit(str(k).strip().lower())} THEN {_lit(v)}"
                             for k, v in n["map"].items())
            expr = f"CASE {cases} ELSE {expr} END"
        if n.get("case") == "lower":  # codes such as species abbreviations: 'Cesaur ' -> 'cesaur'
            expr = f"lower(regexp_replace({expr}, '\\s+', ' ', 'g'))"
        if n.get("case") == "title":
            expr = f"array_to_string(list_transform(string_split(lower({expr}), ' '), lambda x: upper(x[1]) || x[2:]), ' ')"
        kind = n.get("type") or spec.get("type")
        if kind == "number":
            expr = f"TRY_CAST(regexp_replace({expr}, '(?i)(rs\\.?|inr|₹|,|\\s)', '', 'g') AS DOUBLE)"
        elif kind == "date":
            fmts = n.get("formats") or [spec.get("format") or "%d/%m/%Y"]
            expr = "COALESCE(" + ", ".join(f"TRY_STRPTIME({expr}, {_lit(f)})::DATE" for f in fmts) + ")"
        sel.append(f'{expr} AS "{c}"')
    con.execute(f'CREATE OR REPLACE VIEW "{base}" AS SELECT {", ".join(sel)} FROM "{base}_raw"')
    return sheet, hdr[sheet], df


RULES = {
    "required": lambda v, a: v != "",
    "number": lambda v, a: v == "" or as_number(v) is not None,
    "date": lambda v, a: v == "" or any(_parses(v, f) for f in (a or ["%d/%m/%Y"])),
    "email": lambda v, a: v == "" or bool(EMAIL.match(v)),
    "phone": lambda v, a: v == "" or bool(PHONE.match(re.sub(r"[\s-]", "", v))),
    "in_list": lambda v, a: v == "" or v.strip().lower() in {str(x).strip().lower() for x in (a or [])},
    "range": lambda v, a: v == "" or (as_number(v) is not None and a[0] <= as_number(v) <= a[1]),
    "regex": lambda v, a: v == "" or bool(re.fullmatch(a, v)),
    "not_future": lambda v, a: v == "" or _not_future(v, a),  # arg: date formats
}


def excel_formula(rule, ref, arg, message):
    m = message.replace('"', "'")
    if rule == "required":
        return f'=IF(LEN(TRIM({ref}&""))=0,"{m}","")'
    if rule == "number":
        return (f'=IF({ref}="","",IF(ISNUMBER({ref}),"",IF(ISERROR(VALUE(SUBSTITUTE(SUBSTITUTE(SUBSTITUTE('
                f'{ref},",",""),"Rs.",""),"₹",""))),"{m}","")))')
    if rule == "email":
        return f'=IF({ref}="","",IF(ISERROR(FIND(".",{ref},FIND("@",{ref}))),"{m}",""))'
    if rule == "phone":
        return (f'=IF({ref}="","",IF(LEN(SUBSTITUTE(SUBSTITUTE(SUBSTITUTE({ref}&""," ",""),"-",""),"+91",""))'
                f'=10,"","{m}"))')
    if rule == "date":
        fmts = arg or ["%d/%m/%Y"]
        ok = []
        for f in fmts:  # one shape test per accepted format; formats Excel can't test are checked in Python
            if f in ("%d/%m/%Y", "%d-%m-%Y"):
                s = f[2]
                ok.append(f'AND(LEN({ref})=10,MID({ref},3,1)="{s}",MID({ref},6,1)="{s}",VALUE(LEFT({ref},2))<=31,'
                          f'VALUE(MID({ref},4,2))<=12)')
            elif f == "%Y-%m-%d":
                ok.append(f'AND(LEN({ref})=10,MID({ref},5,1)="-",MID({ref},8,1)="-",VALUE(MID({ref},6,2))<=12,'
                          f'VALUE(RIGHT({ref},2))<=31)')
            else:
                return None
        return (f'=IF({ref}="","",IF(ISNUMBER({ref}),"",IF(OR(' + ",".join(f"IFERROR({c},FALSE)" for c in ok)
                + f'),"","{m}")))')
    if rule == "in_list" and arg and len(arg) <= 15:
        opts = ",".join(f'{ref}="{str(x)}"' for x in arg)
        return f'=IF({ref}="","",IF(OR({opts}),"","{m}"))'
    if rule == "range":
        return f'=IF({ref}="","",IFERROR(IF(AND(VALUE({ref})>={arg[0]},VALUE({ref})<={arg[1]}),"","{m}"),"{m}"))'
    if rule == "not_future":
        to_date = {"%d/%m/%Y": f"DATE(VALUE(RIGHT({ref},4)),VALUE(MID({ref},4,2)),VALUE(LEFT({ref},2)))",
                   "%d-%m-%Y": f"DATE(VALUE(RIGHT({ref},4)),VALUE(MID({ref},4,2)),VALUE(LEFT({ref},2)))",
                   "%Y-%m-%d": f"DATE(VALUE(LEFT({ref},4)),VALUE(MID({ref},6,2)),VALUE(RIGHT({ref},2)))"}
        fmts = arg or ["%d/%m/%Y"]
        if any(f not in to_date for f in fmts):
            return None
        d = to_date["%Y-%m-%d"] if fmts == ["%Y-%m-%d"] else to_date[fmts[0]]
        if "%Y-%m-%d" in fmts and fmts != ["%Y-%m-%d"]:
            d = f'IF(MID({ref},5,1)="-",{to_date["%Y-%m-%d"]},{d})'
        return f'=IF({ref}="","",IFERROR(IF(IF(ISNUMBER({ref}),{ref},{d})>TODAY(),"{m}",""),""))'
    return None  # computed in Python only (e.g. regex)


def check(path, skill, out_dir):
    """Run the skill's validations. Writes '<name> - checked.xlsx' (original values, one formula column per
    rule, problem cells highlighted, a Problems sheet). Never touches the original file."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    sheets, hdr = raw_sheets(path)
    sheet = skill.get("sheet") if skill.get("sheet") in sheets else main_sheet(sheets)
    df = sheets[sheet]
    by_slug = {slug(c): c for c in df.columns}
    problems = []
    rules = [r for r in skill.get("validations") or [] if r.get("column") in by_slug]
    for r in rules:
        col = by_slug[r["column"]]
        fn = RULES.get(r["rule"])
        if not fn:
            continue
        for i, v in enumerate(df[col]):
            try:
                ok = fn(v, r.get("arg"))
            except Exception:
                ok = False
            if not ok:
                problems.append({"row": hdr[sheet] + 1 + i, "column": col, "value": v,
                                 "problem": r.get("message") or f"{r['rule']} check failed"})
    wb = Workbook()
    ws = wb.active
    ws.title = "Data"
    headers = list(df.columns)
    ws.append(headers + [f"Check: {by_slug[r['column']]}" for r in rules])
    red = PatternFill("solid", fgColor="F8D7DA")
    for c in range(1, len(headers) + len(rules) + 1):
        ws.cell(1, c).font = Font(bold=True)
    bad = {(p["row"], p["column"]) for p in problems}
    for i, row in df.iterrows():
        r = i + 2
        for j, h in enumerate(headers, start=1):
            v = row[h]
            x = as_number(v) if re.fullmatch(r"-?\d+(\.\d+)?", v or "") else None
            ws.cell(r, j, x if x is not None else v)
            if (hdr[sheet] + 1 + i, h) in bad:
                ws.cell(r, j).fill = red
        for k, rule in enumerate(rules):
            ref = f"{get_column_letter(headers.index(by_slug[rule['column']]) + 1)}{r}"
            f = excel_formula(rule["rule"], ref, rule.get("arg"), rule.get("message") or rule["rule"])
            if f is None:
                f = "" if (hdr[sheet] + 1 + i, by_slug[rule["column"]]) not in bad else (rule.get("message") or "check")
            ws.cell(r, len(headers) + k + 1, f)
    ps = wb.create_sheet("Problems")
    ps.append(["Row in original", "Column", "Value", "Problem"])
    for p in problems:
        ps.append([p["row"], p["column"], p["value"], p["problem"]])
    os.makedirs(out_dir, exist_ok=True)
    name = re.sub(r"\s*-\s*checked$", "", os.path.splitext(os.path.basename(path))[0])
    out = os.path.join(out_dir, f"{name} - checked.xlsx")
    wb.save(out)
    return problems, out, sheet


def fill(sql, params, specs):
    for k, spec in (specs or {}).items():
        v = params.get(k)
        if v in (None, "") and spec.get("default") is not None:
            v = spec["default"]
        if v in (None, ""):
            if not spec.get("optional"):
                raise ValueError(f"Missing '{k}': {spec.get('description', '')}")
            v = None
        elif spec.get("type") == "date":
            v = _to_iso(v)
        elif spec.get("type") == "number":
            v = float(v)
        lit = "NULL" if v is None else (str(v) if isinstance(v, float) else _lit(v))
        if spec.get("type") == "date" and v is not None:
            lit = f"DATE {lit}"
        sql = sql.replace("{{" + k + "}}", lit)
    left = re.findall(r"\{\{(\w+)\}\}", sql)
    if left:
        raise ValueError("Unfilled parameter in query: " + ", ".join(left))
    return sql


def _to_iso(v):
    v = str(v).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d %b %Y", "%d %B %Y"):
        try:
            return dt.datetime.strptime(v, fmt).date().isoformat()
        except ValueError:
            pass
    raise ValueError(f"Could not read the date '{v}'. Use YYYY-MM-DD.")


# ---------------------------------------------------------------- CLI for the Teach workspace
def _inspect(path):
    sheets, hdr = raw_sheets(path)
    out = {}
    for name, df in sheets.items():
        out[name] = {"header_row": hdr[name], "rows": len(df), "fingerprint": fingerprint(df),
                     "columns": {slug(c): {"header": c, **classify(df[c])} for c in df.columns}}
    if not path.lower().endswith(".csv"):
        try:
            wm = pd.read_excel(path, sheet_name=WATERMARK)
            out["_watermark"] = dict(zip(wm["key"], wm["value"]))
        except Exception:
            out["_watermark"] = None
    return out


def _test(skill_dir, mock=None):
    """Run a skill's tests.json on its mock. A test is either a form spec
    {"tab": "Visits", "spec": {...}, "expect": [[...], ...]} (rows as lists, in the form's column order) or a
    taught question {"question": id, "params": {...}, "expect": [...]}."""
    import duckdb
    from lib import formkit as fm
    with open(os.path.join(skill_dir, "skill.json")) as f:
        skill = json.load(f)
    with open(os.path.join(skill_dir, "tests.json")) as f:
        tests = json.load(f)
    mock = mock or os.path.join(skill_dir, "mock.xlsx")
    sheets, _ = raw_sheets(mock)
    global SKILLS_DIR
    saved, SKILLS_DIR = SKILLS_DIR, os.path.dirname(os.path.abspath(skill_dir))
    try:
        s, score, tabmap = fm.match_file(sheets)
    finally:
        SKILLS_DIR = saved
    fails = 0 if (s and s.get("id") == skill.get("id")) else 1
    print(("ok  " if not fails else "FAIL") + f" recognises the mock (overlap {score}; tabs {dict((k, v[0]) for k, v in tabmap.items())})")
    con = duckdb.connect()
    built = fm.build(con, mock, skill, "t")
    c = fm.contract(skill, sheets, con, built)
    print(("ok  " if c["status"] != "changed" else "FAIL") + f" contract on the mock: {c['status']} {c['messages']}")
    fails += c["status"] == "changed"
    forms = {}
    for tab in built:
        try:
            forms[tab] = fm.form(con, skill, tab, built)
            print(f"ok   form for '{tab}': {len(forms[tab]['measures'])} measures, {len(forms[tab]['group_by'])} groupings, "
                  f"{len(forms[tab]['filters'])} filters, {len(forms[tab]['presets'])} presets")
        except Exception as e:
            print(f"FAIL form for '{tab}': {e}")
            fails += 1
    problems, _ = fm.check(mock, skill, os.path.join(skill_dir, ".check"))
    print(f"ok   checks ran: {len(problems)} problems in the mock")
    first = next(iter(built))
    qs = {q["id"]: q for q in skill.get("questions", [])}
    for t in tests:
        try:
            if "spec" in t:
                tab = t.get("tab") or first
                r = fm.run(con, forms[tab], built[tab]["table"], t["spec"])
                got = [list(x.values()) for x in r["rows"]]
                label = f"{tab}: {json.dumps(t['spec'])}"
            else:
                q = qs[t["question"]]
                table = built[q.get("tab") or first]["table"]
                got = con.execute(fill(q["sql"].replace("{{table}}", f'"{table}"'), t.get("params", {}),
                                       q.get("params"))).fetchall()
                label = f"{t['question']} {t.get('params', {})}"
            exp = t.get("expect")
            ok = exp is None or _close(got, exp)
            print(("ok  " if ok else "FAIL") + f" {label} -> {got[:3]}" + ("" if ok else f" expected {exp}"))
            fails += 0 if ok else 1
        except Exception as e:
            print(f"FAIL {t.get('question') or t.get('spec')}: {e}")
            fails += 1
    print("ALL PASSED" if not fails else f"{fails} FAILED")
    return fails


def _close(got, exp):
    g = [list(r) for r in got]
    if len(g) != len(exp):
        return False
    for a, b in zip(g, exp):
        for x, y in zip(a, b):
            if isinstance(x, (int, float)) and isinstance(y, (int, float)):
                if abs(x - y) > 0.01 * max(1, abs(y)):
                    return False
            elif str(x) != str(y):
                return False
    return True


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "inspect":
        print(json.dumps(_inspect(sys.argv[2]), indent=1, default=str, ensure_ascii=False))
    elif len(sys.argv) >= 3 and sys.argv[1] == "test":
        sys.exit(1 if _test(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None) else 0)
    else:
        sys.exit(__doc__)
