"""The 9B's instructions have a size budget (owner, 2026-11-21): prefer fixes in code over sentences in the prompt.
A new rule in prose has to replace an old one, or this test fails. Raise a budget only with a reason in the running
list (todos/idli-insights/p1/scaffold_core_round1.md, tagged "prose")."""
import unittest

from lib import idlicli

BUDGET = {'GRAMMAR_HEAD': 5600, 'grammar': 7100, 'STYLE': 1450}  # 2026-11-21: 5,289 / 6,766 / 1,329 characters


class ProseBudget(unittest.TestCase):
    def test_instructions_stay_small(self):
        sizes = {'GRAMMAR_HEAD': len(idlicli.GRAMMAR_HEAD), 'grammar': len(idlicli.grammar()),
                 'STYLE': len(idlicli.STYLE)}
        for k, n in sizes.items():
            self.assertLessEqual(n, BUDGET[k], f'{k} is {n} characters, over its budget of {BUDGET[k]}: '
                                 'fix it in code, or replace an older rule')


if __name__ == '__main__':
    unittest.main()
