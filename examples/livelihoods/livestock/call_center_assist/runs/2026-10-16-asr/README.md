# ASR Engines Report

Conditions order in slash-separated columns: `clean / farm_phone / gsm / opus6k_loss`.
`p50 ms` is median per-clip latency across non-noise clips from each engine `.jsonl` run.

| engine | edacc WER per condition | farmer WER farm_phone | farmer keys per condition | p50 ms | noise hallucinations |
|---|---:|---:|---:|---:|---:|
| canary-1b-v2 | 9.8% / 30.1% / 16.8% / 26.1% | 9.9% | 90.5% / 75.8% / 88.4% / 85.3% | 170 | 0 |
| canary-qwen-2.5b | 7.7% / 32.2% / 17.3% / 23.6% | 8.7% | 91.6% / 80.0% / 91.6% / 89.5% | 407 | 4 |
| fw-base.en-cpu | 19.6% / 50.7% / 31.8% / 47.1% | 22.1% | 87.4% / 56.8% / 84.2% / 74.7% | 376 | 1 |
| fw-turbo-cpu | 10.9% / 29.8% / 17.3% / 25.9% | 9.4% | 91.6% / 77.9% / 90.5% / 85.3% | 4831 | 6 |
| hf-oriserve-apex-gpu | 17.5% / 61.1% / 30.0% / 49.5% | 45.8% | 70.5% / 40.0% / 67.4% / 63.2% | 134 | 6 |
| hf-whisper-turbo-gpu | 9.9% / 41.9% / 16.8% / 26.6% | 8.9% | 90.5% / 81.1% / 90.5% / 85.3% | 146 | 2 |
| hf-whisper-v3-gpu | 10.9% / 33.3% / 17.9% / 27.2% | 6.6% | 93.7% / 87.4% / 92.6% / 90.5% | 308 | 1 |
| or-google_gemini-3.5-flash-lite | 10.9% / 42.2% / 20.9% / 33.5% | 11.3% | 93.7% / 77.9% / 94.7% / 88.4% | 1901 | 6 |
| or-google_gemini-3.8-flash | 6.7% / 28.3% / 12.0% / 24.6% | 4.0% | 100.0% / 94.7% / 98.9% / 96.8% | 5067 | 4 |
| or-qwen_qwen3.8-omni-flash | 6.9% / 27.4% / 13.1% / 20.4% | 6.3% | 93.7% / 86.3% / 95.8% / 93.7% | 3623 | 6 |
| parakeet-v2 | 7.9% / 26.7% / 12.8% / 20.8% | 9.2% | 88.4% / 77.9% / 89.5% / 89.5% | 46 | 0 |
| parakeet-v2-boost | 7.9% / 28.5% / 15.0% / 21.7% | 7.0% | 96.8% / 94.7% / 96.8% / 95.8% | 44 | 0 |
| parakeet-v3 | 6.6% / 24.5% / 12.3% / 18.7% | 8.9% | 90.5% / 74.7% / 86.3% / 85.3% | 50 | 0 |
| parakeet-v3+correct | 7.1% / 24.8% / 12.7% / 19.1% | 8.0% | 90.5% / 78.9% / 90.5% / 88.4% | 1392 | 0 |
| parakeet-v3-boost | 6.9% / 24.8% / 12.2% / 18.8% | 5.9% | 94.7% / 89.5% / 94.7% / 93.7% | 52 | 0 |
| parakeet-v3-boost-cs0.7-ds1.5-a0.5 | 6.8% / 24.4% / 12.3% / 18.7% | 6.1% | 92.6% / 85.3% / 94.7% / 91.6% | 99 | 0 |
| parakeet-v3-boost-cs1.0-ds2.0-a0.6 | 6.8% / 24.4% / 12.0% / 18.7% | 5.4% | 94.7% / 88.4% / 94.7% / 92.6% | 99 | 0 |
| parakeet-v3-boost-cs1.6-ds2.5-a0.9 | 6.9% / 24.8% / 12.2% / 18.8% | 5.9% | 94.7% / 89.5% / 94.7% / 93.7% | 51 | 0 |
| parakeet-v3-boost-vocab | 6.6% / 24.6% / 12.4% / 19.4% | 8.0% | 90.5% / 83.2% / 87.4% / 86.3% | 48 | 0 |
| voxtral-mini-3b | 12.0% / 32.7% / 18.0% / 34.4% | 7.7% | 90.5% / 83.2% / 91.6% / 88.4% | 769 | 3 |

## Requested Engines: Peak GPU Memory
Measured via `torch.cuda.max_memory_allocated()` on one representative corpus clip after model load.

- `parakeet-v2`: 2.510 GiB (2695215616 bytes)
- `hf-whisper-v3-gpu`: 5.587 GiB (5999346688 bytes)
- `hf-oriserve-apex-gpu`: 4.021 GiB (4317946880 bytes)
- `canary-qwen-2.5b`: 4.942 GiB (5306076672 bytes)
- `voxtral-mini-3b`: 8.913 GiB (9570507776 bytes)
- `parakeet-v3-boost-vocab`: 2.639 GiB (2833566208 bytes)
- `parakeet-v2-boost`: 5.076 GiB (5450486272 bytes)

## Notes
- `hf-oriserve-apex-gpu` accepted `language=en` + `task=transcribe`, but output often includes punctuation/casing rewrites and occasional literal `nan` hypotheses on noisy conditions.
