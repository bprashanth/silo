#!/usr/bin/env python3
"""Telegram bot <-> LLM bridge.

Long-polls the Bot API (no public URL needed), sends each text message to an
OpenAI-compatible chat endpoint (OpenRouter by default, or a local server),
and replies. Per-chat history is kept in memory.

Models are picked per chat with /model (see MODELS). Charts: the model emits
```chart JSON, which charts.py renders to a dashboard PNG.

Env (see docs/deployment.md):
  TELEGRAM_BOT_TOKEN  bot token from @BotFather (or "api_key" in $SILO_CONFIG/telegram.json)
  OPENROUTER_API_KEY  optional; enables the external models (or $SILO_CONFIG/openrouter.json)
  SILO_CONFIG         dir holding the json files above (default ~/.config/silo)
  IDLI_BASE_URL       local OpenAI-compatible server (default http://127.0.0.1:8181/v1)
  IDLI_MODEL          model name the local server expects (default muse-glimmer-30b)
  IDLI_KEY            bearer token for the local server, if it wants one
  TG_ALLOWED          comma-separated Telegram user ids/usernames; empty = anyone
  SYSTEM_PROMPT       override the system prompt
"""
import base64
import json
import os
import subprocess
import tempfile
import threading
import time
import urllib.request
import uuid
from collections import defaultdict, deque

import answer
import audit_log
import charts
import harness
import speech
import todos

CFG = os.path.expanduser(os.environ.get("SILO_CONFIG", "~/.config/silo"))


def secret(env, file):
    """A key from the environment, else "api_key" in $SILO_CONFIG/<file>; None if neither."""
    if os.environ.get(env):
        return os.environ[env]
    try:
        return json.load(open(f"{CFG}/{file}"))["api_key"]
    except (OSError, KeyError, ValueError):
        return None


TG_TOKEN = secret("TELEGRAM_BOT_TOKEN", "telegram.json")
if not TG_TOKEN:
    raise SystemExit(f"No bot token: set TELEGRAM_BOT_TOKEN or put api_key in {CFG}/telegram.json")
OR_KEY = secret("OPENROUTER_API_KEY", "openrouter.json")

API = f"https://api.telegram.org/bot{TG_TOKEN}"
OPENROUTER = "https://openrouter.ai/api/v1"
# Ordered small -> large; "idli" is the default. External models exist only with an OpenRouter key.
MODELS = {
    "qwen": {"label": "Qwen3.5 9B", "kind": "external",
             "base": OPENROUTER, "model": "qwen/qwen3.5-9b", "key": OR_KEY},
    "idli": {"label": "Muse Glimmer 30B", "kind": "idli internal",
             "base": os.environ.get("IDLI_BASE_URL", "http://127.0.0.1:8181/v1"),
             "model": os.environ.get("IDLI_MODEL", "muse-glimmer-30b"),
             "key": os.environ.get("IDLI_KEY", "none")},
    "deepseek": {"label": "DeepSeek V4.1 Flash", "kind": "external",
                 "base": OPENROUTER, "model": "deepseek/deepseek-v4.1-flash", "key": OR_KEY},
}
MODELS = {k: m for k, m in MODELS.items() if m["kind"] != "external" or OR_KEY}
DEFAULT_MODEL = "idli"
chat_model = defaultdict(lambda: DEFAULT_MODEL)
ALLOWED = {a.strip().lstrip("@").lower() for a in os.environ.get("TG_ALLOWED", "").split(",") if a.strip()}
SYSTEM = os.environ.get(
    "SYSTEM_PROMPT",
    "You are a helpful assistant chatting over Telegram. Keep replies concise.",
) + charts.SYSTEM_HINT

MAX_DOC_CHARS = 100_000  # ~25k tokens; Glimmer has 131k context
FILE_URL = f"https://api.telegram.org/file/bot{TG_TOKEN}"

history = defaultdict(lambda: deque(maxlen=20))
locks = defaultdict(threading.Lock)


def post_json(url, body, headers=None, timeout=120):
    req = urllib.request.Request(
        url, json.dumps(body).encode(), {"Content-Type": "application/json", **(headers or {})}
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def tg(method, **params):
    return post_json(f"{API}/{method}", params, timeout=70)


def llm(chat, user):
    """Answer the chat's latest message: io's Codex answers, the bridge's harness checks
    (answer.py). Returns (reply, badge, files to send back)."""
    key = chat_model[chat]
    reply, badge, files = answer.respond(chat, user, list(history[chat]), SYSTEM, MODELS[key], key)
    if not reply.strip():
        raise Unsupported("The model didn't produce an answer. Try a narrower question, or /how to see what it tried.")
    return reply, badge, files


class typing:
    """Keep Telegram's "typing..." indicator alive while the model works."""

    def __init__(self, chat):
        self.chat, self.stop = chat, threading.Event()

    def __enter__(self):
        def tick():
            while not self.stop.is_set():
                try:
                    tg("sendChatAction", chat_id=self.chat, action="typing")
                except Exception:
                    pass
                self.stop.wait(4)
        threading.Thread(target=tick, daemon=True).start()

    def __exit__(self, *a):
        self.stop.set()


def model_name(key):
    m = MODELS[key]
    return f"{m['label']} ({m['kind']})"


def model_menu(chat):
    cur = chat_model[chat]
    text = "Current model: " + model_name(cur) + "\nPick a model (switching keeps the conversation):"
    buttons = [[{"text": ("• " if k == cur else "") + model_name(k), "callback_data": f"model:{k}"}]
               for k in MODELS]
    tg("sendMessage", chat_id=chat, text=text, reply_markup={"inline_keyboard": buttons})


def set_model(chat, key):
    if key not in MODELS:
        return f"Unknown model {key!r}. Options: {', '.join(MODELS)}"
    chat_model[chat] = key
    return f"Switched to {model_name(key)}."


def send_file(chat, data, name, caption="", method="sendPhoto", field="photo", mime="image/png"):
    boundary = uuid.uuid4().hex
    parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="chat_id"\r\n\r\n{chat}\r\n'.encode(),
             f'--{boundary}\r\nContent-Disposition: form-data; name="caption"\r\n\r\n{caption[:1000]}\r\n'.encode(),
             f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; filename="{name}"\r\n'
             f'Content-Type: {mime}\r\n\r\n'.encode() + data + b"\r\n",
             f"--{boundary}--\r\n".encode()]
    req = urllib.request.Request(f"{API}/{method}", b"".join(parts),
                                 {"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def send_photo(chat, png, caption=""):
    return send_file(chat, png, "chart.png", caption)


def send_document(chat, data, name, caption=""):
    return send_file(chat, data, name, caption, "sendDocument", "document", "application/octet-stream")


def how(chat, full):
    rec = audit_log.last_answer(chat)
    if not rec:
        send(chat, "Nothing to show yet: ask a question first.")
    elif full:
        send_document(chat, audit_log.how(rec, full=True).encode(), f"how-{rec['id']}.txt",
                      "Every step behind the last answer.")
    else:
        send(chat, audit_log.how(rec))


# Voice out (spoken replies and the Read aloud button) is off until voice in is solid.
VOICE_REPLIES = os.environ.get("VOICE_REPLIES", "0") == "1"
spoken = {}  # (chat, message_id) -> when it was read aloud
READ_ALOUD = {"inline_keyboard": [[{"text": "🔊 Read aloud", "callback_data": "say"}]]}
# What a badge sounds like in a voice reply; the full badge stays in the text.
SPOKEN_BADGE = {"✅": "This answer was checked independently.",
                "⚠️": "Careful: an independent check got a different answer.",
                "◻️": "This answer isn't verified."}


def send(chat, text, aloud=False):
    """Send text in Telegram-sized pieces; aloud=True puts a Read aloud button on the last."""
    chunks = [text[i:i + 4000] for i in range(0, len(text), 4000)] or [""]  # Telegram limit is 4096
    for i, c in enumerate(chunks):
        extra = {"reply_markup": READ_ALOUD} if aloud and VOICE_REPLIES and i == len(chunks) - 1 else {}
        tg("sendMessage", chat_id=chat, text=c, **extra)


def say(chat, text):
    """Read a reply aloud as a voice note. The badge line becomes a short spoken note."""
    body, note = [], ""
    for line in text.splitlines():
        mark = next((b for b in SPOKEN_BADGE if line.startswith(b)), None)
        if mark:
            note = SPOKEN_BADGE[mark]
        elif not line.startswith(("➖", "🎙️")):
            body.append(line.replace("/how", ""))
    send_file(chat, speech.speak("\n".join(body) + ("\n\n" + note if note else "")), "reply.ogg",
              method="sendVoice", field="voice", mime="audio/ogg")


def download(file_id):
    path = tg("getFile", file_id=file_id)["result"]["file_path"]
    with urllib.request.urlopen(f"{FILE_URL}/{path}", timeout=120) as r:
        return r.read()


def pdf_text(data):
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(data)
        f.flush()
        return subprocess.run(
            ["pdftotext", "-layout", f.name, "-"], capture_output=True, text=True, timeout=60
        ).stdout


class Unsupported(Exception):
    """Message can't be passed to the model; str(e) is sent back to the user."""


def sheet_text(data, name):
    """Render every sheet of an .xlsx/.xls as tab-separated text."""
    import openpyxl
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, os.path.basename(name))
        open(path, "wb").write(data)
        if name.lower().endswith(".xls"):  # legacy format: convert with LibreOffice
            subprocess.run(["soffice", "--headless", "--convert-to", "xlsx", "--outdir", d, path],
                           capture_output=True, timeout=120)
            path += "x"
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        out = []
        for ws in wb.worksheets:
            out.append(f"## Sheet: {ws.title}")
            for row in ws.iter_rows(values_only=True):
                if any(v is not None for v in row):
                    out.append("\t".join("" if v is None else str(v) for v in row))
        return "\n".join(out)


def preview(text, rows=8):
    """Header plus first rows of each sheet, so the model knows the columns."""
    out, n = [], 0
    for line in text.splitlines():
        if line.startswith("## Sheet:"):
            out.append(line)
            n = 0
        elif n < rows:
            out.append(line)
            n += 1
    return "\n".join(out)


def to_content(msg):
    """Turn a Telegram message into chat content; raises Unsupported."""
    caption = msg.get("caption") or msg.get("text") or ""
    if "photo" in msg:
        img = base64.b64encode(download(msg["photo"][-1]["file_id"])).decode()
        return [
            {"type": "text", "text": caption or "What's in this image?"},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img}"}},
        ]
    doc = msg.get("document")
    if doc:
        if doc.get("file_size", 0) > 20_000_000:
            raise Unsupported("Sorry, that file is over Telegram's 20MB bot download limit.")
        name, mime = doc.get("file_name", "file"), doc.get("mime_type", "")
        return file_content(msg["chat"]["id"], name, mime, download(doc["file_id"]), caption)
    if not caption:
        raise Unsupported("Sorry, I can read text and voice messages, photos, and PDF, Excel, PNG/JPG, TXT and MD files.")
    return caption


def file_content(chat, name, mime, data, caption):
    """Save an uploaded file to the chat's workdir and turn it into chat content."""
    harness.save_file(chat, name, data)
    if mime == "application/pdf" or name.lower().endswith(".pdf"):
        body = pdf_text(data).strip()
        if not body:
            raise Unsupported("I couldn't extract any text from that PDF (it may be scanned images).")
    elif name.lower().endswith((".xlsx", ".xls")):
        body = sheet_text(data, name).strip()
        if not body:
            raise Unsupported("That spreadsheet looks empty.")
        return (f"Attached file: {name} (saved at /data/{name}; use the python tool to compute "
                f"anything from it). Preview, first rows of each sheet:\n{preview(body)}\n\n"
                + (caption or "Summarize this spreadsheet."))
    elif name.lower().endswith((".txt", ".md", ".csv")):
        body = data.decode("utf-8", "replace")
    elif mime in ("image/png", "image/jpeg"):
        img = base64.b64encode(data).decode()
        return [
            {"type": "text", "text": caption or "What's in this image?"},
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{img}"}},
        ]
    else:
        raise Unsupported(f"Sorry, I can read PDF, Excel, PNG/JPG, TXT and MD files, not {name}.")
    note = "\n[truncated]" if len(body) > MAX_DOC_CHARS else ""
    return (f"Attached file: {name}\n<<<\n{body[:MAX_DOC_CHARS]}{note}\n>>>\n\n"
            + (caption or "Summarize this document."))


def allowed(user):
    if not ALLOWED:
        return True
    return str(user.get("id")) in ALLOWED or (user.get("username") or "").lower() in ALLOWED


def handle(msg):
    chat, user = msg["chat"]["id"], msg.get("from", {})
    who = f"{user.get('username') or user.get('first_name')}({user.get('id')})"
    if not allowed(user):
        print(f"denied {who}", flush=True)
        send(chat, "Sorry, this bot is private.")
        return
    text = msg.get("text") or ""
    if text.strip().lower().startswith("/model"):
        arg = text.split(maxsplit=1)[1:]
        if arg:
            send(chat, set_model(chat, arg[0].strip().lower()))
        else:
            model_menu(chat)
        return
    if text.strip().lower().startswith("/todos"):
        send(chat, todos.list_text(user.get("id")), aloud=True)
        return
    if text.strip().lower().startswith("/how"):
        how(chat, "full" in text.lower())
        return
    if text.strip().lower() in ("/reset", "/start"):
        history[chat].clear()
        harness.clear(chat)
        send(chat, "Hi! I'm Silo. Ask me anything, or send a PDF, Excel sheet, image, or text file. "
                   f"You're on {model_name(chat_model[chat])}; /model to switch, /reset to start over. "
                   "Every answer is checked independently and carries a badge; /how shows the steps behind it.")
        return
    voice = msg.get("voice") or msg.get("audio")
    heard = ""
    if voice:
        try:
            with typing(chat):
                hints = [r["text"] for r in todos.open_todos(user.get("id"))]
                heard = speech.transcribe(download(voice["file_id"]), hints)
        except Exception as e:
            print(f"transcribe error: {e!r}", flush=True)
            send(chat, "Sorry, I couldn't make out that voice note. Try again, or type it.")
            return
        if not heard:
            send(chat, "I couldn't hear any words in that voice note.")
            return
        print(f"<- {who}: [voice {voice.get('duration')}s] {heard}", flush=True)
        msg = {**msg, "text": heard}
        text = heard
        send(chat, f"🎙️ “{heard}”")  # at once, so a mishearing shows before the answer arrives
    prefix = ""
    if text and not msg.get("document") and "photo" not in msg:
        # Todos and reminders first: always the local model, never an external one.
        try:
            with typing(chat):
                done = todos.handle(chat, user.get("id"), text, MODELS["idli"])
        except Exception as e:
            print(f"todo error: {e!r}", flush=True)
            done = None
        if done:
            audit_log.append(chat, {"type": "todo", "chat": chat, "user": {"id": user.get("id")},
                                    "message": text, "voice": bool(voice), "calls": done["calls"],
                                    "reply": done["reply"]})
            history[chat].append({"role": "user", "content": text})
            history[chat].append({"role": "assistant", "content": done["reply"]})
            print(f"-> {who} [{done['kind']}]: {done['reply']}", flush=True)
            send(chat, prefix + done["reply"], aloud=not voice)
            if voice and VOICE_REPLIES:
                say(chat, done["reply"])
            return
    try:
        content = to_content(msg)
    except Unsupported as e:
        send(chat, str(e))
        return
    kind = "photo" if "photo" in msg else (msg.get("document") or {}).get("file_name", "")
    print(f"<- {who}: {('[' + kind + '] ') if kind else ''}{msg.get('caption') or text}", flush=True)
    send(chat, "⏳ Working on it. Every answer is computed and then checked independently, "
               "which usually takes 30–90 seconds.")
    with locks[chat]:
        history[chat].append({"role": "user", "content": content})
        try:
            with typing(chat):
                reply, badge, files = llm(chat, {"id": user.get("id"), "username": user.get("username")})
        except Exception as e:
            print(f"LLM error: {e}", flush=True)
            history[chat].pop()
            send(chat, str(e) if isinstance(e, Unsupported) else "Sorry, the model failed to respond. Try again.")
            return
        history[chat].append({"role": "assistant", "content": reply})
    print(f"-> {who} [{chat_model[chat]}]: {reply}\n   {badge}", flush=True)
    for name, data in files.items():
        try:
            if name.lower().endswith((".png", ".jpg", ".jpeg")):
                send_file(chat, data, name, name, mime="image/png" if name.lower().endswith("png") else "image/jpeg")
            else:
                send_document(chat, data, name)
        except Exception as e:
            print(f"file send error {name}: {e}", flush=True)
    body, specs, errors = charts.extract(reply)
    for spec in specs:
        try:
            send_photo(chat, charts.render(spec), spec.get("title", ""))
        except Exception as e:
            errors.append(str(e))
    if errors:
        print(f"chart errors: {errors}", flush=True)
        body += "\n\n(Couldn't draw a chart: " + "; ".join(errors) + ")"
    full = (body + "\n\n" if body else "") + badge + "  /how"
    send(chat, prefix + full, aloud=not voice)
    if voice and VOICE_REPLIES:
        say(chat, full)


def handle_callback(cb):
    chat, user = cb["message"]["chat"]["id"], cb.get("from", {})
    if not allowed(user):
        return
    if cb.get("data") == "say":
        key = (chat, cb["message"]["message_id"])
        repeat = time.time() - spoken.get(key, 0) < 120  # a second tap while the first is on its way
        tg("answerCallbackQuery", callback_query_id=cb["id"],
           text="Already sent, it may take a moment to arrive." if repeat else "Reading it aloud…")
        if not repeat:
            spoken[key] = time.time()
            t0 = time.time()
            say(chat, cb["message"].get("text", ""))
            print(f"read aloud {key[1]} in {time.time() - t0:.1f}s", flush=True)
        return
    key = cb.get("data", "").removeprefix("model:")
    result = set_model(chat, key)
    tg("answerCallbackQuery", callback_query_id=cb["id"], text=result)
    tg("editMessageText", chat_id=chat, message_id=cb["message"]["message_id"], text=result)


def safe_handle(update):
    try:
        if "callback_query" in update:
            handle_callback(update["callback_query"])
        elif "message" in update:
            handle(update["message"])
    except Exception as e:
        body = getattr(e, "read", lambda: b"")().decode()
        print(f"handle error: {e} {body}", flush=True)


def main():
    answer.cleanup_jobs()
    todos.start_loop(lambda chat, text: send(chat, text, aloud=True))
    print(f"tg bridge up default={model_name(DEFAULT_MODEL)} idli={MODELS['idli']['base']} "
          f"allowed={sorted(ALLOWED) or 'anyone'}", flush=True)
    tg("setMyCommands", commands=[
        {"command": "model", "description": "Switch model (idli internal / external)"},
        {"command": "todos", "description": "Your todo list (add, finish or get reminders by voice or text)"},
        {"command": "how", "description": "Show the steps behind the last answer (/how full: everything)"},
        {"command": "reset", "description": "Start a fresh conversation"},
    ])
    offset = 0
    while True:
        try:
            r = tg("getUpdates", offset=offset, timeout=50, allowed_updates=["message", "callback_query"])
        except Exception as e:
            print(f"poll error: {e}", flush=True)
            time.sleep(5)
            continue
        for u in r.get("result", []):
            offset = u["update_id"] + 1
            threading.Thread(target=safe_handle, args=(u,), daemon=True).start()


if __name__ == "__main__":
    main()
