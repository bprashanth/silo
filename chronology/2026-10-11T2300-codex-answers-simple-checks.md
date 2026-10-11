# Codex answers, the simple harness checks (started)

The plan from `proposals/correctness-receipt.md`, with the roles swapped as the
harness-compare results suggested:
- **Answering:** io's Codex under io's offline profile answers every message on the local model.
- **Checking:** the bridge's own python-tool harness answers the same message in parallel and
  independently: it gets the same files and history, but not Codex's answer.
- **Waiting:** once Codex finishes, the bot waits at most 30 s more for the checker.
  If the checker isn't done, the reply goes out marked unverified. The checker's late result
  is still written to the audit record.
- **Badges:** every reply carries one, and `/how` shows the audit record behind the last answer.

Measured first: llama.cpp honours `reasoning_effort: "low"` on `/v1/chat/completions` for
Muse. On a small word problem it went from 334 to 179 output tokens and from 7.8 s to 3.3 s. The checker
uses it, because the simple harness's median of 256 s (with default reasoning) would almost
never finish within 30 s of Codex's 88 s.

io's AGENTS.md (written by `writeConfig`) tells Codex to save charts as PNG and dashboards as
HTML in the working folder. The bot sends any new file in the job folder back to the chat.
