#!/usr/bin/env python3
"""Column-level PII classification for spreadsheets (the redaction unit is a column).

Generic, sector-free rules ordered from cheapest/highest-precision to model-based:

1. validators     : >=50% of sampled cells match a checksummed/structured pattern
                    (email, phone, Aadhaar+Verhoeff, PAN, IFSC, UPI, GPS, vehicle, voter, DOB).
2. identifier ids : >=80% of cells are 8+ digit strings AND nearly unique -> private
                    identifier (bank account, ration card, mislabelled "col_17").
                    Sequential small integers (Sr No, _id) are not caught.
3. span model     : GLiNER over "header: v1; v2; ..." windows. A column is a direct
                    identifier when >=50% of distinct sampled values are covered by a
                    person/address/village span; a column is free text with PII when
                    cells are long (>40 chars on average) and any span is found.
4. categoricals   : low-cardinality text (<=30 distinct over >=50 rows) is a category,
                    not an identifier -- unless its vocabulary is a protected-attribute
                    vocabulary (caste/religion), which is flagged as sensitive.
5. numeric        : never an identifier by value; 'age' is kept for analysis.

Returns {column: {"class": ..., "rule": ..., "confidence": ...}} so a UI can show why.
"""

from __future__ import annotations

import re
import statistics
from typing import Any, Callable

import pandas as pd

from .detect import REGEXES, verhoeff_ok  # noqa: F401  (validators reused)

SENSITIVE_VOCAB = {"sc", "st", "obc", "general", "nt", "vjnt", "sbc", "ews", "hindu", "muslim", "christian",
                   "buddhist", "sikh", "jain", "dalit", "adivasi", "open"}
DIRECT_SPAN_CLASSES = {"person_name", "address", "village", "email", "phone", "aadhaar", "pan", "bank_account",
                       "ifsc", "upi_id", "ration_card", "voter_id", "vehicle_number"}


def validator_fraction(values: list[str]) -> tuple[str | None, float]:
    best: tuple[str | None, float] = (None, 0.0)
    for label, pattern, check in REGEXES:
        hits = 0
        for value in values:
            m = pattern.search(value)
            if m and (not check or check(m.group(0))) and (m.end() - m.start()) >= 0.6 * len(value.strip()):
                hits += 1
        fraction = hits / len(values) if values else 0.0
        if fraction > best[1]:
            best = (label, fraction)
    return best


def classify_columns(frame: pd.DataFrame, span_engine: Callable[[str], list[tuple[int, int, str, float]]] | None,
                     sample: int = 40) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    n_rows = len(frame)
    for column in frame.columns:
        series = frame[column].dropna().astype(str).str.strip()
        series = series[series != ""]
        if series.empty:
            out[str(column)] = {"class": "none", "rule": "empty", "confidence": 1.0}
            continue
        distinct = series.drop_duplicates()
        values = distinct.head(sample).tolist()
        numeric = pd.to_numeric(series, errors="coerce")
        numeric_fraction = numeric.notna().mean()
        mean_len = statistics.fmean(len(v) for v in values)
        sentence_like = sum(bool(re.search(r"[,.;!?]\s|\s\w+\s\w+\s\w+\s\w+", v)) for v in values) / len(values) >= 0.5
        name_shaped = sum(bool(re.fullmatch(r"[A-Za-z][A-Za-z.'-]*(?:\s[A-Za-z][A-Za-z.'-]*){0,4}", v)) for v in values) / len(values) >= 0.8

        # 1. validators
        label, fraction = validator_fraction(values)
        if label and fraction >= 0.5 and not (label == "dob" and numeric_fraction > 0.9):
            out[str(column)] = {"class": label, "rule": "validator", "confidence": round(fraction, 2)}
            continue

        # 2. long digit identifiers, nearly unique
        digits = sum(bool(re.fullmatch(r"[\d\s-]{8,}", v)) and len(re.sub(r"\D", "", v)) >= 8 for v in values) / len(values)
        uniqueness = len(distinct) / len(series)
        if digits >= 0.8 and uniqueness >= 0.9:
            out[str(column)] = {"class": "bank_account", "rule": "long-unique-number", "confidence": round(digits, 2)}
            continue

        # 2b. code-like record ids (CH-0001, HH_17, uuid) are not private by value
        codes = sum(bool(re.fullmatch(r"[A-Za-z]{1,5}[-_/]?\d{1,8}|[0-9a-f]{8}-[0-9a-f-]{27,}", v)) for v in values) / len(values)
        if codes >= 0.9 and uniqueness >= 0.9:
            out[str(column)] = {"class": "record_id_non_pii", "rule": "code-like-id", "confidence": round(codes, 2)}
            continue

        # 5. numeric columns are never identifiers by value, except precise coordinates
        if numeric_fraction >= 0.95:
            head = str(column).casefold()
            decimals = sum(bool(re.search(r"\.\d{4,}$", v)) for v in values) / len(values)
            in_range = numeric.dropna().between(-180, 180).mean()
            if decimals >= 0.8 and in_range >= 0.99 and uniqueness >= 0.5:
                out[str(column)] = {"class": "gps", "rule": "precise-coordinate", "confidence": round(decimals, 2)}
                continue
            cls = "age" if re.search(r"\bage\b|umar|\bumr\b", head) else "none"
            out[str(column)] = {"class": cls, "rule": "numeric", "confidence": 0.9}
            continue

        # 4. low-cardinality categoricals: categories unless sensitive vocabulary or
        #    the values themselves read as people (staff names are still names)
        if len(distinct) <= 30 and n_rows >= 50 and not sentence_like:
            vocab = {v.casefold() for v in distinct}
            if len(vocab & SENSITIVE_VOCAB) >= 2:
                out[str(column)] = {"class": "caste_category", "rule": "sensitive-vocabulary", "confidence": 0.8}
                continue
            if span_engine is not None and name_shaped:
                text = f"{column}: " + "; ".join(values)
                people = [v for v in values if any(
                    lab == "person_name" and text.find(v) >= 0 and s < text.find(v) + len(v) and text.find(v) < e
                    for (s, e, lab, _sc) in span_engine(text))]
                if len(people) >= 0.5 * len(values):
                    out[str(column)] = {"class": "person_name", "rule": "categorical-names", "confidence": round(len(people) / len(values), 2)}
                    continue
            out[str(column)] = {"class": "none", "rule": "categorical", "confidence": 0.7}
            continue

        # 3. span model on header-anchored windows
        if span_engine is None:
            out[str(column)] = {"class": "none", "rule": "no-model", "confidence": 0.3}
            continue
        covered = 0
        span_labels: dict[str, int] = {}
        any_span = False
        for start in range(0, len(values), 8):
            window_values = values[start:start + 8]
            text = f"{column}: " + "; ".join(window_values)
            offsets = []
            cursor = len(f"{column}: ")
            for v in window_values:
                offsets.append((cursor, cursor + len(v)))
                cursor += len(v) + 2
            spans = span_engine(text)
            for (s, e, lab, _sc) in spans:
                if lab in DIRECT_SPAN_CLASSES or lab in {"dob", "gps", "caste_category", "long_number"}:
                    any_span = True
            for (vs, ve) in offsets:
                hit = [lab for (s, e, lab, _sc) in spans if s < ve and vs < e and lab in DIRECT_SPAN_CLASSES]
                if hit and sum(min(e, ve) - max(s, vs) for (s, e, lab, _sc) in spans if lab in DIRECT_SPAN_CLASSES and s < ve and vs < e) >= 0.5 * (ve - vs):
                    covered += 1
                    span_labels[hit[0]] = span_labels.get(hit[0], 0) + 1
        coverage = covered / len(values)
        top = max(span_labels, key=span_labels.get) if span_labels else None
        if mean_len > 40 or sentence_like:
            cls = "free_text_with_pii" if any_span else "none"
            out[str(column)] = {"class": cls, "rule": "free-text", "confidence": round(coverage, 2)}
        elif coverage >= 0.5 and top:
            out[str(column)] = {"class": top, "rule": "span-coverage", "confidence": round(coverage, 2)}
        else:
            out[str(column)] = {"class": "none", "rule": "span-coverage", "confidence": round(1 - coverage, 2)}
    return out
