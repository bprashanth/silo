import io
import unittest
from unittest.mock import patch

from lib import google_api, idlicli


class FirstSyncTest(unittest.TestCase):
    def test_first_sync_prints_url_then_runs_with_selected_account(self):
        def consent(email, open_url):
            self.assertEqual(email, 'tester@example.org')
            open_url('https://example.org/test-consent')

        with (patch.object(google_api, 'connected', return_value=False),
              patch.object(google_api, 'connect', side_effect=consent),
              patch('sys.stdin.isatty', return_value=True),
              patch('sys.stderr', new_callable=io.StringIO) as stderr,
              patch('webbrowser.open') as browser, patch.object(idlicli.rs, 'connect'),
              patch.object(idlicli, 'log'), patch('sys.stdout', new_callable=io.StringIO),
              patch.object(idlicli, 'run_argv') as run):
            self.assertEqual(idlicli.main(['sync', 'gmail', '--as', 'tester@example.org']), 0)
            self.assertIn('https://example.org/test-consent', stderr.getvalue())
            browser.assert_called_once()
            run.assert_called_once()

    def test_missing_unattended_consent_exits_before_opening_store(self):
        with (patch.object(google_api, 'connected', return_value=False),
              patch('sys.stdin.isatty', return_value=False),
              patch('sys.stderr', new_callable=io.StringIO),
              patch.object(idlicli.rs, 'connect') as store):
            self.assertEqual(idlicli.main(['sync', 'gmail']), 2)
            store.assert_not_called()

    def test_existing_grant_skips_browser_in_unattended_sync(self):
        with (patch.object(google_api, 'connected', return_value=True),
              patch.object(google_api, 'connect') as consent,
              patch.object(idlicli.rs, 'connect'), patch.object(idlicli, 'log'),
              patch('sys.stdout', new_callable=io.StringIO), patch.object(idlicli, 'run_argv') as run):
            self.assertEqual(idlicli.main(['sync', 'gmail']), 0)
            run.assert_called_once()
            consent.assert_not_called()
