# Decode speed

**Question:** how many tokens per second does local Muse Glimmer 30B produce
on the DGX Spark, under each quant and drafter setting?

**Protocol:** `tg-bridge/bench.py` sends 3 fixed prompts (prose, code, data) to
`127.0.0.1:8181` at temperature 0, and reports tok/s and drafter acceptance.
Start the server with `tg-bridge/serve_muse.sh <model.gguf> [drafter.gguf] [args]`.

| run | contents |
|---|---|
| 2026-10-11-quant-drafter-sweep/output.txt | Q8+d, Q4, Q4+d, Q6+d: speed and eval wall time |
| 2026-10-11-quant-drafter-sweep/q8-drafter-n8-vs-n16.txt | Q8 + Q4_K_M drafter, draft window 8 vs 16 |

The Q8 baseline without a drafter (7.4 tok/s) was measured before this layout
existed, and its raw output was not kept.
