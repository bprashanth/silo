# Handoff

Last updated 2026-11-21. Keep this current: whoever ends a session rewrites the "State" and "Next" sections.

Current experiment: [WhatsApp retrieval handoff](whatsapp-retrieval.md).

## What this repo is

The Idli core: a command-line tool (`core/idli`) over a DuckDB store per sandbox, that answers questions about a
person's own email, calendar and Drive. It was built and measured in the io repo and copied here on 2026-11-21.
Ignore `archive/` and `examples/`: they are the old Telegram version of Silo.

## Read first

1. [goals.md](../docs/goals.md): the core as built and tested, and what isn't built.
2. [cli.md](../docs/cli.md) and `core/idli help` for the commands.
3. [decisions.md](../docs/decisions.md) for design choices.
4. [The docs index](../docs/README.md) for the store, mapper, models and privacy.
5. [../todos/README.md](../todos/README.md): what's next; `../todos/core.md`: every bug, its evidence and its fix.
6. [from-io.md](../docs/from-io.md): where the evidence and the history are in io.

## How we work

- The owner tests by hand: `cd core; IDLI_SANDBOX=~/idli-sbx/NAME ./idli ask "..."`. When something fails, find the
  cause in `<sandbox>/log.jsonl` (every command and every turn, with the prompt sent, the plan, the menu, the chips),
  check the right answer with read-only SQL (`./idli query "SELECT ..."`), and fix it so the whole class of
  questions works, never one question.
- Prefer code over prose (a sentence in the 9B's instructions). The prose has a size budget:
  `.venv/bin/python -m unittest tests.test_scaffold_prose` from `core/`.
- Add the owner's questions, with answers checked by SQL, to `benchmarks/bank/tasks_owner_dev.json`. Measure on the
  dev banks; claim only on a new held-out set run once on frozen code, graded blind (`benchmarks/README.md`).
- A change that can't be shown safe ships off by default.
- Plain words in anything a person reads. Say "idli-remote", never the provider's name. Never print tokens, OAuth
  files or keys.
- Long runs and grading go to Cursor `agent` or `codex exec`. Nothing under `~/.codex` is edited.
- Commit as you go; then `bash -ic 'declaude origin/main'` (it rewrites hashes; quote hashes only after it). Don't
  push: the owner reviews and pushes.

## State (2026-11-21)

- Branch `idli-core` (from `merging`). The core runs from `core/` with its own `.venv` (`core/requirements.txt`).
- The [setup guide](../README.md#try-it) covers Google consent, account selection, DGX access and hosted judging.
- Test account 87profligate. Sandboxes: `~/idli-sbx/t2` (the owner's), `~/idli-sbx/silo-smoke` (synced from this
  repo on 2026-11-21).
- Smoke test from this repo: see `chronology/2026-11-21T2300-core-from-io.md`.

## Next

See [../todos/README.md](../todos/README.md): a new held-out set, Mini v0, subtables, the menu budget, local Clef,
a Signal front end.
