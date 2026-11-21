# Ask Idli from Signal

The DGX runs the existing CLI and a linked Signal device. On your phone open
**Note to Self** and send `how many emails are in my sandbox?`. Every text
note you send there from your phone or another linked device becomes an Idli
turn. Reply `yes` to accept a pending card. The old `/idli` prefix also works.
Idli uses `core/idli ask --output humanize` for replies, with short counts, bulleted matches and confirmation by text. The shell defaults to its usual command trace. Linking a device grants it account-level Signal access. You can
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

## Direct messages to the bot

The DGX also has a separate linked device for the bot. This pilot pairs one
tester with one sandbox. In the bot service environment set:

- `IDLI_SIGNAL_BOT_ACI` to the bot's Signal account UUID. The bridge checks
  this against the linked account before receiving messages.
- `IDLI_SIGNAL_PEER_ACI` to the tester's independently verified Signal account
  UUID. Only direct messages from this sender can query the sandbox.
- `IDLI_SANDBOX` to a dedicated copy of that tester's synced store. Use a
  different directory from the Note to Self service so each chat has its own
  history, queue and writer.

Run the same Python entry point as above. The bot transport uses
`silo-signal-bot` and `/opt/bot-cli/bin/signal-cli` (0.14.10 on the DGX)
with its private device keys in `/device`. A numberless bot uses its ACI for
the account selector. A tester's Google account and data must be provisioned
separately before enabling access. Other senders and groups are ignored.
