# Silo

Silo is where the Idli core lives: a private assistant for NGO teams that answers questions about their own
email, calendar and Drive, on their own machine. The data stays in a local database; a small private model picks
commands and writes short replies; anything that defines a new meaning ("leads", "urgent") is shown to the person
first.

**Start here:** [docs/README.md](docs/README.md) (what to read, in order), then [docs/goals.md](docs/goals.md).
If you are an agent picking up work, read [docs/handoff.md](docs/handoff.md) first.

## Layout

```text
core/          the core: a command-line tool over a DuckDB store per sandbox (core/idli, core/lib/)
docs/          what the core is and why (goals, commands, decisions, the store, the mapper, models, privacy)
benchmarks/    how we check it: task banks, the grading rubric, the bench script
todos/         what's next, and the full running list of bugs and fixes
chronology/    append-only log, one file per step
archive/v1/    the earlier Telegram bot version of Silo (tg-bridge, wa-bridge, its benchmarks and notes). Old.
examples/      frozen livestock call-center examples from v1. Old; a service still runs from here, so it stays put.
```

## Try it

On the DGX, with the test account signed in (`~/.config/idlisseus/`):

```bash
cd core
uv venv -p 3.12 .venv && uv pip install -p .venv/bin/python -r requirements.txt   # once
export IDLI_SANDBOX=~/idli-sbx/mine
./idli sync gmail -v && ./idli sync gcalendar -v && ./idli sync drive -v
./idli ask "which docs talk about border effects?"
./idli help
```

The models it calls run on the DGX (see [docs/models.claude.md](docs/models.claude.md)).

## History

Silo started as a Telegram bot on a 30B model with answer checking (October 2026), now in `archive/v1/`. The core
was built and measured in the io repo in November 2026 and moved here; see [docs/from-io.md](docs/from-io.md).
