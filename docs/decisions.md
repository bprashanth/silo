# Decisions

Why the core looks the way it does. Each line was decided by the owner or settled by a measurement in io.

## The approach (from io's CLI_CHOICES.md, 2026-11-19)

- Everything is a command with one shape, `idli VERB RESOURCE [REF] [flags]`, like kubectl and gh, because models
  already know those patterns. Commands with descriptions and examples beat a flat menu: the 9B went from 78% to
  97% on partial questions (io: `benchmarks/runs/2026-11-19-capability-cli-mapping/`).
- Examples with real dates teach the 9B most. Dates are worked out in code, never by a model.
- Reading verbs only read. Writing verbs (`draft`, later `send`, `book`) only preview without `--apply`, and the
  mapper never gets them.
- The mapper fills in values; it doesn't plan workflows. Words with private meanings (leads, follow-up) are fixed
  once, as views and definitions, by the person.

## Commands (decided 2026-11-21)

The command set is in [cli.claude.md](cli.claude.md); what was decided, and why:

- **One way to do each thing.** `count` folded into `list --count`; `read` and `describe` into `get --text` and
  `get --outline`; `--by` is `--group-by` (SQL's word). Old forms still parse but the mapper never sees them. Two
  ways to say one thing split the 9B and idli-remote on the same question (`--search` vs `--where ~`). **[decided]**
- **Names.** `sync` names the place (`gmail`, `gcalendar`, `drive`); other verbs name the record (`mail`,
  `calendar`, `files`). The manual verb is `help`, not `explain`: people say "explain X" about topics. **[decided]**
- **The same flags everywhere, and repeating one means "and".** `judge` takes `--search`, `--in`, `--since`,
  `--until`, `--on` like `list`. A repeated `--where`, `--search` or `--label` means all of them (argparse's default,
  last one wins, silently dropped conditions three times). **[decided]**
- **Search.** Quotes are an exact phrase, as in Google and Gmail (models know it). Unquoted words are ranked by
  words and by meaning. **[decided]**
- **Code over prose.** A fix goes in code when code can catch it (counts, quoting, `'me'`, judge narrowing); a
  sentence in the 9B's instructions is the last resort, and the instructions have a size budget enforced by a test
  (`core/tests/test_scaffold_prose.py`). Prose rules the 9B ignored until they became code: "use the person's own
  words", "never call a draft saved". **[decided]**
- **New meanings go through the person.** A `define` or `view` from the mapper stops at a yes card; an existing name
  is reused, never redefined. **[decided]**

## How we work

- General fixes only. A failure is fixed so the whole class of questions works, never one question.
- Code over prose. If code can check it, code checks it. A sentence in the 9B's instructions is the last resort,
  and the instructions have a size budget.
- Measure on the dev bank while fixing; claim only on a held-out set run once on frozen code, graded blind.
- New features must not regress: if a change can't be shown to be safe, it ships off by default (the smaller menu).
