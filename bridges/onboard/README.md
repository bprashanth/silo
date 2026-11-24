# Silo Alpha Onboarding Service (`bridges/onboard/`)

Mobile- and desktop-friendly onboarding flow implementing [Signal alpha](../../deployment/alpha/signal.md):

1. **Signal DM trigger** — An invited (or allowed) user messages the Idli Signal bot. The bridge (`bridges/signal/bridge.py` with `IDLI_ONBOARD_STATE`) issues an expiring, single-use setup link bound to their Signal ACI.
2. **Connect accounts (read-only)** — Google Web OAuth with PKCE (`drive.readonly`, `gmail.readonly`, `calendar.readonly`) and/or WhatsApp read-only pairing via `bridges/whatsapp` (`silo-wa-sync`, QR or 8-digit phone code).
3. **Pick scope (`--in`)** — Simple checkboxes for specific Google Drive folders and WhatsApp groups/chats so testers only share what they are comfortable with. Runs `core/idli sync ... --in ...` into that tester's isolated `0700` sandbox directory.
4. **Role & intended use** — Optional form with clickable examples (Insights, Partnerships, Marketing). Deterministically detects Drive links and mentioned folder/group names to suggest scopes, and saves the tester's intent privately in `<sandbox>/profile.json` (`0600`) — strictly outside the 9B mapper prompt so it helps triage future workflows without hurting core CLI accuracy.
5. **Confirm in Signal** — Displays a 6-digit `confirm <code>` command that must be sent from the original Signal DM before the workspace activates (a forwarded URL alone can never activate a mailbox or chat store).

## Local preview (DGX)

```bash
python3 -m bridges.onboard.server \
  --state ~/.local/share/silo-onboard-preview \
  --port 18770 \
  --demo \
  --demo-google-sandbox ~/idli-sbx/silo-smoke \
  --wa-snapshot ~/.local/share/silo-owner-pilot/whatsmeow-smoke/snapshot.json \
  --no-embed \
  --print-demo-url
```

## Multi-tester Signal bridge

```bash
export IDLI_SIGNAL_BOT_ACI="<bot-uuid>"
export IDLI_ONBOARD_STATE="$HOME/.local/share/silo-onboard"
export IDLI_ONBOARD_PUBLIC_BASE="https://silo.idli.cc"
export IDLI_ONBOARD_INVITE_ONLY=1
python3 bridges/signal/bridge.py
```
