# Operator assist: protocol cards (prototype)

**Question.** Should the assist give the ERC call-taker protocol guidance during important calls, or only collect
data?

**What real systems do.** The systems with published methods guide the non-clinical call-taker, within strict
limits:

- **MPDS (ambulance dispatch).**
  - The chief complaint selects a card.
  - The card's key questions set a determinant code (Ω, A–E), which sets the response.
  - The call-taker reads scripted pre-arrival instructions.
- **NHS Pathways (NHS 111).**
  - Non-clinical advisers follow symptom-based algorithms to an endpoint with a level of care and a time frame.
  - They give care advice and "call back if worse" advice.
  - A restricted module is for clinicians, who validate or take over.
- **The 1962 veterinary ERCs.**
  - The call-taker collects the case.
  - A vet at the centre triages and gives online medical direction, or dispatches the mobile unit (Tamil Nadu,
    Kerala, Assam).
  - BFIL's Madhya Pradesh and Maharashtra lines describe "tele consultation or schedule a visit based on the
    severity". Their severity mapping is not public. I could not verify another agent's "108 diseases" figure.

**Decision: guide, within limits.**
- **Yes:**
  - The extra key questions for the complaint.
  - A rule-based priority, with the escalation it requires (E: bring the vet on, dispatch now).
  - A few pre-approved lines to read out.
  - The call-back-if-worse line.
- **No:** diagnosis, disease names or medicines to the farmer. Those belong to the vet.
- **For the vet:** DAHD's Standard Veterinary Treatment Guidelines (2024) are referenced only in the vet handoff.
  This matches the other agent's three layers (intake / triage / clinical). The clinical layer stays with the
  vet, so it is a reference in the handoff, not live guidance.

**Built** as one revertable commit:
- New files: `assist/protocol.py`, `assist/protocol_cards.json`, `assist/tests/test_protocol.py`, and a role-play
  script that follows the cards.
- Small hooks in `server.py` and the page.
- `ASSIST_PROTOCOL=0` turns it off at runtime.

The cards render inside the care record column, keeping the two-column screen.

**What the live role-play caught on the way:** Muse, offered every card field, filled them with the nearest
words:
- "Ate what" got the operator's goodbye.
- "Age" got "two of them are coughing".
- A bare "No" landed in three fields.
- "How old was the small one?" counted as confirming one death.

The fix:
- A farmer answer fills only the fields just asked about, or the fields of a card her words opened, when her
  words are about them.
- An operator line only confirms what the farmer said, and a wh-question isn't a repeat.
- Every value needs its words in the line.

The cards and lines are illustrative and need a vet's sign-off. The real input would be the ERC's own
severity mapping and SOPs.
