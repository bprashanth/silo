# Harness comparison results

Run: `benchmarks/harness-compare/runs/2026-10-11-muse-q4d`. 67 questions × 2 harnesses ×
2 trials = 268 jobs on local Muse Q4 + drafter, 4 at a time, about 5 hours of wall time.

| | io Codex | simple harness |
|---|---|---|
| correct | 131/134 (97.8%) | 125/134 (93.3%) |
| wrong | 3 | 5 |
| missing | 0 | 4, all HTTP 500 malformed tool calls |
| median / p90 seconds | 88 / 173 | 256 / 443 |
| median output tokens | 1.6k | 4.2k |
| median input tokens | 117k (mostly cached) | 38k |
| audit flags | none | none |

Per case, Codex was ≥ simple on every case except `field_log` (10/12 vs 11/12). The
big gap is `big_ledger`: 20k rows, two registers plus a lookup join, 12/12 vs 8/12.
3 of the simple harness's 4 misses there hit the 12-step limit.

**Traps.** The plain variants, worded without hints, scored 39/40. The only
miss was a 500. Muse noticed subtotal rows, offset headers, the second table,
uncached formulas and mixed units by itself in both harnesses.

**Wrong answers are logic errors, not invented numbers.** In all 268 jobs the final
answer number appeared in a tool output. The errors were:
- a blank separator row read as a unique visit, giving 481 visits instead of 480, which both
  harnesses did;
- DD/MM dates parsed as MM/DD;
- filters that dropped rows;
- a filter that matched nothing, answered as 0.

So tracing numbers to tool output (`receipt.py`) caught 1–2 real errors. Its
other flags were mostly arithmetic done in prose, which it is right to flag, but which
does not predict a wrong answer.

**Disagreement does catch them.**
- Checking each simple answer against Codex's answer for the same question flagged 9/9 of
  the simple harness's non-correct answers and 0/125 of its correct ones.
- Checking Codex against the simple harness flagged 2/3 and 7/131. Every one of those 7
  false alarms was a case where the simple harness itself was wrong.
- A harness checked against its own second run does worse: Codex catches 1/3, because
  its errors repeat.

**Speed.** The simple harness is slower because Muse reasons more there: 4.2k output
tokens against 1.6k. Codex asks for `model_reasoning_effort = "low"`. Turning reasoning
down in the simple harness has not been tried yet.

**Audit.** Neither harness attempted network access, touched paths outside its
workspace, or had a sandbox refusal. Codex used no tools other than shell. Its actions are
`bash -lc` strings, mostly `python3 -c` and heredocs; the simple harness's are
whole Python scripts. The first pass flagged "network_attempt" 8 times; all 8 were false:
the `nc` pattern matched `"\nColumns"`. The pattern is fixed.

**Fixes made from this run.**
- `harness.retrying()` re-samples on a llama.cpp 500. The 4 failed jobs were re-run in
  `runs/2026-10-11-muse-q4d-retry500`: 3 correct, 1 wrong with the 481 mistake.
- `receipt.py` now handles grouped numbers (Western, Indian and spaced), skips dates,
  flags a 0 answer, and uses the fixed network pattern. `summarize.py` recomputes
  receipts and audits from transcripts.
- The bot was restarted with the retry.

**Limits.** 9 synthetic cases, 2 trials, one model. Codex ran without io's masking
proxy, which is not needed for a local model. The generated questions mostly state their
conventions; the 10 plain variants are the only test of noticing problems unprompted.
