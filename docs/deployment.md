# Deploying the Telegram bridge

This brings up the Silo Telegram bot on one Linux box, next to a model you're already
serving. The bot long-polls Telegram, so it needs outbound HTTPS to
`api.telegram.org`, but no public URL, open port or tunnel.

```text
 Telegram app -> api.telegram.org <- long poll - tg_bridge.py
                                                   |
                                                   |-> answers: io's Codex, io's offline bwrap profile --+
                                                   |                                                     |-> local model
                                                   |-> checks:  python-tool harness,                   --+   (OpenAI-compatible)
                                                   |            docker run --network none idli-sandbox:1
                                                   |
                                                   '-> audit record per reply (/how)
```

Every message is answered twice, independently and in parallel. io's Codex writes the
reply, and the bridge's own one-tool harness checks it. The reply carries a badge saying
whether the two agreed (`proposals/correctness-receipt.md`), and `/how` shows the audit
record behind it (`proposals/audit-checker.md`).

## What you need

- **A model server that speaks the OpenAI chat API** (`POST /v1/chat/completions`) with
  tool calling, reachable from the box. This doc assumes it's already running.
  - Silo was built and measured against Muse Glimmer 30B on llama.cpp. For reference,
    `tg-bridge/serve_muse.sh` is how it's served on the DGX Spark: llama.cpp in Docker
    on `127.0.0.1:8181`, 4 slots of 64k, `--jinja`, and the DFlash drafter.
  - llama.cpp needs `--jinja`, or tool calls won't work.
- **For Codex,** these must also hold on the server; the bot also runs if they don't (see below):
  - The model server serves the Responses API (`POST /v1/responses`). Recent llama.cpp does.
  - A checkout of [io](https://github.com/bprashanth/io) at `../io` next to this repo, or
    `IO_APP` pointing at its `app/io`, with its pinned Codex binary and Python runtime fetched,
    as io's own setup does. The bridge uses io's `codex.js` `writeConfig` to build the
    sandbox profile (`tg-bridge/io_config.js`).
  - Node.js, to run `io_config.js`.
  - Bubblewrap working for the bot's user. On Ubuntu 24.04 and later that needs io's AppArmor
    profile (`/etc/apparmor.d/io-bwrap`). io's sandbox conformance test should pass.
  - Without io, every reply falls back to the checker's answer, marked ◻️ unverified.
- **Docker.** The checker's Python runs in a throwaway container.
- **[uv](https://docs.astral.sh/uv/)** to make the venv (any Python 3.12 venv also works).
- **`ffmpeg`** for voice notes and read aloud.
- **About 2 GB of disk for the speech models**, which run on the CPU: Whisper large-v3-turbo
  is fetched from Hugging Face on the first voice note, and `start.sh` fetches Kokoro v1.0.
- **`pdftotext`** (poppler-utils) for PDFs. Optionally **`soffice`** (LibreOffice) for
  legacy `.xls`.
- **A Telegram bot token:** message @BotFather, `/newbot`, and copy the token.

## Configure

All settings are environment variables. The two secrets can also live in files under
`$SILO_CONFIG` (default `~/.config/silo`, mode 700), as `{"api_key": "..."}`.

| variable | default | what it is |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | `api_key` in `$SILO_CONFIG/telegram.json` | the bot token; required |
| `IDLI_BASE_URL` | `http://127.0.0.1:8181/v1` | your model server's OpenAI base URL |
| `IDLI_MODEL` | `muse-glimmer-30b` | the model name the server expects (llama.cpp: its `--alias`) |
| `IDLI_KEY` | `none` | a bearer token, if your server checks one |
| `TG_ALLOWED` | empty, meaning **anyone** | comma-separated Telegram usernames or numeric user ids allowed to use the bot |
| `OPENROUTER_API_KEY` | `api_key` in `$SILO_CONFIG/openrouter.json` | optional; adds external models to `/model`. Leave it unset to keep all data on the box. |
| `WORK_ROOT` | `~/.local/share/idli-bridge/work` | where uploaded files are kept, one directory per chat |
| `SYSTEM_PROMPT` | a short Telegram-assistant prompt | replaces the base system prompt (the checker's, and replies to external models) |
| `IO_APP` | `../io/app/io` next to this repo | io's app folder, which holds `codex.js` and the pinned Codex |
| `CHECK_GRACE` | `30` | seconds to wait for the checker after Codex has answered, before replying ◻️ unverified |
| `CHECK_REASONING` | `low` | `reasoning_effort` for the checker's model calls; it has to keep up with Codex |
| `CODEX_TIMEOUT` | `1500` | seconds before a Codex run is stopped |
| `CODEX_ROOT` | `~/.local/share/idli-bridge/codex` | per-run Codex home and working folder, deleted after each run (must not be under `/tmp`) |
| `AUDIT_ROOT` | `~/.local/share/idli-bridge/audit` | audit records, `<chat>/<date>.jsonl` |
| `SILO_DB` | `~/.local/share/idli-bridge/silo.db` | todos, reminders and each user's morning-list time (SQLite) |
| `TODO_DAILY` | `09:00` | default time (IST) for the morning todo list |
| `MODELS_DIR` | `~/.local/share/idli-bridge/models` | speech weights: `kokoro/` and `whisper/` |
| `WHISPER_MODEL` | `large-v3-turbo` | the speech-to-text model |
| `LOG_CONTENT` | `0` | `1` writes message and reply text to `tg_bridge.log`, for debugging. Off, the log holds only who, what kind and how long, so `/reset` leaves nothing behind. |
| `VOICE_REPLIES` | `0` | `1` turns on voice out: spoken replies to voice notes, and a 🔊 Read aloud button. Off while voice in is being settled. |
| `TTS_VOICE` / `TTS_SPEED` | `af_heart` / `1.0` | the Kokoro voice used for read aloud, e.g. `bf_emma`, `am_michael`, `bm_george` |

Names Whisper keeps mishearing (organisations, villages, people) go one per line in
`$SILO_CONFIG/glossary.txt`. They, and the user's open todos, are given to Whisper as hints.

**Always set `TG_ALLOWED`.** A Telegram bot can be found and messaged by anyone.
Allowing usernames is easiest; numeric ids survive a username change. A denied user's id
is printed in `tg_bridge.log` (`denied name(12345)`), which is an easy way to learn ids.

The "idli internal" model is whatever `IDLI_BASE_URL` points at, so pointing it at a
different local server or model is just these two variables:

```sh
export IDLI_BASE_URL=http://127.0.0.1:8000/v1   # e.g. vLLM, Ollama (/v1), LM Studio
export IDLI_MODEL=<name from GET $IDLI_BASE_URL/models>
```

## Start

```sh
cd tg-bridge
export TELEGRAM_BOT_TOKEN=123456:ABC...        # or ~/.config/silo/telegram.json
TG_ALLOWED=alice,bob,7196436554 ./start.sh
```

`start.sh` does the following:
- creates `.venv` from `requirements.txt` if it's missing;
- builds the sandbox image `idli-sandbox:1` from `sandbox/Dockerfile` if it's missing;
- warns if nothing answers at `$IDLI_BASE_URL/models`, if io isn't found, or if `TG_ALLOWED` is empty;
- stops any bridge it started before, then starts a new one in the background, logging to
  `tg_bridge.log` with its pid in `tg_bridge.pid`.

`./start.sh stop` stops it. The first log line should look like:

```text
tg bridge up default=Muse Glimmer 30B (idli internal) idli=http://127.0.0.1:8181/v1 allowed=['alice', 'bob']
```

It doesn't restart after a reboot or a crash. For that, run the same command from a
systemd unit.

## Check it end to end

In Telegram, open your bot and:
1. Send `/start`. It replies "Hi! I'm Silo…" and names the current model.
2. Send a spreadsheet with a question as the caption, e.g. "total spend by
   category". The reply comes back with the number and a badge, e.g.
   `✅ Verified: an independent second computation also got 5238900.`
3. Send `/how`. It lists the files (with hashes), every step each side ran with its key
   output line, the model and code versions, and the badge. `/how full` sends all of it,
   in full, as a `.txt` file.
4. Ask for a chart ("plot monthly spend"). Codex saves a PNG, which comes back as a photo.

5. Send a voice note: "add to my todos: call Meena about the April budget". The reply shows
   what it heard (🎙️ “…”), the updated list, and comes back as a voice note too. Then try
   "what are my todos?", "I already did 1", and "send me a reminder at 6".

`/todos` shows the list and `/model` shows the model menu. `/reset` asks for confirmation, then
erases everything the box keeps for that person: the conversation, uploaded files, todos,
reminders and the audit records, which hold voice-note transcripts. Voice notes themselves are
transcribed in memory and never written to disk. Telegram keeps its own copy of the chat. It
doesn't clear the audit records.

To test without a phone, `tl_session.py` drives the bot as a Telegram user. It needs a
Telegram API app (`telethon_ap_id` and `telethon_app_hash` in
`$SILO_CONFIG/telegram.json`, plus `botfather_bot_name`) and a one-time login with
`tl_login.py`:

```sh
.venv/bin/python tl_session.py /reset "file:../benchmarks/ngo-workbook-correctness/cases/asha_ngo_finances_FY25-26.xlsx|What was our total actual expenditure from April through September 2025, in INR?"
# expect 19,080,600 and ✅
```

## Google Drive (optional)

A user pastes a Drive folder or file link, and the bot copies only that link into their files:
every subfolder, Google Sheets as `.xlsx`, Docs as `.md` or `.txt`, Slides as `.pdf`, plus
`_drive_manifest.csv` saying where each file came from. To refresh the copy, they send the
link again. `tg-bridge/drive.py` is the only code that talks to Google; the agents read the
copy and still have no network.

There are two ways to reach the user's Drive. If a service account key is present, the bot
uses it; otherwise it asks the user to sign in.

### Service account (recommended)

The folder's owner shares it with the service account's email as a Viewer. Nobody signs in,
there's no list of users to keep, and the account can read only what has been shared with
it. If a link isn't shared yet, the bot replies with the email to share it with. Access is
removed in the same Share dialog. Two things to know:
- Anyone on `TG_ALLOWED` who has a link the account can read can get a copy of it.
- A Google Workspace organisation that blocks sharing outside the domain won't let its users
  add the account.

One-time setup in [Google Cloud Console](https://console.cloud.google.com/):
1. In a project, enable the **Google Drive API**.
2. **IAM & Admin → Service accounts → Create**. It needs no roles.
3. On the account, choose **Keys → Add key → JSON**. Save the file as
   `$SILO_CONFIG/drive_sa.json` with `chmod 600`, then restart the bot.

Signing in as the account uses the `openssl` command, so nothing extra needs installing.

### Sign in with Google

Use this when no service account key is present. The bot asks the user to sign in with
Google, copies the link, and revokes the sign-in straight away. Google's consent screen
says "see and download all your Google Drive files", because that's the narrowest scope that
can read an existing folder.

One-time setup in [Google Cloud Console](https://console.cloud.google.com/):
1. In a project, enable the **Google Drive API**.
2. **Google Auth Platform** (formerly the OAuth consent screen):
   - Under **Branding**, give the app a name and contact emails.
   - Under **Audience**, choose External and leave it in Testing. Add each team member's
     Google account as a test user; up to 100 are allowed, and only they can sign in.
   - Under **Data Access**, add the scope `.../auth/drive.readonly`.
   - Leaving Testing requires Google's verification, which for this scope includes a paid
     security assessment. Testing mode's 7-day token expiry doesn't matter, because each
     sign-in is used once.
3. **Clients → Create client**, then do one of:
   - **Desktop app** (paste-back mode, works anywhere). After sign-in, Google sends the
     browser to `http://localhost:8791/oauth/callback?...`, a page that doesn't load on a
     phone. The user copies that address into the chat, and the bot finishes the sign-in.
   - **Web application** (automatic mode). Add the redirect URI
     `https://<public host>/oauth/callback` and set `OAUTH_REDIRECT` to it. The bot then serves
     the callback on `127.0.0.1:$OAUTH_PORT`, which has to be reachable at that URL.
     On this box, Tailscale Funnel does it: enable HTTPS and Funnel for the node in the
     Tailscale admin console, run `sudo tailscale funnel --bg 8791`, and use
     `https://gx10-0a47.tail5ef239.ts.net/oauth/callback`.
4. Download the client's JSON to `$SILO_CONFIG/google_oauth.json` and restart the bot.

| variable | default | what it is |
|---|---|---|
| `OAUTH_REDIRECT` | `http://localhost:8791/oauth/callback` | where Google sends the browser after sign-in |
| `OAUTH_PORT` | `8791` | the local callback server's port (automatic mode only) |
| `DRIVE_MAX_MB` / `DRIVE_MAX_FILES` | `500` / `2000` | copy limits per link; anything beyond is listed as skipped |

## What runs where

- **Uploads** go to `$WORK_ROOT/<chat id>/` on the host. `/reset` deletes them.
  - The model sees the full text of PDFs, `.txt`, `.md` and `.csv` files, up to about 100k
    characters.
  - For spreadsheets it sees only the first 8 rows of each sheet and computes everything
    else with the tool.
- **The answer:** io's Codex 0.154.0 under io's own profile, one fresh run per message.
  - The profile: bubblewrap, network off, writes only to the run's folder and `/tmp`, reads
    only the platform, io's Python and Codex itself, `approval_policy = never`, and io's
    `AGENTS.md`.
  - The run's folder holds copies of the chat's files, and the conversation so far goes in
    the prompt.
  - New PNG or JPEG files Codex saves are sent back to the chat. Other new files (HTML, PDF,
    xlsx, csv…) are sent only when the reply names them.
  - The folder is deleted after the run.
  - There's no masking proxy as in io, because the model is local.
- **The check:** the bridge's own harness answers the same message from the same files and
  history, with low reasoning effort. It never sees Codex's answer. Both end with an
  `ANSWER:` line, which is stripped from the reply. Their values are compared at the precision
  each was written, so 480 and 481 disagree, while 79.6 and 0.796 (as a fraction) agree.
- **The badge:**
  - ✅ the two agree;
  - ⚠️ they disagree, and both values are shown;
  - ◻️ unverified: the check didn't finish within `CHECK_GRACE` s of Codex or reached no
    answer, both got 0, the answer doesn't appear in anything Codex computed, or Codex failed
    and the checker answered alone;
  - ➖ nothing to check: no single figure or name in the reply, an external model, or a picture,
    which Codex here can't see and so has no second check.
  - A check that finishes late is still written to the audit record, and `/how` shows it.
- **Voice notes:** Whisper (faster-whisper, int8, CPU) transcribes them on the box, and the
  transcript is then handled exactly like typed text. A voice note gets a voice reply as well
  as the text; typed messages get a 🔊 button. Kokoro speaks on the CPU, about 6× faster
  than real time. Before speaking, the bot drops emoji and markdown, says large amounts the
  Indian way ("1 crore 90 lakh"), and turns the badge into one short sentence.
- **Todos and reminders:** a typed or spoken message first goes to one local-model call with
  todo tools: add, complete, delete, edit, show, remind at a time, morning time.
  - Anything else goes on to Codex and the checker.
  - The bot carries out the chosen operations in SQLite and writes the confirmation from storage,
    so the list you see is the stored one.
  - A bare hour means IST and 1–7 means pm, so "remind me at 6" is 6 pm; a time already past
    rolls to tomorrow.
  - A background loop sends each person's open todos every morning and fires reminders.
  - Todos are per Telegram user and never go to an external model.
- **The audit record:** one hash-chained JSON line per reply in `$AUDIT_ROOT/<chat>/<date>.jsonl`.
  `.venv/bin/python audit_log.py verify <chat id>` checks the chain. Records hold code and
  outputs, so they're as sensitive as the files themselves.
- **The checker's `python` tool:** each call is
  `docker run --rm --network none --read-only --memory 2g --cpus 2 --pids-limit 128`,
  with the chat's folder mounted read-only at `/data` and 60 s to run. It can't write
  to the host or reach any network. This is the attack surface of the checker
  (`tg-bridge/harness.py`).
- **The checker** gets up to 12 tool calls per message, then one final call with tools turned off,
  so a reply always comes back. A llama.cpp HTTP 500 (a malformed tool call) is re-sampled
  up to 3 times.
- **Chat history** is kept in memory, the last 20 turns per chat, and lost on restart.
- **External models** (`/model qwen`, `/model deepseek`) send the conversation, including
  file contents, to OpenRouter. They only appear when an OpenRouter key is
  configured.

## Capacity

Each message takes two model streams, Codex and the checker, so one llama.cpp server with
`-np 4` serves two chats at once; the next waits for a free slot. On the DGX Spark, Muse
Glimmer Q4 with the drafter decodes at about 34 tok/s for a single stream.

In the first live tests the spreadsheet questions took 30–85 s for Codex and 27–56 s for the
checker. Small talk took about 20 s, because it goes through Codex too.
