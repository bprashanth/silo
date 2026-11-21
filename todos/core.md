# Core: the running list (bugs with evidence, decisions, proposals)

Started 2026-11-20 from the owner's first hands-on session with `desktop/idli` (sandbox `~/idli-sbx/t1`).
Scaffold code: `benchmarks/runs/2026-11-06-oss-desktop-independent/cowork/lib/{recstore,idlicli}.py`.
Design context: [GOALS_V0.5](../../../narrative/GOALS_V0.5.md). Nothing below is built yet unless marked done.

## Bugs found in the session (fix first)

## Fix tags (code or prose), from 2026-11-21

Rule: prefer **code** (Idli enforces it); **prose** (a sentence in the 9B's instructions) only when code can't
catch it, with a reason. The prose has a size budget (`tests/test_scaffold_prose.py`).

| Fix | Tag | Why prose, if prose |
|---|---|---|
| counts and numbers in replies match what is shown; "nothing found" with rows; drafts never "saved" | code | |
| `--search` words must be the person's; a judge narrows only to a search already shown | code (was prose, ignored) | |
| double-quoted values; `'me'`; `REF` placeholders; `end` as a field; `calendar` in SQL; repeated flags mean "and" | code | |
| existing definitions and views reused; new ones on the yes card | code | |
| field meanings (is_bulk, my_response, owner) | prose (menu) | a connector's own description of its fields; it is data, not a rule |
| "a question about a field shows it" | prose | the mapper chooses fields; no check can tell which field was meant |
| "group words get a proposed view" | prose | not followed by the 9B so far; kept small |
| "a named file goes to summarise file / get sheet" | prose | routing by intent |
| manual examples (who emails me the most; which has the most rows) | prose | examples teach the 9B most (2026-11-19 benchmark) |

Done 2026-11-21 (later): embeddings and merged search, the smaller menu with menu-miss logging, kind chips and
struggle signals, `help`, the prose budget, every sheet tab, docs (GOALS_V0.6, handoff prompt).

Done 2026-11-21: phrase search with ranking, `summarise --search`, `judge --search/--on/--until`, Clef as default
judge, folds and renames, B4, B5, B8, field meanings in the menu, sync progress, and 20 fixes from the agent trial
(chronology 2026-11-21T0000). Held-out rerun: 9B 5 -> 10 correct, idli-remote 13 -> 13.
Next: a new held-out set; workflows (views, Minis); spreadsheet tabs beyond the first; the 9B dropping the person's
words and copying manual examples.

Done 2026-11-20 night: **B3, B9, B10, B11, B12, B13, B14** (the yes card, contents for every kind, skips, saving as
it lands), `-v` levels and the log, `sync drive` with pages and content search, summary cards (chronology section 7).
Still open: **B4, B5, B6, B7, B8**, the renames (sync gmail/gcalendar, events -> calendar, count and --by folds),
the log-to-dev-bank export, a harder judge set.

Done 2026-11-20: **B1, B2** (cursor per thread, retries for temporary errors only, failures not saved and
reported; checked on a copy of the owner's sandbox: 93 judged, 0 failed, where 187 of 191 had failed).

| # | Bug | Evidence | Fix |
|---|---|---|---|
| B1 | judge crashes on files: 4 threads share one DuckDB connection; first-time PDF text writes collide | 187 of 191 "unsure" were `could not judge: ResourceInUseException`; reproduced on a copy | a cursor per thread; retry only transient errors (Drive 429/5xx, 9B timeout), backoff, 2 tries |
| B2 | a failed judgement is saved as `unsure` | same | don't save failures; report "N couldn't be read"; the next judge picks them up |
| B3 | the mapper silently redefined an existing definition (`economics` v1 with `contains_economic_data` -> v2 yes,no) | session turn "show me docs on economics" | mapper may not run define/view on existing names; menu shows each definition's answers |
| B4 | the reply was worded from an earlier step's rows while the last step showed "Nothing matches" | "emails from everyone I've declined meetings with": 0 declined events, reply claimed one | word the reply only from what is shown (or show every step) |
| B5 | spelled-out numbers ("one") skip the number check | same | check number words too |
| B6 | the mapper read an incoming "Declined:" notice as "I declined" | same | `explain mail`/`explain calendar` say what is_calendar_notice and my_response mean |
| B7 | `get event X` / `get mail X` silently take the first substring match | code: `title ILIKE %X%` ... LIMIT 1 | more than one match: list them and ask |
| B11 | a text definition is judged on folders, images and videos too (by name) | `judge files --def adivasi` judged all 191 files incl. 18 folders | skip folders and media unless the definition is on photos |
| B12 | labels are saved only when the whole run ends; Ctrl+C loses everything | owner's interrupted 9B run kept nothing | save each label as it lands; Ctrl+C stops cleanly and says how many were kept |
| B13 | an empty document is sent to the judge | Clef gave an empty "Untitled document" P(yes) 0.86 | no text: `unsure`, no model call |
| B14 | the mapper wrote a definition from the document it had just read: "Adivasi tribes (e.g., Toda, Kota, Irular, PVTGs)" | owner's test doc (a list of other tribes): both 9Bs no, Clef 0.16; with a plain question Clef 0.96 | the yes card for new meanings (agreed 3); show the exact wording |
| B10 | judge only reads text for PDFs and Word files; CSV, Excel, text and Python are judged by name | judge test: the 9B goes 20 -> 33 of 38 with contents | show the first 1,200 characters (Excel as rows) for every file kind |

## Agreed (owner, 2026-11-20)

1. **Naming:** `sync` names the place (`sync gmail`, `sync gcalendar`, `sync drive`); every other verb names the
   kind of record (`list mail`, `list calendar`, `list files`). `events` becomes `calendar`. Google Calendar only for
   now; a provider comes later.
2. **Fewer verbs:** `count` folds into `list --count` / `list --group-by`; `read`, `summarise`, `describe` fold into
   `get file X --text / --summary / --outline`.
3. **Stated meanings:** when the mapper has to pick a meaning the menu doesn't hold, it says so in plain words with
   the answer; on the person's yes the meaning is saved as a view.
4. **Logging:** every `ask` turn appended to `<sandbox>/log.jsonl` with context (earlier turns, date, store counts,
   definitions and views present, masked prompt, raw plan, each step's output, errors, reply, why wording was
   dropped, timings). `--verbose` prints it live. `(Ran: ...)` dimmed, one command per line, store-writing steps marked.
5. **Turns become the dev bank automatically:** on "look over my sandbox chats", the agent checks each logged turn
   with read-only SQL, marks right / wrong / can't tell with a reason, asks the owner only the can't-tell ones, and
   adds them to the dev bank with context and the expected answer. Never the held-out set.

6. **B4 shape:** `ask` shows the last step's rows and the reply is worded from those only; every step's rows go
   to `--verbose` and the log.

## Proposed in discussion (waiting for the owner's ack)

- Document text: one row per page (`file_pages(file_id, page, text)`), full-text index (DuckDB `fts`, BM25), read
  in the background when a sandbox is made, newest first, scoped to what the sandbox can reach, with a size and time
  estimate up front and "read 120 of 312 so far" in answers until done. Incremental on `modifiedTime`.
- Script steps write their output as a table in the sandbox store (its own columns), listed in the menu with an
  about line, so later steps and the mapper can query it. Rebuilt when the step reruns.
- One test for view vs definition: decidable exactly from fields and joins -> view; needs reading content -> definition.
  Both are new saved meanings, so both go through the same yes card, and a definition's card states the judging cost.

- `--by` renamed `--group-by` (SQL's word). Prefer one way per thing: `--search` vs `--where x ~ y` gave the 9B and
  idli-remote different plans for the same ask.
- Field origins shown by `explain`: copied from the site / connector rule / your label.
- Boundary: a rule that needs only columns already in the store is a view (Sandbox Claude); a rule that needs
  something the store doesn't copy yet is a connector change (Builder).
- Order of preference inside a chain: SQL view, then a script step that writes a table, then judge for meaning only.
- `assumes` in the mapper's plan, plus a code backstop: any raw `query` or a join across resources counts as an
  assumption and is shown for a yes.
- Text search inside documents: `--search` reaches extracted file text (DuckDB full-text index), and a way to read
  all text up front (`sync drive --text`).
- Judge model probe: 9B (today) vs Clef-flash (LoRA on a frozen Qwen3.5-9B, Apache 2.0, if the weights are really
  on Hugging Face) vs Muse 28B dense, on ~40 hand-labelled files. Muse images are fine (2026-11-16 crash was a flake).

- `--verbose` prints the menu and the grammar sent to the mapper (owner asked, 2026-11-20).
- B8: the menu's "is one of" lists any short text column with <=10 values, so a small calendar lists every event
  title as if it were a fixed choice (seen in a 3-event demo store). Limit it to declared enum fields.
- B9 (root of B3): the menu lists each definition's question but not its answers.
- A resources registry in the store (today `RESOURCES` is a dict in recstore.py), so connectors and Mini steps can
  add kinds of records with an about line; the menu reads it.
- Derived tables: a script step's output is its own table in the sandbox store, linked by ids (file_id, event id);
  the registry records which Mini and step made it, it is rebuilt when the step reruns, and dropped with the Mini.

## Judge test (done 2026-11-20, `benchmarks/runs/2026-11-20-judge-models/README.md`)

- Result: what the judge sees matters most (B10). Clef-flash and idli-remote 38/38 with content; 9B BF16 35, Q5 33,
  Muse 33 (4x slower). Hosted Clef sees real content, so for real data it must run locally. The set is too easy at
  the top: a harder second set is needed to separate Clef from idli-remote.
- Labels to confirm by the owner: listed in that README.
- `idli ask --mapper nine` now uses the BF16 9B (`idli-9b-bf16`, port 8292); `nine_compressed` the served Q5.
- `--judge nine|nine_compressed|clef` on `ask` and `judge`; it covers every judge step inside `ask`. It follows the
  mapper; with `--mapper remote` it stays the served 9B (judging reads real content). Clef only when named: hosted,
  it sees real content. Yes/no definitions use P(yes) with 0.35 to 0.65 as unsure; others the top answer if >= 0.5.
  Labels are kept per definition version whoever judged, so comparing judges needs a fresh copy or a new version.

### The plan as agreed

- Topic "about endangered species", deliberately hard: CSV, Excel, PDF, Python, Docs, with near misses (endangered
  languages, extinct species, wildlife tourism budgets, a species list with no threat status, a zoo ticket CSV).
  About 40 items, a new synthetic set, labelled by the agent and confirmed by the owner. Standalone harness: same
  text extraction and prompt as `recstore.judge`.
- Candidates: 9B Q5 (today), Qwen3.5-9B BF16 (to see what compression costs), Clef-flash, Muse 28B, idli-remote as
  a reference (synthetic data only).
- Measures: agreement with labels, misses vs false alarms, unsure rate, seconds per item, memory.
- Clef facts (checked 2026-11-20): `Cloudflare/clef-flash` on Hugging Face, Apache-2.0, 18.8 GB BF16 plus a 0.24 GB
  scoring head (`joint_head.safetensors`, custom code `joint_schema_model.py`). Its weights differ from Qwen3.5-9B
  (LoRA merged), so it cannot share memory with our 9B. Not on OpenRouter; listed on Workers AI. No torch+CUDA
  environment on the DGX yet. Full Qwen3.5-9B BF16 is in `~/.cache/huggingface/hub/models--Qwen--Qwen3.5-9B` (19 GB).

## Session 2 findings (2026-11-20 night, the adivasi chat)

- Search failed because `--search` reads names and folders only; "adivasi" is in 2 documents' text. Content search
  first; summary cards (with key terms kept verbatim) during background reading; embeddings only if tests still miss.
- No progress output on long judges; proposed: a progress line by default, `-v`/`-vv`/`-vvv` for detail, `--show N`
  rows per minority answer after `judge`. pypdf's "Ignoring wrong pointing object" (a PDF with a broken xref,
  read anyway) only at `-vvv`.
- The owner's re-sync didn't reach `~/idli-sbx/t1` (last Drive sync 20:47; the test doc was made 21:05); sync on a
  copy works.

## Open questions

(filled in at the end of the discussion)

## For dune (carry over)

- The blind task bank, frozen held-out, SQL grader and tester: `benchmarks/runs/2026-11-19-record-store/{bank,grader,tester}`.
- The log-to-dev-bank loop above.
- This ledger's format: bugs with evidence, agreed, proposed, open.
