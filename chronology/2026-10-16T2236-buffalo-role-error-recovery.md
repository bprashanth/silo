# Recover animal report sent while in vet mode

The latest repeated report failed because the owner had selected /vet and had no active assignment. The engine correctly rejected a vet report without a case, but the Telegram adapter hid this actionable state behind its generic processing-error message. The adapter now explains vet mode and the /farmer or operator-assignment next steps. The vet greeting also makes this distinction explicit.

Replaying the report against actual Muse in a scratch database separately reproduced empty extraction and the earlier animal-question loop. Added a narrow grounded fallback for unambiguous animal mentions and explicitly stated weakness, with questions and negated statements excluded. This does not constitute general conversational clarification support.

Twenty-nine regression tests pass, including unassigned-vet guidance, empty-extraction recovery and negation. Restored the owner's farmer role and requeued only the most recent failed report, retaining earlier retries as failure history. The live bot successfully processed it into the existing intake: animal type cow, symptoms weak, then asked about inability to stand, breathing difficulty or unconsciousness. The inbox is done and the Telegram reply succeeded. No case was submitted or confirmed on the user's behalf. Original io bot remains untouched.
