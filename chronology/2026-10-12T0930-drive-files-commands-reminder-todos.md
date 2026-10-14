# /drive, /files, and reminders become todos

**Asked:**
- `/drive` shows the service account email in its own message, so it's easy to copy.
- `/files [folder]` lists the user's files like `ls`.
- A reminder also adds the task to the todo list.
- Write up v1's three features (voice, Drive, todos and reminders) as a narrative.

**Built:**
- `tg_bridge.py`:
  - **`/drive`:**
    - An explanation, then a second message holding only `<code>email</code>`, which Telegram
      copies on tap.
    - Falls back to sign-in or "not set up" if there's no key.
  - **`/files`:**
    - `files_view(chat, rel)`: folders first, then files with sizes.
    - A button per subfolder and a ⬆️ Up button. Taps edit the same message (`files:` callbacks).
    - Button data is limited to 64 bytes, so deep paths are shown without a button.
    - Paths are resolved and must stay inside the chat's work folder; `../../..` gets
      "That folder isn't in your files." Symlinks are skipped.
  - Both are in the command menu and `/start`.
- `todos.py`:
  - `remind_at` with a `what` adds it as a todo unless `same_todo()` finds an open one.
    `same_todo()` treats two todos as the same when one's words, minus stop words, contain
    the other's.
  - Adds are processed before reminders in the same message, so "add X and remind me at 6
    about X" makes one todo.
  - A fired reminder whose todo is still open says "It's on your todo list; tell me when
    it's done."

**Tested live:**
- `/drive` sent the email as a separate monospace message.
- `/files`, `/files Cell Ag/Tufts`, and tapping Protocols then Up all showed the right folders.
- `/files ../../..` was refused.
- "remind me at 6 to call Meera about the zebrafish permit" set the reminder for 6:00 pm
  IST and added the todo. I then deleted that test todo and reminder by hand. The user's own
  pending reminder ("meeting with Swadesh", 10:15) was left alone.

**Narrative:** `narrative/2026-10-12-v1-features.md`.
