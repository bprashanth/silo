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
