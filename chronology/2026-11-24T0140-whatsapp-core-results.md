# 2026-11-24 01:40 IST — First-class WhatsApp search in core, `whatsmeow` pairing test, and blind held-out verification

## What we wanted

1. Validate a lightweight, strictly read-only `whatsmeow` Go sidecar as a multi-user alternative to headed Chromium + WA-JS.
2. Move WhatsApp retrieval out of benchmark views (`wa_candidates`) into clean, kubectl-style first-class `chats` / `messages` resources in `core/` without adding new verbs, breaking the prose budget, or regressing Google workflows.
3. Measure both dev ablation (with vs without local cross-encoder reranker) and a fresh blind held-out set run once on frozen code.

## What we built & observed

### 1. Read-only `whatsmeow` sidecar ([bridges/whatsapp/](../bridges/whatsapp/README.md))
- Built `silo-wa-sync` (`golang:1.26-bookworm` → `debian:bookworm-slim`), zero write/send/mark-read calls compiled in, with loopback QR + 8-digit phone-number pairing UI and auto-refresh on QR timeout (`b52775d`).
- Owner paired live: used **9.8 MiB RAM** (vs ~500 MB–1 GB for headed Chrome + Xvfb), captured `21` groups + `42` DMs (`1,874` messages, `299` reply-parent links, `36` image captions, `28` link previews, `11` document filenames) from the last 14 days in ~5s, and ingested cleanly into `core/idli sync whatsapp` (`6.3 MB` DuckDB).

### 2. Core generalization (`core/lib/searchkit.py`, `recstore.py`, `idlicli.py`, frozen at `345e74d`)
- Added `chats`, `messages`, `chat_members`, `message_episodes` tables with a `provider` column, reusing `--in CHAT`, `--on/--since/--until`, `--search`, `--count`, `--group-by`, `get message|chat REF`, `summarise messages --search`, and `define/judge --on message`.
- Brought up local `bge-reranker-v2-m3-Q8_0` (`idli-rerank` on `127.0.0.1:8294`, ~80–150 ms per rerank).
- Prose budget stayed **under** the Nov 21 baseline (`5243 / 6836 / 1329` vs limits `5600 / 7100 / 1450`).
- Iterative fixes driven by telemetry & traces (`v1` → `v5`):
  - Telemetry caught DuckDB 2.0's alias binder error on `match_bm25` (`v1`→`v2`).
  - Hid empty (0-row) resources from `menu()` and listed synced chats (`v2`).
  - Dropped hallucinated `--in` and `--since/--until/--on` flags in `own_words()`, threaded full user question intent into Bi-encoder + Cross-encoder, added weak-scope cross-chat rescue (`v3`).
  - Fixed a critical recall bug where `LIMIT` ran *before* scope filtering in BM25 and episode embeddings; handled stray `'continue'` strings in `commands[]`; removed first-call `repeat_penalty` to restore determinism (`v4`).
  - Unified `body ~ '...'` into hybrid search, normalized `s`/`z` spelling in `own_words`, added missing-`--in` fallback on search, and added Signal `--output humanize` message receipt formatting (`v5`, `345e74d`).

### 3. Frozen verification results (`345e74d`)
- **Dev bank (`ask-LMunvw/bank.json`):** `core_rerank` hit **5/8 prior (multi-msg), 12/12 new, 12/12 repeat, 3/4 controls** (median `5.0s`), vs `core_rrf` **3/8 prior, 11/12 new, 11/12 repeat, 3/4 controls** and Nov 23 stock **0/8, 0/12**.
- **Blind held-out (`blind-heldout-2026-11-24/bank.json`, 20 brand-new unseen cases drafted & graded by `codex exec`):**
  - Evidence recall: `core_rerank` **10/12 single + 3/4 multi = 13/16 (81%)**, 3/4 controls; `core_rrf` **9/12 single + 3/4 multi = 12/16 (75%)**, 3/4 controls.
  - Blind factual answer grading: `core_rerank` **12/20 correct, 3/20 partial, 5/20 wrong** (0 wrong on multi-message); `core_rrf` **11/20 correct, 4/20 partial, 5/20 wrong**.
- **Google regression (`tasks_owner_dev.json`, 19 turns on `silo-smoke`):** `0` errors, `0` WhatsApp routing leaks.
- **Mixed Google + live-`whatsmeow` store + Signal `--output humanize`:** All sources coexisted cleanly in one `store.duckdb` (`26/26` core tests + `10/10` Signal bridge tests passing).

Full numbers, private paths, and replay commands: [benchmarks/runs/2026-11-24-whatsapp-core/README.md](../benchmarks/runs/2026-11-24-whatsapp-core/README.md).

## What remains open

1. **Ambiguous single-letter sender queries (`V`, `S`):** `resolve_sender` works deterministically when `--where "sender ~ 'V'"` is emitted, but the 9B still occasionally uses `--search "S"` or drops the sender filter.
2. **Wording compression gap (`13/16` blind evidence vs `9/16` strict wording on positives):** Local 9B `compose()` occasionally drops caveats or misreads dates/titles; keeping verbatim receipts visible mitigates this, and stronger reader grounding is worth investigating.
3. **End-to-end Signal + multi-user onboarding:** Wire `bridges/whatsapp` (`whatsmeow`) + Google Web OAuth PKCE into the Signal bot invite/onboarding flow ([deployment/alpha/signal.md](../deployment/alpha/signal.md)).
