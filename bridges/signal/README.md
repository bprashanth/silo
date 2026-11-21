# Ask Idli from Signal

The DGX runs the existing CLI and a linked Signal device. On your phone open
**Note to Self** and send `/idli how many emails are in my sandbox?`. Prefix
follow-ups too, including `/idli yes` to accept a pending card. Replies appear
in Note to Self. The bridge reads sent-message syncs and processes only prefixed
self notes. Linking a device grants it account-level Signal access. You can
remove **Idli DGX** in Signal's Linked Devices settings.

## DGX setup

From the repo root, complete the [CLI setup](../../README.md#try-it) and check
that your chosen test sandbox works with `core/idli ask`. Copy its database
while the source sandbox is idle, into a fresh directory for Signal. This gives
Signal its own conversation history and DuckDB writer.

```bash
state="$HOME/.local/share/silo-signal"
install -d -m 700 "$state/device" "$state/sandbox"
cp --reflink=auto "$IDLI_SANDBOX/store.duckdb" "$state/sandbox/"
export IDLI_SANDBOX="$state/sandbox"
docker run -d --name silo-signal --restart unless-stopped \
  --user "$(id -u):$(id -g)" -e HOME=/device -v "$state/device:/device" \
  --entrypoint sleep bbernhard/signal-cli-rest-api:0.101 infinity
docker exec -it silo-signal signal-cli -d /device link -n 'Idli DGX'
```

Scan the terminal QR with Signal → Settings → Linked Devices → Link New Device.
Then run `python3 bridges/signal/bridge.py` with the same account and model
environment as the working CLI. The bridge discovers the linked number itself.
Only signal-cli runs inside the container. It publishes no ports. Device keys,
the sandbox and pending replies stay under the private state directory.

Turns run serially. Duplicate timestamps are ignored. After a restart, an
interrupted ask is reported and pending replies are retried. If a send succeeded
just before a crash, you may see its reply twice. A crash while receiving a
batch can lose a note before it reaches the local queue. Resend it if needed.

[signal-cli linked device and command reference](https://github.com/AsamK/signal-cli)
