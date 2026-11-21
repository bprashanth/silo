# Prompt for the next agent

Paste this to start a new agent here. The agent that ends a session rewrites it.

---

You're picking up the Idli core in `~/src/github.com/bprashanth/silo` (branch `idli-core`, on the DGX). Only
`core/`, `docs/`, `benchmarks/`, `todos/` and recent `chronology/` matter; `archive/` and `examples/` are an older
version of this repo, so leave them alone.

Read `docs/handoff.md` first, then `docs/goals.md`, `docs/cli.claude.md`, `docs/decisions.md`, and `todos/README.md`.
The owner's own notes are the plain `docs/*.md`; the `docs/*.claude.md` files next to them are drafts that say what
the code does today. Keep them accurate when you change the code.

The work: the owner tries the core by hand (`cd core; IDLI_SANDBOX=~/idli-sbx/t2 ./idli ask "..."`) and reports
what's off. Find the cause in `<sandbox>/log.jsonl`, check the right answer with `./idli query`, and fix it for the
whole class of questions, in code where you can. Add their questions with checked answers to
`benchmarks/bank/tasks_owner_dev.json`. Don't claim an improvement without a held-out run.

Before you stop: update `docs/handoff.md` (State, Next), `todos/`, add a `chronology/` entry, commit, run
`bash -ic 'declaude origin/main'`, and rewrite this prompt. Don't push.
