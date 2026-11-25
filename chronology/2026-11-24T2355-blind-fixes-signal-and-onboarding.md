# 2026-11-24 23:55 IST — Blind-bench hardening, mixed Signal verification, and alpha onboarding UI

## What the owner asked for

Execute all three items from the post-live-testing roadmap with high quality (preferring depth over shortcuts, fixing any gaps exposed by blind testing, and taking Playwright screenshots to confirm the onboarding UI renders as expected):

1. Close the remaining retrieval/reader gaps from live testing and the `2026-11-24` blind bank, and verify on a fresh blind held-out bank.
2. Verify mixed Google + `--in`-scoped WhatsApp over `bridges/signal/bridge.py` and add multi-tester routing support.
3. Build a simple alpha onboarding flow (`bridges/onboard/`): Signal DM → setup link → read-only Google OAuth / WhatsApp pairing → simple `--in` folder/group checkboxes → optional role & intended-use form (with Insights, Partnerships, and Marketing examples saved safely without degrading core CLI mapping) → Signal DM confirmation code.

## What we built and verified

### 1. Core retrieval & reader hardening (`e1bdee5` + `616d18c`)

- Fixed 6 systemic gaps from live testing + `blind-heldout-2026-11-24` (`e1bdee5`):
  - Fold `body ~` into `--search` even when `--search` or other `--where` clauses are already present.
  - Expand same-chat ±180s same-sender neighbors and up to 2 direct replies across `--where` filters (so `links <> ''` no longer drops the quoted parent/context explaining a link).
  - Raise top-5 row `body` render limit from `450 → 1200` chars (`compose()` slice `6000 → 9000`) and omit raw reranker float scores from the `found` column shown to the reader.
  - Resolve 1-word sender queries (`--search "S"`) via `resolve_sender` so ambiguous initials prompt the user.
  - Detect recency-only `summarise messages` prompts (`"latest discussion"`) to pull the newest episodes chronologically, and strengthen weekday temporal anchoring.
  - Preserve conditions/caveats and exact names in `STYLE` within the `1450`-char prose budget.
- Drafted a brand-new 20-case unseen blind bank (`blind-heldout-2026-11-25/bank.json`, 0 overlap across 48 prior rows) via `codex exec`. Its initial pass (`e1bdee5`: `11 correct / 4 partial / 5 wrong`) immediately caught 4 real general bugs:
  1. Multi-`OR` `body ~` stripping left a dangling `or` in SQL (`ParserException`).
  2. `idli get message --in ... --search ...` (no `REF`) failed argparse instead of normalizing to `list messages`.
  3. Post-latest / upcoming-date `--since`/`--until` filters on `--search`/`summarise` returned 0 rows (while past out-of-window dates must remain strictly empty).
  4. Unknown `--in CHAT` cross-chat fallback returned weak unrelated matches instead of reporting the missing group.
- Fixed all 4 in `616d18c`; re-running `blind-heldout-2026-11-25` jumped to **`10/10` single, `3/6` correct + `3/6` partial multi, `4/4` controls (`17 correct, 3 partial, 0 wrong`, `15/16` positive evidence)**. Google owner regression (`tasks_owner_dev.json`, 19 turns): **`0` errors, `0` WhatsApp routing leaks**. Full run note: [2026-11-25-whatsapp-core-v2](../benchmarks/runs/2026-11-25-whatsapp-core-v2/README.md).

### 2. Mixed Google + WhatsApp over Signal (`a3bb304`)

- Extended `bridges/signal/bridge.py` so `ask()` accepts explicit per-tester `sandbox` and `extra_env` (defaulting `IDLI_CHIPS=0`), and added opt-in multi-tester routing (`handle_multi_turn`, `serve_multi` when `IDLI_ONBOARD_STATE` is set) supporting single-use invites, Signal DM `confirm <code>`, `status`, `setup`, and `disconnect`.
- Verified live mixed queries (Google Drive, WhatsApp Jam Buns, WhatsApp Acumen, Gmail) through `bridges.signal.bridge.ask()` against a combined Google + `--in`-scoped WhatsApp sandbox with zero cross-source leaks.

### 3. Alpha onboarding web UI (`bridges/onboard/`, `a3bb304`)

- Built `bridges/onboard/{store.py,server.py,test_onboard.py,README.md}` and documented implementation status in [signal.agent.md](../deployment/alpha/signal.agent.md).
- Implements 4-step mobile- & desktop-friendly flow: Connect (Google PKCE OAuth / local preview + WhatsApp read-only pairing) → Scope Picker (`--in` checkboxes for Drive folders & WhatsApp groups) → Role & Intended Use (Insights, Partnerships, Marketing examples + deterministic link/folder matching saved privately to `<sandbox>/profile.json`, never injected into 9B prompts) → Real scoped `--in` sync + 6-digit Signal DM confirmation code.
- End-to-end Playwright run caught and fixed a real HTML-attribute double-quote bug in checkbox `onchange` handlers and verified all 4 steps across desktop (`1100×860`) and mobile (`390×844`) viewports with screenshots.
- Two-tester canary isolation test verified neither tester can redeem another's invite, confirm another's code, or see unchecked private chats or each other's DuckDB stores (`49/49` tests passing across `core`, `bridges/signal`, and `bridges/onboard`).

## Open items

- Register production Google Web OAuth client + HTTPS callback on `silo.idli.cc` and add per-tester container isolation for `silo-wa-sync` + worker processes before public alpha invites.
- Run one fresh `blind-v3` single-pass check on frozen `616d18c` if we want an un-iterated headline number for `17/3/0`, and optionally investigate multi-turn attribution in `compose()` for the remaining 3 `partial` `heldout_multi` cases.
