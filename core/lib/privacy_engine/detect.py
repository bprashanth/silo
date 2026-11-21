"""Regex validators copied from app/io/engine/detect.py."""
import re
from typing import Callable
Span = tuple[int, int, str, float]

def verhoeff_ok(number: str) -> bool:
    d = [[0,1,2,3,4,5,6,7,8,9],[1,2,3,4,0,6,7,8,9,5],[2,3,4,0,1,7,8,9,5,6],[3,4,0,1,2,8,9,5,6,7],
         [4,0,1,2,3,9,5,6,7,8],[5,9,8,7,6,0,4,3,2,1],[6,5,9,8,7,1,0,4,3,2],[7,6,5,9,8,2,1,0,4,3],
         [8,7,6,5,9,3,2,1,0,4],[9,8,7,6,5,4,3,2,1,0]]
    p = [[0,1,2,3,4,5,6,7,8,9],[1,5,7,6,2,8,3,0,9,4],[5,8,0,3,7,9,6,1,4,2],[8,9,1,6,0,4,3,5,2,7],
         [9,4,5,3,1,2,6,8,7,0],[4,2,8,6,5,7,3,9,0,1],[2,7,9,3,8,0,6,4,1,5],[7,0,4,6,9,1,3,2,5,8]]
    c = 0
    for i, ch in enumerate(reversed(number)):
        c = d[c][p[i % 8][int(ch)]]
    return c == 0


REGEXES: list[tuple[str, re.Pattern[str], Callable[[str], bool] | None]] = [
    ("email", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), None),
    ("aadhaar", re.compile(r"(?<!\d)([2-9]\d{3}[ -]?\d{4}[ -]?\d{4})(?!\d)"),
     lambda s: verhoeff_ok(re.sub(r"\D", "", s))),
    ("pan", re.compile(r"(?<![A-Z])[A-Z]{3}[ABCFGHLJPT][A-Z]\d{4}[A-Z](?![A-Z])"), None),
    ("ifsc", re.compile(r"(?<![A-Z])[A-Z]{4}0[A-Z0-9]{6}(?![A-Z0-9])"), None),
    ("upi_id", re.compile(r"\b[\w.-]{2,}@(?:ybl|okaxis|oksbi|okicici|okhdfcbank|paytm|upi|apl|ibl|axl|icici|sbi|hdfcbank)\b"), None),
    ("phone", re.compile(r"(?<!\d)(?:\+91[ -]?|0)?[6-9]\d{4}[ -]?\d{5}(?!\d)"), None),
    ("vehicle_number", re.compile(r"\b[A-Z]{2}[ -]?\d{1,2}[ -]?[A-Z]{1,3}[ -]?\d{4}\b"), None),
    ("voter_id", re.compile(r"\b[A-Z]{3}\d{7}\b"), None),
    ("gps", re.compile(r"(?<![\d.])-?\d{1,2}\.\d{2,}\s*,\s*-?\d{1,3}\.\d{2,}(?!\d|\.\d)"),
     lambda s: abs(float(s.split(",")[0])) <= 90 and abs(float(s.split(",")[1])) <= 180),
    ("dob", re.compile(r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2})\b"), None),
]


def regex_engine(text: str) -> list[Span]:
    spans: list[Span] = []
    for label, pattern, check in REGEXES:
        for match in pattern.finditer(text):
            if check and not check(match.group(0)):
                continue
            spans.append((match.start(), match.end(), label, 1.0))
    return spans


