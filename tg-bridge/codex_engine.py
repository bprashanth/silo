"""Run one question through io's Codex, under io's own offline profile, on the local model.

io_config.js calls io's writeConfig (bwrap wall, network off, writes only to the job
folder and /tmp, io's AGENTS.md) and points the profile at IDLI_BASE_URL. Each run gets a
fresh CODEX_HOME and working folder holding copies of the chat's files.
"""
import json
import os
import shutil
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
TIMEOUT = int(os.environ.get("CODEX_TIMEOUT", "1500"))


def run(files, prompt, root, timeout=TIMEOUT, keep=False):
    """files: host paths copied into the working folder. root: a fresh dir for this run,
    not under /tmp (Codex refuses a CODEX_HOME there).

    Returns {text, finish, actions, usage, errors, codex_version, workspace, new_files,
    stderr_tail}. new_files are files Codex left in the folder (charts, dashboards); the
    folder is deleted unless keep, so read them before it goes.
    """
    shutil.rmtree(root, ignore_errors=True)
    home, ws = os.path.join(root, "home"), os.path.join(root, "ws")
    os.makedirs(home)
    os.makedirs(ws)
    for f in files:
        if os.path.isdir(f):  # a Drive folder copy
            shutil.copytree(f, os.path.join(ws, os.path.basename(f)))
        else:
            shutil.copy(f, ws)
    before = set(os.listdir(ws))
    info = json.loads(subprocess.check_output(["node", os.path.join(HERE, "io_config.js"), home, ws], text=True))
    env = {k: v for k, v in os.environ.items()
           if not (k.startswith("OPENAI_") or k.startswith("OPENROUTER_") or k in ("CODEX_API_KEY", "TELEGRAM_BOT_TOKEN"))}
    env["CODEX_HOME"] = home
    env["PATH"] = os.path.join(info["libs"], "bin") + os.pathsep + env.get("PATH", "")
    cmd = [info["bin"], "exec", "-p", info["profile"], "--json", "--skip-git-repo-check", "-C", ws, prompt]
    try:
        # Without stdin=DEVNULL, codex exec waits for more input on stdin.
        p = subprocess.run(cmd, env=env, cwd=ws, stdin=subprocess.DEVNULL, capture_output=True,
                           text=True, timeout=timeout)
        stdout, stderr, finish = p.stdout, p.stderr, f"exit={p.returncode}"
    except subprocess.TimeoutExpired as e:
        stdout = e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
        stderr, finish = "", "timeout"
    actions, texts, usage, errors = [], [], {"input": 0, "output": 0}, []
    for line in stdout.splitlines():
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        it = e.get("item") or {}
        if e.get("type") == "item.completed":
            if it.get("type") == "command_execution":
                actions.append({"kind": "shell", "input": it.get("command", ""),
                                "output": it.get("aggregated_output", ""), "exit_code": it.get("exit_code")})
            elif it.get("type") == "agent_message":
                texts.append(it.get("text", ""))
            elif it.get("type") == "error":
                errors.append(it.get("message", ""))
            elif it.get("type") not in ("reasoning",):
                actions.append({"kind": it.get("type"), "input": json.dumps(it)[:2000], "output": ""})
        elif e.get("type") == "turn.completed":
            u = e.get("usage") or {}
            usage["input"] += u.get("input_tokens", 0)
            usage["output"] += u.get("output_tokens", 0)
        elif e.get("type") in ("error", "turn.failed"):
            errors.append(json.dumps(e)[:500])
    new_files = {}
    for name in sorted(set(os.listdir(ws)) - before):
        path = os.path.join(ws, name)
        if os.path.isfile(path) and os.path.getsize(path) <= 20_000_000:
            new_files[name] = open(path, "rb").read()
    if not keep:
        shutil.rmtree(root, ignore_errors=True)
    return {"text": texts[-1] if texts else "", "finish": finish, "actions": actions, "usage": usage,
            "errors": errors, "codex_version": info["version"], "workspace": ws, "new_files": new_files,
            "stderr_tail": "\n".join(l for l in stderr.splitlines()[-15:]
                                     if not l.startswith("WARNING: proceeding"))}
