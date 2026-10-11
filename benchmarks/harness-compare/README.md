# Harness compare: the bridge's harness vs io's Codex

**Question:** on messy, realistic NGO spreadsheets, which harness gives local
Muse Glimmer the more correct, more auditable answers, and at what cost in time?

## Harnesses

Both run on the same local model server (Muse Glimmer 30B Q4_K_XL with the DFlash
drafter, llama.cpp, 4 slots of 64k). Every job is one question in a fresh workspace.

| | simple | codex |
|---|---|---|
| code | `tg-bridge/harness.py` | io's pinned Codex 0.154.0 (`../io/app/io/codex-bin`) |
| prompt | built by `tg_bridge.file_content`, exactly as for a Telegram upload: an 8-row preview of each xlsx, full text of a csv | the question, plus the names of the files in the folder; io's `AGENTS.md` |
| actions | one `python` tool | any shell command |
| sandbox | Docker: `--network none`, files read-only at `/data`, 2 GB, 60 s | io's profile (`io_config.js` calls io's own `writeConfig`): bwrap, network off, writes only to the folder and temp, reads only the platform, io's python and Codex itself; `approval_policy = never` |

The one deliberate difference from io: there's no masking proxy. Model traffic goes
straight to the local server, because nothing leaves the machine.

## Cases

`cases/SPEC.md` is the brief. `cases/<id>/case.json` holds each case's questions and
answers, `gen.py` builds the files, and `verify.py` re-derives every answer from the
messy files. `clean` is the tidy baseline workbook from `../ngo-workbook-correctness`.

## Measures (per job, in `jobs.jsonl`)

- **verdict:** correct, wrong (a confident wrong answer) or missing (no answer).
- **seconds** and **actions** (tool calls or shell commands).
- **receipt** (`receipt.py`): is every number in the reply, and above all the `ANSWER`
  value, present in some tool output, at the precision it was written? "Clean" means
  fully traced. It's scored by how many wrong answers it catches and how many correct
  answers it flags.
- **audit:** network attempts, paths outside the workspace, sandbox refusals, and
  any action that isn't python or shell.

## Run

```sh
cd benchmarks/harness-compare
../../tg-bridge/.venv/bin/python run.py runs/<date>-<slug> --trials 2 --par 4
```

Jobs are appended to `jobs.jsonl`, so re-running resumes where it stopped. Full
transcripts go to `transcripts/`, and `summary.md` is regenerated at the end.

## Results

| run | codex | simple | notes |
|---|---|---|---|
| [2026-10-11-muse-q4d](runs/2026-10-11-muse-q4d/summary.md) | 131/134 correct, median 88 s | 125/134 correct (4 missing from HTTP 500s), median 256 s | No audit flags in either. Disagreement between harnesses flagged 11 of 12 wrong or missing answers. |
| [2026-10-11-muse-q4d-retry500](runs/2026-10-11-muse-q4d-retry500/README.md) | — | 3/4 correct | The 4 HTTP-500 jobs, re-run after adding `harness.retrying()` |
