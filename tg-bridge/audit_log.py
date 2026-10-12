"""The audit record behind every answer (proposals/audit-checker.md).

One JSON line per event in $AUDIT_ROOT/<chat>/<YYYY-MM-DD>.jsonl. Each line carries the
sha256 of the line before it in that chat (across days), so editing or deleting a line
breaks the chain: tamper-evident, not tamper-proof. `python audit_log.py verify <chat>`
checks a chain.

Events: "answer" (one per reply) and "late_check" (the checker finished after the reply
went out; its result is recorded but the badge already sent is not changed).
"""
import datetime
import glob
import hashlib
import json
import os
import sys
import threading
import uuid

ROOT = os.path.expanduser(os.environ.get("AUDIT_ROOT", "~/.local/share/idli-bridge/audit"))
MAX_IN, MAX_OUT = 8000, 4000
_lock = threading.Lock()


def sha256(data):
    return hashlib.sha256(data if isinstance(data, bytes) else data.encode()).hexdigest()


def trim_actions(actions):
    """Keep each action's code and a bounded output, plus the hash of the full output."""
    out = []
    for a in actions:
        o = a.get("output") or ""
        out.append({**a, "input": (a.get("input") or "")[:MAX_IN], "output": o[:MAX_OUT],
                    "output_chars": len(o), "output_sha256": sha256(o)})
    return out


def _files(chat):
    return sorted(glob.glob(os.path.join(ROOT, str(chat), "*.jsonl")))


def _last_hash(chat):
    for path in reversed(_files(chat)):
        lines = open(path).read().splitlines()
        if lines:
            return json.loads(lines[-1])["hash"]
    return None


def append(chat, rec):
    """Add id, time, prev and hash to rec, write it, and return it."""
    with _lock:
        rec = {"id": rec.get("id") or uuid.uuid4().hex[:12],
               "ts": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
               **rec, "prev": _last_hash(chat)}
        rec["hash"] = sha256(json.dumps(rec, sort_keys=True, default=str))
        d = os.path.join(ROOT, str(chat))
        os.makedirs(d, mode=0o700, exist_ok=True)
        with open(os.path.join(d, rec["ts"][:10] + ".jsonl"), "a") as f:
            f.write(json.dumps(rec, default=str) + "\n")
        return rec


def erase(chat):
    """Delete this chat's records (on /reset). The chain starts again from nothing."""
    import shutil
    with _lock:
        shutil.rmtree(os.path.join(ROOT, str(chat)), ignore_errors=True)


def records(chat):
    return [json.loads(l) for p in _files(chat) for l in open(p) if l.strip()]


def last_answer(chat):
    """The latest answer or todo record, with any late check folded in as rec["late_check"]."""
    ans, late = None, {}
    for r in records(chat):
        if r["type"] in ("answer", "todo"):
            ans = r
        elif r["type"] == "late_check":
            late[r["of"]] = r
    if ans and ans["id"] in late:
        ans["late_check"] = late[ans["id"]]
    return ans


def verify(chat):
    """(ok, n, first bad line index or None)."""
    prev = None
    rs = records(chat)
    for i, r in enumerate(rs):
        body = {k: v for k, v in r.items() if k != "hash"}
        if r["prev"] != prev or sha256(json.dumps(body, sort_keys=True, default=str)) != r["hash"]:
            return False, len(rs), i
        prev = r["hash"]
    return True, len(rs), None


# ---- /how ------------------------------------------------------------------------------

def _short(s, n):
    s = " ".join((s or "").split())
    return s if len(s) <= n else s[:n - 1] + "…"


def _key_line(output):
    lines = [l for l in (output or "").splitlines() if l.strip()]
    return _short(lines[-1], 150) if lines else "(no output)"


def _run_summary(title, run, full):
    if not run:
        return [f"{title}: did not run"]
    out = [f"{title}: {run['engine']}, {run['seconds']} s, {len(run['actions'])} step(s), "
           f"answer {run.get('answer')!r}"]
    for i, a in enumerate(run["actions"], 1):
        if full:
            out += [f"--- step {i} ({a['kind']}"
                    + (f", exit {a['exit_code']}" if a.get("exit_code") is not None else "") + ")",
                    a["input"], f"--- output ({a['output_chars']} chars, sha256 {a['output_sha256'][:16]}):",
                    a["output"]]
        else:
            out += [f" {i}. {_short(a['input'], 160)}", f"    → {_key_line(a['output'])}"]
    if full:
        out += ["--- reply:", run.get("text") or ""]
    if run.get("flags"):
        out.append(f"   sandbox flags: {', '.join(run['flags'])}")
    return out


def how(rec, full=False):
    """A readable account of one answer record; full=True includes all code and outputs."""
    if rec["type"] == "todo":
        return "\n".join([
            "How the last reply was made", "",
            f"Message{' (voice note, transcribed on this box)' if rec.get('voice') else ''}: {rec['message']}",
            "The local model chose these todo operations, and the bot carried them out:",
            *[f" - {c['name']}({json.dumps(c['args'], ensure_ascii=False)})" for c in rec["calls"]],
            "", "The list in the reply is read back from storage on this box, not written by the model.",
            f"Record {rec['id']}, hash {rec['hash'][:16]}…"])
    m, v = rec["model"], rec["versions"]
    out = ["How the last answer was made", "",
           f"Message: {_short(rec['message'], 300)}",
           "Files: " + (", ".join(f"{f['name']} ({f['bytes']:,} bytes, sha256 {f['sha256'][:12]}…)"
                                  for f in rec["files"]) or "none"),
           f"Model: {m['label']} at {m['base']} ({m['kind']})",
           f"Code: silo {v.get('silo')}" + (f", Codex {v['codex']}" if v.get("codex") else ""), ""]
    out += _run_summary("Answer", rec.get("primary"), full)
    out.append("")
    if rec.get("checker_status") == "off":
        out.append("Independent check: off (strict mode is off; /strict turns it on)")
    else:
        out += _run_summary("Independent check", rec.get("checker"), full)
    if rec.get("checker_status") == "late":
        lc = rec.get("late_check")
        out.append("  (the check was still running when the reply was sent"
                   + (f"; it finished later with {lc['checker'].get('answer')!r}" if lc else "") + ")")
    flags = sorted({f for k in ("primary", "checker") for f in ((rec.get(k) or {}).get("flags") or [])})
    out += ["", f"Badge: {rec['badge']['text']}",
            "Sandbox: " + ("flags: " + ", ".join(flags) if flags
                           else "no network attempts, nothing outside the chat's folder, nothing refused"),
            f"Record {rec['id']}, hash {rec['hash'][:16]}…"]
    if not full:
        out.append("/how full sends every step in full as a file.")
    return "\n".join(out)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "verify":
        ok, n, bad = verify(sys.argv[2])
        print(f"{'ok' if ok else 'BROKEN at line ' + str(bad)}: {n} records")
        sys.exit(0 if ok else 1)
    print("usage: audit_log.py verify <chat_id>")
