"""A scripted farmer for role-playing the operator: answers what the operator just asked, from recorded clips.

The clips are fixed (assist/scenarios.json, rendered by make_scenarios.py), so the same farmer can be
replayed to many operators. The farmer corrects a wrong read-back ("No madam, Kunigal"), gives the
"_again" variant when asked twice, says "Yes, correct" to a right read-back, and "I could not hear"
when the operator's words don't ask anything it knows.
"""
import re
from collections import Counter
import assist as assist_mod

def right(k, said, truth):
    if k == 'contact_details': return re.sub(r'\D', '', str(said))[-10:] == truth
    if k == 'symptoms':  # every real symptom made it into the record
        said = said if isinstance(said, list) else [said]
        return all(any(assist_mod.same(s, t) for s in said) for t in truth)
    return assist_mod.same(said, truth)

class ScriptedFarmer:
    def __init__(self, scenario):
        self.sc, self.truth, self.lines = scenario, scenario['truth'], scenario['lines']
        self.used = Counter(); self.opened = False; self.whats = 0

    def undo(self):
        """The operator kept talking before the farmer answered: forget that reply."""
        if getattr(self, '_saved', None): self.used, self.opened, self.whats = self._saved; self._saved = None

    def reply(self, asking, facts, text=''):
        """-> clip key, or None to stay quiet."""
        self._saved = (self.used.copy(), self.opened, self.whats)
        if re.search(r'\b(good ?bye|bye)\b', text, re.I): return 'bye'
        for k, v in (facts or {}).items():  # a wrong read-back gets corrected first (not symptoms: any wording will do)
            if k in self.truth and k != 'symptoms' and v not in (None, '', []) and not right(k, v, self.truth[k]):
                return f'no_{k}' if f'no_{k}' in self.lines else 'no_other'
        if not self.opened and asking in (None, 'greeting', 'symptoms', 'other'):
            self.opened = True; return 'opening'
        self.opened = True
        if asking in assist_mod.REQUIRED:
            key = f'{asking}_again' if self.used[asking] and f'{asking}_again' in self.lines else asking
            self.used[asking] += 1; self.whats = 0; return key
        if asking == 'summary' or facts: self.whats = 0; return 'yes'
        self.whats += 1
        return 'what' if self.whats <= 2 else None
