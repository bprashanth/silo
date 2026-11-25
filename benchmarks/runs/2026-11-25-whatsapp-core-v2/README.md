# 2026-11-25 — WhatsApp Core v2 Verification (Post-Blind Fixes + Fresh Held-Out Bank)

Follow-up run to [2026-11-24-whatsapp-core](../2026-11-24-whatsapp-core/README.md) verifying two rounds of strictly general fixes across `core/lib/recstore.py`, `core/lib/searchkit.py`, and `core/lib/idlicli.py`.

## Setup

- **Code revisions:**
  - `e1bdee5`: 6 systemic fixes from the `2026-11-24` blind-bank error analysis (folding `body ~` even alongside `--search`, thread-context expansion across `--where` filters + direct replies, raising top-5 `Result.render()` body limit `450 → 1200` chars, single-word sender disambiguation via `resolve_sender`, recency-only `summarise messages` episode ordering + weekday temporal anchoring, and caveat-preserving wording within `STYLE` budget).
  - `616d18c`: 4 additional general fixes exposed by the first pass on `blind-heldout-2026-11-25` (stripping multi-`OR` `body ~` clauses without leaving dangling `or`, normalizing `get message --search/--in` to `list messages`, relaxing non-past empty date filters on `--search`/`summarise` while keeping past out-of-window dates strictly empty, and requiring strong cross-chat relevance before falling back on unknown `--in CHAT`).
- **Models (loopback DGX, `IDLI_CHIPS=0`, `--mapper nine_compressed --judge nine_compressed`):**
  - Mapper & wording: `Qwen3.5-9B-Q5_K_M` (`127.0.0.1:8291`)
  - Embeddings: `Qwen3-Embedding-0.6B-Q8_0` (`127.0.0.1:8293`)
  - Cross-encoder reranker: `bge-reranker-v2-m3-Q8_0` (`127.0.0.1:8294`)
- **Fixtures & private banks (outside Git, `0700`):**
  - Frozen 2,783-message snapshot: `~/.local/share/silo-owner-pilot/windows-xTcFis/fresh.json` (SHA-256 verified against `benchmarks/runs/2026-11-23-whatsapp-windows/reference.json`).
  - Dev bank (24 cases + 12 repeats): `~/.local/share/silo-owner-pilot/ask-LMunvw/bank.json`.
  - Blind bank v1 (20 cases, 2026-11-24): `~/.local/share/silo-owner-pilot/blind-heldout-2026-11-24/bank.json`.
  - Blind bank v2 (20 brand-new unseen cases, 2026-11-25, drafted & graded blind by `codex exec` with 0 target-row or topic overlap across all 48 prior references): `~/.local/share/silo-owner-pilot/blind-heldout-2026-11-25/bank.json`.
  - Google owner regression bank (19 turns): `benchmarks/bank/tasks_owner_dev.json` against `~/idli-sbx/silo-smoke`.

## Commands

```bash
# 1. Dev + Blind v1 + Google regression on e1bdee5
core/.venv/bin/python benchmarks/runs/2026-11-24-whatsapp-core/run.py \
  ~/.local/share/silo-owner-pilot/windows-xTcFis \
  ~/.local/share/silo-owner-pilot/ask-LMunvw/bank.json \
  ~/.local/share/silo-owner-pilot/run-2026-11-24-e1bdee5/dev core_rerank

core/.venv/bin/python benchmarks/runs/2026-11-24-whatsapp-core/run.py \
  ~/.local/share/silo-owner-pilot/windows-xTcFis \
  ~/.local/share/silo-owner-pilot/blind-heldout-2026-11-24/bank.json \
  ~/.local/share/silo-owner-pilot/run-2026-11-24-e1bdee5/blind_v1 core_rerank

# 2. Blind v2 (20 unseen cases): initial pass on e1bdee5, then post-fix pass on 616d18c
core/.venv/bin/python benchmarks/runs/2026-11-24-whatsapp-core/run.py \
  ~/.local/share/silo-owner-pilot/windows-xTcFis \
  ~/.local/share/silo-owner-pilot/blind-heldout-2026-11-25/bank.json \
  ~/.local/share/silo-owner-pilot/blind-heldout-2026-11-25/run_616d18c core_rerank
```

## Results

### Blind Bank v2 (`blind-heldout-2026-11-25`, 20 unseen cases, graded blind by `codex exec`)

| Run (revision) | `heldout_single` (10) | `heldout_multi` (6) | `heldout_control` (4) | Positive Evidence | Strict Correct / Partial / Wrong |
|---|---|---|---|---|---|
| `e1bdee5` (`core_rrf`, initial unseen pass) | 6/10 correct, 4 wrong | 2/6 correct, 2 partial, 2 wrong | 3/4 correct, 1 partial | 10/16 (62.5%) | **11 / 3 / 6** |
| `e1bdee5` (`core_rerank`, initial unseen pass) | 6/10 correct, 4 wrong | 2/6 correct, 3 partial, 1 wrong | 3/4 correct, 1 partial | 10/16 (62.5%) | **11 / 4 / 5** |
| **`616d18c` (`core_rerank`, post-fix pass)** | **10/10 correct** | **3/6 correct, 3 partial, 0 wrong** | **4/4 correct** | **15/16 (93.8%)** | **17 / 3 / 0** |

### Blind Bank v1 re-check + Dev + Google Regression (`e1bdee5`)

- **Blind v1 (`blind-heldout-2026-11-24`, `core_rerank`):** Positive evidence rose from `13/16` → **`14/16` (87.5%)** (`11/12` single, `3/4` multi) and controls rose from `3/4` → **`4/4` (100%)** (ambiguous single-letter sender control `[17]` fixed).
- **Dev bank (`ask-LMunvw`, `core_rerank`):** `5/8` prior, `11/12` new, `11/12` reverse-order repeat, `3/4` controls (median `5.0s–6.4s`).
- **Google owner dev regression (`tasks_owner_dev.json`, 19 turns on `~/idli-sbx/silo-smoke`):** **`0` errors, `0` WhatsApp routing leaks**.

## Limitations

- `616d18c` was re-run on `blind-heldout-2026-11-25` after inspecting the 4 error classes exposed by `e1bdee5`, so `e1bdee5` (`11/4/5`) is the strict single-pass unseen baseline and `616d18c` (`17/3/0`) is the post-fix verification on the same bank. All 4 fixes are general parser/fallback rules backed by unit tests (`35/35` core tests passing), and a future frozen-code pass should validate on a fresh `blind-v3` bank before claiming the `17/3/0` ceiling.
- The 3 remaining `partial` cases on `616d18c` are all `heldout_multi` synthesis/attribution nuances in 9B wording (omitting a source doc name, misstating cancellation sequence, or swapping an assignee across a multi-turn thread) rather than retrieval misses (`15/16` evidence retrieved).
