# Deploying the Telegram bridge

This brings up the Silo Telegram bot on one Linux box, next to a model you're already
serving. The bot long-polls Telegram, so it needs outbound HTTPS to
`api.telegram.org`, but no public URL, open port or tunnel.

```text
 Telegram app -> api.telegram.org <- long poll - tg_bridge.py -> local model (OpenAI-compatible)
                                                         |
                                                         |-> docker run --network none idli-sandbox:1
                                                             (python over the chat's files, read-only)
```

## What you need

- **A model server that speaks the OpenAI chat API** (`POST /v1/chat/completions`) with
  tool calling, reachable from the box. This doc assumes it's already running.
  - Silo was built and measured against Muse Glimmer 30B on llama.cpp. For reference,
    `tg-bridge/serve_muse.sh` is how it's served on the DGX Spark: llama.cpp in Docker
    on `127.0.0.1:8181`, 4 slots of 64k, `--jinja`, and the DFlash drafter.
  - llama.cpp needs `--jinja`, or tool calls won't work.
- **Docker.** The model's Python runs in a throwaway container.
- **[uv](https://docs.astral.sh/uv/)** to make the venv (any Python 3.12 venv also works).
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
| `SYSTEM_PROMPT` | a short Telegram-assistant prompt | replaces the base system prompt |

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
- warns if nothing answers at `$IDLI_BASE_URL/models`, or if `TG_ALLOWED` is empty;
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
   category". Each step the model runs appears in `tg_bridge.log` as
   `[tool step N] ... chars of code -> ...`, and the reply comes back with the number.
3. Ask for a chart ("plot monthly spend"). It comes back as an image.

`/model` shows the model menu, and `/reset` clears the chat's history and its files.

To test without a phone, `tl_session.py` drives the bot as a Telegram user. It needs a
Telegram API app (`telethon_ap_id` and `telethon_app_hash` in
`$SILO_CONFIG/telegram.json`, plus `botfather_bot_name`) and a one-time login with
`tl_login.py`:

```sh
.venv/bin/python tl_session.py /reset "file:../benchmarks/ngo-workbook-correctness/cases/asha_ngo_finances_FY25-26.xlsx|What was our total actual expenditure from April through September 2025, in INR?"
# expect 19,080,600
```

## What runs where

- **Uploads** go to `$WORK_ROOT/<chat id>/` on the host. `/reset` deletes them.
  - The model sees the full text of PDFs, `.txt`, `.md` and `.csv` files, up to about 100k
    characters.
  - For spreadsheets it sees only the first 8 rows of each sheet and computes everything
    else with the tool.
- **The `python` tool:** each call is
  `docker run --rm --network none --read-only --memory 2g --cpus 2 --pids-limit 128`,
  with the chat's folder mounted read-only at `/data` and 60 s to run. It can't write
  to the host or reach any network. This is the attack surface of the bridge
  (`tg-bridge/harness.py`).
- **The model** gets up to 12 tool calls per message, then one final call with tools turned off,
  so a reply always comes back. A llama.cpp HTTP 500 (a malformed tool call) is re-sampled
  up to 3 times.
- **Chat history** is kept in memory, the last 20 turns per chat, and lost on restart.
- **External models** (`/model qwen`, `/model deepseek`) send the conversation, including
  file contents, to OpenRouter. They only appear when an OpenRouter key is
  configured.

## Capacity

One llama.cpp server with `-np 4` answers four chats at once. A fifth waits for a free slot.
On the DGX Spark, Muse Glimmer Q4 with the drafter decodes at about 34 tok/s for a single
stream. A spreadsheet question takes a median of about 4 minutes through this bridge
(`benchmarks/harness-compare`).
