# Examples: the layers on concrete asks

2026-11-19. From io (`narrative/EXAMPLES_V0.md`). See [goals.md](goals.md). Each example shows the connector calls, the DuckDB
tables, the queries, and what the 9B does. Nothing here is built yet beyond the Google APIs and `nine_b`.

**Update 2026-11-21:** these examples are still the right shapes. What changed in practice
([goals.md](goals.md)): the calendar resource is `calendar` (the table is still `events`); many "own
definition" asks are answered by search first, since search reads every page and ranks by meaning ("conservation
correspondence" lists emails and files that use the words, then a judge narrows to "really about it" on the yes
card); every tab of a spreadsheet is its own table; `leads` is a view (an exact rule over a sheet), not a
definition. The WhatsApp example is not built (no connector).

Granularity rule: **one row per natural item**. That means one email, one WhatsApp message, one Drive file, one
calendar event (not one day). Reactions, guests and labels go in side tables, joined by id. A **label** from a
definition is a row in one shared table:

```sql
labels(kind, record_id, definition, version, label, detail, judged_at)  -- e.g. ('mail', 'm123', 'conservation', 2, 'yes', 'tiger reserve survey', ...)
```

Who does what, in every example:
- **Connector CLI:** the only way data comes in (`idli sync ...`). The only way anything goes out is a write verb,
  previewed unless `--apply`.
- **DuckDB:** holds the rows; filters, joins and counts with SQL. No model.
- **The 9B:**
  - picks argument values for a saved chain ("last 2 days", which lead);
  - runs `judge`, a label per row, with vision for images.
- **idli-remote:** for a new question, writes SQL over the masked schema, never seeing rows.
- **Sandbox Claude:** writes the chain, the views and the definitions once, on masked samples.

### 1. Gmail: "look over last week's emails and find all the conservation correspondence"

```
idli sync mail --since 2026-11-12 --as me                 # Gmail API -> table mail (about 200 rows)
idli judge mail --def conservation \
     --where "date >= '2026-11-12' and not is_bulk"      # 9B, about 60 rows -> labels
idli list threads --where "label.conservation = 'yes'"   # SQL below
```

```sql
mail(id, thread_id, account, date, direction, from_addr, from_name, to_addrs, subject, snippet, body_text,
     is_bulk,            -- List-Unsubscribe header, noreply senders: decided by code
     is_calendar_notice) -- "Accepted:", "Declined:", invitations: decided by code

SELECT m.thread_id, any_value(m.subject), min(m.date), count(*) AS emails
FROM mail m JOIN labels l ON l.kind='mail' AND l.record_id=m.id AND l.definition='conservation' AND l.label='yes'
WHERE m.date >= '2026-11-12'
GROUP BY m.thread_id ORDER BY min(m.date);
```

- **The definition `conservation` (v2), written by Sandbox Claude:** "Is this email about wildlife, habitat,
  forests, species or conservation work?"
  - Answer shape: `{yes | no | unsure, why}`.
  - It has 4 examples you marked.
- **The 9B reads** the subject and the first 1,500 characters of each candidate, about a second each. Results are
  cached, so next week only new mail is judged.
- **Code, not the 9B,** removes newsletters and notices first (`is_bulk`, `is_calendar_notice`).
- **Trust:** "show me 10 it called conservation, and 10 it didn't". You mark them, and the agreement is shown.
- **Daily questions:** "only from funders" adds a `--where`. "The last 2 days" changes `--since`. The 9B or
  idli-remote picks those values; nothing is re-judged.

### 2. Drive: "categorise all my pictures with animals"

```
idli sync files --in "Drive/My Drive/Field photos" --type image     # Drive API metadata -> table files
idli judge files --def animal --where "mime like 'image/%'"         # 9B vision on a 512 px thumbnail per image
idli list files --where "label.animal != 'none'" -o table           # or: count by category
```

```sql
files(id, path, folder, name, mime, size, modified, taken_at, width, height, thumb_cached)

SELECT l.label AS category, count(*) FROM files f
JOIN labels l ON l.kind='file' AND l.record_id=f.id AND l.definition='animal'
GROUP BY l.label;                       -- bird 140, mammal 37, reptile 5, none 812
```

- **The definition `animal`:** answer shape `{none | bird | mammal | reptile | insect | other, unsure}`.
- **The 9B's vision** sees thumbnails on this computer only. Images never leave it. Sandbox Claude sees counts and
  coded file names.
- **Categorising:** that's the label column. Moving or tagging files in Drive would be a write verb (`idli move
  files ... --apply`), built by our team.

### 3. WhatsApp: "my funder chats where a message I sent last week got a blue tick or a heart"

```
idli sync whatsapp chats                                   # browser connector (WhatsApp Web), read-only
idli judge chats --def funder                              # once per chat (about 50), you check the list once
idli sync whatsapp messages --where "label.funder='yes'" --since 2026-11-12
idli list messages --where "direction='out' and (status='read' or reaction='❤️')"
```

```sql
wa_chats(chat_id, name, is_group, participants)
wa_messages(id, chat_id, time, direction,        -- 'in' or 'out'
            sender, text, status)                 -- 'sent' | 'delivered' | 'read' (blue ticks)
wa_reactions(message_id, reactor, emoji, time)

SELECT c.name, m.time, m.text, m.status, list(r.emoji) AS reactions
FROM wa_messages m
JOIN wa_chats c USING (chat_id)
JOIN labels l ON l.kind='chat' AND l.record_id=c.chat_id AND l.definition='funder' AND l.label='yes'
LEFT JOIN wa_reactions r ON r.message_id = m.id
WHERE m.direction='out' AND m.time >= '2026-11-12'
GROUP BY c.name, m.time, m.text, m.status
HAVING m.status='read' OR list_contains(list(r.emoji), '❤️');
```

- **"Funder" applies to a chat, not a message.** The 9B labels each chat once, from its name and recent messages.
  You confirm the list once. Alternatively, a sheet of funders works as a view, with no model at all.
- **The 9B's only role here** is that one chat-level label. Ticks, hearts and dates are fields, so SQL does the
  rest.
- **The connector is the hard part.** It reads WhatsApp Web in a Chrome profile: messages, tick status and
  reactions. It is read-only, and never sends.

### 4. Calendar, and the leads workflow, for comparison

```sql
events(id, account, start, end, title, organizer, my_response, is_recurring)  -- one row per event instance
event_guests(event_id, email, response)
sheet_rows(sheet, row, data_json)              -- the leads sheet; view leads = (name, email) from it
```

- **The views,** defined by Sandbox Claude in the Mini:
  - `leads` = the sheet's rows;
  - `replies` = `mail` where `from_addr in leads.email and not is_calendar_notice`.
- **The 9B's judgement,** `judge replies --def intent` with answer shape `{agreed | picked_time(when) | other}`.
- **The rest is queries:**
  - "who hasn't replied" is `leads LEFT JOIN replies ... WHERE replies.id IS NULL`;
  - "what happens next for Ravi" is `--where lead~Ravi`.
- **The action:** `idli draft reply --to-thread ... --apply` (preview without `--apply`).

### What crosses the line

| | idli-remote | Sandbox Claude |
|---|---|---|
| Question | masked | masked |
| Schema (tables, columns, types) | yes | yes |
| Sample values | a few, masked | masked sample rows, while building |
| Rows, email bodies, images | never | never: Idli runs its code, and it gets masked output after your yes |
