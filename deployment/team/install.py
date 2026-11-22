#!/usr/bin/env python3
"""Install a team CLI from this checkout or its release archive."""
import argparse
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tarfile
import tempfile


def install_config(source, target, required):
    candidate = source or target
    if not candidate.is_file():
        raise SystemExit(f'Ask a maintainer for {target.name} and pass it with the matching installer option.')
    data = json.loads(candidate.read_text())
    for field in required:
        value = data
        for key in field.split('.'):
            value = value.get(key) if isinstance(value, dict) else None
        if not isinstance(value, str) or not value:
            raise SystemExit(f'{candidate} is missing {field}')
    if source and target.exists() and source.read_bytes() != target.read_bytes():
        raise SystemExit(f'Existing configuration differs at {target}. Move it aside to replace it.')
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        with target.open('xb') as dest:
            dest.write(source.read_bytes())
    target.chmod(0o600)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--account', required=True)
    parser.add_argument('--bundle', type=Path, help='silo CLI source tarball')
    parser.add_argument('--google-client', type=Path, help='Google Desktop client JSON')
    parser.add_argument('--model-access', type=Path, help='maintainer-issued muse-access.json')
    args = parser.parse_args()
    email = args.account.lower()
    if not re.fullmatch(r'[a-z0-9._+%-]+@[a-z0-9.-]+\.[a-z]{2,}', email):
        parser.error('Supply the email address of your Google test account.')
    if not shutil.which('uv'):
        parser.error('Install uv and put it on PATH first.')
    os.umask(0o077)
    home = Path.home()
    cfg = Path(os.environ.get('XDG_CONFIG_HOME') or home / '.config') / 'silo'
    data = Path(os.environ.get('XDG_DATA_HOME') or home / '.local/share') / 'silo'
    install_config(args.google_client, cfg / 'io_oauth_client_gcp.json',
                   ('installed.client_id', 'installed.client_secret'))
    install_config(args.model_access, data / 'config/muse-access.json', ('url', 'client_id', 'client_secret'))
    if args.bundle:
        data.mkdir(parents=True, exist_ok=True)
        with tarfile.open(args.bundle, 'r:gz') as archive:
            # Only install regular source files. No paths supplied by the archive may escape this directory.
            prefix = 'core/'
            members = [m for m in archive if m.name.startswith(prefix) and not m.isdir()]
            if not members or any(not m.isfile() or '..' in Path(m.name).parts for m in members):
                parser.error('Invalid CLI bundle')
            core = Path(tempfile.mkdtemp(prefix='release-', dir=data)) / 'core'
            for member in members:
                dest = core.parent / member.name
                dest.parent.mkdir(parents=True, exist_ok=True)
                with dest.open('xb') as out:
                    shutil.copyfileobj(archive.extractfile(member), out)
    else:
        core = Path(__file__).resolve().parents[2] / 'core'
    subprocess.run(['uv', 'venv', '--allow-existing', '-p', '3.12', str(core / '.venv')], check=True)
    python = core / '.venv/bin/python'
    subprocess.run(['uv', 'pip', 'install', '-p', str(python), '-r', str(core / 'requirements.txt')], check=True)
    launcher = data / 'accounts' / email / 'idli'
    launcher.parent.mkdir(parents=True, exist_ok=True)
    env = {'IDLI_GOOGLE_ACCOUNT': email, 'IDLI_GOOGLE_CONFIG': str(cfg), 'IDLI_HOME': str(data),
           'IDLI_SANDBOX': str(data / 'sandboxes' / email)}
    with tempfile.NamedTemporaryFile(mode='w', dir=launcher.parent, delete=False) as out:
        out.write('#!/bin/sh\numask 077\n')
        for key, val in env.items():
            out.write(f'export {key}={shlex.quote(val)}\n')
        out.write(f'cd {shlex.quote(str(core))} && exec .venv/bin/python -m lib.idlicli "$@"\n')
    Path(out.name).chmod(0o700)
    os.replace(out.name, launcher)
    print(f'Run {shlex.quote(str(launcher))} sync gmail -v')


if __name__ == '__main__':
    main()
