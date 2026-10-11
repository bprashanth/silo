# Re-run of the 4 jobs that failed with HTTP 500

In `../2026-10-11-muse-q4d`, four simple-harness jobs got no answer: llama.cpp
returned 500 "The model produced output that does not match the expected
peg-native format", which means Muse emitted a malformed tool call on the
chat-completions path. Codex uses `/v1/responses` and never hit this.

`harness.retrying()` now re-samples up to 3 times on a 500. With that fix, the same
four questions (trial 0 here) came back as follows:

| question | result |
|---|---|
| field_log.q5 | wrong, 30.56 (the same 481-visit mistake Codex made) |
| mixed_units.q2 | correct |
| mixed_units.q5 | correct |
| two_tables.q1_plain | correct |
