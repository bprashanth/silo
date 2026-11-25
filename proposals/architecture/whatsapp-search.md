# Architecture: First-Class Chat & WhatsApp Search in Idli Core

Status: **Implemented** (`345e74d`, 2026-11-24) · Links: [CLI principles](../../docs/cli.md) · [Design decisions](../../docs/decisions.md) · [Narrative](../../narrative/whatsapp-search.md) · [Benchmark report](../../benchmarks/runs/2026-11-24-whatsapp-core/README.md) · [Chronology](../../chronology/2026-11-24T0140-whatsapp-core-results.md)

## Problem

The WhatsApp benchmarks ([2026-11-22-whatsapp-lookup](../../benchmarks/runs/2026-11-22-whatsapp-lookup/README.md), [2026-11-23-whatsapp-windows](../../benchmarks/runs/2026-11-23-whatsapp-windows/README.md), [2026-11-23-whatsapp-ask](../../benchmarks/runs/2026-11-23-whatsapp-ask/README.md)) proved two things:

1. **Stock CLI scored `0/8` (prior multi-message) and `0/12` (new single-record)** because WhatsApp was bolted on via `idli view`: `GRAMMAR_HEAD` told the 9B WhatsApp wasn't connected, views have no date column (`--on`/`--since` fail), hybrid search was hardcoded to `files`, `get`/`summarise`/`judge` rejected views, and exact `group_name`/`sender` filters failed on nicknames.
2. **Pre-computing a per-question `wa_candidates` view jumped new lookups to `11/12`**, proving that the 9B handles WhatsApp well once it sees compact source-referenced excerpts and resolved group names — **but** mutating DuckDB views per query breaks concurrency, diverges from Drive/Mail, and broke all four controls (counts, ambiguous sender, unknown group, out-of-window dates).

## Design Principles

- **Zero new verbs, zero WhatsApp-only flags.** Reuse `idli VERB RESOURCE [REF] [flags]`.
- **Stay inside the prose budget.** `core/tests/test_scaffold_prose.py` enforces strict character limits (`GRAMMAR_HEAD <= 5600`, `grammar() <= 7100`, `STYLE <= 1450`). Fixes live in code, not prompt sentences.
- **One search & resolution engine across apps.** Upgrades built for `messages` (DuckDB FTS BM25, contextual embeddings, reranker, entity resolver, coverage reporting) also improve `files` and `mail`.
- **Telemetry before complexity.** Every retrieval stage logs its candidates, ranks, scores, latency, and fallbacks in `<sandbox>/log.jsonl` so we can verify whether a component helps or hurts.

---

## 1. CLI & Resource Terminology

In `idli VERB RESOURCE [REF] [flags]`:
- **`sync PLACE`**: names the connector (`gmail`, `gcalendar`, `drive`, `whatsapp`).
- **`RESOURCE`**: names the record kind in the store (`mail`, `threads`, `calendar`, `files`, `folders`, `sheets`, `rows`, `chats`, `messages`, or a saved `view`).
- **`--in CONTAINER`**: means "inside this named container" across apps:
  - on `files` / `photos` / `folders`: Drive folder (`--in "Strategy Classics"`)
  - on `messages` (and `summarise messages`, `judge messages`): chat / group (`--in "Jam Buns"`)
  - on `mail` / `threads`: Gmail label/mailbox (future consistency)

### Core Commands Used for Chat

```bash
idli sync whatsapp                                         # ingest into store.duckdb (2-week default window for POC)
idli list chats                                            # active chats with provider, coverage dates, message counts
idli list messages --in "Jam Buns" --on "last week"        # deterministic chat + IST date filtering
idli list messages --in "Jam Buns" --search "birding"      # hybrid BM25 + embeddings + rerank, returns ref + excerpt
idli list messages --count --in "Jam Buns" --where "links <> ''"  # exact DuckDB count over full messages table
idli get message <REF>                                     # message + quoted parent + direct replies + ±3 neighbors
idli summarise messages --search "session length" --in "Royal Enfield"  # episode retrieval + cited synthesis
idli define PROPOSAL --on message --ask "..." --answers yes,no
idli judge messages --def PROPOSAL --in "Jam Buns" --on "last week"
idli view NAME --sql "SELECT ..."                          # saved SQL rule over any tables, reusable as a resource
```

---

## 2. Store Schema (One `store.duckdb` per Sandbox)

Keep the single-file DuckDB invariant and include a `provider` column so Slack / Mattermost / Signal can share the exact same schema later.

| Table | One row per | Key columns |
|---|---|---|
| `chats` | group or DM | `id` (PK), `provider` (`whatsapp`, ...), `name`, `is_group`, `active_at`, `earliest_at`, `latest_at`, `msg_count`, `partial_history` |
| `messages` | single message or caption | `id` (stable ref, PK), `provider`, `chat_id` (FK → `chats.id`), `chat_name`, `sent_at` (IST), `sender_id`, `sender`, `is_from_me`, `source_type` (`text`\|`image_caption`\|`document`), `body`, `links` (HTTP/S + bare domains), `link_preview`, `filename`, `parent_id` (FK → `messages.id`), `reply_count` |
| `chat_members` | observed participant per chat | `(chat_id, sender_id)` (PK), `display_name`, `pushname`, `phone`, `last_seen` |
| `message_episodes` | stitched conversation unit | `episode_id` (PK), `chat_id`, `start_at`, `end_at`, `message_ids` (list), `speakers`, `context_text`, `vec FLOAT[1024]` |

### Conversation Episodes & Contextual Enrichment

Built deterministically during `idli sync whatsapp` (zero LLM cost at sync time, incremental per updated chat):

1. **Episode grouping:** Partition a chat's messages into connected components of `(explicit parent_id reply edges) ∪ (same-chat messages within a 10–15 minute gap)`, splitting very long threads at ~1,500 chars with a 2-message overlap.
2. **Contextual text (what gets indexed for BM25 and embedded into `0.6B`):**
   ```text
   Chat: Royal Enfield | 19–20 Nov 2026 | Vidya, Abhiram
   [Quoting Vidya, 18 Nov: "DICE invitation..."]
   Abhiram (20 Nov 13:12): Won't be able to make it
   Abhiram (20 Nov 13:13): https://docs.google.com/... [DICE Notes]
   ```
3. **Why embed episodes (not every individual message twice):**
   - Embedding **episodes** avoids duplicating vectors for every "ok" / "thanks" / bare URL while keeping reply chains and link previews attached to the surrounding discussion.
   - Single-message precision is handled by **BM25 (`fts`) on individual `messages`** (exact names, URLs, rare words) fused with **dense vector search on `message_episodes`** (meaning, paraphrases, multi-turn context), then mapped back to the supporting source message refs.
   - `judge messages` can receive either a single message plus its parent/neighbors (`_item_text` for `message` includes `[In chat X] [Quoting ...]`) so Clef/9B always sees enough context to judge accurately.

---

## 3. Unified Retrieval Engine (`recstore.py`)

Generalize `--search` so any indexed resource (`files`, `messages`, and later `mail`) uses the same pipeline:

1. **Quoted `"exact phrase"`**: literal match only (preserves existing contract).
2. **Unquoted query**:
   - **Lexical (DuckDB built-in `fts` — Okapi BM25 + Porter stemming):** Replaces brittle `AND`-of-`LIKE` and SQL regex IDF loops. Adds stemming (`birding` ↔ `birders`) and OR-scored IDF ranking inside DuckDB, with a `jaro_winkler_similarity` fuzzy fallback for typos and Indian-English spelling variants (`borders` → `birders`, `IndusInd`).
   - **Semantic (DuckDB `array_cosine_similarity` over `Qwen3-Embedding-0.6B` vectors):** Scores query vector against `message_episodes.vec` (or `file_chunks.vec` + `card_vecs`), using calibrated score floors.
   - **Fusion (RRF):** Merges lexical message hits and semantic episode hits into a top-30 candidate set.
   - **Optional Local Cross-Encoder Reranker (`Qwen3-Reranker-0.6B` or `bge-reranker-v2-m3` on DGX loopback, e.g. `:8294`):** Scores `(query, candidate_passage)` pairs directly (~50–100 ms for 30 candidates) to sharpen top-5 precision and abstain on weak matches. Falls back cleanly to RRF when the reranker endpoint is not configured/running.
3. **Telemetry:** Log per-search lexical count, semantic count, reranker scores/latency, and top-K refs in `log.jsonl` so regressions or harmful components are immediately visible.

---

## 4. Deterministic Code Over Prose (`recstore.py` & `idlicli.py`)

| Mechanism | Where it runs | What it fixes |
|---|---|---|
| **Entity resolver (`--in` & sender filters)** | Inside `select()` / `compile_where()` — **after** the mapper, so direct CLI users and the 9B share one path. | Fuzzy/prefix match on `chats` and `chat_members`. Returns **unique binding** (shown in `Result.note`, e.g. `In chat "Jam Buns …" (cached 9–23 Nov, 172 msgs)`), **disambiguation choices** (`Which V: Vidya, Vikram…?`), or **unknown entity error** (never silent `Count: 0`). |
| **Coverage-aware dates** | Inside `select()` whenever `--on` / `--since` / `--until` is used. | Compares requested window against `chats.earliest_at` (or `sync_log`). For POC we can default sync to the **last 2 weeks** and surface that window explicitly when a question asks earlier (e.g., September). |
| **Lean `menu()` without pre-search** | Inside `menu()` before the mapper. | No preemptive message search! Only list active chat names (just like Drive folders, capped at 25 with token-matching names first) and annotate empty sources (`mail (0 rows)`) so the 9B routes to populated sources without seeing raw chat content. |
| **Formatting & temporal grounding** | `_fmt()` and `compose()`. | Don't truncate `messages` bodies/URLs at 160 chars (render match-centered excerpts + full URLs). Pass `Today is <IST date>` into `compose()` so historical *"today"* / *"tomorrow"* inside old messages is anchored to the message's timestamp, not the query date. |
| **Citations / receipts** | `Result.note` + `--output humanize` | Show compact attribution (`_In Jam Buns · Vidya · 19 Nov 14:10 · ref 8a3f…_`) at the bottom of CLI and Signal replies. |

---

## 5. Decoupled Collector Path (Looking Ahead to Signal Onboarding)

Keep the DuckDB ingest format independent of how messages are fetched:

- **Phase 1 (CLI & search iteration):** `idli sync whatsapp --from-snapshot <path>` ingests the frozen 2,783-message DGX capture (`windows-xTcFis/fresh.json`) reproducibly in seconds, with zero browser flakiness.
- **Phase 2 (Multi-user Signal onboarding):** Replace per-user headed Chromium with a tiny **read-only `whatsmeow` Go sidecar** inside each user's sandbox container:
  - ~20 MB RAM per user (vs ~500 MB–1 GB for Chromium + Xvfb).
  - No write/send methods compiled in.
  - Supports **8-digit phone-number pairing codes** (in addition to QR) directly on the `silo.idli.cc` onboarding web page, so a user signing up from their phone over Signal doesn't need a second screen.
  - Streams HistorySync, `ContextInfo` reply parents, captions, and incremental updates into the user's `store.duckdb`.

---

## 6. Verification & Rollout Gates

1. **Zero regression on core:** Existing unit tests (`test_scaffold_prose.py`, CLI tests) + Google dev banks pass unchanged.
2. **Frozen WhatsApp dev bank (`windows-xTcFis` + `ask-LMunvw`):** Measure retrieval recall, all 4 controls (exact count, ambiguous `"V"`, unknown group, out-of-window September), and end-to-end grounded answers.
3. **Blind held-out bank:** Generate fresh questions from unseen messages/groups (can use `codex` / Cursor `agent` for blind drafting & grading) and run once on frozen code before claiming accuracy.
4. **Signal + onboarding smoke test:** Verify `--output humanize` citations over Signal DM, then smoke-test one containerized `whatsmeow` sidecar pairing end-to-end.
