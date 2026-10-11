# A small local model needs a calculator, not a bigger prompt

The first instinct with a spreadsheet question is to paste the spreadsheet into
the prompt. With a 314-row ledger, that works for a strong hosted model:
DeepSeek V4.1 Flash got 33 of 33. It mostly works for Muse Glimmer 30B, at 32 of
33, but the cost is hidden. Muse reaches the right total by adding hundreds of
rows in its reasoning, tens of thousands of tokens per question, and at 7 tokens
a second on this box that is many minutes per answer. Qwen 9B shows what happens
when a model is weaker at that arithmetic. It got 23 of 33, its totals were off
by lakhs, and the wrong answers looked as confident as the right ones.

Giving the model one tool changed which part of the problem it does. The model
sees eight rows of each sheet, writes pandas, and reads the result. Local Muse
went to 11 of 11 and then 22 of 22. Qwen 9B went to 9 of 11, and the two misses
were missing answers, not wrong ones: every number it did give was exact. That
difference is what matters for trust. A miss is visible; a wrong total is not.

The harness's first failure was not arithmetic but diligence. With an 8-step
limit, Muse sometimes kept re-verifying until it ran out of steps and said
nothing (18 of 22). Raising the limit to 12, and making one last tools-off call
that demands an answer, fixed it.

Speed was then the problem, and it was memory bandwidth, not compute. A
4-bit quant reads half the bytes of Q8, and a small drafter lets Muse verify
up to 16 guessed tokens per pass. Together they took decode from 7.4 to 35.5
tokens a second, with every setup still at 22 of 22. A real Telegram question
went from about 400 s to 67 s.

What this does not show: the workbook is synthetic and tidy, with one table per
sheet, headers in row 1 and no total rows. Real NGO sheets have merged
headers, subtotal rows that double-count, and formulas without cached values.
The next evidence has to come from messier cases, and has to compare this small
harness with io's Codex harness on the same cases (see chronology
`2026-10-11T1500-harness-choice-open.md`).
