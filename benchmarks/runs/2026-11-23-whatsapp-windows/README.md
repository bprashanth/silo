# Finding evidence across WhatsApp messages

A 23 November 2026 development benchmark on the owner’s linked DGX client, with the CLI at 64396b5. The [13 questions](cases.json) include eight positive lookups and five controls. Cases were selected with knowledge of the history. This run can guide an experiment on fresh cases; it does not estimate user-facing accuracy.

## What was tested

The [collector](../2026-11-22-whatsapp-groups/snapshot.py) read locally cached text, image captions and reply metadata from 26 groups active in the last calendar month. It retained 2,783 messages. Date filters apply in IST. On Monday Nov 23, “last week” means Nov 16–22. The initial CLI run used one independent shell turn per question, the local compressed 9B and local judge, no hosted chips. It used a clean copy of the WhatsApp-only DuckDB. The private stock log records the actual plans, answers and struggle signals. No source was written.

The [retrieval harness](trial.py) reads the same snapshot and uses the existing local Idli embedder and answer writer. It takes explicit group and date slots to isolate retrieval from natural-language parsing. The exact-link count uses DuckDB. The resolver matches normalized token prefixes against the scoped directory. The control with an ambiguous sender returns choices. This is assisted input and a structured result in a benchmark, not a shipped clarification flow.

The initial arms used two token-overlap hits, two message embeddings, ±5 chronological neighbors of those same semantic hits, a reply-aware packet from those hits, or the three highest-ranked conversation bursts. A burst contains up to five same-group messages with gaps of at most five minutes. The reply packet includes in-cache parent/direct-reply edges, nearby same-sender posts within five minutes, and ±3 chronological neighbors. A final arm asked the local judge to select evidence from the entire scope if at most 50 messages, otherwise from the reply packet. Results are candidate-message IDs plus the unchanged answer writer’s output or guard rejection. The writer has its existing 4,000-character input cap. Ranking and context assembly here use in-memory arrays, so this trial gives no DuckDB expansion latency claim.

For each positive case the [reference](reference.json) lists the source records that establish the answer. Each inner set contains alternatives; all sets must be represented. Form retrieval gets credit for Tejasa’s actual document link. A claim to have read the full questionnaire is graded separately. The orgs case tests three specifically discussed partner leads, distinct from names in the pasted conference agenda.

## First comparison

| Measure across eight positives | Literal | Message embedding | ±5 | Reply-aware | Burst embedding | Local judge |
|---|---:|---:|---:|---:|---:|---:|
| Cases with all reference evidence retrieved | 2 | 2 | 2 | 2 | 2 | 2 |

The two successes in every column were the roster and Nadhi. A plain message embedding plus the existing answer writer reproduced the roster and its lead. The Nadhi attendance-eligibility note was retrievable, yet the writer also folded an unrelated discussion of future calls into its summary. Burst retrieval picked up one of three partner leads. For the remaining cases, expanding two low-quality hits mostly provided more unrelated text. The stock CLI produced no complete, grounded answer on the eight positive cases.

For controls, binding Jam Buns by its abbreviated title gave the correct six HTTP(S)-bearing rows. A nonexistent group yielded suggestions rather than a count. The weak similarity suggestions included unrelated groups. Matching “V” across any token produced six sender choices, including surname and interior tokens. Choices still need ranking. September yielded zero captured records, so the IAF question has no coverage in this snapshot. Record the coverage gap, not a negative claim about IAF. For actual Royal Enfield attendance, the reply-aware writer introduced unsupported attendee counts. No final attendance was established. The stock `struggled` signal flagged the sender command failure; it missed the confidently wrong zero count for the unknown group.

## Replay and evidence access

Private frozen input and outputs are on the owner’s DGX at `~/.local/share/silo-owner-pilot/windows-xTcFis`. `fresh.json` supplies source records and relations, `sandbox/` holds the imported views, and `stock/log.jsonl` contains the shell audit. `result-*.json` captures all initial packets and actual wording. `rewrite-*.json` and `scope-*.json` preserve later retrieval traces and citations. `shots.json` maps four receipts to exact message refs; the PNGs remain private under `shots/`.

To repeat, create a private directory and copy only `fresh.json` and `sandbox/` from that frozen run. With Idli’s local 9B on 8291 and embedder on 8293, run from the repository root:

```sh
suite=benchmarks/runs/2026-11-23-whatsapp-windows
OPENBLAS_NUM_THREADS=1 core/.venv/bin/python "$suite/trial.py" "$trial"
```

Here `trial` is the private directory. The harness validates the snapshot checksum, caches local vectors and skips completed case files. The [screenshot helper](screenshot.py) needs system Python with Playwright, a linked profile, Chromium, and the pinned WA-JS archive. Pass the source snapshot, private manifest, and a private output folder. It launches a disposable copy, loads the client, switches offline before navigating to any group, verifies the group header and message ID, and captures only the matching row. We visually inspected all four PNGs. No chat images went to a model.
