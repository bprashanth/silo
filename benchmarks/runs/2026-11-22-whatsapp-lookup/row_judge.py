"""Judge four reviewed, de-identified message projections from the frozen timing exchange."""
import hashlib
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "core"))
from lib.recstore import _clef

# Restrict outbound content to these reviewed projections, even if the snapshot changes.
root = Path(sys.argv[1])
raw = (root / "reviewed-projections.json").read_bytes()
if hashlib.sha256(raw).hexdigest() != "b625571bab0341533749056ba8234ac0fb1a6e6d5813b2f3a4b7c37c100b882b":
    raise ValueError("Unexpected outbound projections")
samples = json.loads(raw)
group = next(g for g in json.loads((root / "groups.json").read_text())["groups"]
             if g["name"] == "Jam Buns @ T4GC")
rows = {r["t"]: r["body"] for r in group["rows"]}
criterion = "Does the author propose concrete meeting time(s)? Merely describing personal availability does not qualify."
for timestamp, projection, expected in samples:
    body = re.sub(r"cc futures", "[topic]", rows[timestamp], flags=re.I)
    if not body.startswith(projection):
        raise ValueError("Source differs from reviewed projection")
    label, detail = _clef(projection, criterion, ["yes", "no", "unsure"])
    print(timestamp, expected, label, detail, flush=True)
