# Benchmarks

How we check the core. Results that hold real test-account rows stay on the machine that ran them, not in git.

## Banks (`bank/`)

| File | What | Use |
|---|---|---|
| [tasks_dev.json](bank/tasks_dev.json) | 53 tasks written blind on 2026-11-19 (trust, own definition, own workflow, other site) | while fixing |
| [tasks_owner_dev.json](bank/tasks_owner_dev.json) | the owner's own questions with answers checked by SQL on the test account | while fixing; add to it |
| [tasks_heldout.json](bank/tasks_heldout.json) | 27 tasks, frozen (sha256 c81e4cd249e09e62fe3150254f59a3fd5c0e6ddaae715e78776092a394cd4587) | **used up**: run twice already; write a new held-out set before the next claim |
| [tasks_signal_dev.json](bank/tasks_signal_dev.json) | Short Signal DMs for email, calendar, Drive and sharing | [Alpha setup and live checks](../deployment/alpha/signal.md) |

Kinds in the original banks predate search-first: many "own definition" tasks are now answered by search.

These JSON banks ship with Silo. The original question banks also live
in the local io checkout. The upstream paths are included for completeness.
Private run outputs and sandbox copies stay on the DGX. Ask a maintainer for
the matching clean test-account snapshot to reproduce a historical run.

- [Original record-store bank](https://github.com/bprashanth/io/tree/main/benchmarks/runs/2026-11-19-record-store/bank)
- [Capability CLI questions for mail and Drive](https://github.com/bprashanth/io/tree/main/benchmarks/runs/2026-11-19-capability-cli-mapping)
- [Agent trial questions, round 3 and retries](https://github.com/bprashanth/io/tree/main/benchmarks/runs/2026-11-21-agent-trial)
- [Blind tester prompts](https://github.com/bprashanth/io/tree/main/benchmarks/runs/2026-11-19-blind-tester/prompts)

## Running

From the Silo repository root, choose a fresh output path per run (the runner appends).

```
core/.venv/bin/python benchmarks/bench.py run --tasks "$PWD/benchmarks/bank/tasks_owner_dev.json" \
    --mapper nine_compressed --sandbox ~/idli-sbx/COPY --out /tmp/run.jsonl
```

Run on a copy of a synced sandbox with no definitions, labels or views. The bench says yes to a yes card on the
tester's behalf and logs it.

## Grading

Blind: a separate agent per run whose only tool is read-only SQL on that run's store, following
[the grading rubric](grader/RUBRIC.md). The script that sets this up (`grade.sh`, a Cursor `agent` in a network wall) is still in io
(`benchmarks/runs/2026-11-19-record-store/grader/` and `2026-11-19-blind-tester/wall.sh`). One grader per run is
noisy (1 to 3 tasks, sometimes more); compare with repeats or two graders.

## Rules

- General fixes only, measured on dev. A claim needs a held-out set written blind, run once on frozen code.
- A change that can't be shown safe ships off by default.
