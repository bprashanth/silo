"""Decode-speed benchmark against the local llama-server (127.0.0.1:8181).

Runs a few fixed prompts (prose, code, data reasoning), temperature 0, and
reports generation tok/s plus speculative-draft acceptance when present.
"""
import json, sys, urllib.request
URL = "http://127.0.0.1:8181/v1/chat/completions"
PROMPTS = [
    ("prose", "Explain in about 300 words why NGOs track program-spend ratio."),
    ("code", "Write a pandas function that loads an xlsx with sheets Transactions and Budget, "
             "and returns spend by program vs budget as a DataFrame. Include docstring."),
    ("data", "A charity spent 3.98 crore, of which 3.17 crore on programs, 52 lakh admin, 29 lakh "
             "fundraising. Compute each share to one decimal and comment briefly."),
]
label = sys.argv[1] if len(sys.argv) > 1 else "run"
tot_n = tot_ms = 0
for name, p in PROMPTS:
    body = {"messages": [{"role": "user", "content": p}], "temperature": 0, "max_tokens": 1500}
    req = urllib.request.Request(URL, json.dumps(body).encode(), {"Content-Type": "application/json"})
    r = json.load(urllib.request.urlopen(req, timeout=1800))
    t = r.get("timings", {})
    n, ms = t.get("predicted_n", 0), t.get("predicted_ms", 1)
    tot_n += n; tot_ms += ms
    acc = f" draft {t['draft_n_accepted']}/{t['draft_n']}" if t.get("draft_n") else ""
    print(f"{label:14} {name:6} {n:5d} tok  {1000 * n / ms:6.1f} tok/s{acc}", flush=True)
print(f"{label:14} ALL    {tot_n:5d} tok  {1000 * tot_n / tot_ms:6.1f} tok/s", flush=True)
