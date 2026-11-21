"""PDFs that come with spreadsheets in a sandbox (owner, 2026-11-18): they go to Claude too, as masked text.

A folder of PDFs and Excel or CSV files, with a question, goes to Sandbox Claude after masking, the same as files:
- the spreadsheets through the privacy review, as always (lib/home.prepare, lib/maskcopy);
- each PDF's text, read here (pypdf), then masked with the folder's known values, the rules and the name scanner
  (lib/privacy.mask_account_text: the codes are kept, so Claude's replies show the person the real values again),
  written to Claude's folder as docs/<name>.txt. Claude never gets the PDF itself.
The text is read once per file version and kept beside the download.
"""
import json
import re
from pathlib import Path

from lib import home

MAX_CHARS = 150_000     # about 50 pages; the rest is left out and the file says so


def _rejoin(text):
    """Some PDFs come out of pypdf one word per line ("Matthew\\n \\nMcEniry"), which hides names from a line-by-line
    scanner (the 2025 NDSA report's authors reached Claude, 2026-11-19). Join those runs back into lines."""
    return re.sub(r'[ \t]*\n[ \t]+\n[ \t]*', ' ', text)


def pdf_text(path):
    cache = Path(str(path) + '.text2.txt')  # text2: joined word-per-line runs
    if cache.is_file() and cache.stat().st_mtime >= Path(path).stat().st_mtime:
        return cache.read_text()
    from pypdf import PdfReader
    pages = []
    try:
        reader = PdfReader(str(path))
        for i, page in enumerate(reader.pages, 1):
            try:
                pages.append(f'[page {i}]\n' + _rejoin(page.extract_text() or '').strip())
            except Exception:  # noqa: BLE001  (one bad page: skip it)
                pages.append(f'[page {i}: could not be read]')
    except Exception:  # noqa: BLE001
        return ''
    text = '\n\n'.join(pages)
    cache.write_text(text)
    return text


class LineScanner:
    """The name scanner, one line at a time and many lines at once. On a whole page it misses most names in a list
    (its confidence drops with length: 11 authors on a report's first page gave 0 hits as one piece, 9 line by line)."""

    def __init__(self, workers=16):
        from concurrent.futures import ThreadPoolExecutor
        from lib import privacy
        self.scanner, self.pool = privacy.Scanner(), ThreadPoolExecutor(workers)

    WINDOW = 70  # a long line is read in overlapping windows: the scanner misses names in long pieces

    def __call__(self, text):
        lines, at = [], 0
        for line in str(text).split('\n'):
            if len(line.strip()) > 2:
                if len(line) <= self.WINDOW:
                    lines.append((at, line))
                else:
                    step = self.WINDOW // 2
                    for start in range(0, len(line), step):
                        a = line.rfind(' ', 0, start) + 1 if start else 0
                        lines.append((at + a, line[a:a + self.WINDOW]))
                        if a + self.WINDOW >= len(line):
                            break
                    # Lists ("Kari May, University of Pittsburgh, Krista Oldham, ..."): each piece on its own too.
                    off = 0
                    for piece in line.split(','):
                        if 2 < len(piece.strip()) <= self.WINDOW:
                            lines.append((at + off, piece))
                        off += len(piece) + 1
            at += len(line) + 1
        spans = []
        for (off, _), got in zip(lines, self.pool.map(lambda x: self.scanner(x[1]), lines)):
            spans += [(a + off, b + off, k, c) for a, b, k, c in got]
        return sorted(set(spans))

    def close(self):
        self.pool.shutdown(wait=False)


def _mask(data_dir, text):
    """Masked with the folder's known values, the rules and the name scanner (line by line); the new codes are kept,
    as privacy.mask_account_text does, so Claude's replies show the person the real values."""
    from lib import privacy
    full = privacy._session_map(str(data_dir))
    vault = privacy.active_vault(str(data_dir), full)
    scan = LineScanner()
    try:
        out = [privacy._redact(page, vault, scan)[0] for page in re.split(r'(?=\[page \d+)', text)]
    finally:
        scan.close()
    full.forward.update(vault.forward)
    full.display.update(vault.display)
    full.counters.update(vault.counters)
    privacy._save(full)
    return ''.join(out)


def prepare(data_dir, paths):
    """Download the PDFs under these @ paths, and write their masked text to Claude's folder. Returns
    {'docs': [{'title', 'local' (in Claude's folder), 'pages', 'cut'}], 'missed': [titles]}."""
    from lib import transforms
    got = transforms.fetch_drive(Path(data_dir), paths, ['pdf'])
    if got.get('error'):
        return {'docs': [], 'missed': [], 'error': got['error']}
    out_dir = home.work_dir(data_dir) / 'docs'
    out_dir.mkdir(parents=True, exist_ok=True)
    docs, missed = [], list(got.get('missed') or [])
    for f in got['files']:
        text = pdf_text(f['path'])
        if not text.strip() or not re.search(r'\w{3,}', re.sub(r'\[page \d+[^\]]*\]', '', text)):
            missed.append(f['title'])  # a scan, with no text to read
            continue
        cut = len(text) > MAX_CHARS
        kept = Path(str(f['path']) + '.masked2.txt')  # masked once per file version (about a minute for 50 pages)
        if kept.is_file() and kept.stat().st_mtime >= Path(f['path']).stat().st_mtime:
            body = kept.read_text()
        else:
            body = _mask(data_dir, text[:MAX_CHARS])
            kept.write_text(body)
        name = re.sub(r'[^\w .()-]+', '_', Path(f['title']).stem).strip(' .')[:80] or 'document'
        local = f'docs/{name}.txt'
        head = (f'Text of the PDF "{_mask(data_dir, f["title"])}", masked by Idli: codes stand for names, places '
                'and other private values.' + (' Only the first part is here.' if cut else '') + '\n\n')
        (home.work_dir(data_dir) / local).write_text(head + body)
        docs.append({'title': f['title'], 'local': local, 'pages': text.count('[page '), 'cut': cut})
    home.write(Path(data_dir) / '.idli' / 'docs-last.json', {'docs': docs})
    return {'docs': docs, 'missed': missed}


def words(docs):
    return ', '.join(d['title'] for d in docs)


def note_for_claude(docs):
    if not docs:
        return ''
    return (' Also the text of ' + str(len(docs)) + (' PDF' if len(docs) == 1 else ' PDFs') + ', masked by Idli: ' +
            ', '.join(d['local'] for d in docs) + '.')


def dumps(docs):
    return json.dumps(docs)
