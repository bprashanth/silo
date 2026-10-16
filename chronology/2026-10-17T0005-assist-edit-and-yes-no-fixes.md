# Call center assist: an edit button, and fixes from the user's 23:40 call

The user took a live loose-motions call (session `20261016-234019-929f94`) and found four problems.

**A question counted as a confirmation.**
- ASR gave "is the breathing normal." without a "?". Muse returned `breathing_ok: true` for the operator's line.
  `said_by_operator` always kept yes/no facts, so the field showed *yes, confirmed* before the farmer had
  answered.
- Fix: an operator yes/no fact needs its topic in a sentence that is not a yes/no question (is/are/can/does/...).
  "Not able to stand, right?" and "And the breathing is normal." still count.
- Now the farmer's "breathing is fine" fills the field as *heard only* until the operator repeats it.
- "breathing normal" no longer lands in Problem either.

**Animals sick stayed empty.**
- "My three Adu have bidi" and "my three Adu are sick" gave no count. Muse put "three" in *Since* instead.
- Fix: a rule backstop, `nlu.count_sick`, reads "N are sick", "N of them" and "N <animal word>" (with `adu`
  added to the Kannada aliases).
- *Since* now needs a time word, so "three" and "after grazing near the tank" are dropped from it.

**The name went into Problem.**
- "My name is Lakshmama from Hasa Hali." gave only a symptom.
- Fix: "my name is X" fills the name. "from X" fills the village when X matches the gazetteer. Name and place
  phrases are kept out of Problem.

**The village was the taluk.**
- From "Hassaheli Kanakapura Talak, Ramanagara District", Muse took Kanakapura or Ramanagara as the village.
- Fix: a village that is really a taluk or district is replaced by a gazetteer village named in the same line.

**Edit button.**
- Every field (record and protocol cards) has ✎. A typed value wins, shows as *edited*, survives later turns,
  and can be cleared.
- New endpoint: `POST /api/sessions/{id}/edit {field, value}`.
- Polling doesn't redraw the record while a field is being edited.

**Landing page** (:8770) is now plain: the headline "Helpline service" and two bordered cards. No colours, no
status dots and no extra text.

**Verified.**
- 58 unit tests pass, 4 of them new from this call.
- Live young-jowar: 10/11 fields, QA 13/15 (same as before). The village is now *confirmed*, and the browser
  edit check passed.
- Live case 2: 11/11. Recorded buffalo: 11/11, edit passed.
- `nlu.py` is shared, so the agent call (:8775) was restarted with the same fixes.
