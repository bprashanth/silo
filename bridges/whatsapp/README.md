# Read-only WhatsApp sync sidecar (`whatsmeow`)

Lightweight Go container (~25 MB image, ~20 MB RAM) using [`whatsmeow`](https://github.com/tulir/whatsmeow) as a read-only linked device. No write/send methods (`SendMessage`, `MarkRead`, presence updates) are compiled in.

## Smoke test on the DGX

```bash
state="$HOME/.local/share/silo-owner-pilot/whatsmeow-smoke"
install -d -m 700 "$state"
docker build -t silo-wa-sync bridges/whatsapp
docker run -d --name silo-wa-smoke --user "$(id -u):$(id -g)" \
  -p 127.0.0.1:18766:18766 \
  -v "$state:/state" \
  silo-wa-sync --state /state --days 14 --public-base http://127.0.0.1:18766
cat "$state/url"
```

Forward port `18766` from your laptop over SSH (`ssh -L 18766:127.0.0.1:18766 <dgx>`), open the URL in `$state/url`, and link via QR code or the 8-digit phone-number code.

Captured messages (last 14 days by default) are written to `$state/snapshot.json` (mode `0600`), keeping private chat data outside Git.

## Stop / revoke

```bash
docker rm -f silo-wa-smoke
```

Revoke the linked device anytime in WhatsApp → **Linked Devices**.
