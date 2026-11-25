"""End-to-end unit and isolation tests for bridges/onboard and multi-tester Signal handoff."""
import json
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

from bridges.onboard.server import OnboardConfig, start_server
from bridges.onboard.store import OnboardStore, extract_intent_signals
from bridges.signal.bridge import handle_multi_turn


def _make_snapshot(path: Path):
    snap = {
        'provider': 'whatsapp',
        'window_days': 14,
        'groups': [
            {
                'id': 'g_jb',
                'name': 'Jam Buns @ T4GC',
                'rows': [
                    {'id': 'm1', 't': '2026-11-20T13:13:00+05:30', 'sender': 'Abhiram', 'sender_id': 'u1',
                     'body': 'Sharing the DICE doc: https://docs.google.com/document/d/abc/edit',
                     'links': ['https://docs.google.com/document/d/abc/edit']},
                ],
            },
            {
                'id': 'g_ac',
                'name': 'Internal Core Group for Acumen @ T4GC',
                'rows': [
                    {'id': 'm2', 't': '2026-11-23T10:00:00+05:30', 'sender': 'Yashaswi', 'sender_id': 'u2',
                     'body': 'Updated Acumen report is ready for review.'},
                ],
            },
            {
                'id': 'g_priv',
                'name': 'Family Chat (Private)',
                'rows': [
                    {'id': 'm3', 't': '2026-11-23T11:00:00+05:30', 'sender': 'Mom', 'sender_id': 'u3',
                     'body': 'CANARY_PRIVATE_FAMILY_SECRET'},
                ],
            },
        ],
        'dms': [],
    }
    path.write_text(json.dumps(snap))


class OnboardAndSignalIsolationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.snap = self.root / 'snapshot.json'
        _make_snapshot(self.snap)
        self.store = OnboardStore(self.root / 'state')
        self.cfg = OnboardConfig(
            store=self.store,
            public_base='http://127.0.0.1:0',
            demo=True,
            wa_snapshot=str(self.snap),
            skip_embed=True,
        )
        self.srv = start_server(self.cfg, host='127.0.0.1', port=0)
        self.port = self.srv.server_address[1]
        self.base = f'http://127.0.0.1:{self.port}'
        self.cfg.public_base = self.base
        self.thread = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.tmp.cleanup()

    def _post(self, path, payload=None):
        data = json.dumps(payload or {}).encode()
        req = urllib.request.Request(self.base + path, data, {'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.load(r)

    def test_intent_signal_extraction(self):
        sig = extract_intent_signals(
            'I work on leads tracker and events here https://drive.google.com/drive/folders/xyz123',
            available_folders=[{'name': 'Leads & Partnerships'}, {'name': 'Events & Content Calendar'}, {'name': 'Finance'}],
            available_chats=[{'name': 'Jam Buns @ T4GC'}, {'name': 'Events Team'}],
        )
        self.assertEqual(sig['drive_links'], ['https://drive.google.com/drive/folders/xyz123'])
        self.assertIn('Leads & Partnerships', sig['suggested_folders'])
        self.assertIn('Events & Content Calendar', sig['suggested_folders'])
        self.assertIn('Events Team', sig['suggested_chats'])

    def test_full_signal_to_web_to_signal_flow_and_two_tester_canary_isolation(self):
        # 1. Single-use invite enforcement
        inv_a = self.store.create_invite(label='Tester A')
        inv_b = self.store.create_invite(label='Tester B')
        # Unknown stranger in invite-only mode is ignored
        self.assertIsNone(handle_multi_turn(self.store, 'aci-stranger', 'hello', self.base, invite_only=True))

        # Tester A redeems invite A -> gets setup link
        r_a = handle_multi_turn(self.store, 'aci-a', f'invite {inv_a}', self.base, invite_only=True)
        self.assertIn('/setup/', r_a)
        tok_a = r_a.split('/setup/')[1].split()[0]

        # Replaying Tester A's invite from Tester B fails!
        replay = handle_multi_turn(self.store, 'aci-b', f'invite {inv_a}', self.base, invite_only=True)
        self.assertIn('already been redeemed', replay)

        # Tester B redeems their own invite B -> gets their own setup link
        r_b = handle_multi_turn(self.store, 'aci-b', f'invite {inv_b}', self.base, invite_only=True)
        tok_b = r_b.split('/setup/')[1].split()[0]

        # 2. Tester A connects Google + WhatsApp, selects ONLY "Jam Buns @ T4GC", saves role & intended use, syncs!
        self._post(f'/setup/{tok_a}/google/demo')
        self._post(f'/setup/{tok_a}/whatsapp/connect')
        _, st_a = self._post(f'/setup/{tok_a}/sync', {
            'selected_drive_folders': ['Leads & Partnerships'],
            'selected_wa_chats': ['Jam Buns @ T4GC'],
            'role': 'Partnerships',
            'intended_use': 'I work on converting leads in the leads tracker.',
        })
        code_a = st_a['confirm_code']
        self.assertEqual(len(code_a), 6)

        # Tester B selects ONLY "Internal Core Group for Acumen @ T4GC"
        self._post(f'/setup/{tok_b}/whatsapp/connect')
        _, st_b = self._post(f'/setup/{tok_b}/sync', {
            'selected_drive_folders': [],
            'selected_wa_chats': ['Internal Core Group for Acumen @ T4GC'],
            'role': 'Insights',
            'intended_use': 'Analyse connections across docs and sheets.',
        })
        code_b = st_b['confirm_code']

        # 3. Cross-account confirmation attack MUST fail (forwarded link / stolen code cannot activate other ACI)
        bad_conf = handle_multi_turn(self.store, 'aci-b', f'confirm {code_a}', self.base, invite_only=True)
        self.assertIn('does not match', bad_conf)

        # 4. Legitimate Signal DM confirmations activate each tester in their own sandbox
        ok_a = handle_multi_turn(self.store, 'aci-a', f'confirm {code_a}', self.base, invite_only=True)
        self.assertIn('now active', ok_a)
        ok_b = handle_multi_turn(self.store, 'aci-b', f'confirm {code_b}', self.base, invite_only=True)
        self.assertIn('now active', ok_b)

        # 5. Verify REAL DuckDB isolation + --in scoping (neither tester synced Family Chat canary!)
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'core'))
        from lib import recstore as rs

        t_a = self.store.get_tester_by_aci('aci-a')
        t_b = self.store.get_tester_by_aci('aci-b')
        self.assertNotEqual(t_a['sandbox_dir'], t_b['sandbox_dir'])

        con_a = rs.connect(t_a['sandbox_dir'], read_only=True)
        con_b = rs.connect(t_b['sandbox_dir'], read_only=True)
        try:
            chats_a = [r[0] for r in con_a.execute('SELECT name FROM chats').fetchall()]
            chats_b = [r[0] for r in con_b.execute('SELECT name FROM chats').fetchall()]
            bodies_a = ' '.join(r[0] for r in con_a.execute('SELECT body FROM messages').fetchall())
            bodies_b = ' '.join(r[0] for r in con_b.execute('SELECT body FROM messages').fetchall())
        finally:
            con_a.close()
            con_b.close()

        self.assertEqual(chats_a, ['Jam Buns @ T4GC'])
        self.assertEqual(chats_b, ['Internal Core Group for Acumen @ T4GC'])
        self.assertNotIn('CANARY_PRIVATE_FAMILY_SECRET', bodies_a)
        self.assertNotIn('CANARY_PRIVATE_FAMILY_SECRET', bodies_b)
        self.assertNotIn('Acumen', bodies_a)
        self.assertNotIn('DICE', bodies_b)

        # Verify profile.json persisted privately for both testers
        prof_a = json.loads((Path(t_a['sandbox_dir']) / 'profile.json').read_text())
        self.assertEqual(prof_a['role'], 'Partnerships')
        self.assertIn('leads tracker', prof_a['intended_use'])

        # 6. Verify Signal routing passes each tester's own sandbox to ask_fn
        seen = []
        def fake_ask(q, sandbox=None, extra_env=None):
            seen.append((q, sandbox, extra_env))
            return f'answered from {Path(sandbox).name}'

        rep_a = handle_multi_turn(self.store, 'aci-a', 'find dice doc', self.base, ask_fn=fake_ask)
        rep_b = handle_multi_turn(self.store, 'aci-b', 'acumen status', self.base, ask_fn=fake_ask)
        self.assertIn(t_a['tester_id'], rep_a)
        self.assertIn(t_b['tester_id'], rep_b)
        self.assertEqual(seen[0][1], t_a['sandbox_dir'])
        self.assertEqual(seen[1][1], t_b['sandbox_dir'])

        # 7. Disconnect deletes sandbox data and blocks further turns
        disc = handle_multi_turn(self.store, 'aci-a', 'disconnect', self.base, ask_fn=fake_ask)
        self.assertIn('Disconnected', disc)
        self.assertFalse((Path(t_a['sandbox_dir']) / 'store.duckdb').exists())
        after_disc = handle_multi_turn(self.store, 'aci-a', 'find dice doc', self.base, ask_fn=fake_ask)
        self.assertIn('/setup/', after_disc)


if __name__ == '__main__':
    unittest.main()
