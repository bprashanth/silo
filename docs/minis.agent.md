# Minis: what exists and what is missing (companion to minis.md)

Implementation notes, 2026-11-21. minis.md describes what a Mini is. In the core today a Mini **is not built**; the
pieces it will be made of are.

## Built, and usable by a Mini

- **Views:** saved rules, real database views, made only after a yes card (`idli view NAME --sql ...`).
- **Definitions and labels:** `define` (after a yes card), `judge` (Clef by default), `list --label`.
- **Commands with the same flags everywhere**, so a chain step is one command line.
- **The log** of every command, to replay or turn into steps.

## Missing

- A Mini file: its views, definitions and chain, with a description.
- Running it: whole, one step, or asking about it ("what would step 4 draft for Asha?").
- Script steps that write their own table (minis.md: "output a sql table into the duck db store").
- Fork: copy a Mini, change one step, save as new; the original never changes.
- Which views belong to a Mini and which to the sandbox, and what happens to other Minis when one changes a view
  (io todo `capability_versions.md`).

## Proposed v0 (to discuss)

```
<sandbox>/minis/leads-followup/
  mini.yaml        name, about, the views and definitions it needs, the steps in order
  scripts/         any script steps (they write a table named after the Mini and step)
```

Commands: `idli mini list`, `idli mini run NAME [--step N]`, `idli mini help NAME` (what it reads, its steps).
Build it against the leads example (views `leads`, `replies`; definition `intent`; chain: list replies, judge
intent, draft) and test it with the owner dev bank's workflow questions.

## Current handoff from ask

The mapper can chain a bounded set of existing commands and continue after seeing their results. In shell output a request classified as a workflow can end with a suggestion to make it a Mini. Classification and that footer are skipped for Signal’s humanized replies. Suggesting a Mini does not create or schedule one. The [daily digest](../proposals/workflows/daily-digest.md) is a candidate to benchmark once the runner exists.
