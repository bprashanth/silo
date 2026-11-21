#!/usr/bin/env python3
"""Sheltered mode: reversible pseudonymisation of tabular/text data.

Design notes (what makes follow-ups work):
- Tokens are class-prefixed and stable within a session: NAME_017, PHONE_003.
  A remote model can still group/count/rank by them and its SQL or HTML comes
  back containing tokens that local code rehydrates.
- The map is value -> token, so the same person appearing in a name column and
  inside a remarks cell gets the same token (exact, casefolded, whitespace-
  normalised match). Free-text spans found by a detector are added to the map.
- A follow-up question is redacted by (1) matching known values from the map,
  longest first, (2) running the span detector on the rest for values never seen
  before. If a partial name matches several tokens the caller gets the
  candidates back and can ask the user which one.
- Numeric quasi-identifiers that analysis needs (age, height, marks) are kept.
  DOB is reduced to year by default. GPS is rounded to 2 decimals (~1 km).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

import pandas as pd

PREFIX = {
    "person_name": "NAME", "phone": "PHONE", "email": "EMAIL", "aadhaar": "AADHAAR", "pan": "PAN",
    "bank_account": "ACCOUNT", "ifsc": "IFSC", "upi_id": "UPI", "ration_card": "RATION", "voter_id": "VOTER",
    "vehicle_number": "VEHICLE", "address": "ADDRESS", "village": "PLACE", "long_number": "NUMBER",
}
# any vault-style token; lookup decides. A code may follow a literal backslash escape as
# well as a word boundary: a shell command like printf '\nNAME_005,...' glues the code to
# the "n" of "\n", and \b alone left NAME_005 in a file on disk (DGX, 2026-09-15).
TOKEN_RE = re.compile(r"(?:(?<!\w)|(?<=\\[ntr]))[A-Z][A-Z_]{1,24}\\?_\d{3,}\b")


def normalise(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).casefold()


class PseudonymMap:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self.forward: dict[str, str] = {}   # normalised value -> token
        self.display: dict[str, str] = {}   # token -> original display value
        self.counters: dict[str, int] = {}
        if path and path.exists():
            saved = json.loads(path.read_text())
            self.forward, self.display, self.counters = saved["forward"], saved["display"], saved["counters"]

    def token(self, value: str, pii_class: str) -> str:
        key = normalise(value)
        if key in self.forward:
            return self.forward[key]
        bare = value.strip().strip("'\"`")
        if re.fullmatch(TOKEN_RE.pattern, bare, re.I):
            return value.strip()       # already one of our tokens (possibly quoted or
                                       # lower-cased by a script's repr): never re-mint
        prefix = PREFIX.get(pii_class, pii_class.upper())
        self.counters[prefix] = self.counters.get(prefix, 0) + 1
        token = f"{prefix}_{self.counters[prefix]:03d}"
        self.forward[key] = token
        self.display[token] = value.strip()
        return token

    def save(self) -> None:
        if self.path:
            self.path.write_text(json.dumps(
                {"forward": self.forward, "display": self.display, "counters": self.counters},
                indent=1, ensure_ascii=False))

    def known_regex(self) -> re.Pattern[str] | None:
        """One compiled alternation over all display values (longest first), rebuilt on growth.

        Rebuilding costs ~30 ms for a thousand values, and a coding pass mints a value per
        row: 107 rebuilds were 4.0 s of a 4.1 s pass (2026-09-15). In bulk mode (set by
        pseudonymise_frame) the regex is rebuilt every 64 new values and on refresh(); the
        detector still sees every cell, so the only thing a stale regex can miss during
        the pass is a value minted moments earlier, and the free-text columns are coded
        last, after a refresh, precisely so that all column values are known by then."""
        n = len(self.display)
        if n == 0:
            return None
        last = getattr(self, "_known_n", -1)
        if last != n and (not getattr(self, "bulk", False) or last <= 0 or n - last >= 64):
            values = sorted((v for v in self.display.values() if len(v) >= 3), key=len, reverse=True)
            # same boundary rule as TOKEN_RE: a value glued to a literal \n escape still counts
            self._known_re = re.compile(r"(?:(?<![\w@.])|(?<=\\[ntr]))(?:" + "|".join(re.escape(v) for v in values) + r")(?!(?:[\w@]|\.[\w@]))", re.I)  # a trailing dot only blocks when it starts a domain-like tail; plain sentence periods must not hide a name
            self._known_n = n
        return self._known_re

    def refresh(self) -> None:
        """Force the next known_regex() to rebuild."""
        self._known_n = -1

    def rehydrate(self, text: str) -> str:
        return TOKEN_RE.sub(lambda m: self.display.get(m.group(0).replace("\\_", "_"), m.group(0)), text)

    def candidates(self, fragment: str) -> list[tuple[str, str]]:
        key = normalise(fragment)
        return [(token, self.display[token]) for value, token in self.forward.items()
                if key and (key in value or value in key)]


def redact_text(text: str, pmap: PseudonymMap, detector: Callable[[str], list[tuple[int, int, str, float]]] | None,
                classes: set[str] | None = None, kept: set[str] | None = None) -> tuple[str, list[dict[str, Any]]]:
    """Replace known values (longest first) and detector spans with tokens.
    kept: casefolded values that stay clear even though the vault knows them (what the
    person chose to keep, and the column names of the sheltered tables)."""
    events: list[dict[str, Any]] = []
    spans: list[tuple[int, int, str]] = []
    existing = [(m.start(), m.end()) for m in TOKEN_RE.finditer(text)]
    if detector:
        for start, end, label, _score in detector(text):
            if any(start < te and ts < end for ts, te in existing):
                continue  # never re-tokenise a token
            if classes is None or label in classes:
                spans.append((start, end, label))
    # known values: one alternation scan (case-insensitive)
    known = pmap.known_regex()
    if known:
        for m in known.finditer(text):
            if kept and m.group(0).casefold() in kept:
                continue
            token = pmap.forward.get(normalise(m.group(0)))
            if token:
                spans.append((m.start(), m.end(), f"known:{token}"))
    # resolve overlaps: longest span wins
    spans.sort(key=lambda s: (s[0], -(s[1] - s[0])))
    chosen: list[tuple[int, int, str]] = []
    last_end = -1
    for start, end, label in spans:
        if start >= last_end:
            chosen.append((start, end, label))
            last_end = end
    out: list[str] = []
    cursor = 0
    for start, end, label in chosen:
        out.append(text[cursor:start])
        original = text[start:end]
        token = label.split(":", 1)[1] if label.startswith("known:") else pmap.token(original, label)
        out.append(token)
        events.append({"start": start, "end": end, "text": original, "token": token})
        cursor = end
    out.append(text[cursor:])
    return "".join(out), events


SEP = "\n\u241f\n"


def redact_cells(values: list[str], pmap: PseudonymMap, detector: Callable | None,
                 chunk_chars: int = 1500) -> dict[str, str]:
    """Redact many short cells with few detector calls: cells are joined with a
    separator into chunks, the detector runs once per chunk, spans are mapped back."""
    out: dict[str, str] = {}
    i = 0
    while i < len(values):
        chunk: list[str] = []
        size = 0
        while i < len(values) and (size + len(values[i]) < chunk_chars or not chunk):
            chunk.append(values[i])
            size += len(values[i]) + len(SEP)
            i += 1
        text = SEP.join(chunk)
        spans = detector(text) if detector else []
        offsets = []
        cursor = 0
        for v in chunk:
            offsets.append((cursor, cursor + len(v)))
            cursor += len(v) + len(SEP)
        for (vs, ve), v in zip(offsets, chunk):
            local = [(s - vs, e - vs, lab, sc) for (s, e, lab, sc) in spans if s >= vs and e <= ve]
            out[v] = redact_text(v, pmap, (lambda _t, _l=local: _l))[0]
    return out


def pseudonymise_frame(frame: pd.DataFrame, column_classes: dict[str, Any], pmap: PseudonymMap,
                       detector: Callable[[str], list[tuple[int, int, str, float]]] | None = None,
                       kept_validator: Callable[[str], list[tuple[int, int, str, float]]] | None = None) -> pd.DataFrame:
    """column_classes: {column: class | [classes] | 'free_text_with_pii' | 'none'}.
    kept_validator: hard validators (email/PAN/aadhaar/...) still applied to cells of
    kept columns — a mangled header must never let a checksummed identifier through."""
    result = frame.copy()
    # Direct identifier columns first, free text last: by the time remarks are coded every
    # name and place from the other columns is in the vault and one rebuilt regex catches
    # them all. Bulk mode throttles the regex rebuilds in between.
    def is_free(c):
        return "free_text_with_pii" in (c if isinstance(c, list) else [c])
    ordered = sorted(column_classes.items(), key=lambda kv: is_free(kv[1]))
    was_bulk = getattr(pmap, "bulk", False)
    pmap.bulk = True
    refreshed = False
    for column, cls in ordered:
        if is_free(cls) and not refreshed:
            pmap.refresh()
            refreshed = True
        if column not in result.columns or cls in (None, "none", "record_id_non_pii", "age"):
            if kept_validator is not None and column in result.columns:
                series = result[column].astype("string")
                uniq = [str(v) for v in series.dropna().unique() if str(v).strip()]
                if uniq:
                    mapping = redact_cells(uniq, pmap, kept_validator)
                    if any(mapping.get(v, v) != v for v in uniq):
                        result[column] = series.map(lambda v: mapping.get(str(v), v) if pd.notna(v) else v)
            continue
        classes = cls if isinstance(cls, list) else [cls]
        series = result[column].astype("string")
        if "free_text_with_pii" in classes:
            uniq = [v for v in series.dropna().unique() if str(v).strip()]
            mapping = redact_cells([str(v) for v in uniq], pmap, detector)
            result[column] = series.map(lambda v: mapping.get(str(v), v) if pd.notna(v) else v)
        elif "dob" in classes:
            result[column] = series.map(lambda v: str(pd.to_datetime(v, errors="coerce", dayfirst=True).year)
                                        if pd.notna(v) and v.strip() else v)
        elif "gps" in classes:
            result[column] = pd.to_numeric(series, errors="coerce").round(2).astype("string")
        elif "caste_category" in classes:
            result[column] = series.map(lambda v: pmap.token(v, "caste_category") if pd.notna(v) and v.strip() else v)
        else:
            primary = classes[0]
            def tok(v: Any) -> Any:
                if pd.isna(v) or not str(v).strip():
                    return v
                # mixed columns (email/phone): pick class by shape
                c = primary
                if len(classes) > 1:
                    c = "email" if "@" in str(v) else ("phone" if re.search(r"\d{6,}", str(v)) else primary)
                return pmap.token(str(v), c)
            result[column] = series.map(tok)
    pmap.bulk = was_bulk
    pmap.refresh()
    return result


def rehydrate_frame(frame: pd.DataFrame, pmap: PseudonymMap) -> pd.DataFrame:
    return frame.map(lambda v: pmap.rehydrate(v) if isinstance(v, str) else v)


def redact_question(question: str, pmap: PseudonymMap, detector: Callable | None) -> dict[str, Any]:
    """Redact a follow-up question.

    Order matters: (1) exact known values, longest first; (2) partial matches of
    capitalised words against known NAME/PLACE values -- one hit is substituted,
    several hits are returned as an ambiguity for the UI to ask about; (3) only
    then the span detector, for values never seen before. Returns the redacted
    text plus ambiguities."""
    direct = {"person_name", "phone", "email", "aadhaar", "pan", "bank_account", "ifsc", "upi_id",
              "ration_card", "voter_id", "vehicle_number", "address", "village"}
    stop = {"what", "which", "show", "give", "list", "tell", "the", "and", "for", "how", "who", "now", "only",
            "compare", "make", "dashboard", "table", "download", "source", "average", "total"}
    text, events = redact_text(question, pmap, None)          # step 1: exact known values
    ambiguous = []
    for word in re.findall(r"\b[A-Z][a-z]{2,}\b", text):          # step 2: partial known names
        if word.casefold() in stop or TOKEN_RE.search(word):
            continue
        options = [(t, v) for t, v in pmap.candidates(word) if t.split("_")[0] in {"NAME", "PLACE"}
                   and re.search(rf"\b{re.escape(word)}\b", v, flags=re.I)]
        if len(options) > 1:
            ambiguous.append({"fragment": word, "options": options})
        elif len(options) == 1:
            text = re.sub(rf"\b{re.escape(word)}\b", options[0][0], text)
            events.append({"text": word, "token": options[0][0], "partial": True})
    if ambiguous:
        return {"redacted": text, "events": events, "ambiguous": ambiguous}
    text, more = redact_text(text, pmap, detector, classes=direct)   # step 3: unseen values
    return {"redacted": text, "events": events + more, "ambiguous": []}
