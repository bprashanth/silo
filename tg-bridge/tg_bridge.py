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
import html
import json
import os
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from collections import defaultdict, deque

import answer
import audit_log
import charts
import drive
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
    action = "typing"

    def __init__(self, chat):
        self.chat, self.stop = chat, threading.Event()

    def __enter__(self):
        def tick():
            while not self.stop.is_set():
                try:
                    tg("sendChatAction", chat_id=self.chat, action=self.action)
                except Exception:
                    pass
                self.stop.wait(4)
        threading.Thread(target=tick, daemon=True).start()

    def __exit__(self, *a):
        self.stop.set()


class recording(typing):
    """The "recording voice..." indicator, while read-aloud audio is made."""
    action = "record_voice"


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


# Voice out. Audio is made only when someone taps 🔊 Read aloud on a reply (READ_ALOUD=1, the
# default). VOICE_REPLIES=1 would also speak every reply to a voice note unasked; it's off,
# because doing that for every message backed the box up.
READ_ALOUD = os.environ.get("READ_ALOUD", "1") == "1"
VOICE_REPLIES = os.environ.get("VOICE_REPLIES", "0") == "1"
spoken = {}  # (chat, message_id) -> when it was read aloud
speaking = set()  # chats with a read-aloud being made; one at a time per chat
# /voice choices: Kokoro voices. The Hindi ones read English with an Indian accent.
VOICES = {"af_heart": "Heart (US, woman)", "af_bella": "Bella (US, woman)", "am_michael": "Michael (US, man)",
          "bf_emma": "Emma (British, woman)", "bm_george": "George (British, man)",
          "hf_alpha": "Alpha (Indian, woman)", "hm_omega": "Omega (Indian, man)"}
chat_voice = {}  # chat -> Kokoro voice; default speech.VOICE
# The log holds who/what kind/how long, not what was said, unless LOG_CONTENT=1 (debugging):
# otherwise /reset couldn't erase it.
LOG_CONTENT = os.environ.get("LOG_CONTENT", "0") == "1"


def shown(text):
    return text if LOG_CONTENT else f"({len(text or '')} chars)"
READ_ALOUD_BUTTON = {"inline_keyboard": [[{"text": "🔊 Read aloud", "callback_data": "say"}]]}
# What a badge sounds like in a voice reply; the full badge stays in the text.
SPOKEN_BADGE = {"✅": "This answer was checked independently.",
                "⚠️": "Careful: an independent check got a different answer.",
                "◻️": "This answer isn't verified."}


def send(chat, text, aloud=False):
    """Send text in Telegram-sized pieces; aloud=True puts a Read aloud button on the last."""
    chunks = [text[i:i + 4000] for i in range(0, len(text), 4000)] or [""]  # Telegram limit is 4096
    for i, c in enumerate(chunks):
        extra = {"reply_markup": READ_ALOUD_BUTTON} if aloud and READ_ALOUD and i == len(chunks) - 1 else {}
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
    send_file(chat, speech.speak("\n".join(body) + ("\n\n" + note if note else ""), chat_voice.get(chat)), "reply.ogg",
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
    if text.strip().lower().startswith("/voice"):
        body, markup = voice_menu(chat)
        tg("sendMessage", chat_id=chat, text=body, reply_markup=markup)
        return
    if text.strip().lower().startswith("/drive"):
        drive_help(chat)
        return
    if text.strip().lower().startswith("/files"):
        arg = text.strip().split(maxsplit=1)
        body, markup = files_view(chat, arg[1] if len(arg) > 1 else "")
        tg("sendMessage", chat_id=chat, text=body, **({"reply_markup": markup} if markup else {}))
        return
    if text.strip().lower().startswith("/how"):
        how(chat, "full" in text.lower())
        return
    if text.strip().lower() == "/reset":
        tg("sendMessage", chat_id=chat, text=(
            "This erases everything I keep about you on this box: the conversation, your files, "
            "your todos and reminders, and the record of past answers and voice notes. It can't be undone."),
           reply_markup={"inline_keyboard": [[{"text": "Erase everything", "callback_data": "reset:yes"},
                                              {"text": "Cancel", "callback_data": "reset:no"}]]})
        return
    if text.strip().lower() == "/start":
        send(chat, "Hi! I'm Silo. Ask me anything, or send a PDF, Excel sheet, image, or text file. "
                   f"You're on {model_name(chat_model[chat])}; /todos for your list, /files for your files, /drive to add a Google Drive folder, /voice for the read-aloud voice, /model to switch, /reset to erase everything. "
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
        print(f"<- {who}: [voice {voice.get('duration')}s] {shown(heard)}", flush=True)
        msg = {**msg, "text": heard}
        text = heard
        send(chat, f"🎙️ “{heard}”")  # at once, so a mishearing shows before the answer arrives
    prefix = ""
    if text and drive_message(chat, user, text):
        return
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
            print(f"-> {who} [{done['kind']}]: {shown(done['reply'])}", flush=True)
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
    print(f"<- {who}: {('[file] ' if 'document' in msg else '[photo] ') if kind else ''}{shown(msg.get('caption') or text)}", flush=True)
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
    print(f"-> {who} [{chat_model[chat]}]: {shown(reply)} {badge.split(':')[0]}", flush=True)
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


DRIVE_NOTE = ("To copy it, sign in with Google. I'll download only this link: the folder, every "
              "folder inside it, and a list of where each file came from. Google's screen will say "
              "\"see and download all your Google Drive files\": that's the only read permission Google "
              "offers for an existing folder, but I copy just this link, once, and sign out straight after. "
              "Nothing that could read your Drive again is kept. The sign-in link works for 15 minutes.")


def drive_message(chat, user, text):
    """A Drive link starts a copy (service account) or a sign-in; a pasted Google redirect
    finishes a sign-in. True if handled."""
    got = drive.parse_redirect(text)
    if got:
        threading.Thread(target=drive_signed_in, args=got, daemon=True).start()
        return True
    link = drive.find_link(text)
    if not link:
        return False
    if drive.sa():
        send(chat, "📁 Copying that link: the folder and every folder inside it…")
        threading.Thread(target=drive_copy, args=(chat, user.get("id"), link[0]), daemon=True).start()
        return True
    if not drive.client():
        send(chat, "Google Drive isn't set up on this box yet, so I can't copy that link.")
        return True
    url = drive.sign_in_url(chat, user.get("id"), link[0])
    note = DRIVE_NOTE
    if not drive.REDIRECT.startswith("https://"):
        note += ("\n\nAfter you sign in, your browser will show a page that doesn't load. "
                 "That's expected: copy that page's address and paste it here.")
    tg("sendMessage", chat_id=chat, text="📁 " + note,
       reply_markup={"inline_keyboard": [[{"text": "Sign in with Google", "url": url}]]})
    print(f"drive sign-in started for {chat}", flush=True)
    return True


def drive_signed_in(state, code):
    """Finish a Google sign-in, copy the link, then revoke the token."""
    p = drive.pending.get(state)
    if not p:
        return
    try:
        p, token = drive.finish(state, code)
    except Exception as e:
        send(p["chat"], str(e) if isinstance(e, ValueError) else "Google didn't accept that sign-in. Send the link again.")
        return
    send(p["chat"], "Signed in. Copying now…")
    try:
        drive_copy(p["chat"], p["user"], p["file_id"], token)
    finally:
        drive.revoke(token)


def drive_copy(chat, user_id, file_id, token=None):
    """Copy the link into the chat's files: with a sign-in token, else as the service account."""
    t0 = time.time()
    try:
        with locks[chat]:
            s = drive.copy(token or drive.sa_token(), file_id, harness.workdir(chat),
                           progress=lambda m: send(chat, m))
        reply = drive.summary_text(s, signed_in=bool(token))
        history[chat].append({"role": "user", "content": f"(I shared the Google Drive {'folder' if s['is_folder'] else 'file'} "
                                                          f"“{s['name']}”; it is copied into the files.)"})
        history[chat].append({"role": "assistant", "content": reply})
        audit_log.append(chat, {"type": "drive", "chat": chat, "user": {"id": user_id}, "file_id": file_id,
                                "via": "sign-in" if token else "service account",
                                "summary": s, "seconds": round(time.time() - t0, 1)})
        print(f"drive copy {chat}: {s['files']} files {s['bytes']} bytes in {time.time() - t0:.0f}s", flush=True)
    except drive.NoAccess:
        reply = ("I couldn't open that link with your Google account: it may not be shared with you, or it "
                 "was deleted.") if token else (
                 "I can't see that link yet. In Google Drive, open its Share dialog and add\n"
                 f"{drive.sa_email()}\nas a Viewer (you can untick \"Notify people\"). Then send the link again.")
    except urllib.error.HTTPError as e:
        reply = f"The copy stopped partway: Google said {e.code}. Send the link again to retry."
    except Exception as e:
        print(f"drive copy {chat} failed: {e!r}", flush=True)
        reply = "Something went wrong copying that link. Send it again to retry."
    send(chat, reply)


def voice_menu(chat):
    """/voice: pick the voice that 🔊 Read aloud uses; picking one plays a short sample."""
    cur = chat_voice.get(chat, speech.VOICE)
    body = ("🔊 Pick the voice for Read aloud. Tapping one plays a short sample.\n"
            f"Now: {VOICES.get(cur, cur)}")
    buttons = [[{"text": ("• " if k == cur else "") + name, "callback_data": f"voice:{k}"}] for k, name in VOICES.items()]
    return body, {"inline_keyboard": buttons}


def drive_help(chat):
    """/drive: how to share a folder, then the email alone so it's easy to copy."""
    email = drive.sa_email()
    if not email:
        send(chat, "📁 Paste a Google Drive link and I'll ask you to sign in with Google to copy it."
             if drive.client() else "Google Drive isn't set up on this box yet.")
        return
    send(chat, "📁 To give me a Google Drive folder: in Drive, open the folder's Share dialog, add the "
               "email below as a Viewer (you can untick \"Notify people\"), then paste the folder's link "
               "here. I'll copy it, with every folder inside it, into your files (/files). "
               "To take access away, remove the email in the same Share dialog.")
    tg("sendMessage", chat_id=chat, text=f"<code>{html.escape(email)}</code>", parse_mode="HTML")


def files_view(chat, rel):
    """/files [folder]: what's in this chat's files, like ls. Folders get buttons to open them."""
    root = os.path.realpath(harness.workdir(chat))
    rel = rel.strip().strip("/")
    path = os.path.realpath(os.path.join(root, rel))
    if path != root and not path.startswith(root + os.sep):
        return "That folder isn't in your files.", None
    if not os.path.isdir(path):
        return f"There's no folder called “{rel}” in your files. /files shows the top level.", None
    rel = os.path.relpath(path, root) if path != root else ""
    dirs, files = [], []
    for e in sorted(os.scandir(path), key=lambda e: e.name.lower()):
        if e.is_symlink():
            continue
        (dirs if e.is_dir() else files).append(e)
    title = f"📂 {rel}/" if rel else "📂 Your files"
    lines = [f"📁 {d.name}/" for d in dirs] + [f"📄 {f.name}  ({size_text(f.stat().st_size)})" for f in files]
    if not lines:
        lines = ["(empty)" if rel else "(nothing yet: send me a file, or a Google Drive link)"]
    body = title + "\n" + "\n".join(lines)
    if len(body) > 4000:
        body = body[:3990] + "\n…"
    buttons = []
    for d in dirs:
        target = f"{rel}/{d.name}" if rel else d.name
        if len(f"files:{target}".encode()) <= 64:  # Telegram's limit on button data
            buttons.append([{"text": f"📁 {d.name}", "callback_data": f"files:{target}"}])
    if rel:
        up = os.path.dirname(rel)
        if len(f"files:{up}".encode()) <= 64:
            buttons.append([{"text": "⬆️ Up", "callback_data": f"files:{up}"}])
    return body, ({"inline_keyboard": buttons[:40]} if buttons else None)


def size_text(n):
    for unit in ("bytes", "KB", "MB", "GB"):
        if n < 1000 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "bytes" else f"{n:.1f} {unit}"
        n /= 1000


def erase(chat, user):
    """/reset: everything the box keeps for this chat and user. Voice notes are never written
    to disk (they're transcribed in memory), so their transcripts in history and the audit
    records are what's left of them."""
    with locks[chat]:
        history[chat].clear()
        harness.clear(chat)
        todos.erase(user)
        audit_log.erase(chat)
        for k in [k for k in spoken if k[0] == chat]:
            del spoken[k]
        chat_voice.pop(chat, None)


def handle_callback(cb):
    chat, user = cb["message"]["chat"]["id"], cb.get("from", {})
    if not allowed(user):
        return
    if cb.get("data", "").startswith("reset:"):
        if cb["data"] == "reset:yes":
            erase(chat, user.get("id"))
            result = ("Erased. Your conversation, files, todos, reminders and answer records are gone "
                      "from this box. (Telegram keeps its own copy of this chat; you can clear it in Telegram.)")
            print(f"reset {chat}", flush=True)
        else:
            result = "Cancelled; nothing was erased."
        tg("answerCallbackQuery", callback_query_id=cb["id"])
        tg("editMessageText", chat_id=chat, message_id=cb["message"]["message_id"], text=result)
        return
    if cb.get("data", "").startswith("files:"):
        body, markup = files_view(chat, cb["data"].removeprefix("files:"))
        tg("answerCallbackQuery", callback_query_id=cb["id"])
        tg("editMessageText", chat_id=chat, message_id=cb["message"]["message_id"], text=body,
           **({"reply_markup": markup} if markup else {}))
        return
    if cb.get("data") == "say":
        key = (chat, cb["message"]["message_id"])
        if time.time() - spoken.get(key, 0) < 120:  # a second tap while the first is on its way
            tg("answerCallbackQuery", callback_query_id=cb["id"], text="Already sent, it may take a moment to arrive.")
            return
        if chat in speaking:
            tg("answerCallbackQuery", callback_query_id=cb["id"],
               text="Still making the last one. Tap again once it arrives.")
            return
        speaking.add(chat)
        spoken[key] = time.time()
        tg("answerCallbackQuery", callback_query_id=cb["id"], text="Making the audio…")
        t0 = time.time()
        try:
            with recording(chat):
                say(chat, cb["message"].get("text", ""))
            print(f"read aloud {key[1]} voice={chat_voice.get(chat, speech.VOICE)} in {time.time() - t0:.1f}s", flush=True)
        except Exception as e:
            spoken.pop(key, None)
            print(f"read aloud failed: {e!r}", flush=True)
            send(chat, "I couldn't make the audio for that one. Try again in a moment.")
        finally:
            speaking.discard(chat)
        return
    if cb.get("data", "").startswith("voice:"):
        v = cb["data"].removeprefix("voice:")
        if v not in VOICES:
            tg("answerCallbackQuery", callback_query_id=cb["id"])
            return
        chat_voice[chat] = v
        tg("answerCallbackQuery", callback_query_id=cb["id"], text=f"Voice: {VOICES[v]}")
        body, markup = voice_menu(chat)
        tg("editMessageText", chat_id=chat, message_id=cb["message"]["message_id"], text=body, reply_markup=markup)
        if chat not in speaking:
            speaking.add(chat)
            try:
                with recording(chat):
                    say(chat, f"Hi, this is {VOICES[v].split(' (')[0]}. Your todo list has 3 items, and the "
                              "Gadchiroli programme spent ₹4,52,300 this quarter.")
            except Exception as e:
                print(f"voice sample failed: {e!r}", flush=True)
            finally:
                speaking.discard(chat)
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
    if drive.client() and drive.REDIRECT.startswith("https://"):
        drive.serve(drive_signed_in)
    todos.start_loop(lambda chat, text: send(chat, text, aloud=True))
    print(f"tg bridge up default={model_name(DEFAULT_MODEL)} idli={MODELS['idli']['base']} "
          f"allowed={sorted(ALLOWED) or 'anyone'}", flush=True)
    tg("setMyCommands", commands=[
        {"command": "todos", "description": "Your todo list"},
        {"command": "files", "description": "Your files"},
        {"command": "drive", "description": "Add a Google Drive folder"},
        {"command": "voice", "description": "Read-aloud voice"},
        {"command": "model", "description": "Switch model"},
        {"command": "how", "description": "How the last answer was made"},
        {"command": "reset", "description": "Erase everything"},
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
