# 2026-11-26 — Jetson Orin Nano 8GB Quantization & Smaller-Model Shootout

Controlled 5-arm comparison measuring whether Silo's `core/idli` CLI mapper + wording layer can drop from DGX `Qwen3.5-9B-Q5_K_M` (`6.13 GB`, `65k` ctx) to a smaller quantization (`Q4_K_M`, `IQ4_XS`) or a 4B model (`Qwen3.5-4B-Q5_K_M`, `Gemma-4-E4B-it-Q5_K_M`) to fit an **NVIDIA Jetson Orin Nano Super 8GB** (8 GB unified LPDDR5, ~6.5–6.8 GB usable headless) without sacrificing accuracy across WhatsApp, Drive, Sheets, Mail, Calendar, and mixed stores.

## Setup

- **Code revision:** `49cd8e6` (`q4_quantization` branch, unmodified `core/idli`, `--mapper nine_compressed --judge nine_compressed`, `IDLI_CHIPS=0`).
- **Retrieval sidecars (held constant across all 5 arms):** `Qwen3-Embedding-0.6B-Q8_0` (`:8293`) + `bge-reranker-v2-m3-Q8_0` (`:8294`).
- **Runtime:** `ghcr.io/ggml-org/llama.cpp:server-cuda13` (`build 10524`, CUDA 13.0). All 4 Jetson candidate arms ran on an isolated container (`127.0.0.1:8299`) with Jetson-realistic flags: **`-ngl 999 -c 8192 -np 1 -fa on --cache-type-k q8_0 --cache-type-v q8_0`** and **no `mmproj`** vision tower.
- **Suites (87 turns per arm × 5 arms = 435 total turns):**
  1. `wa_blind_v3.json` (**20 unseen WhatsApp cases:** 10 single, 6 multi, 4 controls — drafted blind by `codex exec` with 0 target-row ID or body overlap across all 3 prior WA banks).
  2. `mixed_google_wa.json` (**16 mixed-store cross-routing cases:** 4 Drive/Sheets, 3 Mail, 1 Calendar, 4 WhatsApp, 4 boundary controls — run on one combined DuckDB containing both `silo-smoke` Google data and all 24 WA chats / 2,783 messages).
  3. `benchmarks/bank/tasks_owner_dev.json` (**11 tasks / 19 turns:** Drive PDFs/cards/summarise, Sheets, Gmail leads, Calendar) run with `--no-yes`.
  4. `benchmarks/bank/tasks_heldout.json` (**27 tasks / 32 turns:** Mail, Calendar, Drive, Sheets, write-refusals, connector boundaries) run with `--no-yes`.
- **Grading:** Strictly blind across all 5 arms via 3 independent `codex exec` grader runs (WA `blind-v3`, Mixed Google+WA with routing-leak checks, and Google `owner_dev` + `heldout` verified via read-only SQL against `base_google/store.duckdb` per `benchmarks/grader/RUBRIC.md`).
- **Private inputs & raw outputs (outside Git, `0700`):** `~/.local/share/silo-owner-pilot/jetson-shootout-2026-11-26/` (`wa_blind_v3.json`, `mixed_google_wa.json`, `telemetry_summary.json`, `grades_wa_blind_v3.json`, `grades_mixed.json`, `grades_google.json`, `arms/<arm>/`). Model GGUFs live under `/mnt/seagate/io-models/`.

## Command

```bash
core/.venv/bin/python benchmarks/runs/2026-11-26-jetson-quant-shootout/run_shootout.py \
  --work-dir ~/.local/share/silo-owner-pilot/jetson-shootout-2026-11-26 \
  --arms qwen35_9b_q5 qwen35_9b_q4 qwen35_9b_iq4xs qwen35_4b_q5 gemma4_e4b_q5
```

## Results

### Overall Scoreboard (87 blind-graded turns per arm)

| Arm | GGUF Size | GPU Memory (`nvidia-smi`) | WA `blind-v3` (20) C/P/W | Mixed (16) C/P/W (leaks) | Google Owner Dev (19) C/P/W | Google Heldout (32) C/P/W | **All 87 Turns C/P/W** | **Non-Wrong** | CLI Errors | Median Latency |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **`qwen35_9b_q5`** (DGX baseline, 65k ctx + mmproj) | 6.13 GB | 8,591 MiB (8.39 GiB) | 13/3/4 (14/16 ev) | 11/2/3 (1) | 9/6/4 | 8/14/10 | **41 / 25 / 21** | **66 / 87 (76%)** | 5 | 3.7–4.5 s |
| **`qwen35_9b_q4`** (Jetson 8k ctx, no mmproj) | 5.29 GB | **5,353 MiB (5.23 GiB)** | **13/3/4** (14/16 ev) | **11/2/3 (0)** | 5/9/5 | 12/12/8 | **41 / 26 / 20** | **67 / 87 (77%)** | **5** | 2.7–4.2 s |
| **`qwen35_9b_iq4xs`** (Jetson 8k ctx, no mmproj) | 4.81 GB | **4,862 MiB (4.75 GiB)** | 12/3/5 (12/16 ev) | 10/2/4 (0) | **9/7/3** | **13/11/8** | **44 / 23 / 20** | **67 / 87 (77%)** | 8 | **2.3–3.7 s** |
| **`qwen35_4b_q5`** (Jetson 8k ctx) | 2.93 GB | 3,471 MiB (3.39 GiB) | 5/1/14 (5/16 ev) | 5/1/10 (1) | 5/4/10 | 9/16/7 | 24 / 22 / 41 | 46 / 87 (53%) | 28 | 2.1–3.6 s |
| **`gemma4_e4b_q5`** (Jetson 8k ctx) | 5.11 GB | 3,838 MiB (3.75 GiB) | 7/2/11 (6/16 ev) | 9/1/6 (2) | 4/7/8 | 10/12/10 | 30 / 22 / 35 | 52 / 87 (60%) | 14 | 4.0–7.2 s |

### Breakdown by Resource (Google 51 turns + Mixed 16 turns)

| Arm | Google Drive/Sheets (27) | Google Mail (9) | Google Calendar (8) | Google Other (7) | Mixed Drive (4) | Mixed Mail+Cal (4) | Mixed WA (4) | Mixed Control (4) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `qwen35_9b_q5` | 14/9/4 | 0/5/4 | 1/4/3 | 2/2/3 | 3/0/1 | 2/1/1 | 3/0/1 | 3/1/0 |
| `qwen35_9b_q4` | 11/12/4 | 1/4/4 | 2/2/4 | 3/3/1 | 2/0/2 | 2/1/1 | **4/0/0** | 3/1/0 |
| `qwen35_9b_iq4xs` | 13/9/5 | 1/6/2 | 4/1/3 | 4/2/1 | 2/0/2 | 2/1/1 | 3/0/1 | 3/1/0 |
| `qwen35_4b_q5` | 6/11/10 | 2/4/3 | 2/4/2 | 4/1/2 | 3/0/1 | 1/0/3 | 0/0/4 | 1/1/2 |
| `gemma4_e4b_q5` | 5/10/12 | 1/5/3 | 3/3/2 | 5/1/1 | 3/0/1 | 2/0/2 | 2/0/2 | 2/1/1 |

## Key Findings & Hardware Recommendation

1. **`Qwen3.5-9B` quantizes cleanly down to `Q4_K_M` and `IQ4_XS` with zero meaningful accuracy loss:**
   - Across 87 turns spanning WA, Drive, Sheets, Mail, Calendar, and Mixed cross-routing, **`Q4_K_M` (`41/26/20`, `5` errors)** and **`IQ4_XS` (`44/23/20`, `8` errors)** matched or slightly edged the `Q5_K_M` DGX baseline (`41/25/21`, `5` errors), while running **20–30% faster** and cutting GPU memory from **8.39 GiB → 4.75–5.23 GiB**.
   - **Zero context overflows at `-c 8192 -np 1`:** Peak prompt length across all 435 turns (including the full mixed Google + 24-chat WA menu) was `16,841` characters (~4.5k tokens), with `0` `mapper_failed` turns.
2. **Both 4B models (`Qwen3.5-4B-Q5_K_M` and `Gemma-4-E4B-it-Q5_K_M`) are NOT sufficient for Silo's CLI mapper:**
   - `Qwen3.5-4B-Q5_K_M` collapsed on WhatsApp (`5/16` evidence, `5/1/14` strict; `0/4` on Mixed WA) and generated **28 CLI errors** (`5.6×` worse than 9B).
   - `Gemma-4-E4B-it-Q5_K_M` scored `4/4` on WA controls and `9/1/6` on Mixed, but collapsed on WA retrieval (`6/16` evidence, `7/2/11`), Google Drive (`5/10/12`), and triggered **27 `compose()` fallbacks** on Google (`6.8×` worse than 9B).
3. **Jetson Orin Nano Super 8GB sizing verdict:**
   - **Recommended model for headless 8 GB Jetson:** **`Qwen3.5-9B-IQ4_XS`** (`4,862 MiB` / `4.75 GiB` GPU, leaving ~1.8–2.0 GiB OS/headroom on headless JetPack) or **`Qwen3.5-9B-Q4_K_M`** (`5,353 MiB` / `5.23 GiB` GPU, leaving ~1.3–1.5 GiB headroom) — with `-c 8192 -np 1 --cache-type-k q8_0 --cache-type-v q8_0`, **no `mmproj`**, and **embeddings + reranker hosted remotely** (e.g., on DGX via `silo.idli.cc` or run on-demand).
   - Note that `Qwen3.5-9B-Q4_K_M` had slightly stronger WA retrieval (`14/16` vs `12/16` evidence, `5` vs `8` CLI errors), whereas `IQ4_XS` saves ~500 MiB GPU RAM and led slightly on Google (`22` vs `17` strict correct across the 51 Google turns). On a real 8 GB Jetson, test `Q4_K_M` first headless; drop to `IQ4_XS` if OS/DuckDB memory pressure triggers swap or OOM.

## Limitations

- Memory was measured on DGX GB10 (CUDA 13.0) with `nvidia-smi` GPU MiB; Jetson Orin Nano Super unified memory shares OS + CUDA allocations, so real headless Jetson peak RAM should be verified once on device (expect ~1.2–1.5 GiB JetPack baseline + the measured GPU MiB).
- Google `tasks_owner_dev` and `tasks_heldout` were run with `--no-yes` (stopping cleanly at yes-cards for `define`/`view` tasks, which accounts for many `partial` grades across all 5 arms uniformly) and against the live `silo-smoke` snapshot rather than the original Nov 21 `io` fixture dates. Cross-arm comparisons remain apples-to-apples because every arm saw the exact same store and flags.
- `idli-embed` and `idli-rerank` stayed on DGX (`:8293` / `:8294`) for all 5 arms; latency on Jetson's 102 GB/s memory bandwidth will be ~2.5–3× slower than DGX GB10 (~273 GB/s).
