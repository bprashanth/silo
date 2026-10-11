# Proposal: a correctness receipt on every data answer

**Status:** proposed, 2026-10-11. **Evidence:** `benchmarks/harness-compare`
(268 jobs) and `narrative/2026-10-11-which-harness-and-what-a-receipt-is.md`.

## Problem

When Silo answers "how much did we spend on travel in Q2?" from a spreadsheet, the
person asking usually can't check it. They need a sign on the answer that tells them
whether to trust it, and the sign should go red when the answer is wrong.

The obvious receipt is provenance: every number in the reply must appear in some tool
output. We built it (`benchmarks/harness-compare/receipt.py`), and it doesn't do this
job. In all 268 jobs local Muse computed its final answer and never typed it from
memory. The wrong answers were computed faithfully from the wrong rows:
- a blank separator row counted as a visit;
- DD/MM dates read as MM/DD;
- a filter that matched nothing, reported as 0.

Provenance was clean on nearly all of them.

## What worked: an independent second computation

Answer the question twice, by routes that don't share their mistakes, and compare.

| check | wrong or missing answers flagged | correct answers flagged |
|---|---|---|
| simple harness, checked by Codex | 9 / 9 | 0 / 125 |
| Codex, checked by the simple harness | 2 / 3 | 7 / 131 (all 7: the checker was the one wrong) |
| Codex, checked by a second Codex run | 1 / 3 | — |
| number tracing alone | 1–2 of 12 | a handful |

A run checked against itself repeats its own mistakes. Different harnesses (prompt,
tooling and context shape) disagree much more usefully, even on the same model.

## Proposal

For every reply that contains a numeric answer drawn from the chat's files:

1. **Primary.** The main harness answers as it does today, ending with a machine-readable
   `ANSWER: <value>` line that the bot strips before sending.
2. **Checker, run in parallel.** A second harness gets only the question and the same files:
   not the primary's answer, code or reasoning. It also ends with `ANSWER:`.
3. **Compare**, with the benchmark's tolerance rules (relative 0.5% by default, exact for
   counts, names compared case-insensitively). Then:
   - they agree → the reply carries **✅ checked: two independent computations agree**;
   - they disagree → **⚠️ not verified**, with both values and one line on each method
     (the filter or rows each used), so a person can see where they part;
   - the checker failed or timed out → **◻️ unchecked**. This is never shown as verified.
4. **Number tracing as a cheap first gate.** If the primary's `ANSWER` doesn't appear in any
   of its tool outputs, the reply is never ✅, even if the checker happens to agree.
   It also flags arithmetic done in prose.
5. **A zero or empty answer is never ✅** unless both sides also report the row count they
   filtered on. "0" is the classic result of a filter that matched nothing.

Questions with no single number (summaries, "what's odd in this sheet?") get no
badge. The proposal is for answers that can be checked, not for everything.

### Which pairing

- **Now:** primary = the bridge's harness, checker = io's Codex profile, both on local
  Muse. That's the measured pair. If the engine flips to Codex as the narrative suggests,
  swap the roles: Codex primary, simple checker.
- **Later:** add diversity in the model as well as the harness, e.g. a second local model
  as the checker. Both harnesses made the same 481 error once, so harness diversity alone
  doesn't remove correlated errors. External models are out, because the checker sees the files.

### What it costs

- **Compute:** twice the compute per checked answer. With 4 llama.cpp slots, that's 2
  concurrent checked questions instead of 4.
- **Latency:** set by the slower of the two. The bridge's harness median is 256 s and
  Codex's is 88 s; lowering the bridge's reasoning effort (untested) should close most of that.
- **Option:** reply with the primary's answer straight away, marked "checking…", then
  edit the message when the checker finishes. Telegram's `editMessageText` allows this.

## Reproducibility (the "same answer every time" goal)

A receipt is only meaningful if re-asking gives the same badge.
- Pin the model file by sha256 and the harness by git commit, and record both in each
  answer's audit record (see [audit-checker.md](audit-checker.md)).
- Use temperature 0 for the primary. llama.cpp with a fixed seed and one slot is
  deterministic; with several busy slots, batching can still change the output.
- Keep a cache keyed by (file hashes, question, model, harness commit) so the same
  question returns the same answer and badge without recomputing.

## How we'd know it works

Re-run `benchmarks/harness-compare` with the checker wired in, and report:
- the share of wrong answers that do not get ✅ (target ≥ 95%);
- the share of correct answers that get ✅ (target ≥ 90%);
- the latency added.

Then repeat on real, anonymised team spreadsheets with questions written by the team and
answers checked by hand, because synthetic cases flatter the method.

## Open questions

- **Disagreement with a weak checker:** when the checker is the one that's wrong, a ⚠️
  costs the person time for nothing. Should a third run break ties, or is showing both
  values the honest answer?
- **Non-numeric answers** (names, lists, "which district"): exact-match on sets probably
  works for lists; free text needs something else.
- **Where the checker runs:** as part of the bridge, or as a separate service that both
  the bridge and future dashboards (io) call.
