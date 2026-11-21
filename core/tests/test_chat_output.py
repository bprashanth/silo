import unittest

from lib.idlicli import Result, chat_result, parser


class ChatOutputTest(unittest.TestCase):
    def test_shell_default(self):
        self.assertEqual(parser().parse_args(['ask', 'hello']).output, 'shell')

    def test_search_list(self):
        r = Result(['name', 'found'], [('Report.pdf', 'phrase x12; p.2: ...excerpt...')])
        self.assertEqual(chat_result(r), 'The words occur together in 1 of these files.\n\n• Report.pdf — phrase mentioned 12×, p. 2')
        self.assertIn('1 row (name, found)', r.render())

    def test_empty_list(self):
        self.assertEqual(chat_result(Result()), 'I couldn’t find a match.')


class SignalSourceTest(unittest.TestCase):
    def setUp(self):
        import duckdb
        from lib import recstore
        self.db = duckdb.connect(':memory:')
        self.db.execute(recstore.DDL)
        self.addCleanup(self.db.close)

    def test_two_ashas_and_latest_outgoing(self):
        from lib.idlicli import account, last_sent_reply
        for mid, direction, name, address, to, day in [
            ('old', 'out', 'Me', 'me@example.org', 'Asha Rao <rao@example.org>', 1),
            ('latest', 'out', 'Me', 'me@example.org', 'Asha Rao <rao@example.org>', 2),
            ('new-thread', 'out', 'Me', 'me@example.org', 'rao@example.org', 5),
            ('in', 'in', 'Asha Shah', 'shah@example.org', 'me@example.org', 3),
            ('later', 'in', 'Asha Rao', 'rao@example.org', 'me@example.org', 4),
        ]:
            self.db.execute('INSERT INTO mail (id,thread_id,direction,from_name,from_addr,to_addrs,date,account,body_text) '
                            'VALUES (?,?,?,?,?,?,?,?,?)',
                            [mid, mid, direction, name, address, to, f'2026-11-0{day}', account(), mid+' body'])
        self.db.execute("UPDATE mail SET thread_id='latest', date='2026-10-31' WHERE id='later'")
        prompt, clarify = last_sent_reply(self.db, 'Show me what I responded to Asha with last', [])
        self.assertTrue(clarify)
        self.assertIn('shah@example.org', prompt)
        answer, clarify = last_sent_reply(self.db, 'rao@example.org', [{'clarify_recipient': clarify}])
        self.assertFalse(clarify)
        self.assertIn('latest body', answer)
        self.assertIn('https://mail.google.com/mail/#all/latest', answer)
        self.assertNotIn('later body', answer)

    def test_duplicate_names_have_distinct_links(self):
        from lib.idlicli import run_argv
        self.db.execute("INSERT INTO files (id,name,kind,size) VALUES ('id-A','Report.pdf','pdf',10),"
                        "('id-B','Report.pdf','pdf',10)")
        result = run_argv(self.db, ['list', 'files', '--all'], chat=True)
        self.assertEqual(set(result.links), {'https://drive.google.com/open?id=id-A',
                                            'https://drive.google.com/open?id=id-B'})
        self.assertNotIn('id-A', result.render())

    def test_budget_query_links_the_underlying_workbook(self):
        from lib.idlicli import run_argv
        self.db.execute('CREATE TABLE march_budget(category VARCHAR, period VARCHAR, amount INTEGER)')
        self.db.execute("INSERT INTO march_budget VALUES ('Travel','March',1200),('Travel','March',800),"
                        "('Travel','April',900),('Catering','March',600),('Subtotal','March',2600)")
        self.db.execute("INSERT INTO sheets (file_id,tab,tbl,name) VALUES ('budget-id','Budget','march_budget','Events')")
        result = run_argv(self.db, ['query', "SELECT sum(amount) AS travel_inr FROM march_budget "
                                            "WHERE category='Travel' AND period='March'"], chat=True)
        self.assertEqual(result.rows, [(2000,)])
        self.assertIn('https://drive.google.com/open?id=budget-id', chat_result(result))

    def test_explicit_link_projection(self):
        from lib.idlicli import run_argv
        self.db.execute("INSERT INTO files (id,name,kind,size) VALUES ('event-id','Royal Enfield invite.pdf','pdf',10)")
        result = run_argv(self.db, ['list', 'files', '--fields', 'name, link', '--search', '"Royal Enfield"'], chat=True)
        self.assertIn('https://drive.google.com/open?id=event-id', chat_result(result))

    def test_distinct_count_uses_named_tab_and_preserves_filters(self):
        from lib.idlicli import sheet_distinct_count
        self.db.execute('CREATE TABLE blocks("Block code" VARCHAR)')
        self.db.execute("INSERT INTO blocks VALUES ('A'), ('A'), (''), ('B'), (NULL)")
        self.db.execute("INSERT INTO sheets (file_id,tab,tbl,name) VALUES ('source-id','Raw','blocks','Plots.xlsx')")
        reply, _ = sheet_distinct_count(self.db, 'In the Raw tab of Plots.xlsx, how many distinct block codes are there?')
        self.assertIn('2 distinct nonblank values', reply)
        self.assertIn('open?id=source-id', reply)
        self.assertIsNone(sheet_distinct_count(self.db, 'How many distinct block codes are in Plots.xlsx / Raw for March?'))
