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
import zipfile

CONFIG_FILES = {
    'io_oauth_client_gcp.json': ('installed.client_id', 'installed.client_secret'),
    'muse-access.json': ('url', 'client_id', 'client_secret'),
}


def _validate_json_bytes(raw: bytes, label: str, required):
    try:
        data = json.loads(raw.decode('utf-8'))
    except Exception as e:
        raise SystemExit(f'{label} is not valid JSON ({e})')
    for field in required:
        value = data
        for key in field.split('.'):
            value = value.get(key) if isinstance(value, dict) else None
        if not isinstance(value, str) or not value:
            raise SystemExit(f'{label} is missing {field}')
    return data


def install_config_bytes(raw: bytes | None, label: str, target: Path, required):
    if raw is None:
        if not target.is_file():
            raise SystemExit(
                f'Ask a maintainer for {target.name} (or a --config bundle) and pass it to the installer.'
            )
        _validate_json_bytes(target.read_bytes(), str(target), required)
        target.chmod(0o600)
        return
    _validate_json_bytes(raw, label, required)
    if target.exists() and target.read_bytes() != raw:
        raise SystemExit(f'Existing configuration differs at {target}. Move it aside to replace it.')
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        with target.open('xb') as dest:
            dest.write(raw)
    target.chmod(0o600)


def install_config(source: Path | None, target: Path, required):
    raw = source.read_bytes() if source else None
    install_config_bytes(raw, str(source or target), target, required)


def extract_config_bundle(bundle_path: Path):
    """Safely read io_oauth_client_gcp.json and muse-access.json from a .tar.gz/.tgz/.tar/.zip bundle."""
    if not bundle_path.is_file():
        raise SystemExit(f'Config bundle not found: {bundle_path}')
    found = {}
    name_low = bundle_path.name.lower()

    def _safe_basename(member_name: str):
        parts = Path(member_name).parts
        if not parts or any(p in ('..', '/', '\\') for p in parts) or member_name.startswith('/'):
            raise SystemExit(f'Unsafe path in config bundle: {member_name}')
        return parts[-1]

    if name_low.endswith('.zip') or zipfile.is_zipfile(bundle_path):
        with zipfile.ZipFile(bundle_path, 'r') as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                base = _safe_basename(info.filename)
                if base in CONFIG_FILES:
                    found[base] = zf.read(info)
    else:
        try:
            with tarfile.open(bundle_path, 'r:*') as tf:
                for m in tf.getmembers():
                    if m.isdir():
                        continue
                    base = _safe_basename(m.name)
                    if not m.isfile():
                        continue
                    if base in CONFIG_FILES:
                        fobj = tf.extractfile(m)
                        if fobj is not None:
                            found[base] = fobj.read()
        except tarfile.TarError as e:
            raise SystemExit(f'Could not read config archive {bundle_path}: {e}')

    missing = [k for k in CONFIG_FILES if k not in found]
    if missing:
        raise SystemExit(f'Config bundle {bundle_path} is missing: {", ".join(missing)}')
    return found


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--account', required=True, help='Google account email for this sandbox')
    parser.add_argument('--config', type=Path, help='maintainer config tarball (.tar.gz/.tgz) or .zip containing io_oauth_client_gcp.json and muse-access.json')
    parser.add_argument('--sandbox', '--sandbox-path', '--sandbox_path', dest='sandbox_path', type=Path,
                        help='custom sandbox directory path (default: ~/.local/share/silo/sandboxes/<account>)')
    parser.add_argument('--bundle', type=Path, help='silo CLI source tarball')
    parser.add_argument('--google-client', type=Path, help='Google Desktop client JSON (if not using --config)')
    parser.add_argument('--model-access', type=Path, help='maintainer-issued muse-access.json (if not using --config)')
    parser.add_argument('--skip-venv', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    email = args.account.lower().strip()
    if not re.fullmatch(r'[a-z0-9._+%-]+@[a-z0-9.-]+\.[a-z]{2,}', email):
        parser.error('Supply the email address of your Google test account.')
    if not args.skip_venv and not shutil.which('uv'):
        parser.error('Install uv and put it on PATH first: https://docs.astral.sh/uv/')

    os.umask(0o077)
    home = Path.home()
    cfg = Path(os.environ.get('XDG_CONFIG_HOME') or home / '.config') / 'silo'
    data = Path(os.environ.get('XDG_DATA_HOME') or home / '.local/share') / 'silo'

    if args.config:
        bundled = extract_config_bundle(args.config.expanduser())
        install_config_bytes(
            bundled['io_oauth_client_gcp.json'],
            f'{args.config}:io_oauth_client_gcp.json',
            cfg / 'io_oauth_client_gcp.json',
            CONFIG_FILES['io_oauth_client_gcp.json'],
        )
        install_config_bytes(
            bundled['muse-access.json'],
            f'{args.config}:muse-access.json',
            data / 'config/muse-access.json',
            CONFIG_FILES['muse-access.json'],
        )
    else:
        install_config(args.google_client, cfg / 'io_oauth_client_gcp.json', CONFIG_FILES['io_oauth_client_gcp.json'])
        install_config(args.model_access, data / 'config/muse-access.json', CONFIG_FILES['muse-access.json'])

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

    if not args.skip_venv:
        subprocess.run(['uv', 'venv', '--allow-existing', '-p', '3.12', str(core / '.venv')], check=True)
        python = core / '.venv/bin/python'
        subprocess.run(['uv', 'pip', 'install', '-p', str(python), '-r', str(core / 'requirements.txt')], check=True)

    sandbox_dir = args.sandbox_path.expanduser().resolve() if args.sandbox_path else (data / 'sandboxes' / email)
    sandbox_dir.mkdir(parents=True, exist_ok=True, mode=0o700)

    launcher = data / 'accounts' / email / 'idli'
    launcher.parent.mkdir(parents=True, exist_ok=True)
    env = {
        'IDLI_GOOGLE_ACCOUNT': email,
        'IDLI_GOOGLE_CONFIG': str(cfg),
        'IDLI_HOME': str(data),
        'IDLI_SANDBOX': str(sandbox_dir),
        'IDLI_CHIPS': '0',
        'IDLI_JUDGE': 'nine_compressed',
    }
    with tempfile.NamedTemporaryFile(mode='w', dir=launcher.parent, delete=False) as out:
        out.write('#!/bin/sh\numask 077\n')
        for key, val in env.items():
            out.write(f'export {key}=${{{key}:-{shlex.quote(val)}}}\n')
        out.write(f'cd {shlex.quote(str(core))} && exec .venv/bin/python -m lib.idlicli "$@"\n')
    Path(out.name).chmod(0o700)
    os.replace(out.name, launcher)

    q_launcher = shlex.quote(str(launcher))
    print(f'\nInstalled Idli CLI launcher: {launcher}')
    print(f'Sandbox directory:           {sandbox_dir}')
    print('\nQuick start:')
    print(f'  alias idli={q_launcher}')
    print('  idli help')
    print('  idli sync gmail -v')
    print('  idli sync gcalendar -v')
    print('  idli sync drive --in "<Folder Name>" -v')
    print('  idli ask -v "how many emails did I get last week?"')
    return launcher


if __name__ == '__main__':
    main()
