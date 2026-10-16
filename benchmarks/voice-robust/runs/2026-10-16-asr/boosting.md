# Parakeet TDT Phrase-Boosting Report

Date: 2026-10-16

## What was changed

- Added a new engine name `parakeet-v3-boost` in `benchmarks/voice-robust/asr_engines.py`.
- The new engine loads all phrases from `benchmarks/voice-robust/domain_terms.json`, deduplicates them, and enables NeMo transducer context biasing for `greedy_batch` decode.
- Kept existing engine names and behavior unchanged (`parakeet-v3`, `parakeet-v2`, etc.).
- Added env overrides for tuning:
  - `VR_PARAKEET_BOOST_CONTEXT_SCORE`
  - `VR_PARAKEET_BOOST_DEPTH_SCALING`
  - `VR_PARAKEET_BOOST_ALPHA` (`boosting_tree_alpha`)
- Defaulted `parakeet-v3-boost` to the best trade-off found in this run set:
  - `context_score=1.6`, `depth_scaling=2.5`, `boosting_tree_alpha=0.9`.

## NeMo API used (verified from installed source)

- `nemo/collections/asr/models/rnnt_bpe_models.py`
  - `change_decoding_strategy()` merges `decoding_cfg` and rebuilds RNNT/TDT decoder state.
- `nemo/collections/asr/parts/submodules/rnnt_decoding.py`
  - Reads `cfg.greedy.boosting_tree` and `cfg.greedy.boosting_tree_alpha`.
  - Builds fusion model with `GPUBoostingTreeModel.from_config(...)`.
  - Passes fusion model + alpha into `GreedyBatchedTDTInfer(... fusion_models, fusion_models_alpha ...)` for `greedy_batch`.
- `nemo/collections/asr/parts/context_biasing/boosting_graph_batched.py`
  - `BoostingTreeModelConfig` fields used: `key_phrases_list`, `context_score`, `depth_scaling`, `source_lang`, `use_triton`.
  - `GPUBoostingTreeModel.from_config()` constructs the boosting tree from phrase list + context graph.

## Bench command

`~/.local/share/silo-voice/venv/bin/python asr_bench.py parakeet-v3-boost --sources farmer,edacc`

## Weights tried and summary

Baseline reference: `/mnt/seagate/silo/voice-robust/runs/asr/parakeet-v3.txt` (`parakeet-v3`).

| Run | context_score | depth_scaling | boosting_tree_alpha | edacc WER (%) | farmer WER (%) | farmer key recall (%) | latency p50 / p95 (ms) | noise hallucinations |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| baseline (`parakeet-v3`) | - | - | - | 15.54 | 5.87 | 84.21 | 49.9 / 79.8 | 0 |
| boost A | 1.0 | 2.0 | 0.6 | 15.49 | 3.35 | 92.63 | 98.9 / 142.6 | 0 |
| boost B | 0.7 | 1.5 | 0.5 | 15.57 | 3.76 | 91.05 | 99.1 / 138.8 | 0 |
| boost C | 1.6 | 2.5 | 0.9 | 15.69 | 3.81 | 93.16 | 51.3 / 78.0 | 0 |
| final default (`parakeet-v3-boost`) | 1.6 | 2.5 | 0.9 | 15.69 | 3.81 | 93.16 | 52.2 / 72.1 | 0 |

Saved run artifacts:
- `/mnt/seagate/silo/voice-robust/runs/asr/parakeet-v3-boost-cs1.0-ds2.0-a0.6.txt`
- `/mnt/seagate/silo/voice-robust/runs/asr/parakeet-v3-boost-cs0.7-ds1.5-a0.5.txt`
- `/mnt/seagate/silo/voice-robust/runs/asr/parakeet-v3-boost-cs1.6-ds2.5-a0.9.txt`
- `/mnt/seagate/silo/voice-robust/runs/asr/parakeet-v3-boost.txt` (final default engine run)

## No-harm checks

`edacc` per-condition WER (baseline -> final default):

| condition | baseline WER (%) | final default WER (%) | delta (abs) |
|---|---:|---:|---:|
| clean | 6.6 | 6.9 | +0.3 |
| farm_phone | 24.5 | 24.8 | +0.3 |
| gsm | 12.3 | 12.2 | -0.1 |
| opus6k_loss | 18.7 | 18.8 | +0.1 |

Conclusion on no-harm: small regression on some `edacc` conditions (<= +0.3 abs WER), one small improvement (`gsm`), and no catastrophic degradation.

Noise hallucination check: all runs had `hallucinated=0` on synthetic noise clips.

## Latency impact

- `boost A/B` roughly doubled inference latency vs baseline.
- `boost C` kept latency close to baseline while preserving strong term-recall gains.
- Final chosen default is `boost C` because it gives a good quality/speed trade-off:
  - key recall +8.95 points over baseline (84.21 -> 93.16)
  - farmer WER improved by 2.05 abs points (5.87 -> 3.81)
  - `edacc` change remains small.

## Failures / caveats

- No functional API/inference failures after wiring.
- GPU memory budget (<6 GB) could not be directly confirmed from `nvidia-smi` in this environment because memory query fields returned `N/A`; runs completed successfully on the shared GB10 GPU.
