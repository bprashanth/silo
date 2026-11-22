# Models in the core today (companion to models.md)

Implementation notes, 2026-11-21. models.md splits the work between our team, the Builder and Sandbox Claude. This
lists the models the core itself calls, where they run, and what they cost. All on the DGX, on 127.0.0.1.

| Model | Job | Where | Speed, measured |
|---|---|---|---|
| Qwen3.5-9B, Q5 (`idli-9b`) | picks commands (default mapper), words replies, makes cards | port 8291 | ~1.7 s per judged item; ~5 s per card |
| Qwen3.5-9B, BF16 (`idli-9b-bf16`) | the same, uncompressed: `--mapper nine` | port 8292 | ~2x slower, 2 more right of 38 when judging |
| Clef-flash (Cloudflare) | judges records (default judge); labels the kind of ask | OpenRouter, Cloudflare only | ~0.1-0.5 s per item, ~$1 per 100,000 |
| Qwen3-Embedding-0.6B, Q8 (`idli-embed`) | meaning of page chunks, cards and questions | port 8293 | ~37 chunks a second |
| idli-remote (DeepSeek through OpenRouter) | picks commands from a masked question: `--mapper remote` | OpenRouter | ~1 s |
| GLiNER (`io-privacy-server`) | finds names for masking | port 8899, or `privacy.idli.cc` | milliseconds |

Muse (port 8181, 28B dense) is shared and not used by the core; never restart it.

## Measurements behind the choices (in io)

- Judge: what the judge sees matters most; with file contents Clef 38 of 38, 9B 33 of 38
  (`io/benchmarks/runs/2026-11-20-judge-models/`).
- Mapper: on frozen held-out tasks the 9B got 10 of 27 right and idli-remote 13 of 27
  (`io/benchmarks/runs/2026-11-21-heldout-rerun/`).
- Kind of ask: Clef agrees with the labels on 70% of the questions it labels; workflow chips 10 of 13
  (`io/benchmarks/runs/2026-11-21-kind-classifier/`).

## How this maps to models.md

These are all "inside the sandbox" models. Hosted Clef reads real content, so it stands in for a local Clef (same
size as the 9B) for test accounts only. The Builder and Sandbox Claude don't run in the core yet.
