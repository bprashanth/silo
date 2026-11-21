#!/usr/bin/env python3
"""Summarize a harness-compare run: jobs.jsonl -> summary.md (also printed)."""
import collections
import json
import os
import statistics
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../tg-bridge"))
import receipt  # noqa: E402


def main(out):
    rows = [json.loads(l) for l in open(os.path.join(out, "jobs.jsonl"))]
    # Recompute receipts from transcripts, so receipt.py fixes apply to finished runs.
    for r in rows:
        t = json.load(open(os.path.join(out, "transcripts", r["job"] + ".json")))
        r["receipt"] = receipt.check(t["text"], [a.get("output", "") for a in t["actions"]], ignore=t["question"])
        r["audit"] = receipt.audit(r["harness"], t["actions"], t.get("workspace", ""))
    by_h = collections.defaultdict(list)
    for r in rows:
        by_h[r["harness"]].append(r)
    lines = [f"# Harness comparison: {os.path.basename(os.path.abspath(out))}", "",
             "| harness | jobs | correct | wrong | missing | median s | median actions | "
             "receipt clean | wrong answers caught by receipt | correct answers flagged | audit flags |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for h, rs in sorted(by_h.items()):
        v = collections.Counter(r["verdict"] for r in rs)
        wrong = [r for r in rs if r["verdict"] == "wrong"]
        right = [r for r in rs if r["verdict"] == "correct"]
        caught = sum(1 for r in wrong if not r["receipt"]["clean"])
        false_alarm = sum(1 for r in right if not r["receipt"]["clean"])
        flags = collections.Counter(f for r in rs for f in r["audit"])
        lines.append(
            f"| {h} | {len(rs)} | {v['correct']} | {v['wrong']} | {v['missing']} | "
            f"{statistics.median(r['seconds'] for r in rs):.0f} | {statistics.median(r['actions'] for r in rs):.0f} | "
            f"{sum(r['receipt']['clean'] for r in rs)}/{len(rs)} | {caught}/{len(wrong)} | "
            f"{false_alarm}/{len(right)} | {dict(flags) or '-'} |")
    lines += ["", "## Per case", "", "| case | " + " | ".join(sorted(by_h)) + " |",
              "|---|" + "---|" * len(by_h)]
    cases = sorted({r["case"] for r in rows})
    for c in cases:
        cells = []
        for h in sorted(by_h):
            rs = [r for r in by_h[h] if r["case"] == c]
            cells.append(f"{sum(r['verdict'] == 'correct' for r in rs)}/{len(rs)}")
        lines.append(f"| {c} | " + " | ".join(cells) + " |")
    lines += ["", "## Not correct", ""]
    for r in sorted(rows, key=lambda r: r["job"]):
        if r["verdict"] != "correct":
            lines.append(f"- `{r['job']}` {r['verdict']}: got {r['got']!r}, want {r['want']!r}; "
                         f"receipt {'clean' if r['receipt']['clean'] else 'BROKEN ' + str(r['receipt']['untraced'][:5])}; "
                         f"finish {r['finish']}")
    text = "\n".join(lines) + "\n"
    open(os.path.join(out, "summary.md"), "w").write(text)
    print(text)


if __name__ == "__main__":
    main(sys.argv[1])
