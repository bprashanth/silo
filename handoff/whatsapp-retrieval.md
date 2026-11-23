# WhatsApp retrieval handoff

Completed 23 November 2026 on the owner’s DGX. The source was a read-only capture of 2,783 cached messages and captions from 26 active WhatsApp groups. The fixture’s Google sources were empty. The experimental views and ranking code live in the benchmark. The production CLI and bridges were unchanged.

## What ran and what was scored

| Experiment | Procedure | Outcome |
|---|---|---|
| [Mapper and Clef diagnostic](../benchmarks/runs/2026-11-22-whatsapp-lookup/README.md) | Seven questions each through stock 9B, short-menu 9B and constrained redacted remote mapping. Hosted Clef classified the kind of request. A separate test gave Clef four reviewed timing messages. | No mapper arm produced a complete answer. Clef called all 21 requests lookups and correctly classified the four selected messages as proposals or otherwise. |
| [Windows and local judging](../benchmarks/runs/2026-11-23-whatsapp-windows/README.md) | Thirteen questions included eight positive cases. Diagnostic arms supplied group/date constraints where applicable. An exploratory arm combined lexical search, message and burst embeddings, and local 9B evidence selection. | **5/8** positive cases retained all reference evidence in the hybrid retrieval experiment. This score ends at evidence selection. |
| [Paired CLI trial](../benchmarks/runs/2026-11-23-whatsapp-ask/README.md) | 144 actual CLI subprocesses. Four configurations each ran eight prior positives, twelve new single-record lookups and four controls. The twelve new lookups were repeated in reverse order. Each fresh ask received the original question. | The automatic hybrid candidate view contained all reference evidence for **6/8** prior and **12/12** new positives. The table below counts only source evidence displayed after mapper-selected commands executed. Summary wording was ungraded. |

| CLI menu | Prior /8 | New /12 | New repeat /12 |
|---|---:|---:|---:|
| Stock | 0 | 0 | 0 |
| Hybrid candidate view | 1 | 2 | 2 |
| Also show source counts and resolved group | 0 | 8 | 7 |
| Also show eight short source previews and refs | 2 | 11 | 11 |

The latest run used local 9B mapping and wording with hosted chips off. The named traces below contain no judge commands. Group binding used unique token overlap. Sender aliases were unresolved. Search indexed individual messages and bursts of up to five messages, then added quoted parents of original hits and two nearby messages on either side. The CLI returned individual source rows. The bank was source-derived and the menu variants were explored on it.

## Where to inspect a turn

On the DGX, open `~/.local/share/silo-owner-pilot/ask-LMunvw/preview-NN.json`. Compare `packet` with `event.mapper_calls[].sent` (what the mapper saw), `event.commands` (what it ran), and `event.steps_shown` (what the CLI displayed). `bank.json` holds the private questions and required references. `repeat/` holds the reverse-order trial. The [runner](../benchmarks/runs/2026-11-23-whatsapp-ask/run.py) builds the candidates and the [scorer](../benchmarks/runs/2026-11-23-whatsapp-ask/score.py) checks evidence.

| Trace | Observation |
|---|---|
| 00 · Session duration | Both decisive messages were in the packet. A limit of five displayed the first duration and a question about the second, omitting the later acceptance. |
| 01 · Review document | The command returned the post linking the requested document. The configured Google test account received HTTP 404 on a separate read. Credit was for locating the link. |
| 02 · Futures roster | The correct roster was the first preview. The mapper used the heading inside the message as an exact group-name filter and returned zero rows. |
| 03 · DICE document | The packet contained the link but lacked the decline and its quoted invitation. The mapper also used an exact sender filter with a nickname. In the earlier assisted run, following the neighboring decline’s parent recovered the invitation. |
| 05 · Nadhi | The group binding and literal search returned the participant note. This and trace 01 were the two prior cases credited. |
| 20–23 · Controls | Preview failed the exact count, ambiguous sender, unknown group and missing-history checks. |

The earlier frozen capture, vectors, per-arm traces and four verified message screenshots are under `~/.local/share/silo-owner-pilot/windows-xTcFis/`, with images in `shots/`. Private artifacts stay outside Git. Replay commands are in each linked report. For the reasoning behind the comparisons, see the [window checkpoint](../chronology/2026-11-23T0013-whatsapp-window-results.md) and [paired ask checkpoint](../chronology/2026-11-23T0123-whatsapp-ask-results.md).
