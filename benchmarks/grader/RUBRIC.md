# Grading the assistant's answers

You grade transcripts of an assistant ("Idli") answering requests about one person's Google account. The account's
data is in a database you can query: run `./ask "SELECT ..."` (read-only SQL, DuckDB). Start with
`./ask "SHOW TABLES"` and `./ask "DESCRIBE mail"`. Tables: mail (one row per email), threads (view), events,
event_guests, files (Drive), sheets (one row per spreadsheet; each sheet's rows are in the table named in `tbl`),
file_text, definitions, labels. Times are local (Asia/Kolkata). "Today" is the date the transcripts were made: {TODAY}.

`transcripts.json` holds, per task: the request turns, what a correct answer needs (`expect`, written beforehand by
someone else), and per turn the assistant's commands, the rows it showed, and its reply. `grammar.md` describes
what the assistant's commands can do.

For every task write one object to `grades.json` (a JSON list), with:
- `id`
- `coverage`: could this assistant's design express the request?
  - `yes`: with its existing commands, filters, definitions (its own categories judged per item) and SQL;
  - `new_connector`: needs a site or data source it does not read (WhatsApp, Slack, Canva, LinkedIn...);
  - `new_write`: needs an action that changes something (move, rename, send, post, book) beyond a draft preview;
  - `design_miss`: the data is there but the design has no general way to express it.

  Judge from grammar.md, not only from what it did.
- `correctness`, for the final answer of the task, checked against the database:
  - `correct`;
  - `partial` (right direction, something missing or extra);
  - `wrong`;
  - `refused_ok` (correctly said it can't, e.g. another site or a write);
  - `refused_wrong` (said it can't but it could);
  - `failed` (error, or no useful answer).

  For a category the person defined (urgent, about caste...), judge whether the items shown plausibly fit and
  whether obvious ones are missing. Check a few in the data; don't demand perfection.
- `fit` (1-5): does the reply answer what was asked, at the level asked ("just the number" means a number)? A
  correct refusal that says plainly why and what would make it possible fits well (4-5).
- `ack` (1-5; null when the task has one turn): when a follow-up corrects or points at something ("no, only after lunch",
  "the second one"), does the reply take it in?
- `repetitive` (1-5; null when the task has one turn): 5 means the replies read naturally across the session, 1 means
  the same sentence or formula again and again.
- `notes`: one or two sentences: what was wrong, or what made it good.

Be strict and concrete. Verify numbers with SQL. Write grades.json with your file tools when done.
