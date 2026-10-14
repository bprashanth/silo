# An instant "⏳" with a wait estimate

**Asked:** send an estimate right away, based on how the message is sorted: about 1–10 s for
the model alone, 20–60 s when Codex works on the files.

**Built (`tg_bridge.py`, `todos.py`):**
- **`Status`:** a "⏳ One moment…" message is sent as soon as a text or voice message
  arrives (after the 🎙️ transcript). The sort takes about 2–3 s, then
  `todos.handle(..., on_sorted=)` edits it to the estimate:
  - direct: "⏳ A quick answer from the model: about 1–10 s."
  - todos: "⏳ Updating your todos: about 5–30 s."
  - Codex: "⏳ Working on it with your files: usually 20–60 s", or 30–90 s with /strict.
  - Small talk shows no estimate.
- **What happens to it:**
  - Quick answers stream into that same message.
  - Todo and small-talk replies replace it.
  - Codex answers arrive as a new message, so the phone notifies, and the status message
    is deleted.
  - Errors replace it.
- **Files and photos** skip the sort, so they get the Codex estimate straight away.

**Tested live:**
- "Who wrote the Indian national anthem?" → the status turned into the answer.
- "What are my todos?" → the status turned into the list.
- "How many PDF files are in Cell Ag?" → ⏳ 20–60 s, then the answer arrived as a new
  message 33 s later, and the status was deleted.
