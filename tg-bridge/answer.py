"""Answer a message with io's Codex and check it with the bridge's own harness.

proposals/correctness-receipt.md, with Codex as the answerer (the harness-compare winner)
and the python-tool harness as the independent checker. Both start together on the same
files and history; the checker never sees Codex's answer. Once Codex is done the reply
waits at most CHECK_GRACE seconds more for the checker, then goes out with a badge:

  ✅ verified     both ended with the same ANSWER value
  ⚠️ disagrees   they ended with different values; both are shown
  ◻️ unverified  the check was late or failed, the answer was 0, or the answer
                  doesn't appear in any output the answerer computed
  ➖ nothing to check   no single figure or name in the reply

Every reply, whatever its path, gets an audit record (audit_log.py) for /how.
"""
import concurrent.futures as cf
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import urllib.request

import audit_log
import codex_engine
import harness
import receipt

HERE = os.path.dirname(os.path.abspath(__file__))
GRACE = float(os.environ.get("CHECK_GRACE", "30"))
CHECK_EFFORT = os.environ.get("CHECK_REASONING", "low")  # llama.cpp honours reasoning_effort for Muse
JOB_ROOT = os.path.expanduser(os.environ.get("CODEX_ROOT", "~/.local/share/idli-bridge/codex"))
POOL = cf.ThreadPoolExecutor(16)
ANSWER_TAIL = """
If the message asks for a specific figure or name that comes from the data (a total, a
count, a ratio, the biggest category...), end your reply with one final line
`ANSWER: <value>`: a plain number without commas or units, or the exact name. If there is
no single such value (a summary, a chart, a greeting), end with `ANSWER: none`."""
SEND_EXT = (".png", ".jpg", ".jpeg", ".html", ".pdf", ".xlsx", ".csv", ".docx", ".pptx")


def git_version():
    try:
        return subprocess.check_output(["git", "-C", HERE, "describe", "--always", "--dirty"],
                                       text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


SILO_VERSION = git_version()


# ---- ANSWER lines and agreement ---------------------------------------------------------

ANSWER_LINE = re.compile(r"^[ \t>*_`]*ANSWER:[ \t]*(.*)$", re.M | re.I)


def split_answer(text):
    """(text without ANSWER lines, value or None). 'none' and empty count as None."""
    text = text or ""
    vals = ANSWER_LINE.findall(text)
    body = ANSWER_LINE.sub("", text).rstrip()
    if not vals:
        return body, None
    v = vals[-1].strip().strip("*_`'\" ").rstrip(".").strip()
    return body, (None if v.lower() in ("", "none", "n/a", "na", "null") else v)


def agree(a, b):
    """Same value at the precision either side wrote it: 480 vs 481 differ (a count is
    exact), 79.6 vs 79.61 agree, 190.8 lakh vs 19080600 agree. Names: case and spacing."""
    x, y = receipt.numbers(a), receipt.numbers(b)
    if x and y:
        (vx, hx), (vy, hy) = x[0], y[0]
        # 0.796 and 79.6: the same ratio, one written as a percentage
        return any(abs(vx * f - vy * g) <= max(hx * f, hy * g) + 1e-9 for f, g in ((1, 1), (100, 1), (1, 100)))
    return " ".join(a.lower().split()) == " ".join(b.lower().split())


def badge(primary, checker, status):
    """(kind, text) for a reply, from the two runs and the checker's status."""
    pa = primary.get("answer")
    if status == "fallback":
        return "unverified", "◻️ Unverified: the main answerer failed, so this is the checker's answer, unchecked."
    if pa is None:
        return "none", "➖ Nothing to check: no single figure or name in this reply."
    if status == "late":
        return "unverified", f"◻️ Unverified: the independent check didn't finish within {GRACE:.0f} s of the answer."
    ca = (checker or {}).get("answer")
    if ca is None:
        return "unverified", "◻️ Unverified: the independent check didn't reach an answer."
    if not agree(pa, ca):
        return "disagree", (f"⚠️ Check disagrees: an independent computation got {ca}, not {pa}. "
                            "Treat this answer with care.")
    if receipt.to_number(pa) == 0:
        return "unverified", "◻️ Unverified: both got 0, which often means a filter matched nothing."
    if not primary.get("receipt", {}).get("answer_traced", True):
        return "unverified", "◻️ Unverified: the answer doesn't appear in anything the answerer computed."
    return "verified", f"✅ Verified: an independent second computation also got {ca}."


# ---- the two runs -----------------------------------------------------------------------

def as_text(content):
    """Chat content (a string or OpenAI parts) as plain text; pictures become a marker."""
    if isinstance(content, str):
        return content
    return "\n".join(p.get("text", "") if p.get("type") == "text" else "[picture]" for p in content)


def codex_prompt(history, files):
    """Codex gets no system prompt from us (io's AGENTS.md is its system), so the chat and
    the file names go in the prompt. Spreadsheet previews say /data/<name>; for Codex
    the files are in its working folder."""
    turns = [(m["role"], as_text(m["content"]).replace("/data/", "./")) for m in history]
    *before, (_, now) = turns
    out = ["You're answering a message sent over Telegram by someone at a non-profit.",
           "Their files are in the current folder: " + (", ".join(files) or "(none)") + ".",
           "Files you save in this folder (charts as PNG, reports as HTML) are sent to them.",
           "Keep the reply short; it is read on a phone."]
    if before:
        out += ["", "The conversation so far:"]
        out += [f"{'Them' if r == 'user' else 'You'}: {t}" for r, t in before]
    out += ["", "Their message:", now, ANSWER_TAIL]
    return "\n".join(out)


def run_codex(chat, history, job):
    t0 = time.time()
    files = [os.path.join(harness.workdir(chat), f) for f in harness.files(chat)]
    try:
        r = codex_engine.run(files, codex_prompt(history, harness.files(chat)), os.path.join(JOB_ROOT, job))
    except Exception as e:  # io missing, node missing...: the checker's answer stands in
        r = {"text": "", "finish": f"error: {e!r}", "actions": [], "usage": {}, "new_files": {}}
    r["engine"] = "io Codex " + r.get("codex_version", "")
    r["seconds"] = round(time.time() - t0, 1)
    return r


def run_simple(chat, history, system, model, effort=None):
    """The bridge's python-tool harness. effort sets reasoning_effort (the checker uses low)."""
    t0 = time.time()
    usage = {"input": 0, "output": 0}

    def call(messages, tools):
        body = {"model": model["model"], "messages": messages, **({"tools": tools} if tools else {}),
                **({"reasoning_effort": effort} if effort else {})}
        req = urllib.request.Request(f"{model['base']}/chat/completions", json.dumps(body).encode(),
                                     {"Content-Type": "application/json",
                                      "Authorization": f"Bearer {model['key']}"})
        with urllib.request.urlopen(req, timeout=1800) as resp:
            r = json.load(resp)
        u = r.get("usage") or {}
        usage["input"] += u.get("prompt_tokens", 0)
        usage["output"] += u.get("completion_tokens", 0)
        return r["choices"][0]

    sys_msg = {"role": "system",
               "content": system + harness.SYSTEM_HINT.format(files=", ".join(harness.files(chat)) or "(none yet)")}
    try:
        text, steps, finish = harness.chat_loop(chat, [sys_msg, *history], call, log=lambda *_: None)
    except Exception as e:
        text, steps, finish = "", [], f"error: {e!r}"
    return {"engine": "bridge harness" + (f" (reasoning {effort})" if effort else ""), "text": text,
            "finish": finish, "actions": harness.actions(steps), "usage": usage,
            "seconds": round(time.time() - t0, 1), "workspace": "/data"}


def finish_run(run, question):
    """Split off the ANSWER line, trace it, flag the actions; trim for the record."""
    if run is None:
        return None
    run["text"], run["answer"] = split_answer(run["text"])
    outs = [a.get("output", "") for a in run["actions"]]
    tail = f"\nANSWER: {run['answer']}" if run["answer"] else ""
    run["receipt"] = receipt.check(run["text"] + tail, outs, ignore=question)
    run["flags"] = receipt.audit("codex" if run["engine"].startswith("io") else "simple",
                                 run["actions"], run.get("workspace", ""))
    rec = {k: v for k, v in run.items() if k not in ("new_files", "workspace", "stderr_tail")}
    rec["actions"] = audit_log.trim_actions(run["actions"])
    return rec


# ---- one reply --------------------------------------------------------------------------

def respond(chat, user, history, system, model, model_key):
    """history ends with the user's new message. Returns (reply_text, badge_text, files)
    where files is {name: bytes} to send back (Codex's charts and reports)."""
    current = history[-1]["content"]
    question = as_text(current)
    job = f"{chat}-{int(time.time() * 1000)}"
    status, new_files = "done", {}
    local = model["kind"] != "external"
    has_picture = not isinstance(current, str)

    if not local or has_picture:
        # One run, no check: an external model (the user chose to send data out), or a
        # picture, which Codex here can't see.
        primary, checker = run_simple(chat, history, system, model), None
        status = "skipped"
        kind, text = "none", ("➖ Not checked: you picked an external model, so this went to "
                              f"{model['label']} via OpenRouter." if not local
                              else "➖ Not checked: pictures are answered without a second check for now.")
        primary = finish_run(primary, question)
    else:
        fc = POOL.submit(run_codex, chat, history, job)
        fk = POOL.submit(run_simple, chat, history, system + ANSWER_TAIL, model, CHECK_EFFORT)
        primary = fc.result()
        new_files = primary.pop("new_files", {})
        if not primary["text"].strip():
            status, checker = "fallback", fk.result()
            primary, checker = checker, None
            primary["engine"] += " (fallback: Codex failed)"
        else:
            try:
                checker = fk.result(timeout=GRACE)
            except cf.TimeoutError:
                status, checker = "late", None
        primary, checker = finish_run(primary, question), finish_run(checker, question)
        kind, text = badge(primary, checker, status)

    rec = audit_log.append(chat, {
        "type": "answer", "chat": chat, "user": user, "message": asked(question),
        "files": [{"name": os.path.relpath(p, harness.workdir(chat)), "bytes": os.path.getsize(p),
                   "sha256": file_hash(p)} for p in all_files(harness.workdir(chat))],
        "model": {"key": model_key, "label": model["label"], "kind": model["kind"],
                  "base": model["base"], "model": model["model"]},
        "versions": {"silo": SILO_VERSION, "codex": (primary or {}).get("codex_version")},
        "primary": primary, "checker": checker, "checker_status": status,
        "badge": {"kind": kind, "text": text}, "sent_files": sorted(new_files)})
    if status == "late":
        fk.add_done_callback(lambda f: late_check(chat, rec["id"], f, question))
    reply = primary["text"] if primary else ""
    pa = (primary or {}).get("answer")
    if pa and not mentions(reply, pa):  # the value was only on the stripped ANSWER line
        reply = (reply + "\n\n" if reply else "") + f"Answer: {pa}"
    sendable = {n: d for n, d in new_files.items()
                if n.lower().endswith((".png", ".jpg", ".jpeg")) or
                (n.lower().endswith(SEND_EXT) and n in reply)}
    return reply, text, sendable


def mentions(text, value):
    """Does the reply already state this value (as a number at its precision, or as a name)?"""
    if receipt.numbers(value):
        return any(agree(f"{v}", value) for v, _ in receipt.numbers(text))
    return value.lower() in (text or "").lower()


def asked(text):
    """What the person typed: a file upload's text ends with their caption."""
    return text.rsplit("\n\n", 1)[-1] if text.startswith("Attached file:") else text


def late_check(chat, of, fut, question):
    try:
        checker = finish_run(fut.result(), question)
        audit_log.append(chat, {"type": "late_check", "of": of, "checker": checker})
    except Exception as e:
        print(f"late check failed: {e!r}", flush=True)


def all_files(root):
    """Every file under root, folders (Drive copies) included."""
    return sorted(os.path.join(d, f) for d, _, fs in os.walk(root) for f in fs)


_hash_cache = {}


def file_hash(path):
    st = os.stat(path)
    key = (path, st.st_size, st.st_mtime)
    if key not in _hash_cache:
        with open(path, "rb") as f:
            _hash_cache[key] = hashlib.sha256(f.read()).hexdigest()
    return _hash_cache[key]


def cleanup_jobs(max_age=86400):
    """Remove Codex job folders left behind by a crash."""
    now = time.time()
    for d in os.listdir(JOB_ROOT) if os.path.isdir(JOB_ROOT) else []:
        p = os.path.join(JOB_ROOT, d)
        if now - os.path.getmtime(p) > max_age:
            shutil.rmtree(p, ignore_errors=True)
