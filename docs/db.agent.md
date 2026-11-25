# The store, as built (companion to db.md)

Implementation notes, 2026-11-21. Describes `core/lib/recstore.py` as it is today. db.md has the ideas (views,
definitions, workflows); this has the tables and who writes them.

## One store per sandbox

A sandbox is a folder (`IDLI_SANDBOX`). The store is `store.duckdb` in it. Next to it: `log.jsonl` (every command
and every `ask` turn), `session.json` (the last 6 turns) and `vault/` (the masking codes for this folder).

## Tables

| Table | One row per | Written by |
|---|---|---|
| `mail` | email, last 60 days, sent and received | `sync gmail` |
| `events` (and the view `calendar`) | calendar event, 60 days back and ahead | `sync gcalendar` |
| `event_guests` | guest of an event | `sync gcalendar` |
| `threads` (view) | email conversation | made from `mail` |
| `files` | Drive file or folder | `sync drive` |
| `sheets` | tab of a spreadsheet (`name`, `tab`, `tab_index`, `tbl`, `columns`, `nrows`) | `sync drive` |
| `sheet_<name>` | row of one tab; the first tab keeps the plain name, other tabs get the tab in theirs | `sync drive` |
| `file_text` | file: its text, capped at 60 KB, and the version it was read at | `sync drive` |
| `file_pages` | page of a file (PDF pages; other files cut into ~3,000-character parts) | `sync drive` |
| `file_cards` | file: 2-3 sentences and up to 15 key terms, word for word | `sync drive` (the 9B) |
| `file_chunks` | ~1,200-character piece of a page, with a 1,024-number vector | `sync drive` (embedding model) |
| `card_vecs` | card's vector | `sync drive` |
| `definitions` | version of a definition (name, kind of record, question, answers) | `define`, after a yes card |
| `labels` | answer for one record, one definition version | `judge` |
| `views` (and a real view per name) | saved rule | `view`, after a yes card |
| `chats` | chat or group (`provider`, coverage `earliest_at`/`latest_at`, `msg_count`) | `sync whatsapp` |
| `messages` | chat message, image/video caption or document (`id` = stable 20-char ref, `parent_id`, `links`, `link_preview`, `reply_count`) | `sync whatsapp` |
| `chat_members` | observed sender per chat (`chat_id`, `sender_id`, `sender`, `msg_count`) for deterministic sender resolution | `sync whatsapp` |
| `message_episodes` | stitched conversation episode (reply links ∪ 15-min bursts) with contextual text and 1,024-dim vector | `sync whatsapp` |
| `sync_log` | sync run | every sync |

## Rules that keep it honest

- **Versions.** Text, pages, cards and chunks are kept per file version (Drive's modified time). A changed file is
  read again and its labels are dropped. A deleted file's rows go too.
- **Labels are per definition version.** Changing a definition makes a new version, judged again; the old labels
  stay with the old version.
- **Views are real database views.** So `list mail --where "from_addr IN (SELECT email FROM leads)"` works.
- **Empty files** (a Doc with no text, a 0-byte upload) are hidden from listings unless `--all`.

## Size on the test account (87profligate)

190 emails, 10 events, 192 files, 23 spreadsheets (37 tabs), ~3,600 pages, ~11,000 chunks: about 70 MB, most of
it vectors and text.

## Not built yet

- Tables made by a Mini's script step (db.md principle 3).
- More than one table on a tab (subtables, `todos/subtables.md`).
