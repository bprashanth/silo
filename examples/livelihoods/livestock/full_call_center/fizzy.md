# Optional local Fizzy board

The livestock desk remains authoritative. Fizzy is an independent, read-only presentation of confirmed cases, refreshed by a five-second polling worker. It never modifies a livestock case, assigns a vet, sends Telegram messages, or touches the original Silo bot. Cases in intake and fictional historical seed cases are excluded. Cards include the structured complaint and status, with a link back to the case desk. Phone numbers, Telegram IDs, transcripts and raw media are not copied.

Fizzy is self-hosted on this machine at port **8767**, using the official ARM64 image pinned in `fizzy-compose.yaml`. No case data is uploaded to fizzy.do. The share link is exposed on the same trusted network as the case desk; anyone able to reach it and holding the link can read the mirrored case fields. The native Fizzy interface retains its English navigation; card field names and workflow columns are Hindi.

The native columns are **नए मामले**, **भेंट और प्रतिक्रिया**, and **समीक्षा**. Closed cases move to Fizzy's **Done** section. Operational actions stay in the case desk; this is a one-way mirror, not a second dispatch engine. Refresh the board to see changes (Fizzy may cache a public page for 30 seconds).

## Run or disable

```sh
examples/livelihoods/livestock/full_call_center/fizzy.sh start
examples/livelihoods/livestock/full_call_center/fizzy.sh stop
```

Stopping disables only the mirror and Fizzy container; the dashboard, case history and both bots continue unchanged. Start resumes mirroring. The local service is `silo-livestock-fizzy-sync.service`. Stop also disables automatic startup of the polling worker; start enables it again.

Private SQLite storage, API token, secret, sync checkpoint and log are under `~/.local/share/silo-livestock-fizzy/`. Nothing from that directory belongs in git. The optional integration can be reverted by removing the `examples/livelihoods/livestock/full_call_center/fizzy*` files and dashboard link after stopping it. Keep the existing case database; no rollback or restore of case records is needed. Native Docker layers use this host's existing Docker store; research downloads and screenshots are on Seagate.

## Initial installation

Create the private directory and `storage/`, and a mode-600 `runtime.env` containing a fresh long random `SECRET_KEY_BASE`, `DISABLE_SSL=true`, `BASE_URL=http://100.82.28.38:8767`, and `MAILER_FROM_ADDRESS=livestock@localhost`. The host and port are POC defaults, not public Internet deployment settings.

```sh
docker compose -p livestock -f examples/livelihoods/livestock/full_call_center/fizzy-compose.yaml up -d
docker cp examples/livelihoods/livestock/full_call_center/fizzy-bootstrap.rb silo-livestock-fizzy:/tmp/livestock-bootstrap.rb
docker exec silo-livestock-fizzy bin/rails runner /tmp/livestock-bootstrap.rb
docker cp silo-livestock-fizzy:/rails/storage/livestock-config.json "$HOME/.local/share/silo-livestock-fizzy/config.json"
chmod 600 "$HOME/.local/share/silo-livestock-fizzy/config.json"
examples/livelihoods/livestock/full_call_center/fizzy.sh start
```

The bootstrap creates one local operator identity, account, board, workflow columns and write token for the mirror. It sends no mail. It is safe to rerun. `board_url` in the private config is the read-only browser link; do not print the entire config because it also contains the API token.

## Verification

`python3 -m unittest examples.livelihoods.livestock.full_call_center.fizzy_test` verifies output escaping, private-field exclusion, no publishing of drafts or historical seeds, and recovery of an already-closed card without duplicates. On 16 October, native API validation additionally exercised creation, repeat sync, workflow movement, closure, recovery after lost mirror state and reopening; the temporary synthetic card was deleted. Browser testing opened the read-only board, expanded Done, opened the previous completed synthetic case and inspected its rendered Hindi field labels. Large screenshots live under `/mnt/seagate/silo/livestock-v2/fizzy-*.png`.

The first browser check caught an account prefix missing from the share URL; this was fixed. It also caught duplicate closed cards because Fizzy's default listing omits closed cards. The worker now enumerates open, closed and postponed cards before creating anything, and a regression verifies this recovery path. Duplicate cards created during testing were removed from this isolated instance.

Official references: [Docker deployment](https://github.com/basecamp/fizzy/blob/main/docs/docker-deployment.md), [API](https://github.com/basecamp/fizzy/blob/main/docs/api/README.md).
