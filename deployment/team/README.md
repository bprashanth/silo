# Team laptop setup

Install Python 3 and uv on the laptop. Ask a maintainer to enable your Google test email, provide the Desktop OAuth client JSON and issue a DGX model access JSON for your laptop. From the clone run:

```sh
python3 deployment/team/install.py --account you@example.org \
  --google-client ~/Downloads/io_oauth_client_gcp.json \
  --model-access ~/Downloads/muse-access.json
```

For the release snapshot, pass `--bundle /path/to/silo-cli-REV.tar.gz` to the same script. The tarball contains the CLI source, dependency list, installer and this guide. A recipient without a clone can extract the installer with `tar -xzf silo-cli-REV.tar.gz deployment/team/install.py`. Obtain the expected SHA-256 from the maintainer and compare it with `shasum -a 256` before use.

Run the printed command. It opens Google on the laptop, saves the grant locally and continues the requested sync. Use that same launcher for `sync gcalendar`, `sync drive --no-embed` and `ask`. Each account has its own launcher and sandbox. They live under `$XDG_DATA_HOME/silo` (default `~/.local/share/silo`). The Desktop client and per-account Google tokens live under `$XDG_CONFIG_HOME/silo` (default `~/.config/silo`). On subsequent installs on that laptop you can omit both credential-file arguments.

The bundle ships source only. uv installs Python 3.12 and the requirements using a network connection or its cache. Hosted judging and Drive embeddings have additional service settings in the [manual setup](../../README.md#try-it). For a new release, run from a clean committed revision:

```sh
git archive --format=tar.gz -o "silo-cli-$(git rev-parse --short HEAD).tar.gz" HEAD \
  core/idli core/lib core/requirements.txt deployment/team LICENSE
```
