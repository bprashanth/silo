# Goals: the core as built and tested (2026-11-21)

This is GOALS_V0.6 from io (`narrative/GOALS_V0.6.md`), moved here with the core. It is what two days of the
owner's own testing, an agent trial and three benchmarks left standing. Paths under `benchmarks/runs/` are in io. Each claim is marked **[built]**, **[tested]** (by the owner or a benchmark, with a link) or **[idea]**.

Other documents here: [cli.md](cli.md) and [cli.claude.md](cli.claude.md) (every term and command, with an
example), [decisions.md](decisions.md) (why the commands look the way they do), [examples.md](examples.md) (worked
tables and queries), and the owner's notes [db.md](db.md), [mapper.md](mapper.md), [minis.md](minis.md),
[models.md](models.md), [privacy.md](privacy.md), each with a `.claude.md` companion.

---

## 0. In one paragraph

Idli lets people at NGOs use AI on their own accounts and files without handing that data to an AI company. A
**sandbox** is a folder on their computer with a small database (the **store**) of their emails, calendar, Drive files
and sheets, copied read-only. Every question becomes a few **commands** (`idli list`, `idli judge`, ...) that run on
the real data. A **small private model** (the 9B) picks the commands and words a short reply; a **judge** reads
records when a question needs judging ("which emails need a reply"); **search** finds words and meanings in every
page. A larger outside model (**idli-remote**) can pick commands instead, from a masked question. Anything that
defines a new meaning ("leads", "urgent") is shown to the person first, on a **yes card**.

## 1. Words

| Word | Meaning |
|---|---|
| sandbox | a folder for one area of work: the store, the log, the session |
| store | one DuckDB file, `store.duckdb` |
| resource | a kind of record you can list: mail, threads, calendar, files, folders, photos, sheets, rows, labels, definitions, or a view |
| page | one page of a document's text (PDFs keep their pages; other files are cut into ~3,000-character parts) |
| card | 2-3 sentences and up to 15 key terms per document, kept word for word, made once per version |
| chunk, embedding | ~1,200-character pieces of each page, each stored with a vector of its meaning |
| definition | a named question with fixed answers that needs reading each record ("Is this about climate?") |
| judge | the model that answers a definition per record; its answers are **labels** |
| view | a saved, named rule over the data (a real database view), e.g. `leads` = Name and Email from the Leads sheet |
| mapper | turns words into commands: the 9B (default) or idli-remote (masked) |
| menu | what the mapper is told exists: resources, fields and their meanings, definitions, views, sheet and folder names |
| yes card | shown before a new definition or view: the exact wording and the cost; y, n, or your own wording |
| chip | a coloured tag on a reply: the kind of ask (lookup, judgement, workflow, elsewhere) and whether it struggled |

## 2. The scaffold

Code: `core/lib/{recstore,idlicli}.py`, entry `core/idli`. Try it: `IDLI_SANDBOX=~/idli-sbx/NAME core/idli help`. **[built]**

**Sync** (`idli sync gmail | gcalendar | drive | all`, read only, Ctrl+C keeps what was done) **[built, tested]**:
1. Gmail: the last 60 days; Calendar: 60 days back and ahead.
2. Drive: the file list; every tab of every spreadsheet as its own table (unchanged sheets skipped); the text of
   every document, page by page; a card per document; embeddings of chunks and cards. Changed files are redone and
   their labels dropped; deleted files are removed. Every stage shows progress (`-v`, `-vv` for item by item).
   On the test account: 140 documents, ~3,600 pages, ~11,000 chunks; reading 70 s, cards ~12 min, embeddings ~5 min
   the first time.

**Commands** (one shape, `idli VERB RESOURCE [REF] [flags]`; the same flags everywhere) **[built]**:
`list` (with `--where`, `--search`, `--since/--until/--on`, `--in`, `--label`, `--count`, `--group-by`, `--fields`),
`get` (one record; `--text`, `--outline`), `summarise` (one file, or `--search` across documents), `define`,
`judge`, `query` (read-only SQL), `view`, `draft` (preview only), `help` (the manual page), `ask`. Old forms
(`count`, `read`, `describe`, `explain`, `events`) still work but aren't shown to the mapper.

**Search** (`--search`) **[built, tested]**:
- `"in quotes"`: the exact phrase (spaces, hyphens, line breaks; plural optional). Literal only.
- Without quotes: every word that matters (not "of", "the") must appear, ranked by phrase mentions, then by how much
  each word is used (rarer words weigh more), merged with a ranking by meaning (embeddings; reciprocal rank fusion).
  A file found only by meaning says "similar meaning". Meaning helps for topics ("women entrepreneurs" finds
  `female_entrepreneurship.pdf`); for single rare words and names it is noise and is left out.
- On files it covers names, folders, every page (all tabs of sheets) and the cards, with a "how it matched" column.

**`ask`**, one turn **[built, tested]**:
1. The menu: everything the store holds. A smaller menu (sheet columns only for the sheets a question seems to be
   about) is built but opt-in (`IDLI_MENU_TRIM=1`): on the dev bank it wasn't proven harmless
   (io: `benchmarks/runs/2026-11-21-menu-regression/`). Every turn logs the menu and any **menu miss**.
2. The mapper returns commands. Code then checks them: `--search` words must be the person's own; a judge may only
   narrow to a search already shown; double-quoted values are values; `'me'` is the account's address; placeholders
   (`REF`) wait for results.
3. A new definition or view stops at the **yes card**; an existing name is reused, never redefined.
4. Idli runs the commands (one repair round, up to two continue rounds).
5. The 9B words 1-3 sentences from what is shown. The wording is dropped if a number or count doesn't match, if it
   says nothing was found while rows are shown, if it calls a draft saved; `summarise` output isn't reworded.
6. **Chips**: Clef labels the kind of ask; code adds **struggled** (a step failed or was redone, no steps, a
   hand-written join, the same question again) with an offer: idli-remote, or a Mini for a workflow.

**Judging** **[built, tested]**: Clef-flash by default (`--judge nine_compressed | nine` for the 9Bs). It reads
every file kind's contents (sheets as rows, text and code), plus the card; skips folders, media and empty files;
saves each label as it lands; ends with examples per answer.

## 3. What crosses the line

| | idli-remote | Sandbox Claude | hosted Clef (judge, chips) |
|---|---|---|---|
| The question | masked | masked | as asked |
| Records and file text | never | never | **yes** |

Hosted Clef is for the test accounts only. It stands in for a local Clef (a 9B-sized model with a scoring head),
which is the plan for real data. **[idea: local Clef]**

## 4. Evidence

- **Judge models** (io: `benchmarks/runs/2026-11-20-judge-models/`): what the judge sees matters most (9B 20 -> 33 of 38
  with contents); Clef and idli-remote 38 of 38; BF16 9B 35, Q5 33, Muse 33.
- **Held-out rerun** (`2026-11-21-heldout-rerun/`, frozen tasks, blind graders): 9B 5 -> 10 correct of 27;
  idli-remote 13 -> 13 (the bigger command set didn't confuse it).
- **Agent trial** (io: `benchmarks/runs/2026-11-21-agent-trial/`): 22 owner-style questions plus 12 frozen ones; 20+ general fixes.
- **Owner dev bank** (`benchmarks/bank/tasks_owner_dev.json` here): the owner's own questions with
  SQL-checked answers.
- **Kind chips** (io: `benchmarks/runs/2026-11-21-kind-classifier/`): 70 of 91 labelled questions get a chip, 70% agree; workflow
  chips 10 of 13 right; most disagreements are labels written before search-first.
- **Menu trimming** (io: `benchmarks/runs/2026-11-21-menu-regression/`): fewer errors but 17 vs 26 correct on the dev bank, mostly
  grader and 9B noise; kept opt-in until measured properly.

## 5. What a judgement, a view and a workflow are (as tested)

- **Lookup:** the data already says it (dates, senders, words). The mapper fills in values. Works with both mappers.
- **Judgement:** each record must be read against a meaning the person has in mind ("asks me for money"). Define,
  judge, list by label; the person confirms the wording once on the card.
- **View:** a meaning that is an exact rule over data already in the store ("leads" = the Leads sheet's emails).
  No model reads anything. Views are real database views, usable inside other commands.
- **Workflow:** several steps plus private meanings ("for each lead, who needs a follow-up"). The 9B can't plan
  these reliably; idli-remote does better; the lasting answer is a Mini (views, definitions, a chain), not built.

## 6. Not built yet

- Minis and chains in the scaffold (views and definitions exist; chaining and fork don't).
- Subtables (more than one table on a tab): p1, `todos/subtables.md`.
- Local Clef; running on a schedule; connectors beyond Google; the app's left pane on top of `ask`.

## 7. Next

1. A new held-out set, written blind, to measure everything since 2026-11-21.
2. Mini v0 in the scaffold: a folder of views, definitions and a chain, with `idli mini run|step|explain`.
3. Subtables. Local Clef.
4. Only then the app's left pane on `idli ask`, tested once on the laptop.
