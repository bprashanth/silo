#!/usr/bin/env python3
"""Correctness eval: can a model answer questions over a workbook when called directly?

Feeds the workbook exactly as the bridge does (charts.SYSTEM_HINT-free system prompt +
sheet_text), asks questions whose answers are computed here from the raw data, and
scores the model's JSON answers.

usage: eval_direct.py <xlsx> <model-key>[,<model-key>...] [trials]
model keys: idli (local), muse-or, qwen, deepseek; append "+h" for harness mode
(file in a sandbox + preview, model computes with a python tool)
"""
import collections
import concurrent.futures as cf
import json
import os
import re
import sys

import openpyxl

sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault("TG_ALLOWED", "")
import harness  # noqa: E402
import tg_bridge as br  # noqa: E402  (reuses sheet_text, post_json, MODELS)

OR = br.OR["api_key"]
TARGETS = {
    "idli": (br.MODELS["idli"]["base"], br.MODELS["idli"]["model"], br.MODELS["idli"]["key"]),
    "muse-or": (br.OPENROUTER, "meta/muse-glimmer-30b", OR),
    "qwen": (br.OPENROUTER, br.MODELS["qwen"]["model"], OR),
    "deepseek": (br.OPENROUTER, br.MODELS["deepseek"]["model"], OR),
}


def truth(path):
    wb = openpyxl.load_workbook(path, data_only=True)
    tx = list(wb["Transactions"].iter_rows(min_row=2, values_only=True))
    bud = [r for r in wb["Budget vs Actual"].iter_rows(min_row=2, values_only=True)]
    fund = [r for r in wb["Funding"].iter_rows(min_row=2, values_only=True)]
    amt = lambda rows: round(sum(r[8] for r in rows))  # noqa: E731
    by = lambda i, rows=tx: {k: amt([r for r in rows if r[i] == k]) for k in {r[i] for r in rows}}  # noqa: E731
    prog = by(3)
    edu_types = by(5, [r for r in tx if r[3] == "Education (Shiksha)"])
    budget = {r[0]: r[1] for r in bud}
    over = {p: prog[p] - budget[p] for p in prog if p in budget}
    gaps = {r[0]: r[2] - r[3] for r in fund}
    total = amt(tx)
    return [
        ("total_spend", "Total spend across all transactions (INR)", total),
        ("admin_spend", "Total spend in the Admin category (INR)", amt([r for r in tx if r[4] == "Admin"])),
        ("program_ratio_pct", "Program-category spend as a percentage of total spend (one decimal)",
         round(100 * amt([r for r in tx if r[4] == "Program"]) / total, 1)),
        ("jul_2025_spend", "Total spend in Jul 2025 (INR)", amt([r for r in tx if r[2] == "Jul 2025"])),
        ("usaid_spend", "Total spend funded by 'USAID sub-grant' (INR)",
         amt([r for r in tx if r[7] == "USAID sub-grant"])),
        ("bihar_health_spend", "Spend on 'Maternal & Child Health' in Bihar (INR)",
         amt([r for r in tx if r[3] == "Maternal & Child Health" and r[6] == "Bihar"])),
        ("n_txn_over_1L", "Number of transactions with amount greater than 100000",
         sum(1 for r in tx if r[8] > 100_000)),
        ("top_edu_expense_type", "Expense type with the highest spend within 'Education (Shiksha)' (exact name)",
         max(edu_types, key=edu_types.get)),
        ("most_over_budget_program", "Program with the largest spend minus annual budget, in INR (exact name)",
         max(over, key=over.get)),
        ("largest_funding_gap_funder", "Funder with the largest committed minus received gap (exact name)",
         max(gaps, key=gaps.get)),
        ("beneficiaries_reached", "Total beneficiaries reached across all programs",
         sum(r[3] or 0 for r in bud)),
    ]


def ask(target, doc, key, desc):
    """One question per call, like a user asking in chat. Returns (answer, note)."""
    base, model, api_key = TARGETS[target]
    prompt = (f"{doc}\n\nQuestion: {desc}\nAnswer from the workbook above. End your reply with a final line "
              f'of the form ANSWER: <value> (a plain number without commas or units, or an exact name).')
    r = br.post_json(f"{base}/chat/completions",
                     {"model": model, "messages": [
                         {"role": "system", "content": "You are a careful data analyst."},
                         {"role": "user", "content": prompt}]},
                     {"Authorization": f"Bearer {api_key}"}, timeout=1800)
    c = r["choices"][0]
    text = c["message"].get("content") or ""
    m = re.findall(r"ANSWER:\s*\**\s*(.+)", text)
    if not m:
        return None, f"no answer (finish={c.get('finish_reason')}, tokens={r.get('usage', {}).get('completion_tokens')})"
    return m[-1].strip().strip("*").strip().strip("'\"`").rstrip("."), ""


def preview(text, rows=8):
    """First few rows of each sheet, so the model knows the columns."""
    out, n = [], 0
    for line in text.splitlines():
        if line.startswith("## Sheet:"):
            out.append(line)
            n = 0
        elif n < rows:
            out.append(line)
            n += 1
    return "\n".join(out)


def ask_harness(target, path, desc, chat):
    base, model, api_key = TARGETS[target]
    name = os.path.basename(path)
    harness.save_file(chat, name, open(path, "rb").read())
    prev = preview(br.sheet_text(open(path, "rb").read(), path))
    messages = [
        {"role": "system", "content": "You are a careful data analyst." + harness.SYSTEM_HINT.format(files=name)},
        {"role": "user", "content": f"Attached file: {name} (in /data). Preview, first rows of each sheet:\n{prev}\n\n"
                                    f"Question: {desc}\nEnd your reply with a final line ANSWER: <value> "
                                    "(a plain number without commas or units, or an exact name)."}]

    def call(msgs, tools):
        r = br.post_json(f"{base}/chat/completions", {"model": model, "messages": msgs, **({"tools": tools} if tools else {})},
                         {"Authorization": f"Bearer {api_key}"}, timeout=1800)
        return r["choices"][0]

    text, steps, finish = harness.chat_loop(chat, messages, call, log=lambda *_: None)
    m = re.findall(r"ANSWER:\s*\**\s*(.+)", text)
    ntools = sum(1 for s in steps if s["role"] == "tool")
    if not m:
        return None, f"no answer (finish={finish}, tool calls={ntools})"
    return m[-1].strip().strip("*").strip().strip("'\"`").rstrip("."), f"tools={ntools}"


def correct(got, want):
    if isinstance(want, str):
        return isinstance(got, str) and got.strip().lower() == want.lower()
    try:
        got = float(str(got).replace(",", ""))
    except ValueError:
        return False
    return abs(got - want) <= max(0.01 * abs(want), 0.05)


def main():
    global PATH
    path, targets = sys.argv[1], sys.argv[2].split(",")
    PATH = path
    trials = int(sys.argv[3]) if len(sys.argv) > 3 else 3
    qs = truth(path)
    data = open(path, "rb").read()
    doc = f"Attached file: {os.path.basename(path)}\n<<<\n{br.sheet_text(data, path)}\n>>>"
    print(f"doc chars={len(doc)}; questions={len(qs)}; trials={trials}")
    for t in targets:
        jobs = [(k, d, i) for k, d, _ in qs for i in range(trials)]
        with cf.ThreadPoolExecutor(int(os.environ.get("PAR", "11"))) as ex:
            res = list(ex.map(lambda j: _safe(t, doc, j[0], j[1]), jobs))
        got = collections.defaultdict(list)
        for (k, _, _), r in zip(jobs, res):
            got[k].append(r)
        n = 0
        print(f"\n=== {t} ({TARGETS[t.removesuffix('+h')][1]})")
        for k, _, want in qs:
            ok = [correct(a, want) for a, _ in got[k]]
            n += sum(ok)
            notes = [note for _, note in got[k] if note]
            print(f"{'PASS' if all(ok) else 'FAIL'} {k:28} want={want!r:<26} got={[a for a, _ in got[k]]}"
                  + (f" {notes}" if notes else ""))
        print(f"--> {t}: {n}/{len(qs) * trials} correct ({100 * n / (len(qs) * trials):.0f}%)")


def _safe(t, doc, k, d):
    try:
        if t.endswith("+h"):
            import uuid
            return ask_harness(t[:-2], PATH, d, f"eval-{uuid.uuid4().hex[:8]}")
        return ask(t, doc, k, d)
    except Exception as e:
        return None, f"error: {e}"


if __name__ == "__main__":
    main()
