#!/usr/bin/env python3
"""Compare the Telegram bridge's harness with io's Codex harness on the same cases.

Both use local Muse (llama.cpp on 127.0.0.1:8181). Each job is one question, asked
fresh, with the case's files in a new workspace.

  simple  tg-bridge/harness.py: one `python` tool in a no-network container,
          files mounted read-only at /data. Prompt built by tg_bridge.file_content,
          exactly as a Telegram upload is.
  codex   io's pinned Codex under io's own profile (io_config.js: bwrap wall,
          offline network, escalation closed, io's AGENTS.md), via `codex exec --json`.

usage: run.py <out_dir> [--cases a,b] [--harness simple,codex] [--trials N] [--par P]
Writes <out_dir>/jobs.jsonl, transcripts/, summary.md. Re-running skips finished jobs.
"""
import argparse
import concurrent.futures as cf
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "../.."))
BENCH_HOME = os.path.expanduser("~/.local/share/idli-bench")  # Codex refuses CODEX_HOME under /tmp
os.environ.setdefault("WORK_ROOT", os.path.join(BENCH_HOME, "simple"))
os.environ.setdefault("TG_ALLOWED", "")
sys.path.insert(0, os.path.join(ROOT, "tg-bridge"))
import harness  # noqa: E402
import receipt  # noqa: E402  (benchmarks/harness-compare/receipt.py)
import tg_bridge as br  # noqa: E402

IO_APP = os.path.abspath(os.path.join(ROOT, "../io/app/io"))
CODEX_TIMEOUT = 1500
PROMPT_TAIL = ("\nEnd your reply with a final line of the form ANSWER: <value> "
               "(a plain number without commas or units, or an exact name).")
write_lock = threading.Lock()


def load_cases(names):
    base = os.path.join(HERE, "cases")
    out = []
    for d in sorted(os.listdir(base)):
        p = os.path.join(base, d, "case.json")
        if os.path.isfile(p) and (not names or d in names):
            c = json.load(open(p))
            c["dir"] = os.path.join(base, d, "files")
            # plain.json: the same questions asked the way a person would, without the hints
            pp = os.path.join(base, d, "plain.json")
            if os.path.isfile(pp):
                by_id = {q["id"]: q for q in c["questions"]}
                for v in json.load(open(pp)):
                    c["questions"].append({**by_id[v["of"]], "id": v["id"], "question": v["question"],
                                           "trap": "plain variant of " + v["of"]})
            out.append(c)
    return out


def parse_answer(text):
    m = re.findall(r"ANSWER:\s*\**\s*(.+)", text or "")
    return m[-1].strip().strip("*").strip().strip("'\"`").rstrip(".") if m else None


def correct(got, q):
    if got is None:
        return "missing"
    want = q["answer"]
    if q.get("kind") == "name" or isinstance(want, str):
        return "correct" if got.strip().lower() == str(want).strip().lower() else "wrong"
    v = receipt.to_number(got)
    if v is None:
        return "wrong"
    tol = max(abs(want) * q.get("tol_pct", 1.0) / 100, 0.05)
    return "correct" if abs(v - want) <= tol else "wrong"


# ---- simple harness -------------------------------------------------------------------

def run_simple(case, q, job):
    chat = job
    harness.clear(chat)
    names = case["files"]
    msgs = []
    for i, name in enumerate(names):
        data = open(os.path.join(case["dir"], name), "rb").read()
        last = i == len(names) - 1
        cap = q["question"] + PROMPT_TAIL if last else "Here is a file; my question follows."
        msgs.append({"role": "user", "content": br.file_content(chat, name, "", data, cap)})
    system = br.SYSTEM + harness.SYSTEM_HINT.format(files=", ".join(harness.files(chat)))
    m = br.MODELS["idli"]
    usage = {"input": 0, "output": 0}

    def call(messages, tools):
        r = br.post_json(f"{m['base']}/chat/completions",
                         {"model": m["model"], "messages": messages, **({"tools": tools} if tools else {})},
                         {"Authorization": f"Bearer {m['key']}"}, timeout=1800)
        u = r.get("usage") or {}
        usage["input"] += u.get("prompt_tokens", 0)
        usage["output"] += u.get("completion_tokens", 0)
        return r["choices"][0]

    text, steps, finish = harness.chat_loop(chat, [{"role": "system", "content": system}, *msgs], call,
                                            log=lambda *_: None)
    actions = []
    pending = {}
    for s in steps:
        if s["role"] == "assistant":
            for tc in s.get("tool_calls") or []:
                try:
                    code = json.loads(tc["function"]["arguments"] or "{}").get("code", "")
                except json.JSONDecodeError:
                    code = tc["function"].get("arguments", "")
                pending[tc["id"]] = {"kind": "python", "input": code}
        elif s["role"] == "tool":
            a = pending.pop(s["tool_call_id"], {"kind": "python", "input": ""})
            a["output"] = s["content"]
            actions.append(a)
    harness.clear(chat)
    return {"text": text, "finish": finish, "actions": actions, "usage": usage,
            "workspace": f"/data (container), host {harness.workdir(chat)}"}


# ---- io codex harness -----------------------------------------------------------------

def run_codex(case, q, job):
    root = os.path.join(BENCH_HOME, "codex", job)
    shutil.rmtree(root, ignore_errors=True)
    home, ws = os.path.join(root, "home"), os.path.join(root, "ws")
    os.makedirs(home)
    os.makedirs(ws)
    for name in case["files"]:
        shutil.copy(os.path.join(case["dir"], name), ws)
    info = json.loads(subprocess.check_output(["node", os.path.join(HERE, "io_config.js"), home, ws],
                                              env={**os.environ, "IO_APP": IO_APP}, text=True))
    env = {k: v for k, v in os.environ.items()
           if not (k.startswith("OPENAI_") or k.startswith("OPENROUTER_") or k == "CODEX_API_KEY")}
    env["CODEX_HOME"] = home
    env["PATH"] = os.path.join(info["libs"], "bin") + os.pathsep + env.get("PATH", "")
    prompt = (f"The files for this question are in this folder: {', '.join(case['files'])}.\n\n"
              + q["question"] + PROMPT_TAIL)
    cmd = [info["bin"], "exec", "-p", info["profile"], "--json", "--skip-git-repo-check", "-C", ws, prompt]
    try:
        p = subprocess.run(cmd, env=env, cwd=ws, stdin=subprocess.DEVNULL, capture_output=True,
                           text=True, timeout=CODEX_TIMEOUT)
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
    files_after = sorted(os.listdir(ws))
    shutil.rmtree(root, ignore_errors=True)
    return {"text": texts[-1] if texts else "", "finish": finish, "actions": actions, "usage": usage,
            "errors": errors, "codex_version": info["version"], "workspace": ws,
            "files_after": files_after, "stderr_tail": "\n".join(
                l for l in stderr.splitlines()[-15:] if not l.startswith("WARNING: proceeding"))}


HARNESSES = {"simple": run_simple, "codex": run_codex}


def run_job(out, case, q, h, trial):
    job = f"{case['id']}.{q['id']}.{h}.{trial}"
    t0 = time.time()
    try:
        r = HARNESSES[h](case, q, job)
    except Exception as e:  # a crashed job is a result, not a reason to stop the run
        r = {"text": "", "finish": f"error: {e!r}", "actions": [], "usage": {}}
    r["seconds"] = round(time.time() - t0, 1)
    got = parse_answer(r["text"])
    verdict = correct(got, q)
    rc = receipt.check(r["text"], [a.get("output", "") for a in r["actions"]], ignore=q["question"])
    flags = receipt.audit(h, r["actions"], r.get("workspace", ""))
    row = {"job": job, "case": case["id"], "q": q["id"], "harness": h, "trial": trial,
           "want": q["answer"], "got": got, "verdict": verdict, "seconds": r["seconds"],
           "actions": len(r["actions"]), "usage": r.get("usage"), "finish": r.get("finish"),
           "receipt": rc, "audit": flags}
    os.makedirs(os.path.join(out, "transcripts"), exist_ok=True)
    with open(os.path.join(out, "transcripts", job + ".json"), "w") as f:
        json.dump({**row, "question": q["question"], "trap": q.get("trap"), **r}, f, indent=1, default=str)
    with write_lock, open(os.path.join(out, "jobs.jsonl"), "a") as f:
        f.write(json.dumps(row, default=str) + "\n")
    print(f"{job:40} {verdict:8} got={got!r:.30} want={q['answer']!r:.30} {r['seconds']}s "
          f"acts={len(r['actions'])} receipt={'ok' if rc['answer_traced'] else 'BROKEN'}"
          + (f" audit={flags}" if flags else ""), flush=True)
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--cases", default="")
    ap.add_argument("--harness", default="simple,codex")
    ap.add_argument("--trials", type=int, default=1)
    ap.add_argument("--par", type=int, default=2)
    ap.add_argument("--questions", default="", help="only these question ids")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    done = set()
    jp = os.path.join(a.out, "jobs.jsonl")
    if os.path.exists(jp):
        done = {json.loads(l)["job"] for l in open(jp)}
    cases = load_cases([c for c in a.cases.split(",") if c])
    jobs = [(c, q, h, t) for t in range(a.trials) for c in cases for q in c["questions"]
            if not a.questions or q["id"] in a.questions.split(",")
            for h in a.harness.split(",") if f"{c['id']}.{q['id']}.{h}.{t}" not in done]
    print(f"{len(jobs)} jobs ({len(done)} already done), par={a.par}", flush=True)
    with cf.ThreadPoolExecutor(a.par) as ex:
        list(ex.map(lambda j: run_job(a.out, *j), jobs))
    subprocess.run([sys.executable, os.path.join(HERE, "summarize.py"), a.out])


if __name__ == "__main__":
    main()
