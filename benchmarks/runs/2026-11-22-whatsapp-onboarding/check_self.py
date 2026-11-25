"""Check the synthetic pilot message, exposing only the result to the operator."""
import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--io-reader', required=True, type=Path)
    parser.add_argument('--chrome', required=True)
    parser.add_argument('--state', required=True, type=Path)
    parser.add_argument('--private-config', required=True, type=Path)
    args = parser.parse_args()
    sys.path.insert(0, str(args.io_reader.resolve()))
    from cdp_transport import WhatsAppCDP, BrowserGap
    from whatsapp_reader import WhatsAppReader

    class PageTransport(WhatsAppCDP):
        # The io reader uses an Electron webview. Bind the same self-only navigation to our dedicated page.
        def read(self, function, args=None):
            if urlsplit(page.url).hostname != 'web.whatsapp.com':
                raise BrowserGap('WhatsApp origin required')
            return page.evaluate(function, args or {})

        def _click_sidebar(self, xy):
            if not self.read("p => !!document.elementFromPoint(p.x,p.y)?.closest('#side [role=row]')", xy):
                raise BrowserGap('Self row moved')
            page.mouse.click(xy['x'], xy['y'])
            page.wait_for_timeout(350)

    config = json.loads(args.private_config.read_text())
    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(
            str(args.state / 'browser'), executable_path=args.chrome, headless=False)
        try:
            page = context.pages[0]
            page.goto('https://web.whatsapp.com/', wait_until='domcontentloaded')
            page.locator('#side [role="row"]').first.wait_for(timeout=60000)
            release_notes = page.get_by_role('dialog').filter(has_text='What’s new on WhatsApp Web')
            if release_notes.is_visible():
                release_notes.get_by_role('button', name='Continue', exact=True).click()
                release_notes.wait_for(state='hidden')
            reader = WhatsAppReader(PageTransport(), self_phone=config['self_phone'])
            result = reader.self_read(limit=20, include_text=True)
            found = any('Idli pilot: blue notebook 47' == (row.get('text') or '').strip()
                        for row in result['records'])
            print('Pilot marker found in verified self-chat.' if found else
                  'Marker missing from the visible window of the verified self-chat.')
            return 0 if found else 1
        except Exception:
            print('Read incomplete. Check device linking and that the self-chat is visible.', file=sys.stderr)
            return 2
        finally:
            context.close()


if __name__ == '__main__':
    sys.exit(main())
