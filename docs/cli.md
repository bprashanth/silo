# CLI outline 

## Principles 

1. Have only one way to do each thing
2. Try and mirror popular cli syntax (kubectl, sql, git etc) theyr'e all over the internet and the 9b already understands them.
3. Ensure there are example commands and a manual page. 

## Command outlines 

### Explanations via "summarise"

_Without embeddings_

1. Literal search 
2. Rank by mentions 
3. limit 5
4. Look specifically at a few pages (3-5) that mention X most and take around 2k chars around the first mention
5. 9b write an explanation about the excerpt with citations 

_with embeddings_

1. Question turned into a vector
2. Page first chunked then stored as vector 
3. Map distance between these two and take the top N

## Cross-app resource alignment (proposed, 2026-11-23)

One shape everywhere: `idli VERB RESOURCE [REF] [flags]`. Chat apps (WhatsApp first, later Slack/Mattermost via a `provider` column) reuse the same verbs and flags rather than adding new ones.

| Existing Google pattern | Same pattern for chat (`messages` / `chats`) | Shared contract |
|---|---|---|
| `sync gmail \| gcalendar \| drive` | `sync whatsapp` | `sync` names the place / connector. |
| `files` + `folders`, filtered by `--in FOLDER` | `messages` + `chats`, filtered by `--in CHAT` | `--in` means the container (Drive folder, chat/group, Gmail label/mailbox). |
| `mail` + `threads`, opened by `get mail\|thread REF` | `get message REF` | Returns the message plus its quoted parent, direct replies, and nearby neighbors (the chat equivalent of `get thread`). |
| `list files --search WORDS` (hybrid + `found` snippet) | `list messages --search WORDS [--in CHAT] [--on PERIOD]` | Exact `"quotes"` = literal; unquoted = hybrid (BM25 + embeddings + optional rerank) returning `ref`, timestamp, chat, sender, and excerpt. |
| `list files --count` / `--group-by` | `list messages --count [--in CHAT] [--where "..."]` | Always runs on the full `messages` table — never a truncated search packet. |
| `summarise [files] --search WORDS` | `summarise messages --search WORDS [--in CHAT] [--on PERIOD]` | One-step retrieval + grounded synthesis over conversation episodes with `[Sender, Date, Chat, ref]` citations. |
| `define ... --on mail\|event\|file\|photo` | Add `message` to `--on` | `judge messages --def ... --in CHAT --on PERIOD` uses the same define/judge/label loop. |
| `view NAME --sql "SELECT ..."` | `view NAME --sql "SELECT ..."` | Saved named SQL rule over any table(s) (`mail`, `files`, `messages`, `chats`, sheets), usable as a resource in `list` and SQL joins. |

See [proposals/architecture/whatsapp-search.md](../proposals/architecture/whatsapp-search.md) for the full design.
