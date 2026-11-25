"""Feed hand-located evidence through the existing local CLI answer writer."""
import json
import os
from pathlib import Path
import subprocess
import sys

here = Path(__file__).resolve().parent
core = here.parents[2] / "core"
sys.path.insert(0, str(core))
from lib.idlicli import compose

root = Path(sys.argv[1]).resolve()
os.environ.update(IDLI_SANDBOX=str(root / "base"), IDLI_9B_URL="http://127.0.0.1:8291")
questions = {c["id"]: c["q"] for c in json.loads((here / "cases.json").read_text())}
windows = {"time": ("2026-11-19 11:30", "2026-11-19 11:34"),
           "website": ("2026-11-18 13:28", "2026-11-18 13:29"),
           "doc": ("2026-11-20 13:12", "2026-11-20 13:14")}
os.umask(0o077)
with (root / "context-control.jsonl").open("x") as out:
    for case, (start, end) in windows.items():
        sql = ("SELECT sent_at, sender, body FROM wa_messages WHERE group_name = 'Jam Buns @ T4GC' "
               f"AND sent_at >= '{start}' AND sent_at < '{end}' ORDER BY sent_at")
        shown = subprocess.check_output([core / "idli", "query", sql], text=True)
        reply, reason = compose(questions[case], shown, [])
        out.write(json.dumps(dict(case=case, reply=reply, reason=reason, evidence=shown)) + "\n")
        print(case, shown.splitlines()[0], reason)
