# WhatsApp search in Idli: from `0/12` views to first-class hybrid retrieval

This note summarizes what changed between 22 and 24 November 2026, what the evidence supports, and what remains open before multi-user Signal onboarding.

## What changed

On 22–23 November, WhatsApp messages lived in benchmark-only DuckDB views (`wa_messages`, `wa_groups`) read from headed Chromium + WA-JS. Unmodified `core/idli ask` scored **0/8** on multi-message lookups and **0/12** on single-record lookups ([2026-11-23-whatsapp-ask](../benchmarks/runs/2026-11-23-whatsapp-ask/README.md)). Pre-computing a per-question `wa_candidates` view and stuffing 8 previews into `menu()` lifted single-record lookups to `11/12` (and `2/8` prior), but broke concurrency, diverged from Drive/Mail, and failed all four controls.

On 24 November we promoted chat into the core command surface ([proposals/architecture/whatsapp-search.md](../proposals/architecture/whatsapp-search.md), frozen at `345e74d`) **without adding a single new verb or exceeding the prompt prose budget** (`5243 / 6836 / 1329` chars vs limits `5600 / 7100 / 1450`):

- **First-class resources:** `chats` and `messages` (with a `provider` column for future Slack/Mattermost), reusing `--in CHAT`, `--on/--since/--until`, `--search`, `--count`, `--group-by`, `get message|chat REF`, `summarise messages --search`, and `define/judge --on message`.
- **Unified hybrid retrieval ([docs/search.agent.md](../docs/search.agent.md)):** DuckDB native `fts` (Okapi BM25 + Porter stemming) + fuzzy/stem-lite fallback + `Qwen3-Embedding-0.6B` over contextualized conversation episodes (reply-parent chains ∪ 15-minute bursts) + local cross-encoder reranker (`bge-reranker-v2-m3-Q8_0` on `:8294`), with per-stage telemetry in `log.jsonl`.
- **Deterministic resolvers in code:** Fuzzy chat & sender binding (`resolve_chat`, `resolve_sender`), cached date-coverage checks, `own_words()` filtering of hallucinated `--in` / `--since` flags, and `body ~` rewritten into hybrid search.
- **Lightweight read-only collector ([bridges/whatsapp/](../bridges/whatsapp/README.md)):** Replaced headed Chromium (~500 MB–1 GB RAM) with a read-only `whatsmeow` Go sidecar (~9.8 MiB RAM, zero write/send methods compiled in, QR + 8-digit phone pairing code).

## What the evidence supports

Full run details and replay commands live in [benchmarks/runs/2026-11-24-whatsapp-core/README.md](../benchmarks/runs/2026-11-24-whatsapp-core/README.md) and [chronology/2026-11-24T0140-whatsapp-core-results.md](../chronology/2026-11-24T0140-whatsapp-core-results.md).

1. **First-class core beats the benchmark `preview` hack without menu stuffing.** On the 24-case dev bank (`ask-LMunvw`), unmodified `core/idli ask` with `bge-reranker-v2-m3` jumped from stock **0/8, 0/12** (and `preview` **2/8, 11/12**) to **5/8 prior, 12/12 new, 12/12 reverse-repeat, and 3/4 controls** (median `5.0s`).
2. **Generalizes to unseen questions.** On a brand-new 20-case blind held-out bank (`0` overlap with dev, drafted and graded blind by `codex exec` on frozen `345e74d`), `core_rerank` achieved **13/16 (81%) positive evidence recall** (`10/12` single, `3/4` multi), **12/20 strict correct + 3/20 partial (0 wrong on multi-message threads)**, and **3/4 controls clean** (exact count, unknown group, out-of-window August coverage notice).
3. **The local cross-encoder reranker earns its keep.** Across both dev and blind held-out runs, `bge-reranker-v2-m3` consistently outperformed RRF-only (`core_rrf`: `3/8` prior, `11/12` new, `12/16` blind evidence, `11/20` blind factual correct) at ~0.2–0.4s median overhead and falls back cleanly when disabled (`IDLI_RERANK=0`).
4. **Zero regression to Google & clean mixed-store coexistence.** Replaying `tasks_owner_dev.json` (19 turns across Drive/Gmail/Calendar/Sheets) produced **0 errors and 0 WhatsApp routing leaks**. Syncing the owner’s live `whatsmeow` capture (`63` chats, `1,874` messages) into a populated Google sandbox worked cleanly under Signal `--output humanize`.

## What remains uncertain or open

- **Ambiguous single-letter senders (`V`, `S`):** `resolve_sender` works deterministically in unit tests, but in both dev (`[21]`) and blind held-out (`[17]`), the 9B omitted `sender ~ 'V'` or used `--search "S"`, bypassing disambiguation.
- **Reader/wording fidelity:** Blind grading showed a gap between retrieving the right messages (`13/16`) and compressing them into 1–3 sentences without dropping caveats or misreading dates (`9/16` strict correct on positives). Keeping attributed verbatim receipts visible underneath the reply (enabled in `--output humanize`) helps immediately; stronger reader verification remains open.
- **Multi-user Signal + WhatsApp onboarding:** Containerized `whatsmeow` pairing is verified for one user (9.8 MiB RAM); wiring it with Google Web OAuth PKCE into the multi-tenant Signal bot invite flow is the next milestone ([deployment/alpha/signal.md](../deployment/alpha/signal.md)).
