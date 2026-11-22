"""Capture bounded text evidence from active groups using a linked WhatsApp Web profile."""
import argparse
import calendar
import hashlib
import json
import os
import tarfile
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright

CAP = 2000
HERE = Path(__file__).resolve().parent


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--profile', required=True, type=Path)
    ap.add_argument('--chrome', required=True)
    ap.add_argument('--wa-js-tgz', required=True, type=Path)
    ap.add_argument('--out', required=True, type=Path)
    ap.add_argument('--all-active', action='store_true', help='default is the Jam Buns smoke test')
    args = ap.parse_args()
    os.umask(0o077)
    now = datetime.now(ZoneInfo('Asia/Kolkata'))
    year, month = (now.year, now.month - 1) if now.month > 1 else (now.year - 1, 12)
    since = now.replace(year=year, month=month, day=min(now.day, calendar.monthrange(year, month)[1]))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    if args.out.exists():
        ap.error('Choose a new snapshot path')
    import base64
    digest = base64.b64encode(hashlib.sha512(args.wa_js_tgz.read_bytes()).digest()).decode()
    if digest != '3xMNZt/rCrJKZBmfD428LsaGakYGvq4vNmH+AzKM2uf7x3/XL4tpyqKO/MtB7NFQmh8UlL957tGOu3i5iMOQqw==':
        ap.error('Expected the published @wppconnect/wa-js 4.8.2 npm archive')
    with tarfile.open(args.wa_js_tgz) as archive:
        js = archive.extractfile('package/dist/wppconnect-wa.js').read().decode()
    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(str(args.profile), executable_path=args.chrome, headless=False)
        try:
            page = context.pages[0]
            page.goto('https://web.whatsapp.com/', wait_until='domcontentloaded')
            page.locator('#side [role=row]').first.wait_for(timeout=60000)
            context.set_offline(True)
            page.evaluate(js)
            for _ in range(80):
                if page.evaluate('Boolean(window.WPP?.isReady)'):
                    break
                time.sleep(0.25)
            result = page.evaluate((HERE / 'groups.js').read_text(), dict(
                since=since.timestamp(), until=now.timestamp(), all=args.all_active, cap=CAP))
        finally:
            context.close()
    result.update(since=since.isoformat(), as_of=now.isoformat(), cap=CAP)
    with args.out.open('x') as out:
        json.dump(result, out)
    print('Groups selected:', len(result['groups']), 'text messages:', sum(len(g['rows']) for g in result['groups']),
          'read errors:', sum(g['failed'] for g in result['groups']))


if __name__ == '__main__':
    main()
