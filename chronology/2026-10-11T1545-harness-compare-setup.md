# Harness comparison: cases and runner

New benchmark `benchmarks/harness-compare/`. It runs the bridge's harness and io's
Codex harness side by side on local Muse, over messy NGO spreadsheets.

**Cases.** Cursor's `agent` (GPT-5.6 Sol) built 8 cases from `cases/SPEC.md`:
- **Layouts:** subtotal rows, offset merged headers, two tables on one sheet, and live
  formulas with no saved values.
- **Data problems:** mixed lakh/crore/k units and three date formats, a 20k-row ledger
  with a lookup join, a field log with duplicate IDs and messy village names, and a
  CSV joined to an xlsx.

Each case's truth comes from the clean records before they were made messy. An
independent `verify.py` re-derives every answer from the messy files, and all 8 pass.
The original tidy workbook is the `clean` baseline.

The generated questions mostly spell out the trap ("excluding every monthly subtotal…").
That tests reading comprehension more than whether the harness notices the problem. So
10 questions also get a plain variant in `plain.json`, worded the way a programme
manager would ask. That makes 67 questions in all.

**io harness, unmodified.** `io_config.js` calls io's own `writeConfig`, using the
offline setting and io's runtime and Codex 0.154.0. It then swaps the model provider for
local Muse, which is the only change. The first probe got the right July total in 55 s,
using 12 commands.

**Receipt check** (`receipt.py`). It extracts every number in the reply, including
lakh/crore/k forms, and accepts it if some tool output matches at the precision the
number was written. A wrong total typed from memory shows up as untraced.

**Server.** It now runs 4 slots of 64k context instead of 2 of 65k
(`serve_muse.sh` now reads `NP` and `CTX`). Single-stream speed is unchanged at
34.1 tok/s. Memory use is about 45 GB of 121 GB.

**Bot.** `tg_bridge.file_content()` was split out of `to_content` so the eval builds
prompts with the bot's own code. The bot was restarted.

Run started: `runs/2026-10-11-muse-q4d`, 67 questions × 2 harnesses × 2 trials.
