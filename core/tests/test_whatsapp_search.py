"""Unit tests for first-class chats/messages schema, entity & coverage resolution,
DuckDB FTS BM25 + fuzzy fallback, episode stitching, get message, and CLI wiring.
Uses synthetic fixtures only (no private chat data)."""
import datetime as dt
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from lib import idlicli, recstore as rs, searchkit as sk


def _ts(year, month, day, hour, minute):
    tz = dt.timezone(dt.timedelta(hours=5, minutes=30))
    return int(dt.datetime(year, month, day, hour, minute, tzinfo=tz).timestamp())


SYNTH_SNAPSHOT = {
    'provider': 'whatsapp',
    'cap': 2000,
    'groups': [
        {
            'id': '120363001@g.us',
            'name': 'Jam Buns 🍞',
            'active_at': _ts(2026, 11, 20, 14, 0),
            'fetched': 6,
            'failed': False,
            'rows': [
                {'id': 'm1', 't': _ts(2026, 11, 2, 11, 20), 'sender': 'Vidya', 'source_type': 'image_caption',
                 'body': "Young Birders' Month is live! Sign up at https://birders.example.org/join"},
                {'id': 'm2', 't': _ts(2026, 11, 18, 10, 0), 'sender': 'Vidya',
                 'body': 'DICE invitation for Nov 25 workshop — please RSVP by Friday.'},
                {'id': 'm3', 't': _ts(2026, 11, 18, 10, 2), 'sender': 'Vidya',
                 'body': 'Also check rainmatter.org for reference'},
                {'id': 'm4', 't': _ts(2026, 11, 20, 13, 12), 'sender': 'Abhiram',
                 'body': "Won't be able to make it to that one."},
                {'id': 'm5', 't': _ts(2026, 11, 20, 13, 13), 'sender': 'Abhiram',
                 'body': 'Sharing my notes doc here: https://docs.google.com/document/d/abc123456789/edit'},
                {'id': 'm6', 't': _ts(2026, 11, 20, 14, 0), 'sender': 'Vikram',
                 'body': 'Budget sheet link: https://example.org/budget'},
            ],
            'relations': [
                {'id': 'm4', 't': _ts(2026, 11, 20, 13, 12), 'type': 'chat', 'sender': 'Abhiram',
                 'parent': 'm2', 'filename': None},
            ],
        },
        {
            'id': '120363002@g.us',
            'name': 'Royal Enfield Climate',
            'active_at': _ts(2026, 11, 19, 16, 0),
            'fetched': 3,
            'failed': False,
            'rows': [
                {'id': 'r1', 't': _ts(2026, 11, 19, 15, 0), 'sender': 'Tejasa',
                 'body': 'Session 1 is 30 minutes and session 2 is 1 hour.'},
                {'id': 'r2', 't': _ts(2026, 11, 19, 15, 2), 'sender': 'Me', 'is_from_me': True,
                 'body': 'Let us do at least 2 rehearsals before Friday.'},
                {'id': 'r3', 't': _ts(2026, 11, 19, 16, 0), 'sender': 'Varun',
                 'body': 'Shared the review form https://docs.google.com/forms/d/xyz987'},
            ],
            'relations': [],
        },
    ],
    'dms': [
        {
            'id': '919999@s.whatsapp.net',
            'name': 'Rinju',
            'is_group': False,
            'active_at': _ts(2026, 11, 21, 9, 0),
            'rows': [
                {'id': 'd1', 't': _ts(2026, 11, 21, 9, 0), 'sender': 'Rinju',
                 'body': 'Field crew update: Shiks leads Pooja and Jency in Pune; second crew heads to Mysuru.'},
            ],
        },
    ],
}


class WhatsAppSearchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sbx = Path(self.tmp.name) / 'sbx'
        self.snap = Path(self.tmp.name) / 'snap.json'
        self.snap.write_text(json.dumps(SYNTH_SNAPSHOT))
        self.con = rs.connect(self.sbx)
        # Sync offline (no embedder/reranker needed for deterministic unit tests)
        self.prev_rerank = os.environ.get('IDLI_RERANK')
        os.environ['IDLI_RERANK'] = '0'
        self.sync_res = rs.sync_whatsapp(self.con, snapshot_path=self.snap, with_embed=False)

    def tearDown(self):
        self.con.close()
        if self.prev_rerank is None:
            os.environ.pop('IDLI_RERANK', None)
        else:
            os.environ['IDLI_RERANK'] = self.prev_rerank
        self.tmp.cleanup()

    def test_sync_ingests_groups_dms_parents_and_episodes(self):
        self.assertEqual(self.sync_res['chats'], 3)
        self.assertEqual(self.sync_res['messages'], 10)
        self.assertGreaterEqual(self.sync_res['episodes'], 3)
        self.assertTrue(self.sync_res['fts'])
        # Verify parent_id edge from WA-JS relations was wired cleanly
        m4_ref = sk.stable_ref('m4')
        m2_ref = sk.stable_ref('m2')
        parent = self.con.execute('SELECT parent_id FROM messages WHERE id = ?', [m4_ref]).fetchone()[0]
        self.assertEqual(parent, m2_ref)
        rc = self.con.execute('SELECT reply_count FROM messages WHERE id = ?', [m2_ref]).fetchone()[0]
        self.assertEqual(rc, 1)

    def test_chat_resolution_exact_partial_acronym_unknown(self):
        # Partial name matches Jam Buns emoji title
        r = idlicli.run_argv(self.con, ['list', 'messages', '--count', '--in', 'Jam Buns', '--where', "links <> ''"])
        self.assertIn('Count: 3 messages match.', r.text)
        self.assertIn('In chat "Jam Buns', r.text)
        # Acronym RE matches Royal Enfield Climate
        crow = sk.resolve_chat(self.con, 'RE')
        self.assertEqual(crow[1], 'Royal Enfield Climate')
        # Unknown group MUST raise EntityNotFoundError, never return Count: 0
        with self.assertRaises(sk.EntityNotFoundError):
            rs.select(self.con, 'messages', folder='Jam Biscuits Review', count=True)

    def test_sender_resolution_unique_ambiguous_and_me(self):
        # Prefix Abhi -> Abhiram inside Jam Buns
        cols, rows, _ = rs.select(self.con, 'messages', folder='Jam Buns', where="sender = 'Abhi'")
        self.assertEqual(len(rows), 2)
        self.assertIn('Sender resolved: Abhiram', rs.LAST_SELECT_NOTE)
        # Ambiguous initial V across all chats -> Vidya, Vikram, Varun
        with self.assertRaises(sk.EntityAmbiguousError) as ctx:
            rs.select(self.con, 'messages', where="sender = 'V' AND links <> ''")
        self.assertIn('Vidya', str(ctx.exception))
        self.assertIn('Vikram', str(ctx.exception))
        # 'me' resolves to is_from_me
        _, rows_me, _ = rs.select(self.con, 'messages', folder='Royal Enfield', where="sender = 'me'")
        self.assertEqual(len(rows_me), 1)
        self.assertIn('rehearsals', rows_me[0][4])

    def test_coverage_note_on_out_of_window_dates(self):
        cols, rows, _ = rs.select(self.con, 'messages', folder='Jam Buns', since='2026-09-01', until='2026-09-30')
        self.assertEqual(rows, [])
        self.assertIn('outside the cached window', rs.LAST_SELECT_NOTE)
        self.assertIn('02 Nov 2026', rs.LAST_SELECT_NOTE)

    def test_fts_stemming_and_fuzzy_typo_fallback(self):
        # Stemming: "birding" matches "Young Birders' Month"
        with mock.patch.object(rs, 'embed', side_effect=RuntimeError('offline')):
            cols, rows, _ = rs.select(self.con, 'messages', folder='Jam Buns', search='birding')
            self.assertTrue(rows)
            self.assertEqual(rows[0][0], sk.stable_ref('m1'))
            # Typo fallback: "young borders month" still recovers m1
            cols2, rows2, _ = rs.select(self.con, 'messages', folder='Jam Buns', search='young borders month')
            self.assertTrue(rows2)
            self.assertEqual(rows2[0][0], sk.stable_ref('m1'))

    def test_dice_thread_parent_and_followup_expansion(self):
        with mock.patch.object(rs, 'embed', side_effect=RuntimeError('offline')):
            cols, rows, _ = rs.select(self.con, 'messages', folder='Jam Buns', search='DICE Abhiram')
            self.assertGreater(sk.LAST_TELEMETRY.get('bm25_msg_hits', 0), 0)
            self.assertGreater(sk.LAST_TELEMETRY.get('bm25_ep_hits', 0), 0)
            returned_ids = {r[0] for r in rows}
            # Should contain the DICE invite (m2), Abhiram's decline quoting m2 (m4), and his 13:13 link (m5)
            self.assertIn(sk.stable_ref('m2'), returned_ids)
            self.assertIn(sk.stable_ref('m4'), returned_ids)
            self.assertIn(sk.stable_ref('m5'), returned_ids)

    def test_get_message_shows_parent_and_neighbors_without_truncating_urls(self):
        m5_ref = sk.stable_ref('m5')
        res = idlicli.run_argv(self.con, ['get', 'message', m5_ref[:8]])
        self.assertIn('https://docs.google.com/document/d/abc123456789/edit', res.text)
        self.assertIn('DICE invitation', res.text)  # quoted parent of neighbor m4!
        self.assertIn("Won't be able to make it", res.text)

    def test_menu_lists_chats_and_empty_tags(self):
        m = idlicli.menu(self.con, question='What did we say in Jam Buns?')
        self.assertIn('messages (10 rows)', m)
        self.assertIn('Empty (not synced, 0 rows', m)
        self.assertIn('Jam Buns', m)

    def test_define_and_item_text_on_message(self):
        name, ver = rs.define(self.con, 'proposal', 'message', 'Does this propose a time?', 'yes,no')
        self.assertEqual((name, ver), ('proposal', 1))
        txt = rs._item_text(self.con, 'message', sk.stable_ref('m4'), '')
        self.assertIn('DICE invitation', txt)
        self.assertIn('Jam Buns', txt)

    def test_own_words_drops_hallucinated_in_chat(self):
        prev_said = idlicli.SAID
        try:
            idlicli.SAID = 'What did Saahas need to procure?'
            cmd, dropped = idlicli.own_words('idli list messages --in "Founders Office @ T4GC" --search "Saahas"')
            self.assertNotIn('--in', cmd)
            self.assertIn('--in Founders Office @ T4GC', dropped)
            # Legitimate chat name or acronym in the question is kept
            idlicli.SAID = 'How many links in Jam Buns?'
            cmd2, dropped2 = idlicli.own_words('idli list messages --in "Jam Buns @ T4GC" --count')
            self.assertIn('--in', cmd2)
            self.assertEqual(dropped2, [])
            idlicli.SAID = 'How long is the RE session?'
            cmd3, dropped3 = idlicli.own_words('idli list messages --in "Royal Enfield" --search "session" --since "today"')
            self.assertIn('--in', cmd3)
            self.assertNotIn('--since', cmd3)
            # 4-letter plural stems cleanly ("runs" -> "run") and explicit date cues are kept
            idlicli.SAID = 'How many practice runs last week?'
            cmd4, dropped4 = idlicli.own_words('idli list messages --search "practice run" --on "last week"')
            self.assertIn('--search', cmd4)
            self.assertIn('--on', cmd4)
            self.assertEqual(dropped4, [])
        finally:
            idlicli.SAID = prev_said

    def test_weak_scope_rescue_finds_cross_chat_match(self):
        with mock.patch.object(rs, 'embed', side_effect=RuntimeError('offline')):
            # "birders" is in Jam Buns, not Royal Enfield; weak-scope rescue finds it and notes the fallback
            cols, rows, _ = rs.select(self.con, 'messages', folder='Royal Enfield', search='birders',
                                      intent='Where was Young Birders Month posted?')
            self.assertTrue(rows)
            self.assertEqual(rows[0][0], sk.stable_ref('m1'))
            self.assertIn('No strong match inside', rs.LAST_SELECT_NOTE)

    def test_body_tilde_rewrites_to_hybrid_search(self):
        with mock.patch.object(rs, 'embed', side_effect=RuntimeError('offline')):
            cols, rows, sql = rs.select(self.con, 'messages', folder='Jam Buns',
                                        where="body ~ 'birding'", intent='Find birders signup')
            self.assertTrue(rows)
            self.assertEqual(rows[0][0], sk.stable_ref('m1'))
            self.assertIn('hybrid_messages', sql)

    def test_humanize_chat_output_for_messages(self):
        with mock.patch.object(rs, 'embed', side_effect=RuntimeError('offline')):
            r = idlicli.run_argv(self.con, ['list', 'messages', '--in', 'Jam Buns', '--search', 'birding'], chat=True)
            txt = idlicli.chat_result(r, 'Find birders signup')
            self.assertIn('Young Birders', txt)
            self.assertIn('Vidya', txt)
            self.assertIn('_In chat "Jam Buns', txt)
            self.assertNotIn('these files', txt)

    def test_merge_list_searches_combines_same_scope_commands(self):
        cmds = [
            'idli list messages --in "Jam Buns @ T4GC" --search "dice" --limit 20',
            'idli list messages --in "Jam Buns @ T4GC" --search "Abhi" --limit 20',
            'idli list messages --in "Jam Buns @ T4GC" --search "doc" --limit 20',
        ]
        merged = idlicli._merge_list_searches(cmds)
        self.assertEqual(len(merged), 1)
        self.assertIn('--search "dice Abhi doc"', merged[0])
        # Different --in scopes are NOT merged
        diff = [
            'idli list messages --in "Jam Buns" --search "dice"',
            'idli list messages --in "Royal Enfield" --search "session"',
        ]
        self.assertEqual(idlicli._merge_list_searches(diff), diff)

    def test_sync_whatsapp_in_filter_scopes_chats(self):
        sbx2 = Path(self.tmp.name) / 'sbx_scoped'
        con2 = rs.connect(sbx2)
        try:
            res = rs.sync_whatsapp(con2, snapshot_path=self.snap, only_chats=['Jam Buns'], with_embed=False)
            self.assertEqual(res['chats'], 1)
            self.assertEqual(res['messages'], 6)
            chats = [r[0] for r in con2.execute('SELECT name FROM chats').fetchall()]
            self.assertEqual(chats, ['Jam Buns 🍞'])
            # Multiple --in selectors (comma or repeated)
            res2 = rs.sync_whatsapp(con2, snapshot_path=self.snap, only_chats=['Jam Buns', 'RE'], with_embed=False)
            self.assertEqual(res2['chats'], 2)
            self.assertEqual(res2['messages'], 9)
        finally:
            con2.close()

    def test_source_type_document_falls_back_to_shared_links(self):
        # Google Docs links are stored as source_type='text' with links <> '';
        # querying source_type='document' with a search relaxes cleanly to shared links when no attachment matches.
        _, rows, _ = rs.select(
            self.con,
            'messages',
            folder='Jam Buns',
            search='dice',
            where="source_type = 'document'",
            limit=10,
        )
        joined = '\n'.join(str(r) for r in rows)
        self.assertIn('docs.google.com', joined)
        self.assertIn('shared links', rs.LAST_SELECT_NOTE)
        # Thread context expansion also pulls in the preceding reply + quoted parent even though they have no links!
        self.assertIn('DICE invitation', joined)

    def test_body_tilde_folds_even_when_search_present(self):
        _, rows, _ = rs.select(
            self.con,
            'messages',
            folder='Jam Buns',
            search='Abhiram',
            where="body ~ 'research'",
            limit=10,
        )
        joined = '\n'.join(str(r) for r in rows)
        self.assertIn('docs.google.com', joined)

    def test_single_letter_search_triggers_ambiguous_sender_clarification(self):
        with self.assertRaises(sk.EntityAmbiguousError) as ctx:
            rs.select(
                self.con,
                'messages',
                folder='Jam Buns',
                search='V',
                order='sent_at desc',
                limit=1,
                intent='What was the last message from V in Jam Buns?',
            )
        self.assertIn('Vidya', str(ctx.exception))
        self.assertIn('Vikram', str(ctx.exception))

    def test_recency_only_topic_detection_and_long_body_render(self):
        self.assertTrue(idlicli._is_recency_only_topic('latest discussion'))
        self.assertTrue(idlicli._is_recency_only_topic('recent updates'))
        self.assertFalse(idlicli._is_recency_only_topic('latest dice discussion'))
        long_text = 'A' * 700 + ' ROYAL_TITLE_END'
        res = idlicli.Result(cols=['id', 'body'], rows=[('m1', long_text)])
        rendered = res.render()
        self.assertIn('ROYAL_TITLE_END', rendered)

    def test_multi_or_body_tilde_does_not_leave_dangling_or(self):
        _, rows, _ = rs.select(
            self.con,
            'messages',
            folder='Jam Buns',
            search='Vidya',
            where="body ~ 'birders' or body ~ 'budget' or body ~ 'dice'",
            limit=10,
        )
        self.assertTrue(len(rows) >= 1)

    def test_post_latest_date_filter_relaxes_while_past_out_of_window_stays_strict(self):
        # Future / post-latest date with --search relaxes to find mentions of upcoming dates
        _, rows_future, _ = rs.select(
            self.con,
            'messages',
            folder='Jam Buns',
            search='DICE',
            since='2026-11-25',
            until='2026-11-25',
            limit=10,
        )
        self.assertTrue(any('DICE' in str(r) for r in rows_future))
        self.assertIn('searched cached messages for mentions', rs.LAST_SELECT_NOTE)
        # Past out-of-window date MUST stay strictly empty with coverage note
        _, rows_past, _ = rs.select(
            self.con,
            'messages',
            folder='Jam Buns',
            search='DICE',
            since='2026-07-01',
            until='2026-07-31',
            limit=10,
        )
        self.assertEqual(rows_past, [])
        self.assertIn('outside the cached window', rs.LAST_SELECT_NOTE)

    def test_run_plan_normalizes_get_message_with_search_to_list(self):
        plan = {'commands': ['idli get message --in "Jam Buns" --search "birding" --text']}
        shown, cmds, _, errs = idlicli.run_plan(self.con, plan, question='birding in Jam Buns')
        self.assertEqual(errs, [])
        self.assertTrue(any('list messages' in c for c in cmds))
        self.assertIn('Birders', '\n'.join(shown))


if __name__ == '__main__':
    unittest.main()
