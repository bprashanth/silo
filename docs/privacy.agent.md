# Privacy in the core (companion to privacy.md)

Implementation notes, 2026-11-21. privacy.md asks where GLiNER lives. Short answer: the core calls a GLiNER service; it
doesn't load the model itself.

## Where GLiNER runs

- **The service:** `io-privacy-server` (a systemd user service on the DGX, port 8899, `POST /scan`). Its model is
  in `io/app/io/hf-cache` (set by the unit's `HF_HOME`), not in `~/.cache` or on `/mnt/seagate`.
- **The core's default:** `https://privacy.idli.cc/scan`, the same service through Cloudflare, so a laptop can use
  it. On the DGX you can point the core at it directly: `IDLI_SCANNER=http://127.0.0.1:8899/scan`.
- **If it can't be reached,** masking falls back to the regex rules only (emails, phones, IDs), and names may slip.

## What masking does (`core/lib/privacy.py`, `privacy_engine/`)

`mask_account_text(sandbox, text)` replaces names, emails, places and numbers with codes (`NAME_007`), using this
sandbox's saved codes first (`<sandbox>/vault/`), then the regex rules, then GLiNER. idli-remote's answer is put
back with the real values (`home.rehydrate`).

## What crosses the line

| | idli-remote | hosted Clef (judge, chips) |
|---|---|---|
| The question | masked | as asked |
| Records, file text | never | **yes** |

Hosted Clef is for the test accounts only; real data needs a local Clef or `--judge nine_compressed`.

## Known gaps (io running list)

Surnames inside account text, one PDF author, and over-masking of some words ("fixity from").
