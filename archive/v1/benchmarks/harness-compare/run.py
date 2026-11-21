#!/usr/bin/env python3
"""Compare the Telegram bridge's harness with io's Codex harness on the same cases.

Both use local Muse (llama.cpp on 127.0.0.1:8181). Each job is one question, asked
fresh, with the case's files in a new workspace.

  simple  tg-bridge/harness.py: one `python` tool in a no-network container,
          files mounted read-only at /data. Prompt built by tg_bridge.file_content,
          exactly as a Telegram upload is.
  codex   io's pinned Codex under io's own profile (tg-bridge/codex_engine.py and io_config.js: bwrap wall,
          offline network, escalation closed, io's AGENTS.md), via `codex exec --json`.

usage: run.py <out_dir> [--cases a,b] [--harness simple,codex] [--trials N] [--par P]
Writes <out_dir>/jobs.jsonl, transcripts/, summary.md. Re-running skips finished jobs.
"""
import argparse
import concurrent.futures as cf
import json
import os
import re
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
import codex_engine  # noqa: E402
import harness  # noqa: E402
import receipt  # noqa: E402  (tg-bridge/receipt.py)
import tg_bridge as br  # noqa: E402

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
    prompt = (f"The files for this question are in this folder: {', '.join(case['files'])}.\n\n"
              + q["question"] + PROMPT_TAIL)
    r = codex_engine.run([os.path.join(case["dir"], n) for n in case["files"]], prompt,
                         os.path.join(BENCH_HOME, "codex", job), timeout=CODEX_TIMEOUT)
    r["files_after"] = sorted(case["files"] + list(r.pop("new_files")))
    return r


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
