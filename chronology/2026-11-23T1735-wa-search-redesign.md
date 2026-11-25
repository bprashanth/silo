# 2026-11-23 17:35 IST — WhatsApp search redesign and CLI alignment

## Context

Reviewed the Silo core (`core/lib/recstore.py`, `core/lib/idlicli.py`), the Nov 20–21 `io` design session, the Signal alpha rollout doc, and the Nov 22–23 WhatsApp retrieval benchmarks (`2026-11-22-whatsapp-lookup`, `2026-11-23-whatsapp-windows`, `2026-11-23-whatsapp-ask`).

The owner wanted to improve WhatsApp search without adding new verbs or diverging the core command surface (which confuses the local 9B), and iterated on the proposed design via `.prompts/wa_search_redesign.md` before implementation starts.

## Key observations

- Stock `idli ask` scored `0/8` (prior multi-message) and `0/12` (new single-record) on WhatsApp because `wa_messages` was bolted on via `idli view`: `GRAMMAR_HEAD` still stated WhatsApp was not connected, views had `date: None`, hybrid search was hardcoded to `files`, `get`/`summarise`/`judge` rejected views, `_fmt()` truncated bodies at 160 characters, and `compose()` did not receive today's date.
- The benchmark's `wa_candidates` preview arm reached `11/12` on single-record lookups by mutating a per-question view and putting 8 previews in `menu()`, confirming that compact source-referenced excerpts + group binding unblock the 9B — but the approach breaks concurrency and failed all 4 controls.

## Decisions agreed / proposed

- **Resource naming:** Use `messages` and `chats` with a `provider` column (`whatsapp`, later `slack`/`mattermost`), rather than `wa_messages`/`wa_groups`. Reuses `--in CHAT` identically to Drive's `--in FOLDER`, plus `get message REF`, `summarise messages --search`, `define/judge --on message`, and `view`. Appended cross-app mapping table to [docs/cli.md](../docs/cli.md).
- **Default sync window (POC simplification):** Cache/sync the last **2 weeks** by default for the POC, and always surface the coverage window deterministically when a question asks outside it (e.g., September).
- **Retrieval stack:** Generalize hybrid search in `recstore.py` using DuckDB native `fts` (Okapi BM25 + Porter stemming) + `Qwen3-Embedding-0.6B` on contextualized conversation episodes (reply chains + 10–15 min bursts) + optional local cross-encoder reranker (`Qwen3-Reranker-0.6B` or `bge-reranker-v2-m3`) on DGX loopback, with per-stage telemetry in `log.jsonl`.
- **Collector path:** Decouple ingest from capture; iterate search on the frozen DGX snapshot first, and smoke-test a read-only `whatsmeow` Go sidecar per user container for multi-user Signal onboarding.

## Artifacts updated

- Architecture proposal: [proposals/architecture/whatsapp-search.md](../proposals/architecture/whatsapp-search.md)
- Cross-app CLI mapping appended to [docs/cli.md](../docs/cli.md)

## Open / next

- Finalize any remaining questions from the owner's review of `.prompts/wa_search_redesign.md`.
- Implement Step 1 in a worktree: core `chats`/`messages` resources, unified DuckDB FTS + episode embeddings + reranker hook, deterministic `--in`/sender resolver + coverage notes, and `_fmt()`/`compose()` fixes.
- Benchmark on the frozen DGX fixture (`windows-xTcFis`, `ask-LMunvw`), Google dev banks, and a fresh blind held-out bank.
- Smoke-test read-only `whatsmeow` pairing inside a container for the Signal onboarding flow.
