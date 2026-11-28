# 2026-11-26 19:50 IST — Model Sizing Chart, Live `silo.idli.cc` Q4_K_M Swap & `idli-embed` Tightening

## What the user wanted

1. Visualize the 5-arm shootout as a clear chart of **intelligence (model size) vs. blind score vs. smallest hardware cost (₹)** showing where the dropoffs sit, and embed it in a `narrative/` doc.
2. Swap the live model behind `https://silo.idli.cc` to the recommended 9B quant and stop unused DGX LLMs to free GPU RAM.
3. Clarify what powers the search/stemming layer (and whether `idli-9b-bf16` was needed for stemming), then tighten `idli-embed`'s oversized GPU scratch buffers.

## What we did

1. **Frontier chart & narrative:**
   - Created [benchmarks/runs/2026-11-26-jetson-quant-shootout/plot_shootout.py](../benchmarks/runs/2026-11-26-jetson-quant-shootout/plot_shootout.py) → [narrative/images/jetson-8gb-model-cost-frontier.png](../narrative/images/jetson-8gb-model-cost-frontier.png) (2-panel plot: GPU footprint & India INR hardware cost tiers vs. All-87 Non-Wrong % and WA Evidence Recall %, plus stacked Correct/Partial/Wrong verdict bars, CLI errors, and hardware floor).
   - Wrote [narrative/jetson-8gb-model-sizing.md](../narrative/jetson-8gb-model-sizing.md) embedding the chart and documenting the India street-price comparison (`Jetson Orin Nano Super 8GB` $249 ≈ ₹28k–₹30k landed vs ₹47k–₹65k India reseller retail vs `Mac mini M4 16GB` ₹59,900 official MRP vs `Jetson Orin NX 16GB` ₹1.15L+ vs `DGX Spark` ₹6.9L). Indexed from [README.md](../README.md) and [handoff/handoff.md](../handoff/handoff.md).
2. **Swapped live DGX models behind `https://silo.idli.cc`:**
   - Replaced `idli-9b` (`:8291`): `Qwen3.5-9B-Q5_K_M` + `mmproj-F16` (`-c 65536 -np 2`, `8,591 MiB`) → **`Qwen3.5-9B-Q4_K_M`** (no `mmproj`, `-c 16384 -np 2` = 2 × 8k slots, `-fa on --cache-type-k q8_0 --cache-type-v q8_0`, **`5,561 MiB`**).
   - Stopped (not removed, so `docker start` brings them back anytime): `idli-9b-bf16` (`17,987 MiB`, `:8292`) and `idli-muse` (`25,162 MiB`, `:8181`, last served traffic 20 Nov).
   - Verified `idli-9b-bf16` is **not** used for stemming or search (only reachable via explicit `--mapper nine` / `--judge nine` in `core/lib/recstore.py`; default `nine_compressed` hits `idli-9b`). Stemming & BM25 run purely in CPU/SQL via DuckDB `fts` (`stemmer='porter'`) + Python `_stem_lite`/Jaro-Winkler in [core/lib/searchkit.py](../core/lib/searchkit.py).
3. **Tightened `idli-embed` (`:8293`):**
   - `Qwen3-Embedding-0.6B-Q8_0` (`~640 MB` weights) was holding `6,510 MiB` GPU RAM due to `-c 8192 -ub 8192 -b 8192 -np 4` quadratic attention/ubatch buffers.
   - Recreated `idli-embed` with **`-fa on -c 4096 -ub 2048 -b 2048 -np 2`** → GPU RAM dropped from `6,510 MiB` → **`2,449 MiB`** (`−4,061 MiB`).
   - Verified live over `https://silo.idli.cc`:
     - `/v1/chat/completions` (`model=idli-9b` → `qwen3.5-9b`): `200 OK`
     - `/v1/embeddings`: `200 OK` on single query (`dim=1024`), `batch=32` × `1,200`-char chunks (`0.80 s`), and `6,000`-char max-cap item (matching `recstore.py:711`)
     - `/v1/rerank` (`bge-reranker-v2-m3-Q8_0`, `929 MiB`): `200 OK`
   - **Total active Silo GPU footprint on DGX:** `57.79 GiB` (`59,179 MiB`) → **`8.73 GiB` (`8,939 MiB`)** — **49.1 GiB freed**.

## What remains open

- Branch `q4_quantization` is local-only (not pushed) for owner review/PR into `main`.
- Outside this repo (`io`): the 6-line `/v1/embeddings` + `/v1/rerank` routing edit in `/home/beeps/src/github.com/bprashanth/io/benchmarks/runs/2026-11-06-oss-desktop-independent/dgx/muse_prefix_proxy.py` is running live but uncommitted in `io`; `dgx/idli-9b.sh` still references `Q5_K_M` if restarted via script rather than Docker `--restart unless-stopped`.
- Next engineering tracks: (1) Phase 2 multi-message synthesis & cross-app `Drive ↔ WA` quality pass on `Qwen3.5-9B-Q4_K_M`, (2) one physical headless Jetson Orin Nano Super 8GB smoke test (`Q4_K_M` vs `IQ4_XS` under JetPack + DuckDB + `silo-wa-sync`), (3) Stage 2 public `silo.idli.cc` Signal onboarding route, and (4) Stage 1 laptop feedback triage.
