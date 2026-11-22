# CLI terms and commands (implementation notes, 2026-11-21)

For the owner to read and copy what holds into `cli.md`. It describes `core/` in this repo
(`core/lib/idlicli.py`, `core/lib/recstore.py`). Run it as `IDLI_SANDBOX=~/idli-sbx/NAME core/idli VERB ...`.

## Words

| Word | Meaning | Example |
|---|---|---|
| sandbox | a folder for one area of work; holds the store, the log and the session | `export IDLI_SANDBOX=~/idli-sbx/t1` |
| store | one DuckDB file in the sandbox, `store.duckdb` | |
| resource | a kind of record you can list | `mail`, `threads`, `calendar`, `files`, `folders`, `photos`, `sheets`, `rows`, `labels`, `definitions`, or a view |
| record | one row: one email, one event, one file | |
| field | a column of a resource, copied from the site or set by a connector rule | `my_response` (Google's RSVP), `is_bulk` (rule: unsubscribe header or noreply sender) |
| page | one page of a document's text (PDFs keep their pages; others are cut into parts of about 3,000 characters) | `file_pages` |
| card | 2-3 sentences and up to 15 key terms per document, made once per version by the 9B during `sync drive` | `get file wincoop` shows it |
| chunk, embedding | ~1,200-character pieces of each page, each with a vector of its meaning (Qwen3-Embedding-0.6B, local) | used by `--search` and `summarise --search` |
| chip | a coloured tag on a reply: the kind of ask (lookup, judgement, workflow, elsewhere, from Clef) and `struggled` (from what happened) | `[workflow] [struggled: you asked this again]` |
| menu | what the mapper is told exists; sheet columns only for the sheets the question is about | logged per turn, with any menu miss |
| definition | a named question with fixed answers that needs reading to answer | `urgent`: "Does this email ask me to act soon?" yes/no |
| judge | the model that answers a definition, row by row; the answers are labels | Clef by default |
| label | one record's answer to one definition version, kept | `--label urgent=yes` |
| view | a saved rule over the data (SQL) with a name; no model | `declined_with` |
| mapper | turns your words into commands: the 9B (default) or idli-remote (masked) | `--mapper nine_compressed` |
| yes card | shown before a new definition or view is made: its exact wording and cost; y, n or your own wording | |
| log | every command and every `ask` turn, with context, in `<sandbox>/log.jsonl` | |

## Commands

One shape: `idli VERB RESOURCE [REF] [flags]`. The same flags mean the same thing on every verb.

| Command | What it does | Example |
|---|---|---|
| `sync [gmail\|gcalendar\|drive\|all]` | copy the account into the store, read only. `drive` also reads every sheet tab and every document's text, makes cards and embeddings; unchanged files are skipped; `--no-cards`, `--no-embed` | `idli sync drive -v` |
| `list RESOURCE` | rows that match the flags | `idli list mail --since yesterday --where "direction = 'in'"` |
| `list ... --count` | how many | `idli list files --count --in Power` |
| `list ... --group-by F` | how many per value | `idli list files --group-by kind` |
| `list ... --search WORDS` | `"in quotes"`: the exact phrase only. Without quotes: the words that matter must appear, ranked by mentions and merged with a ranking by meaning (embeddings); a file found only by meaning says "similar meaning". On files: names, folders, every page (every sheet tab) and the cards, with a "how it matched" column | `idli list files --search '"border effects"'` |
| `list ... --label NAME[=VALUE]` | rows a definition labelled; give it twice for both | `idli list files --label trade=yes` |
| `get RESOURCE REF` | one record in full; a file shows its card | `idli get file wincoop` |
| `get file REF --text` / `--outline` | a file's text / its pages and card, or a sheet's columns | `idli get sheet "Leads (test)"` |
| `summarise file REF` | the 9B's summary of one file | `idli summarise file wincoop` |
| `summarise --search WORDS` | what your documents say about a topic, from the pages that mention it most, with sources | `idli summarise --search '"border effects"'` |
| `help [RESOURCE]` | the manual page: fields, their meanings and examples | `idli help files` |
| `define NAME --on KIND --ask Q --answers A,B` | make a definition | `idli define urgent --on mail --ask "..." --answers yes,no` |
| `judge RESOURCE --def NAME` | label rows with a definition; narrow with `--search`, `--in`, `--where`, `--since`, `--until`, `--on` (the same flags as `list`); `--judge clef\|nine_compressed\|nine` | `idli judge files --def trade --search '"trade policy"'` |
| `query "SELECT ..."` | read-only SQL, for joins | `idli query "SELECT count(*) FROM mail"` |
| `view NAME --sql "..."` | save a rule as a resource | `idli view declined_with --sql "..."` |
| `draft mail --reply-to REF --ask "..."` | a draft reply, previewed only | |
| `ask "QUESTION"` | your own words: the mapper picks commands, Idli runs them, the 9B words 1-3 sentences from what is shown | `idli ask "explain border effects to me"` |
| `-v`, `-vv`, `-vvv` | steps and times; prompts, plans and each item; every model call | `idli sync drive -vv` |

Still accepted but not shown to the mapper: `count` (= `list --count`), `read` (= `get file --text`),
`describe` (= `get --outline`), `explain` (= `help`), `events` (= `calendar`), `sync mail|events|files|sheets`, `--by` (= `--group-by`).

## Rules the mapper is given

- A named thing (a term, a person, a place): search; quote a phrase of two or more words.
- "Explain X", "what do my documents say about X": `summarise --search`.
- A category no words capture ("urgent", "about conservation"): define, judge (narrowed), then list by label.
  New definitions go through the yes card; an existing name is reused, never redefined.
- Moving, sending, booking, posting: not available. Other sites (WhatsApp, Slack...): need a connector.

## Defaults

- Mapper and wording: the served 9B (Qwen3.5-9B, Q5). `--mapper remote` for idli-remote (masked).
- Judge: Clef-flash, hosted (OpenRouter, Cloudflare only). It reads real content, so test accounts only; for
  real data it must run locally or `--judge nine_compressed`.

## Dates

`today`, `yesterday`, `tomorrow`, `7d`, `this week`, `last week`, `next week`, `this month`, `last month`,
`next month`, a weekday (`monday`, `next monday`), or `YYYY-MM-DD`. Worked out in code, never by the model:
`idli date "next month"` shows what a phrase means.

## Boundary of the core

The [owner’s CLI outline](cli.md) defines the command shape. Ask whether the proposed operation would be useful in several unrelated tasks. For example, upcoming meetings use `idli list calendar` with date and RSVP filters; filtering a second resource uses the same flags. Combining calendar results, proposal files and incoming requests into a morning message is the [daily digest workflow](../proposals/workflows/daily-digest.md).

`ask --output humanize` is the presentation used by Signal. It includes source links where available and can request an address to disambiguate a correspondent. It does not install a recurring job.
