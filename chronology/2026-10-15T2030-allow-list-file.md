# Allow list in a file, re-read without a restart

The allow list moved from the `TG_ALLOWED` env var (read once at start) to
`~/.config/silo/allowed.txt`: one Telegram username or numeric id per line, `#` comments.
`tg_bridge.allowed_names()` stats the file on every message and re-reads it when its
mtime changes, so adding or removing someone takes effect on their next message.
`TG_ALLOWED` still works and is added to the file's list.

- An empty file allows nobody; only a missing file with no `TG_ALLOWED` lets anyone in,
  so clearing the file can't open the bot up.
- Phone numbers can't be used: Telegram never gives them to bots. Usernames are globally
  unique but can be released and claimed by someone else; ids never change, so swap a
  username for its id (shown in the log as `name(id)`) once the person has written in.

Tested in a scratch `SILO_CONFIG`: no file lets anyone in; a username added to the file is
let in without a restart; an empty file blocks everyone. The live bot was restarted once
(nothing in flight) and came up with the same two entries as before.
