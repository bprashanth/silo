# Silo

<img width="687" height="714" alt="Screenshot from 2026-10-11 22-41-33" src="https://github.com/user-attachments/assets/155accd1-e514-4fa9-a18e-15fccdbd2fd9" />


Silo is the first product prototype to come out of the event [io](https://github.com/bprashanth/io)
was built for.

It's a confidential assistant for a small NGO team. People talk to a model that runs
on a "confidential VM", the model computes over their files in a sandbox.

## Goals

1. Trustable
2. Useful
3. Cheap

AI.

**Trustable** means:
- **private:** data never leaves the laptop `<->` our servers without the user's consent.
- **correct:** two or more models verify each answer independently.
- **reproducible:** the same question asked again gets the same answer.
- **verifiable:** users can check the steps taken to produce the result.

**Useful** means:
- it works on field data formats: messy spreadsheets, pictures, chat logs, voice notes...
- it assumes users aren't coders, and shows visuals first.
- it brings in Indian context without being asked.

**Cheap** is self-explanatory.

Why is privacy a challenge? Because the agent harness is extremely powerful:
1. it can try things;
2. it can backtrack and try more things.

That same power lets it pursue a goal at any cost, even when the cost turns out to be
"send data to a remote server". The chance is small but not zero, so we need measures that
guarantee privacy. The failproof one is to block network access. That can only be done
reliably on the server, because the user base's Windows machines vary too much.

## Current State

Currently it's designed as a private assistant for NGO teams that answers questions about their own
email, calendar and Drive. The data stays in a local database and a private model picks
commands and writes short replies.

**Start here:** [docs/README.md](docs/README.md) (what to read, in order), then [docs/goals.md](docs/goals.md).
If you are an agent picking up work, read [docs/handoff.md](docs/handoff.md) first.

## Layout

```text
core/          the core: a command-line tool over a DuckDB store per sandbox (core/idli, core/lib/)
docs/          what the core is and why (goals, commands, decisions, the store, the mapper, models, privacy)
benchmarks/    how we check it: task banks, the grading rubric, the bench script
todos/         what's next, and the full running list of bugs and fixes
chronology/    append-only log, one file per step
archive/v1/    the earlier Telegram bot version of Silo (tg-bridge, wa-bridge, its benchmarks and notes). Old.
examples/      frozen livestock call-center examples from v1. Old; a service still runs from here, so it stays put.
```

## Try it

From the repository root, install the CLI and select your own test account. Keep these
exports in the shell where you run Idli, using a separate sandbox for each account.

```bash
cd core
uv venv -p 3.12 .venv
uv pip install -p .venv/bin/python -r requirements.txt
export IDLI_GOOGLE_ACCOUNT='your-test-account@gmail.com'
export IDLI_SANDBOX="$HOME/idli-sbx/$IDLI_GOOGLE_ACCOUNT"
export IDLI_GOOGLE_CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}/silo"
install -d -m 700 "$IDLI_GOOGLE_CONFIG"
```

**Google sign-in.** Ask a maintainer for the Google Desktop OAuth client JSON and access
for your test email. Save it as `$IDLI_GOOGLE_CONFIG/io_oauth_client_gcp.json` with mode
600. The config directory defaults to `~/.config/idlisseus` if you omit the override.
On a new device, start consent once from `core/` on a machine with a browser:

```bash
.venv/bin/python -c 'import os, webbrowser; from lib import google_api as g; g.connect(os.environ["IDLI_GOOGLE_ACCOUNT"], webbrowser.open)'
```

Select the same account and grant the requested scopes. The helper saves the refresh
token in `$IDLI_GOOGLE_CONFIG/google-tokens/<lowercase-email>.json`. Sync reuses it.

**DGX access.** Ask a maintainer for the model router HTTPS base URL and a Cloudflare
Access service token authorized for that router. Create the config directory and save
the following JSON with the issued values at
`${IDLI_HOME:-$HOME/idli-insights}/config/muse-access.json` with mode 600:

```json
{"url":"https://silo.idli.cc","client_id":"<issued client ID>","client_secret":"<issued client secret>"}
```

Leave `IDLI_9B_URL` and `MUSE_URL` unset for this route. Without a usable token file
the default mapper tries the DGX-local service at `127.0.0.1:8291`.
For the default hosted Clef judge and question classifier, request a separate
OpenRouter API key for test data and set `IDLI_SQL_KEY`. For full Drive embeddings
from a laptop, ask for a reachable embedding base URL and set `IDLI_EMBED_URL`
(DGX default port 8293).

```bash
./idli sync gmail -v
./idli sync gcalendar -v
./idli sync drive --no-embed -v  # omit --no-embed with a reachable embedding service
./idli ask "which files mention the school visit?"
./idli help
```

## Tests and question banks

The [benchmark guide](benchmarks/README.md) links the development, owner and
held-out questions, upstream trials and grading rubric. Historical answers depend
on the matching test-account snapshot.

## History

Silo started as a Telegram bot on a 30B model with answer checking (October 2026), now in `archive/v1/`. The core
was built and measured in the io repo in November 2026 and moved here; see [docs/from-io.md](docs/from-io.md).
