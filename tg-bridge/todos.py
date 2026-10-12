"""Personal todos and reminders, kept on the box.

A message (typed, or a transcribed voice note) goes through one call to the local model
with todo tools. Small talk is answered in the same call, so "thanks" doesn't wait for Codex. The model only picks the operations ("add this", "mark 1 and 2 done",
"remind me at 6"); the bot executes them and writes the confirmation itself, so what
you read is the stored list, not the model's prose. If the model calls not_about_todos,
handle() returns None and the message goes on to the data path (answer.py).

A background loop sends each user their open todos every morning (09:00 IST unless they
change it) and fires one-off reminders.

Env: SILO_DB (default ~/.local/share/idli-bridge/silo.db), TODO_DAILY (default 09:00).
"""
import datetime
import json
import os
import re
import sqlite3
import threading
import time
import urllib.error
import urllib.request

IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30), "IST")
DB = os.path.expanduser(os.environ.get("SILO_DB", "~/.local/share/idli-bridge/silo.db"))
DAILY = os.environ.get("TODO_DAILY", "09:00")
_lock = threading.Lock()


def db():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    c = sqlite3.connect(DB, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.executescript("""
    CREATE TABLE IF NOT EXISTS todos (id INTEGER PRIMARY KEY, user TEXT, text TEXT,
        created TEXT, done TEXT, deleted TEXT);
    CREATE TABLE IF NOT EXISTS users (user TEXT PRIMARY KEY, chat INTEGER, daily TEXT, last_daily TEXT);
    CREATE TABLE IF NOT EXISTS reminders (id INTEGER PRIMARY KEY, user TEXT, chat INTEGER,
        due TEXT, what TEXT, sent TEXT);
    """)
    return c


CONN = db()


def now():
    return datetime.datetime.now(IST)


def q(sql, *args):
    with _lock:
        cur = CONN.execute(sql, args)
        CONN.commit()
        return cur.fetchall()


def open_todos(user):
    """Open todos, oldest first; their 1-based position is the number the user sees."""
    return q("SELECT * FROM todos WHERE user=? AND done IS NULL AND deleted IS NULL ORDER BY id", str(user))


def touch_user(user, chat):
    # A new user's first morning list is tomorrow's if today's time has already passed.
    t = now()
    first = t.date().isoformat() if t.strftime("%H:%M") >= DAILY else None
    q("INSERT INTO users(user, chat, daily, last_daily) VALUES(?,?,?,?) "
      "ON CONFLICT(user) DO UPDATE SET chat=excluded.chat", str(user), chat, DAILY, first)
    return q("SELECT * FROM users WHERE user=?", str(user))[0]


def numbered(rows):
    return "\n".join(f"{i}. {r['text']}" for i, r in enumerate(rows, 1)) or "(nothing open)"


def _words(text):
    return set(re.findall(r"\w+", text.lower())) - {"the", "a", "an", "to", "my", "me", "for", "of", "and", "with"}


def same_todo(user, text):
    """The open todo that says the same thing as text (same words, or one's words contain the other's)."""
    w = _words(text)
    for r in open_todos(user):
        o = _words(r["text"])
        if w and o and (w <= o or o <= w):
            return r
    return None


def list_text(user, title="Your todos:"):
    rows = open_todos(user)
    return f"{title}\n{numbered(rows)}" if rows else "You have no open todos."


def erase(user):
    """Delete everything stored for this user: todos, reminders, settings."""
    for t in ("todos", "reminders", "users"):
        q(f"DELETE FROM {t} WHERE user=?", str(user))
    with _lock:
        CONN.execute("VACUUM")  # so deleted rows don't linger in the file


# ---- the model call -----------------------------------------------------------------------

def fn(name, desc, props=None, required=()):
    return {"type": "function", "function": {"name": name, "description": desc, "parameters": {
        "type": "object", "properties": props or {}, "required": list(required)}}}


NUMS = {"type": "array", "items": {"type": "integer"}, "description": "todo numbers from the list"}
TOOLS = [
    fn("add_todos", "Add new todos. Write each as a short imperative task in the user's words, "
       "keeping names and details (who, what, which tracker).",
       {"items": {"type": "array", "items": {"type": "string"}}}, ["items"]),
    fn("complete_todos", "Mark todos done: the user did them, or says they already did. "
       "Match a description to the closest open todo.", {"numbers": NUMS}, ["numbers"]),
    fn("delete_todos", "Remove todos that are no longer needed (not done, just dropped).",
       {"numbers": NUMS}, ["numbers"]),
    fn("edit_todo", "Change the wording of one todo.",
       {"number": {"type": "integer"}, "text": {"type": "string"}}, ["number", "text"]),
    fn("show_todos", "The user wants to see their todo list."),
    fn("remind_at", "Send the user a reminder at a time (IST).",
       {"date": {"type": "string", "description": "YYYY-MM-DD"},
        "time": {"type": "string", "description": "HH:MM, 24-hour"},
        "what": {"type": "string", "description": "what to remind about; empty means their todo list"}},
       ["date", "time"]),
    fn("set_daily_time", "Change when the daily todo list is sent each morning (IST).",
       {"time": {"type": "string", "description": "HH:MM, 24-hour"}}, ["time"]),
    fn("cancel_reminders", "Cancel all pending one-off reminders."),
    fn("small_talk", "Greetings, thanks, acknowledgements or chit-chat that need no data, files or "
       "facts: reply briefly and warmly yourself.", {"reply": {"type": "string"}}, ["reply"]),
    fn("not_about_todos", "Anything else: a question, a request about files or data, a task, "
       "anything that needs facts or work."),
]

SYSTEM = """You manage a personal todo list and reminders for someone at an Indian non-profit.
Their message may be a transcribed voice note, so expect small transcription slips in names.
Call the tools that carry out what they ask; several calls are fine ("add X and remind me at 6").
If it is only small talk (hi, thanks, ok), call small_talk. Otherwise, if it is not about their
todos or reminders, call not_about_todos and nothing else.

Now: {now} (IST, Asia/Kolkata). Times are IST. A bare hour without am/pm: 1-7 means pm
(6 -> 18:00), 8-11 means am, 12 means noon. If that time has already passed today, use tomorrow.
"Tomorrow morning" with no time means 09:00.

Their open todos (number. text):
{todos}

Daily list time: {daily}. Pending reminders: {reminders}"""


def call_model(model, messages):
    body = {"model": model["model"], "messages": messages, "tools": TOOLS, "tool_choice": "required",
            "reasoning_effort": "low"}
    req = urllib.request.Request(f"{model['base']}/chat/completions", json.dumps(body).encode(),
                                 {"Content-Type": "application/json", "Authorization": f"Bearer {model['key']}"})
    for i in range(3):  # llama.cpp 500s on a malformed tool call; a resample fixes it
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                return json.load(r)["choices"][0]["message"]
        except urllib.error.HTTPError as e:
            if e.code != 500 or i == 2:
                raise


def parse_when(date, hhmm):
    d = datetime.date.fromisoformat(date)
    h, m = (int(x) for x in hhmm.split(":")[:2])
    when = datetime.datetime(d.year, d.month, d.day, h, m, tzinfo=IST)
    while when < now() - datetime.timedelta(minutes=1):  # "at 6" said at 7pm means tomorrow
        when += datetime.timedelta(days=1)
    return when


def say_when(when):
    day = when.date() - now().date()
    label = {0: "today", 1: "tomorrow"}.get(day.days, when.strftime("%a %d %b"))
    return f"{label} at {when.strftime('%I:%M %p').lstrip('0').lower()} IST"


def handle(chat, user, text, model):
    """Todo operations for this message, or None if it isn't about todos.
    Returns {"reply": str, "calls": [...]} for the audit record."""
    u = touch_user(user, chat)
    rows = open_todos(user)
    pending = q("SELECT * FROM reminders WHERE user=? AND sent IS NULL ORDER BY due", str(user))
    system = SYSTEM.format(now=now().strftime("%A %d %B %Y, %H:%M"), todos=numbered(rows), daily=u["daily"],
                           reminders=", ".join(f"{r['due'][:16]} {r['what'] or 'todo list'}" for r in pending) or "none")
    msg = call_model(model, [{"role": "system", "content": system}, {"role": "user", "content": text}])
    calls = []
    for tc in msg.get("tool_calls") or []:
        try:
            calls.append((tc["function"]["name"], json.loads(tc["function"]["arguments"] or "{}")))
        except json.JSONDecodeError:
            pass
    if not calls or any(n == "not_about_todos" for n, _ in calls):
        return None
    chat_reply = next((a.get("reply") for n, a in calls if n == "small_talk" and a.get("reply")), None)
    if chat_reply and all(n == "small_talk" for n, _ in calls):
        return {"reply": chat_reply.strip(), "calls": [{"name": n, "args": a} for n, a in calls], "kind": "chat"}

    def pick(nums):
        return [rows[n - 1] for n in dict.fromkeys(nums or []) if isinstance(n, int) and 1 <= n <= len(rows)]

    out, show = [], False
    stamp = now().isoformat(timespec="seconds")
    # Adds first, so a reminder for something added in the same message isn't added twice.
    for name, a in sorted(calls, key=lambda c: c[0] != "add_todos"):
        if name == "add_todos":
            items = [i.strip() for i in a.get("items") or [] if i and i.strip()]
            for i in items:
                q("INSERT INTO todos(user, text, created) VALUES(?,?,?)", str(user), i, stamp)
            out += [f"➕ Added: {i}" for i in items]
            show = True
        elif name in ("complete_todos", "delete_todos"):
            col, mark = ("done", "✔️ Done") if name == "complete_todos" else ("deleted", "🗑️ Removed")
            for r in pick(a.get("numbers")):
                q(f"UPDATE todos SET {col}=? WHERE id=?", stamp, r["id"])
                out.append(f"{mark}: {r['text']}")
            show = True
        elif name == "edit_todo":
            r = pick([a.get("number")])
            if r and a.get("text"):
                q("UPDATE todos SET text=? WHERE id=?", a["text"].strip(), r[0]["id"])
                out.append(f"✏️ Changed: {r[0]['text']} → {a['text'].strip()}")
                show = True
        elif name == "show_todos":
            show = True
        elif name == "remind_at":
            try:
                when = parse_when(a["date"], a["time"])
            except (KeyError, ValueError):
                out.append("I couldn't work out the time for that reminder. Try \"remind me at 6 pm\".")
                continue
            what = (a.get("what") or "").strip()
            q("INSERT INTO reminders(user, chat, due, what) VALUES(?,?,?,?)", str(user), chat,
              when.isoformat(timespec="minutes"), what)
            out.append(f"⏰ I'll remind you {say_when(when)}" + (f": {what}" if what else " with your todo list") + ".")
            # A reminder about something is also a todo, unless the list already has it.
            if what and not same_todo(user, what):
                q("INSERT INTO todos(user, text, created) VALUES(?,?,?)", str(user), what, stamp)
                out.append(f"➕ Added: {what}")
                show = True
        elif name == "set_daily_time":
            try:
                h, m = (int(x) for x in a["time"].split(":")[:2])
                t = f"{h:02d}:{m:02d}"
                q("UPDATE users SET daily=? WHERE user=?", t, str(user))
                out.append(f"🌅 I'll send your todo list every day at {t} IST.")
            except (KeyError, ValueError):
                out.append("I couldn't work out that time.")
        elif name == "cancel_reminders":
            q("UPDATE reminders SET sent='cancelled' WHERE user=? AND sent IS NULL", str(user))
            out.append("Cancelled your pending reminders.")
    if show or not out:
        out.append("\n" + list_text(user))
    return {"reply": "\n".join(out).strip(), "calls": [{"name": n, "args": a} for n, a in calls], "kind": "todo"}


# ---- morning list and reminders ------------------------------------------------------------

def due_messages():
    """[(chat, text)] to send now: daily lists and one-off reminders. Marks them sent."""
    t = now()
    out = []
    for u in q("SELECT * FROM users"):
        today = t.date().isoformat()
        if u["last_daily"] != today and t.strftime("%H:%M") >= (u["daily"] or DAILY):
            q("UPDATE users SET last_daily=? WHERE user=?", today, u["user"])
            if open_todos(u["user"]):
                out.append((u["chat"], list_text(u["user"], "☀️ Good morning! Your todos for today:")
                            + "\n\nTell me when you've done any, by voice or text (\"I did 1 and 3\")."))
    for r in q("SELECT * FROM reminders WHERE sent IS NULL AND due <= ?", t.isoformat(timespec="minutes")):
        q("UPDATE reminders SET sent=? WHERE id=?", t.isoformat(timespec="seconds"), r["id"])
        if r["what"]:
            text = f"⏰ Reminder: {r['what']}"
            if same_todo(r["user"], r["what"]):
                text += "\n\nIt's on your todo list; tell me when it's done."
        else:
            text = list_text(r["user"], "⏰ Reminder, your todos:")
        out.append((r["chat"], text))
    return out


def start_loop(send, every=30):
    """Check for due messages every `every` seconds; send(chat, text) delivers one."""
    def loop():
        while True:
            try:
                for chat, text in due_messages():
                    send(chat, text)
            except Exception as e:
                print(f"todo loop error: {e!r}", flush=True)
            time.sleep(every)
    threading.Thread(target=loop, daemon=True).start()
