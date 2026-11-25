# The mapper and its menu, as built (companion to mapper.md)

Implementation notes, 2026-11-21. Describes `core/lib/idlicli.py` (`menu`, `grammar`, `map_question`, `run_plan`).

## What the mapper is

Whatever turns a person's words into `idli` commands: the 9B (`--mapper nine_compressed`, the default; `nine` for
the uncompressed one) or idli-remote (`--mapper remote`, sees only masked text). It never sees records.

## What it is sent each turn

1. **The instructions** (`GRAMMAR_HEAD` plus `grammar()`): the command forms, the rules and a few worked examples
   with real dates. They have a size budget, enforced by `core/tests/test_scaffold_prose.py`.
2. **The menu** (`menu()`), built from the store:
   - each resource with a one-line description (written in code, `recstore.RESOURCES`);
   - its fields (read from DuckDB) and, where the name isn't enough, their meaning (`recstore.FIELD_NOTES`:
     `is_bulk` = newsletters and notifications, `my_response` = my RSVP, `owner` = an email, `'me'` = mine);
   - short sets of values that repeat (`direction` is in or out);
   - every sheet and tab with its columns;
   - Drive folders;
   - definitions with their answers, and views with their columns ("reuse these");
   - today's date and whose account it is.
3. **The last two turns**: the questions, the commands and what was shown.

For idli-remote the whole message is masked first.

## The menu's size

The full menu is ~13,700 characters on the test account. A smaller one (columns only for the sheets a question is
about, found by words or by meaning) is built but **opt-in** (`IDLI_MENU_TRIM=1`): on the dev bank it gave fewer
errors but fewer correct answers, mostly noise, so it isn't proven safe. Plan: full menu while it fits a budget,
the smaller one above it, once measured with repeated runs. Every turn logs what the menu held and any **menu
miss** (a command or error that used a sheet whose columns weren't sent).

## What code checks after the mapper answers

- `--search` words must be the person's own; a judge may only narrow to a search already shown.
- Double-quoted values are values; a bare word compared with a field is a value; `'me'` is the account.
- A placeholder (`REF`, `<id>`) waits for results (a continue round).
- A new definition or view stops at a yes card; an existing name is reused, never redefined.
- One repair round if a command fails; up to two continue rounds.

## Separate from the mapper

A Clef call labels the kind of ask for the chips (lookup, judgement, workflow, elsewhere). It doesn't change the
plan.
