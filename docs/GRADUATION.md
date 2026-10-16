# Graduating a benchmark into a stack

A benchmark (`benchmarks/<name>/`) is where an idea gets measured: its own scripts, its own port, its own
results in `runs/`, and a README of what was found. Once it has been fully tested and the user says
"move this to the <X> stack", it graduates. It stops being an experiment and becomes an **entry point**
that a person can open from an index page, and that one bootstrap script starts.

The pattern is copied from good-shepherd's `examples/stacks/` (`run_stacks.py` plus one directory per
stack, each with an `index.html` hub of cards).

## Layout

```text
examples/stacks/
  run_stacks.py                  # optional top level: --stack livestock,... calls each stack's run.py
  livelihoods/
    livestock/
      README.md                  # what this stack is, its entry points, ports, what each needs
      run.py                     # the one bootstrap: frees ports, starts every server, prints URLs
      web/index.html             # hub page: one card per entry point (static, served by run.py)
      agent_call/                # entry point: the agent takes the farmer's call (from benchmarks/voice-robust)
      operator_assist/           # entry point: a human takes the call, the agent listens and helps
      case_desk/                 # entry point: Telegram case workflow / Idli Ops (Codex's livestock/)
      shared/                    # code more than one entry point imports (ASR, TTS, intake policy, gazetteer)
```

Group by domain (`livelihoods/`), then by program (`livestock/`). Each entry point is one directory and
one card. Where the stack lives inside the domain is decided once, in `run.py`.

## What moves and what stays

| moves to the stack | stays in `benchmarks/<name>/` |
|---|---|
| server, page, policy, the code it imports | benchmark harnesses (`asr_bench.py`, `sim.py`, corpus builders) |
| unit tests of the policy (`tests/`) | `runs/` results and the README of findings, as the record |
| the config it needs (gazetteer, prompts, voice cache) | anything only a benchmark imports |
| a short "how it was measured" link back to the benchmark | |

Results are never moved or rewritten. The benchmark README gets one line at the top:
`Graduated to examples/stacks/livelihoods/livestock/<entry>/ on <date>; this directory is the measurement record.`
If a harness still needs the code, it imports it from the stack (one `sys.path` line) instead of
keeping a copy. Two copies would drift.

Large files (models, audio, call recordings) never enter the repo. They stay on the Seagate
(`/mnt/seagate/silo/...`) or in `~/.local/share/...`, and `run.py` checks they exist.

## `run.py` contract

Same shape as good-shepherd's `run_stacks.py`:

- **Process table.** A list of `(name, port, argv, cwd, env)`, one row per server: the agent-call
  server, the operator-assist server, the hub page (`python -m http.server --directory web`), and
  anything an entry point needs that Silo owns (for example a model server). The ports are the ones the
  benchmark already used, so links keep working.
- **Validate first.** Check required files (pages, venvs, model files on the Seagate, the secrets file
  *exists*, never its contents) and stop with one clear message listing what is missing.
- **Free only its own ports** before starting, and only ports in its own table. It never stops
  processes it didn't start: not the Telegram bot, not Codex's servers, not another stack, not
  containers that aren't Silo's. If a port is held by something else, print who holds it and stop.
- **Spawn the children, print the URLs** (localhost and the tailnet address), and stop all of them on
  Ctrl+C.
- **Flags:** `--only agent_call,operator_assist`, `--check` (validate and print, start nothing),
  `--bind 127.0.0.1` (the default is 0.0.0.0 to match the benchmarks).
- **Shared models are external.** Shared services the stack only uses, like Muse on :8181 or OpenRouter,
  are checked (a health check, or the key file exists) and reported, never started or restarted.

## Hub page

`web/index.html` is a static page of cards, in the style of good-shepherd's `research/web`. Each card
gives the entry point's name, one line on what it shows, its status (benchmarked / piloted /
production), its URL, and a link to the benchmark that measured it. Keep it static: no build step, and
links point to the ports in `run.py`.

## Steps, when the user says "move <benchmark> to the <program> stack"

1. Create `examples/stacks/<domain>/<program>/` if it doesn't exist yet, with `README.md`, `run.py` and
   `web/index.html`.
2. `git mv` the serving code into `<entry>/` (keeps history), and pull imports shared by entry points
   into `shared/`. Update imports and paths.
3. Move the tests that test the moved code. Run them, and run the benchmark harness once against the
   moved code to show the numbers didn't change (for voice: `tests/test_intake.py`, one `sim.py` run,
   one `tests/browser_call.py` call).
4. Add the entry point's row(s) to `run.py`'s table and a card to the hub page.
5. Leave the graduation line in the benchmark README.
6. Write a chronology entry (`chronology/YYYY-MM-DDTHHMM-<slug>.md`, IST) saying what moved, where, and
   which commands verified it.
7. Commit on a branch. Don't push; the user runs `declaude` and pushes.

If another agent owns code going into the same stack (Codex's `livestock/` for example), move only
your own entry point and leave a card that points at theirs. Their code moves when they or the user
decide to move it.

## Livestock, concretely

| entry point | today | moves from | port |
|---|---|---|---|
| Agent takes the call | benchmarked | `benchmarks/voice-robust/` (`server.py`, `call.py`, `intake.py`, `nlu.py`, `speech.py`, `static/`) | 8775 |
| Operator assist | benchmarked | `benchmarks/voice-robust/assist/` | 8776 |
| Case desk (Telegram + Idli Ops) | Codex's | `livestock/` on `poc/livestock-voice` | Codex's |

The agent-call and operator-assist entry points both use the same ASR (Parakeet v3 with boosting), the
same gazetteer and the same intake record, so these go in `shared/`. Then one call record format
reaches the case desk, whether the agent or a person took the call.
