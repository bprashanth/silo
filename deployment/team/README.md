# Team laptop setup (Stage 1 — Inner `idli` CLI Loop)

Everything stays **inside this repository directory** (`.env`, `bin/idli`, `.silo/` — all gitignored). Nothing is installed globally. Setup is idempotent: you can re-run `./setup.sh` anytime to refresh credentials or change defaults.

## Prerequisites

- Python 3 and [uv](https://docs.astral.sh/uv/) on your laptop.
- A maintainer-issued config archive (`silo-team-config.tar.gz` or `.zip`) containing `io_oauth_client_gcp.json` (Google Desktop OAuth client) and `silo.json` (your Cloudflare Access service token for `https://silo.idli.cc`).
- *(Optional, WhatsApp only)* Docker installed and running. Gmail, Calendar, and Drive do **not** need Docker.

## 1. Install (repo-local, idempotent)

```bash
git clone <repo-url> && cd silo
./setup.sh --config ~/Downloads/silo-team-config.tar.gz
```

Optional overrides (all have sensible defaults inside `.silo/`):
- `--account you@example.org` — set your Google email immediately (otherwise edit `IDLI_GOOGLE_ACCOUNT` in `.env` before running `idli`; `./bin/idli` fails fast with a reminder if it is unset).
- `--sandbox_path /path/to/sandbox` — store your DuckDB sandbox outside `.silo/sandbox/`.

In any shell (now or later when resuming):

```bash
source .env          # loads your account, sandbox & puts ./bin/idli on PATH
idli help
```

*(You can also run `./bin/idli ...` directly without sourcing `.env` — the launcher loads `.env` automatically.)*

The launcher routes the 9B mapper, embeddings (`/v1/embeddings`), and cross-encoder reranker (`/v1/rerank`) through `https://silo.idli.cc` with your Cloudflare Access token, and sets `IDLI_CHIPS=0` and `IDLI_JUDGE=nine_compressed` so **no OpenRouter key is required**.

## 2. Scoped read-only sync (start small with `--in`)

The first interactive `idli sync gmail -v` prints a Google consent URL, opens your browser, saves the refresh token in `.silo/config/google-tokens/`, and finishes syncing. Repeat `--in` to share only specific Drive folders or WhatsApp groups:

```bash
idli sync gmail -v
idli sync gcalendar -v
idli sync drive --in "Strategy Classics" --in "Leads & Partnerships" -v
```

*(If your router does not yet expose `/v1/embeddings`, pass `--no-embed` to `sync drive` for lexical + card search.)*

**Optional — WhatsApp on your laptop (read-only, last 14 days, requires Docker):**

If Docker is running, `./setup.sh` automatically starts the read-only `bprashanth/silo-wa-sync:latest` container in `.silo/wa/` and prints the browser QR / 8-digit code URL. Re-run `./setup.sh` anytime after a reboot to bring it back up (pass `--no-whatsapp` to skip, or `--whatsapp` to fail fast if Docker is missing):

```bash
# After pairing in the browser URL printed by ./setup.sh:
idli sync whatsapp --in "Jam Buns" --in "Acumen" -v
```

## 3. Understand the deterministic CLI basics (no LLM)

```bash
idli size                                                       # exact row counts per resource
idli list folders                                               # verify only chosen Drive folders synced
idli list files --group-by kind                                 # exact counts by file type
idli list mail --on "last week" --where "direction = 'in' and not is_bulk"
idli list calendar --on "this week"
idli list chats                                                 # verify only chosen WhatsApp chats synced
idli list messages --in "Jam Buns" --where "links <> ''" --count
```

## 4. Direct search, read & summarise

```bash
idli list files --search "border effects"
idli get file "<name>" --outline                                # summary card + pages
idli summarise --search "border effects"                        # grounded summary with file/page citations
idli list messages --in "Jam Buns" --search "dice"
idli get message <ref>                                          # full thread: quoted parent + replies + ±3 neighbors
idli summarise messages --in "Acumen" --search "latest discussion"
```

## 5. Natural-language `ask` (watch every command with `-v`)

```bash
idli ask -v "how many PDFs are in Strategy Classics?"
idli ask -v "which leads haven't replied this week?"
idli ask -v "there was a doc abhi sent as a followup to a dice call, can you find it in jam buns"
idli ask -v "summarize the latest discussion in acumen"
idli ask -v "draft a reply to <sender> saying I'll review it Friday"   # preview only; never sent
```

See [ALPHA_TESTING.md](../../narrative/ALPHA_TESTING.md) for the full Stage 1 + Stage 2 test guide and feedback checklist.

---

## Maintainer: cutting bundles

**Config bundle for a teammate** (keep private, mode `0600`, never commit):

```bash
tar -czf ~/idli-shares/silo/silo-team-config.tar.gz \
  -C ~/.config/idlisseus io_oauth_client_gcp.json silo.json
chmod 600 ~/idli-shares/silo/silo-team-config.tar.gz
```

*(Accepts `silo.json`, `silo-access.json`, or `muse-access.json`; `"url"` defaults to `https://silo.idli.cc` if omitted.)*

**Source release tarball** (from a clean committed revision):

```bash
git archive --format=tar.gz -o "silo-cli-$(git rev-parse --short HEAD).tar.gz" HEAD \
  setup.sh core/idli core/lib core/requirements.txt deployment/team bridges/whatsapp/start.sh LICENSE
```
