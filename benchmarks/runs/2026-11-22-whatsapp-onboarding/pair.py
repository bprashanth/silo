"""Single-owner pairing fixture. Run on a trusted DGX, forward loopback over SSH."""
import argparse
from http.server import BaseHTTPRequestHandler, HTTPServer
import os
from pathlib import Path
import secrets
import time
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--chrome', required=True)
    parser.add_argument('--state', required=True, type=Path)
    parser.add_argument('--port', type=int, default=18765)
    args = parser.parse_args()
    os.umask(0o077)
    args.state.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = '/' + secrets.token_urlsafe(24)
    addr = f'127.0.0.1:{args.port}'
    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(
            str(args.state / 'browser'), executable_path=args.chrome, headless=False)
        page = context.pages[0]
        page.goto('https://web.whatsapp.com/', wait_until='domcontentloaded')
        qr = page.locator('canvas[aria-label="Scan this QR code to link a device"]')
        rows = page.locator('#side [role="row"]')
        ready = page.locator('#side').is_visible

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                if self.headers.get('Host') != addr or self.path not in {path, path + '/qr'}:
                    self.send_error(404)
                    return
                if urlsplit(page.url).hostname != 'web.whatsapp.com':
                    self.send_error(503)
                    return
                if self.path == path:
                    mime = 'text/html'
                    if qr.is_visible():
                        body = (f'<p>Use WhatsApp &gt; Linked devices &gt; Link a device.</p>'
                                f'<img src="{path}/qr" alt="WhatsApp device pairing code">')
                    elif ready() and rows.first.is_visible():
                        body = '<p>The chat list is visible. Let the phone finish linking before you close this page.</p>'
                    else:
                        body = '<p>Waiting for WhatsApp. This page updates automatically.</p>'
                    data = (f'<meta http-equiv="refresh" content="4"><title>Idli pilot</title>'
                            f'<h1>Link WhatsApp to your DGX pilot</h1>{body}'
                            '<p>This links a companion device. The pilot reads your self-chat only.</p>').encode()
                elif not qr.is_visible():
                    self.send_error(503)
                    return
                else:
                    mime = 'image/png'
                    try:
                        data = qr.screenshot(timeout=1500)
                    except Exception:
                        self.send_error(503)
                        return
                self.send_response(200)
                self.send_header('Content-Type', mime)
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Referrer-Policy', 'no-referrer')
                self.send_header('Content-Security-Policy', "default-src 'none'; img-src 'self'; frame-ancestors 'none'")
                self.end_headers()
                self.wfile.write(data)

        with HTTPServer(('127.0.0.1', args.port), Handler) as server:
            info = args.state / 'url'
            info.write_text(f'http://{addr}{path}\n')
            server.timeout = 0.5
            deadline = time.monotonic() + 1800
            try:
                settled_since = None
                while time.monotonic() < deadline or settled_since is not None:
                    server.handle_request()
                    if ready() and rows.first.is_visible() and not qr.is_visible():
                        if settled_since is None:
                            settled_since = time.monotonic()
                        if time.monotonic() - settled_since >= 120:
                            print('Chat list stable for two minutes; verify session on reopen.', flush=True)
                            break
                    else:
                        settled_since = None
                else:
                    print('Pairing timed out', flush=True)
            finally:
                info.unlink(missing_ok=True)
                context.close()


if __name__ == '__main__':
    main()
