# Direct answers for questions that need no files; history on disk; the button on voice replies

**Reported by the user, from the last few conversations:**
1. Replies to voice questions had no 🔊 button.
2. A question that needed no computation ("tell me about the graphics card") took about 30 s.
3. "Where is the read aloud option" was answered about the Cell Ag files.

**Causes, from the audit log:**
1. `send(..., aloud=not voice)`: voice replies were meant to be spoken automatically, which
   is now off.
2. Every non-todo message went through Codex: 0 tool steps, 12.6k input tokens and 27 s.
   The same question sent straight to Muse took 16 s (first words at 6 s), and most of that
   was generation at 23–28 tok/s.
3. Codex doesn't know about Silo's own features. Every prompt starts "Their files are in the
   current folder: <14 Cell Ag paths>", so it searched the files for "read aloud" (2 steps,
   39k tokens). Also, history was only in memory, so every restart wiped it.

**Turning reasoning off:** Muse's chat template only has `reasoning_strength` (a default
of high). `reasoning_effort: none`, `chat_template_kwargs.enable_thinking=false`,
`reasoning_budget: 0` and `reasoning_strength` low/minimal/none all still reasoned, taking
16–23 s before the first word. What works: render the prompt with `/apply-template`, then
add `" to=user<|message|>"`. That's the final-answer channel the model would otherwise
reach after reasoning. Then stream `/completion` with stops `<|eot|>`, `<|start|>`, `<|eom|>`.
The first token came at 0.2 s, and a full answer took 1.5–10 s. Answers are a little less
careful without reasoning; for example, it suggested NVLink for the RTX 4090, which has none.

**Built:**
- `todos.py`, the first-pass sort, has two new tools:
  - `general_question`: needs none of their files and isn't a follow-up to a file question.
  - `about_silo`: how to use the bot.
  Both lean towards `not_about_todos`, i.e. Codex, when unsure. The sort now also sees the
  chat's file names and the last 4 messages. It's told that a topic appearing in their file
  names or in recent file talk means Codex: "What is a scaffold in cellular agriculture?"
  went direct before that rule and to Codex after it. `handle()` returns `kind: "direct"`.
- `direct.py`: the streaming answer described above, with a fallback to chat completions with
  reasoning low. `SILO_HELP` (commands, buttons, privacy) is added only for `about_silo`.
  Codex never sees it.
- `tg_bridge.py`:
  - `answer_direct`: sends the first words, then edits the message at most once a second,
    ending with the badge and 🔊. Badges: "➖ From the model's general knowledge, not your
    files. Not checked.", or "➖ About Silo…".
  - An `answer` audit record with `checker_status: "direct"` and the sort's calls; `/how`
    explains it.
  - `Turns`/`History`: each chat's last 20 messages are kept in a `history` table in
    `$SILO_DB`, loaded when the chat is first used, and trimmed on every append. `/reset`
    clears them (`Turns.clear`), then `todos.erase` VACUUMs.
  - The 🔊 button is on every reply unless `VOICE_REPLIES` speaks it automatically.
- `$SILO_DB` is now mode 600. It's outside the repo, so there's nothing to gitignore.

**Tested live:**
- "What's the capital of Meghalaya?": direct, 4 s from sending to the full reply.
- "Where is the read aloud option?": direct, about Silo, 5 s. The answer was right.
- A voice note asking for India's tallest mountain: 10 s to transcribe (Whisper loads on
  first use), then 4 s to the full reply, with the 🔊 button.
- "Tell me about wk6": Codex.
- "What is a scaffold in cellular agriculture?" went to Codex once the file-topic rule was in.
- Restart, then "the state capital I asked about earlier…": the history came back from
  disk and the answer was about Shillong (via Codex, since it was a follow-up).

**Not done, and why:**
- **Codex's own conversations (`codex exec resume <id>`):** this exists, but it's a poor fit.
  - Its sessions hold every tool call and output: the "read aloud" turn alone was 39k
    tokens. Compacting those means extra model calls on the slow local model.
  - The todo, direct and checker paths need the same conversation, and Codex's sessions
    would hold only Codex's turns.
  - Each question runs in a fresh copy of the files.
  So we keep our own short conversation (user and assistant text only) and pass it to every path.
- **History on the Seagate drive:** it's a USB spinning disk with exFAT. It has no file
  permissions (everything on it is readable by every account), no journalling (so a power
  cut or unplug can corrupt the database), and it can be asleep when a message arrives
  (seconds to wake). The internal NVMe is faster and safer, so the history stays there.
