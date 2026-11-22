"""Capture only a verified group message bubble in a disposable, offline linked-client copy."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import os
import shutil
import tarfile
import tempfile
from playwright.sync_api import sync_playwright

parser = argparse.ArgumentParser(description=__doc__)
for name in ('profile', 'chrome', 'tgz', 'snapshot', 'manifest', 'out'):
    parser.add_argument('--' + name, required=True, type=Path)
args = parser.parse_args()
os.umask(0o077)
args.out.mkdir(exist_ok=True)
groups = json.loads(args.snapshot.read_text())['groups']
manifest = json.loads(args.manifest.read_text())
digest = base64.b64encode(hashlib.sha512(args.tgz.read_bytes()).digest()).decode()
if digest != '3xMNZt/rCrJKZBmfD428LsaGakYGvq4vNmH+AzKM2uf7x3/XL4tpyqKO/MtB7NFQmh8UlL957tGOu3i5iMOQqw==':
    raise ValueError('Unexpected WA-JS archive')
with tarfile.open(args.tgz) as archive:
    script = archive.extractfile('package/dist/wppconnect-wa.js').read().decode()
with tempfile.TemporaryDirectory() as tmp, sync_playwright() as pw:
    profile = Path(tmp) / 'profile'
    shutil.copytree(args.profile, profile, ignore=shutil.ignore_patterns('Singleton*', '*Cache*'))
    ctx = pw.chromium.launch_persistent_context(profile, executable_path=args.chrome,
                                               headless=False, args=['--disable-background-networking'])
    try:
        page = ctx.pages[0]
        page.goto('https://web.whatsapp.com/', wait_until='domcontentloaded')
        page.locator('#side [role=row]').first.wait_for(timeout=60000)
        ctx.set_offline(True)
        page.evaluate(script)
        for _ in range(80):
            if page.evaluate('Boolean(window.WPP?.isReady)'):
                break
            page.wait_for_timeout(250)
        for key, name, ref in manifest:
            group, = [g for g in groups if g['name'] == name and g['id'].endswith('@g.us')]
            row, = [r for r in group['rows'] if hashlib.sha256(r['id'].encode()).hexdigest()[:20] == ref]
            page.evaluate('([g,id]) => WPP.chat.openChatAt(g,id)', [group['id'], row['id']])
            stanza = row['id'].split('_')[2]
            page.locator('#main header').get_by_text(name, exact=True).first.wait_for(timeout=12000)
            bubble = page.locator('#main [data-id="' + stanza + '"]')
            bubble.wait_for(timeout=12000)
            if not any(w in bubble.inner_text() for w in row['body'].split() if len(w) >= 4):
                raise ValueError('Visible bubble differs from snapshot')
            bubble.screenshot(path=args.out / (key + '.png'))
            print(key, flush=True)
    finally:
        ctx.close()
