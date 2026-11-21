"""Answer a question that needs no files straight from the local model, with no reasoning,
word by word, so the first words show in about a second instead of after Codex's ~30 s.

Used for general-knowledge questions and questions about Silo itself, which the first-pass
sort in todos.py picks out (leaning towards Codex whenever it's unsure).

Muse's chat template has no "reasoning off" setting (reasoning_strength low/minimal/none all
still think for 5-20 s). So the prompt is rendered with llama.cpp's /apply-template and the
reply is started at the final-answer channel (" to=user<|message|>"), which skips the
reasoning entirely. For a server without /apply-template, it falls back to a normal chat
completion with reasoning low.
"""
import json
import urllib.request

STOP = ["<|eot|>", "<|start|>", "<|eom|>"]
MAX_TOKENS = 900

SYSTEM = """You are Silo, a confidential assistant for a small Indian non-profit, chatting on Telegram.
Answer directly and helpfully, making reasonable assumptions instead of asking questions back.
Keep replies short: they're read on a phone. Use Indian conventions (₹, lakh, crore) where they fit.
This answer comes from your general knowledge, not from the user's files."""

SILO_HELP = """How Silo works, for questions about using it:
- Everything runs on the team's own box. The AI that works on files has no internet access.
- Send a spreadsheet (Excel), PDF, image (PNG/JPG) or text file (TXT, MD, CSV), then ask about it. Codex works out the
  answer with code on a copy of the files. Charts come back as pictures.
- Paste a Google Drive folder link to copy it, with every subfolder. /drive shows the email to
  share the folder with first (as a Viewer). /files lists your files; tap a folder to open it.
- Voice notes in English are transcribed on the box. Every reply has a 🔊 Read aloud button:
  tap it to hear the reply. /language picks the language it speaks in (Hindi by default: the
  reply is translated on the box first). /voice picks the voice.
- Todos: say or type "add … to my todos", "what are my todos", "I did 1 and 3". "Remind me at 6"
  sends a message at 6 pm IST; a reminder is also added to the todo list. Open todos carry over
  from day to day: the list comes every morning at 9, and an evening check-in at 5 shows
  what's done and what's still open. Specific reminders come on top of those.
- /strict turns on checking: every answer is worked out a second time, independently, and a
  badge says whether they agree (✅ agree, ⚠️ differ, ◻️ couldn't check). It's off by default (➖).
- /how shows how the last answer was made: the files, every step, the model.
- /model switches model. /reset erases everything kept about you: conversation, files, todos,
  reminders, settings and records."""


def _post(url, body, key, timeout=300):
    return urllib.request.urlopen(urllib.request.Request(
        url, json.dumps(body).encode(),
        {"Content-Type": "application/json", "Authorization": f"Bearer {key}"}), timeout=timeout)


def messages(history, topic):
    """System prompt plus the conversation as text (pictures dropped: this path can't see them)."""
    system = SYSTEM + ("\n\n" + SILO_HELP if topic == "silo" else "")
    out = [{"role": "system", "content": system}]
    for m in history:
        c = m["content"]
        if not isinstance(c, str):
            c = "\n".join(p.get("text", "") for p in c if p.get("type") == "text")
        out.append({"role": m["role"], "content": c})
    return out


def stream(model, history, topic, on_text):
    """Calls on_text(text_so_far) as the reply grows; returns the full reply."""
    root = model["base"].rstrip("/").removesuffix("/v1")
    msgs = messages(history, topic)
    try:
        with _post(f"{root}/apply-template", {"messages": msgs}, model["key"], 30) as r:
            prompt = json.load(r)["prompt"]
    except Exception:
        return _fallback(model, msgs, on_text)
    text = ""
    with _post(f"{root}/completion", {"prompt": prompt + " to=user<|message|>", "stream": True,
                                      "n_predict": MAX_TOKENS, "temperature": 0.3, "stop": STOP,
                                      "cache_prompt": True}, model["key"]) as r:
        for line in r:
            if not line.startswith(b"data: "):
                continue
            d = json.loads(line[6:])
            if d.get("content"):
                text += d["content"]
                on_text(text)
            if d.get("stop"):
                break
    return text.strip()


def _fallback(model, msgs, on_text):
    with _post(f"{model['base']}/chat/completions", {"model": model["model"], "messages": msgs,
                                                     "reasoning_effort": "low"}, model["key"]) as r:
        text = json.load(r)["choices"][0]["message"]["content"].strip()
    on_text(text)
    return text
