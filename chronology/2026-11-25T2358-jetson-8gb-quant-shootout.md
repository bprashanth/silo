# 2026-11-25 23:58 IST — Jetson 8GB Quantization & 4B Model Shootout (435 blind-graded turns)

## What we tested

To answer whether Silo can fit on an **NVIDIA Jetson Orin Nano Super 8GB** (8 GB unified RAM, with smaller embed/rerank models hosted elsewhere if needed) without risking silent quality regression, we ran a controlled 5-arm shootout across **87 turns per arm (435 total turns)** spanning WhatsApp (`wa_blind_v3`, 20 brand-new unseen cases with 0 overlap across all 3 prior banks), Mixed Google+WA (`mixed_google_wa`, 16 cross-routing cases in one combined sandbox), Google `tasks_owner_dev` (19 turns), and Google `tasks_heldout` (32 turns), graded blind by `codex exec`:

- `qwen35_9b_q5` (`6.13 GB`, `8,591 MiB` GPU, `65k` ctx + `mmproj`) — DGX baseline
- `qwen35_9b_q4` (`5.29 GB`, `5,353 MiB` GPU, `-c 8192 -np 1`, no `mmproj`)
- `qwen35_9b_iq4xs` (`4.81 GB`, `4,862 MiB` GPU, `-c 8192 -np 1`, no `mmproj`)
- `qwen35_4b_q5` (`2.93 GB`, `3,471 MiB` GPU, `-c 8192 -np 1`)
- `gemma4_e4b_q5` (`5.11 GB` on disk, `3,838 MiB` GPU, `-c 8192 -np 1`)

## What we learned

1. **9B `Q4_K_M` and `IQ4_XS` at `-c 8192 -np 1` preserved 100% of `Q5_K_M`'s quality:**
   - `Q5_K_M`: `41 correct / 25 partial / 21 wrong` (`66/87` non-wrong, `5` CLI errors, `13/3/4` WA, `11/2/3` Mixed with `1` leak).
   - `Q4_K_M`: **`41 / 26 / 20`** (`67/87` non-wrong, `5` CLI errors, **`13/3/4` WA**, **`11/2/3` Mixed with `0` routing leaks**).
   - `IQ4_XS`: **`44 / 23 / 20`** (`67/87` non-wrong, `8` CLI errors, `12/3/5` WA, `10/2/4` Mixed with `0` routing leaks, led on Google `22` vs `17` strict correct).
   - Peak prompt across all 435 turns (even with the full mixed Google + 24-chat WA menu) was `16,841` chars (~4.5k tokens) — **0 context overflows at `-c 8192`**.
2. **Both 4B models (`Qwen3.5-4B-Q5_K_M` and `Gemma-4-E4B-it-Q5_K_M`) failed the quality bar:**
   - `Qwen3.5-4B-Q5_K_M`: `24 / 22 / 41` (`5/16` WA evidence, `0/4` on Mixed WA, `28` CLI errors).
   - `Gemma-4-E4B-it-Q5_K_M`: `30 / 22 / 35` (`6/16` WA evidence, `14` CLI errors, `27` Google `compose()` fallbacks).
3. **Decision:** Keep **`Qwen3.5-9B`** (do NOT drop to 4B). For a headless **Jetson Orin Nano Super 8GB**, use **`Qwen3.5-9B-Q4_K_M` (`5.23 GiB` GPU)** or **`Qwen3.5-9B-IQ4_XS` (`4.75 GiB` GPU, ~500 MiB extra headroom)** with `-c 8192 -np 1 --cache-type-k q8_0 --cache-type-v q8_0`, no `mmproj`, and offload `idli-embed` + `idli-rerank` off-device.

Full tables and setup: [benchmarks/runs/2026-11-26-jetson-quant-shootout/README.md](../benchmarks/runs/2026-11-26-jetson-quant-shootout/README.md).
