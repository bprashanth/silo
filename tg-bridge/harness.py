"""Minimal tool-calling harness: the model can run Python over the chat's files.

Each chat has a workdir (WORK_ROOT/<chat>) holding the files the user uploaded.
Code runs in a throwaway container: no network, workdir mounted read-only at
/data, CPU/memory/time limits. Nothing the model writes touches the host.
"""
import json
import os
import subprocess
import urllib.error

WORK_ROOT = os.path.expanduser(os.environ.get("WORK_ROOT", "~/.local/share/idli-bridge/work"))
IMAGE = "idli-sandbox:1"
MAX_STEPS = 12
MAX_OUT = 8000

TOOLS = [{
    "type": "function",
    "function": {
        "name": "python",
        "description": (
            "Run a Python 3 script and get its stdout/stderr. The user's uploaded files are in "
            "/data (read-only); pandas, numpy, openpyxl, pypdf are installed; no network. "
            "Each call is a fresh process, so re-load data every time. print() what you need."
        ),
        "parameters": {
            "type": "object",
            "properties": {"code": {"type": "string", "description": "Python source to run"}},
            "required": ["code"],
        },
    },
}]

SYSTEM_HINT = """
You have a `python` tool. For any question that needs numbers from an uploaded file
(totals, filters, counts, rankings, ratios), compute them with the tool instead of
by hand - never add up rows in your head. Files are in /data: {files}.
"""


def workdir(chat):
    d = os.path.join(WORK_ROOT, str(chat))
    os.makedirs(d, exist_ok=True)
    return d


def save_file(chat, name, data):
    path = os.path.join(workdir(chat), os.path.basename(name) or "file")
    with open(path, "wb") as f:
        f.write(data)
    return path


def files(chat):
    d = os.path.join(WORK_ROOT, str(chat))
    return sorted(os.listdir(d)) if os.path.isdir(d) else []


def clear(chat):
    d = os.path.join(WORK_ROOT, str(chat))
    for f in files(chat):
        os.remove(os.path.join(d, f))


def run_python(chat, code, timeout=60):
    cmd = ["docker", "run", "--rm", "-i", "--network", "none", "--memory", "2g", "--cpus", "2",
           "--pids-limit", "128", "--read-only", "--tmpfs", "/tmp:size=256m",
           "-v", f"{workdir(chat)}:/data:ro", IMAGE, "timeout", str(timeout), "python", "-"]
    try:
        p = subprocess.run(cmd, input=code, capture_output=True, text=True, timeout=timeout + 30)
        out = p.stdout + (f"\n[stderr]\n{p.stderr}" if p.stderr.strip() else "")
        if p.returncode == 124:
            out += f"\n[killed: exceeded {timeout}s]"
    except subprocess.TimeoutExpired:
        out = f"[killed: exceeded {timeout}s]"
    return out[:MAX_OUT] + ("\n[output truncated]" if len(out) > MAX_OUT else "")


def retrying(call, tries=3):
    """llama.cpp answers 500 when Muse emits a malformed tool call ("does not match the
    expected peg-native format"); sampling again almost always fixes it."""
    def wrapped(messages, tools):
        for i in range(tries):
            try:
                return call(messages, tools)
            except urllib.error.HTTPError as e:
                if e.code != 500 or i == tries - 1:
                    raise
    return wrapped


def chat_loop(chat, messages, call, log=print):
    """Run the tool loop. `call(messages, tools)` returns an OpenAI-style choice.

    Returns (final_text, new_messages) where new_messages are the assistant/tool
    turns produced, for the caller to keep in history if it wants.
    """
    call = retrying(call)
    new = []
    for step in range(MAX_STEPS):
        choice = call(messages + new, TOOLS)
        msg = choice["message"]
        calls = msg.get("tool_calls") or []
        if not calls:
            return (msg.get("content") or "").strip(), new, choice.get("finish_reason")
        new.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls})
        for tc in calls:
            try:
                code = json.loads(tc["function"]["arguments"] or "{}").get("code", "")
            except json.JSONDecodeError:
                code = ""
            out = run_python(chat, code) if code else "error: no code given"
            log(f"   [tool step {step + 1}] {len(code)} chars of code -> {out[:120]!r}")
            new.append({"role": "tool", "tool_call_id": tc["id"], "content": out})
    # Out of tool budget: one more call with tools off, so the user always gets an answer.
    new.append({"role": "user", "content": "Tool budget used up. Give your final answer now from the results above."})
    choice = call(messages + new, None)
    return (choice["message"].get("content") or "").strip(), new, "max_steps"
