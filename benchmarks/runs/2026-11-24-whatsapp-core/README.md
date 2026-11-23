# First-class `chats`/`messages` core search + reranker ablation and blind held-out evaluation

Completed 24 November 2026 on the owner’s DGX. Core revision frozen at `345e74d` (prose budget: `5243 / 6836 / 1329`, strictly below `5600 / 7100 / 1450` and smaller than the Nov 21 baseline).

All runs launched unmodified `core/idli ask --new --mapper nine_compressed --judge nine_compressed QUESTION` subprocesses with `IDLI_CHIPS=0`. Zero per-question DuckDB views (`wa_candidates`), zero menu pre-search, zero new CLI verbs.

## Configuration

- **Mapper & wording:** local `Qwen3.5-9B-Q5_K_M` (`idli-9b` on `127.0.0.1:8291`).
- **Embeddings:** local `Qwen3-Embedding-0.6B-Q8_0` (`idli-embed` on `127.0.0.1:8293`) over contextual conversation episodes (`message_episodes`, built via reply-parent links ∪ 15-minute chat bursts).
- **Lexical:** DuckDB 2.0 native `fts` (Okapi BM25 + Porter stemming) over both `messages` and `message_episodes`, plus stem-lite/Jaro-Winkler fuzzy fallback.
- **Cross-encoder reranker (ablation):** local `bge-reranker-v2-m3-Q8_0` (`idli-rerank` on `127.0.0.1:8294`, `llama-server --reranking --pooling rank`), compared against `IDLI_RERANK=0` (`core_rrf`).
- **Ingest:** `core/idli sync whatsapp --from-snapshot ~/.local/share/silo-owner-pilot/windows-xTcFis/fresh.json` → `24` populated chats, `2,783` messages, `678` episodes embedded in `26.8s`.

## 1. Development bank (`ask-LMunvw/bank.json`, 24 cases + 12 reverse repeats)

Same frozen 2,783-message snapshot and exact evidence-recall scoring criterion as [2026-11-23-whatsapp-ask](../2026-11-23-whatsapp-ask/README.md) (`steps_shown` contains all required source refs or identifying prefixes).

| Configuration | Prior (multi-msg) /8 | New (single) /12 | New repeat /12 | Controls /4 | Median ask (s) |
|---|---:|---:|---:|---:|---:|
| Stock CLI (Nov 23) | 0 | 0 | 0 | 0 | — |
| Hybrid `wa_candidates` view (Nov 23) | 1 | 2 | 2 | 0 | — |
| Guided `wa_candidates` (Nov 23) | 0 | 8 | 7 | 1 | — |
| Preview `wa_candidates` (Nov 23) | 2 | 11 | 11 | 0 | — |
| **`core_rrf` (`345e74d`, `IDLI_RERANK=0`)** | **3** | **11** | **11** | **3** | **4.9** |
| **`core_rerank` (`345e74d`, `IDLI_RERANK=1`)** | **5** | **12** | **12** | **3** | **5.0** |

**Controls on `345e74d`:**
- **Exact HTTP(S) link count in Jam Buns (`[20]`):** PASS (`Count: 6 messages match`, with cached coverage note).
- **Unknown group `"Jam Biscuits Review"` (`[22]`):** PASS (`No chat named "Jam Biscuits Review" was found in the synced chats`).
- **Out-of-window September query (`[23]`):** PASS (`Cached history for Insight Out Crew @ T4GC only covers 05 Nov 2026 to 17 Nov 2026; earlier dates are outside the cached window`).
- **Ambiguous initial `"V"` (`[21]`):** FAIL — mapper omitted a `sender` filter in `--where` and instead queried latest incoming link globally; `resolve_sender` works when invoked (verified in unit tests) but wasn't triggered.

## 2. Blind held-out evaluation (`blind-heldout-2026-11-24/bank.json`, run once on frozen `345e74d`)

Twenty brand-new questions (`12` single-record across `11` groups, `4` multi-message threads, `4` controls) were drafted independently by `codex exec` from `windows-xTcFis/fresh.json` with **zero overlap** against `ask-LMunvw/bank.json` (0 overlapping questions, 0 overlapping gold message indices). Frozen `345e74d` was run once without inspecting the bank, then graded blind on both evidence recall and end-to-end factual answer quality by `codex exec`.

### Evidence recall (`steps_shown`)

| Arm | Single /12 | Multi-message /4 | Combined positive /16 | Controls (contract) /4 | Median ask (s) |
|---|---:|---:|---:|---:|---:|
| `core_rrf` | 9 (75%) | 3 (75%) | 12 (75%) | 3 | 3.7 / 5.0 |
| **`core_rerank`** | **10 (83%)** | **3 (75%)** | **13 (81%)** | **3** | **3.9 / 5.3** |

### Blind end-to-end factual answer grading (`codex exec`)

| Arm | Stratum | Correct | Partial | Wrong | Observed failure classes |
|---|---|---:|---:|---:|---|
| `core_rrf` | Single (12) | 7 | 1 | 4 | 02 wrong date, 03 proposed `define` card, 09 omitted caveat, 10 wrong destination, 11 missed exception |
| `core_rrf` | Multi (4) | 1 | 3 | 0 | 13 omitted requester/deadline, 14 missed 2nd fact, 15 omitted caveat |
| `core_rrf` | Control (4) | 3 | 0 | 1 | 17 used `--search "S"` instead of sender filter |
| **`core_rrf`** | **Total (20)** | **11** | **4** | **5** | |
| `core_rerank` | Single (12) | 7 | 1 | 4 | 02 wrong date, 03 proposed `define` card, 05 claimed title absent despite row shown, 09 omitted caveat, 11 missed exception |
| `core_rerank` | Multi (4) | 2 | 2 | 0 | 14 missed 2nd fact, 15 omitted caveat |
| `core_rerank` | Control (4) | 3 | 0 | 1 | 17 used `--search "S"` instead of sender filter |
| **`core_rerank`** | **Total (20)** | **12** | **3** | **5** | |

**Key takeaway:** On unseen questions, `core_rerank` achieved **81% positive evidence recall (13/16)**, **0 wrong answers on multi-message threads (2 correct, 2 partial)**, and **3/4 controls clean** (exact count, unknown group, August coverage gap). The main remaining gap is between evidence recall (`13/16`) and strict 1–3 sentence wording (`9/16` strict correct on positives) — plus the 9B choosing `--search "S"` instead of `--where "sender ~ 'S'"` on ambiguous single-letter sender controls.

## 3. Regression, mixed-store, and live `whatsmeow` checks

- **Unit & bridge tests:** `26/26` core tests (including `test_scaffold_prose.py`) + `10/10` Signal bridge tests pass.
- **Google owner dev bank (`benchmarks/bank/tasks_owner_dev.json`, 19 turns on a copy of `~/idli-sbx/silo-smoke`):** `19/19` turns completed with **0 errors and 0 WhatsApp routing leaks**.
- **Read-only `whatsmeow` sidecar ([bridges/whatsapp](../../../bridges/whatsapp/README.md)):** Paired live against the owner’s account at **9.8 MiB RAM** (zero send/write/mark-read calls compiled in), syncing `21` groups + `42` DMs (`1,874` messages, `299` reply-parent edges, `36` image captions, `28` link previews, `11` documents) from the last 14 days in ~5s.
- **Mixed Google + live-`whatsmeow` store + Signal `--output humanize`:** Synced the live `whatsmeow` snapshot into a copy of `~/idli-sbx/silo-smoke` (`186` emails, `10` events, `192` files, `48` sheet tabs, `63` chats, `1,874` messages, `530` embedded episodes in `24.2s`). Verified Drive search, Calendar, and WhatsApp chat/message queries route cleanly in one `store.duckdb` with Signal-friendly receipts and italic coverage footers.

## Private inputs, raw outputs & replay

All private captures, banks, grades and logs remain outside Git under `~/.local/share/silo-owner-pilot/` (mode `0700` / `0600`):
- Dev benchmark (`v5`): `~/.local/share/silo-owner-pilot/core-bench-2026-11-24-v5/`
- Blind held-out bank, runs & grades: `~/.local/share/silo-owner-pilot/blind-heldout-2026-11-24/{bank.json,run_345e74d/,grades_345e74d.json}`
- Live `whatsmeow` smoke state: `~/.local/share/silo-owner-pilot/whatsmeow-smoke/`

Replay on the DGX (with `idli-9b` on `:8291`, `idli-embed` on `:8293`, `idli-rerank` on `:8294`):

```bash
umask 077
trial=$(mktemp -d)
OPENBLAS_NUM_THREADS=1 core/.venv/bin/python benchmarks/runs/2026-11-24-whatsapp-core/run.py \
  ~/.local/share/silo-owner-pilot/windows-xTcFis \
  ~/.local/share/silo-owner-pilot/ask-LMunvw/bank.json \
  "$trial" core_rrf core_rerank
core/.venv/bin/python benchmarks/runs/2026-11-24-whatsapp-core/score.py \
  ~/.local/share/silo-owner-pilot/ask-LMunvw/bank.json \
  "$trial" core_rrf core_rerank
```

## Limitations & next fixes

1. **Ambiguous 1-letter sender queries (`V`, `S`):** `resolve_sender` catches ambiguity deterministically when `--where "sender ~ 'V'"` is emitted, but the 9B sometimes omits the sender filter or emits `--search "S"` instead.
2. **Wording compression vs evidence:** Local 9B `compose()` occasionally drops a caveat or misreads a date/title present in the retrieved rows; keeping attributed verbatim message receipts visible underneath the summary (already enabled in `--output humanize`) mitigates this for end users, and testing larger/stricter wording verification is worthwhile next.
3. **Multi-user Signal + WhatsApp onboarding:** `bridges/whatsapp/` proved single-user containerized `whatsmeow` pairing (9.8 MiB RAM); next step is wiring it alongside Google Web OAuth PKCE in the Signal alpha onboarding service ([deployment/alpha/signal.md](../../../deployment/alpha/signal.md)).
