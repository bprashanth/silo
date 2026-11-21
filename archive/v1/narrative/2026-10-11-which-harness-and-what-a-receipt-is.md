# Which harness, and what a receipt really is

We expected the trade-off to be correctness against auditability. On one side was a
hundred-line harness with one Python tool in a no-network container, which we could
audit line by line. On the other was io's Codex, a general agent that runs arbitrary
shell commands behind a bubblewrap wall. The measurement did not come out that way.

## Codex was better at the thing we built the small harness for

Across 268 jobs on nine spreadsheets, local Muse got 97.8% right through io's Codex
and 93.3% through our harness. It was also three times faster through Codex: a median
88 s against 256 s. The gap was widest where the work was hardest. On a 20,000-row
ledger that needs a join against a lookup sheet, Codex got 12 of 12 and the small
harness 8 of 12. The small harness's losses there were not arithmetic. Three times it ran
out of its 12-step budget while still exploring the data.

The speed gap mostly came from something incidental. Codex asks the model for low
reasoning effort, and Muse complies: it wrote 1.6k tokens per job through Codex and
4.2k through our harness, most of them hidden thinking. That is a setting, not an
architecture, and we can change it on our side.

## Neither harness did anything we would have to audit for

The fear about Codex was that it would reach for something unexpected. Across 134
Codex jobs, under io's offline profile, nothing reached for the network, no
path outside the workspace was touched, and nothing was refused by the wall. Every action
was a shell command running Python. The small harness was equally clean, by
construction. The first audit pass did report eight "network attempts", but every one was
our own regex matching `\nColumns`. A false alarm in the audit tool is still a
false alarm.

So the audit surface differs in form, not in what was observed: whole Python
scripts against `bash -lc "python3 -c ..."` strings. Both can be read from a
transcript. Codex's are noisier.

## The traps were not where the model failed

The cases were built to be messy: subtotal rows, merged headers that sit three rows down,
two tables on one sheet, formulas with no saved values, lakh and crore written as
text, and dates in three formats. Ten questions were asked plainly, with no hint about
the mess. Muse got 39 of those 40 in both harnesses, and the one miss was a server
error. It noticed the subtotals and the uncached formulas by itself.

Where it did fail, it failed quietly and in code:
- A blank separator row read by pandas became one more "unique" visit, 481 instead of 480.
  Both harnesses did this, and Codex did it twice.
- A date written as 03/04/2025 read the American way.
- A filter that matched nothing, reported as an answer of 0.

## What a receipt is

We built the first receipt to check provenance: every number in the answer must
appear in some tool output. That would catch a model typing a number from
memory. Across 268 jobs Muse never did that with its final answer. Every
answer was computed. The receipt was nearly always clean, including on the wrong
answers, because the wrong answers were computed correctly from the wrong rows.

What did catch them was disagreement. Ask the same question through a second,
independent route and compare:
- With Codex as the checker for the small harness, all nine of the small harness's
  wrong or missing answers were flagged, and none of its 125 correct ones.
- With the small harness checking Codex, two of three errors were flagged.
- Asking the same harness twice was weaker, because a harness that misreads a separator
  row misreads it the same way again.

So the receipt that works is not "show me where this number came from". It is
"someone else, working independently, got the same number". Number tracing still
earns a place as a cheap first check, and it rightly flags arithmetic done in
prose. But only a second, independent computation catches an error that was
computed faithfully from the wrong rows.

## What this suggests

- Make io's Codex runtime, under io's profile, the engine for data questions, including
  behind Telegram, rather than growing a second bespoke harness. The bot becomes a
  front end over per-user workspaces.
- Keep the small harness as the independent checker. For numeric answers, run it in
  parallel and mark the reply verified only when the two agree. That costs a second
  computation, which is a fair price for a receipt that catches errors.
- Before relying on either: real spreadsheets instead of synthetic ones, more
  than two trials, and questions where the people asking do not already know the trap.
