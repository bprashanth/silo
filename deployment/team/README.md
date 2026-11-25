# Team laptop setup (Stage 1 — Inner `idli` CLI Loop)

Install Python 3 and [uv](https://docs.astral.sh/uv/) on your laptop. Ask a maintainer to enable your Google test email and share your private config archive (`silo-team-config.tar.gz` or `.zip`, containing `io_oauth_client_gcp.json` and `muse-access.json` with your Cloudflare Access service token for `https://silo.idli.cc`).

## 1. Install

From a clone of this repo:

```bash
./setup.sh \
  --config ~/Downloads/silo-team-config.tar.gz \
  --account you@example.org \
  --sandbox_path ~/idli-sbx/pilot
```

*(You can also pass `--google-client` and `--model-access` separately, or omit `--sandbox_path` to default to `~/.local/share/silo/sandboxes/<account>`. For a source release tarball without a git clone, pass `--bundle /path/to/silo-cli-REV.tar.gz` to `deployment/team/install.py`.)*

The installer creates a Python 3.12 virtualenv, saves credentials at mode `0600` (`~/.config/silo/` and `~/.local/share/silo/config/muse-access.json`), and prints your account launcher path. Alias it for your shell:

```bash
alias idli="$HOME/.local/share/silo/accounts/you@example.org/idli"
```

The launcher routes the 9B mapper, embeddings (`/v1/embeddings`), and cross-encoder reranker (`/v1/rerank`) through `https://silo.idli.cc` using your Cloudflare Access service token, and sets `IDLI_CHIPS=0` and `IDLI_JUDGE=nine_compressed` so **no OpenRouter key is required**.

## 2. Scoped read-only sync (start small with `--in`)

The first interactive `idli sync gmail -v` prints a Google consent URL, opens your browser, saves the read-only refresh token locally, and finishes syncing. Repeat `--in` to share only specific Drive folders or WhatsApp groups:

```bash
idli help
idli sync gmail -v
idli sync gcalendar -v
idli sync drive --in "Strategy Classics" --in "Leads & Partnerships" -v
```

*(If your `silo.idli.cc` router does not yet proxy `/v1/embeddings`, pass `--no-embed` to `sync drive` for lexical + card search.)*

**Optional — WhatsApp (read-only, last 14 days):**
Pair a local read-only `silo-wa-sync` container (`bridges/whatsapp/README.md`) to capture `snapshot.json`, then scope sync with `--in`:

```bash
idli sync whatsapp --from-snapshot ~/.local/share/silo-wa/snapshot.json \
  --in "Jam Buns" --in "Acumen" -v
```

## 3. Understand the deterministic CLI basics (no LLM)

Before using natural language, inspect what is actually stored in your local DuckDB sandbox:

```bash
idli size                                                       # exact row counts per resource
idli list folders                                               # confirm only chosen folders synced
idli list files --group-by kind                                 # exact breakdown by file type
idli list mail --on "last week" --where "direction = 'in' and not is_bulk"
idli list calendar --on "this week"
idli list chats                                                 # confirm only chosen WhatsApp chats synced
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

## 5. Natural-language `ask` (inspect every step with `-v`)

```bash
idli ask -v "how many PDFs are in Strategy Classics?"
idli ask -v "which leads haven't replied this week?"
idli ask -v "there was a doc abhi sent as a followup to a dice call, can you find it in jam buns"
idli ask -v "summarize the latest discussion in acumen"
idli ask -v "draft a reply to <sender> saying I'll review it Friday"   # preview only; never sent
```

Try a follow-up turn without `--new` (e.g. `idli ask -v "who sent that doc?"`) and test trust controls (ask about an unshared group or an out-of-window month like July 2026). Every command and model call is logged in `<sandbox>/log.jsonl`.

---

## Maintainer: cutting bundles

**Config bundle for a teammate** (keep private, never commit to Git):

```bash
tar -czf silo-team-config.tar.gz -C /path/to/creds io_oauth_client_gcp.json muse-access.json
```

`muse-access.json` format (optional `embed_url` / `rerank_url` if served on separate prefixes):

```json
{"url":"https://silo.idli.cc","client_id":"<CF client ID>","client_secret":"<CF client secret>"}
```

**Source release tarball** (from a clean committed revision):

```bash
git archive --format=tar.gz -o "silo-cli-$(git rev-parse --short HEAD).tar.gz" HEAD \
  setup.sh core/idli core/lib core/requirements.txt deployment/team LICENSE
```
