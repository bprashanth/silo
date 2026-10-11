# Codex answers, the simple harness checks: live

Built and running on the bot. The new code is in `tg-bridge/`:
- `codex_engine.py`: the shared Codex runner, which `benchmarks/harness-compare/run.py` now uses too.
- `answer.py`: both runs, the comparison and the badge.
- `audit_log.py`: the hash-chained records and the `/how` text.
- `io_config.js` and `receipt.py`: moved here from `benchmarks/harness-compare/`.

Live tests: Telegram as the user via `tl_session.py`, or `answer.respond` called directly.

| message | Codex | checker (reasoning low) | badge |
|---|---|---|---|
| NGO workbook: actual spend Apr–Sep | 19080600, 29.9 s, 2 steps | 19080600, 27.0 s | ✅ (truth 19,080,600) |
| field log: % of visits needing follow-up, each ID once | 30.625, 83.3 s, 9 steps | 30.625, 55.5 s | ✅ (truth 147/480) |
| "make a chart of people reached by state" | PNG sent as a photo, 45.1 s | 18.6 s | ➖; the bars sum to 24,717, the truth |
| "thanks, that's all" | 20.6 s, no steps | 11.7 s | ➖ |
| Admin spend, with `CHECK_GRACE=0` | 5238900 | finished after the reply | ◻️; the late result 5238900 was recorded and shown in `/how` |
| io unavailable (`IO_APP=/nonexistent`) | failed | 314 rows | ◻️, the checker's answer alone |

`audit_log.verify` holds across all of these records.

**A bug caught before going live.** The first agreement rule (0.5% relative) counted
480 and 481 as agreeing. That is the field-log error from harness-compare, which this check
exists to catch. Values are now compared at the precision each side wrote them: integers must
match exactly, and 79.6 vs 79.61 agree. A fraction and its percentage (0.796 and 79.6) also agree.

**Not yet measured:** how often the checker misses the 30 s window on harder questions. Every
spreadsheet question so far finished inside it, and on these questions the checker with low
reasoning was faster than Codex. The bot also hasn't yet gone through the 134-question benchmark.

**Cost:** two model streams per message, so `-np 4` now serves two chats at once. Small talk
takes about 20 s, because it goes through Codex.
