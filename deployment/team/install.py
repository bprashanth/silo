#!/usr/bin/env python3
"""Idempotent, repo-local team CLI setup for Silo (no global installs).

Everything stays inside the repository directory (all gitignored):
  .env                  — shell env vars (user sets IDLI_GOOGLE_ACCOUNT here or via --account)
  bin/idli              — launcher that loads .env and fails cleanly if IDLI_GOOGLE_ACCOUNT is unset
  .silo/config/         — 0600 credentials (io_oauth_client_gcp.json, silo.json, google-tokens/)
  .silo/sandbox/        — default DuckDB sandbox (override with --sandbox_path or IDLI_SANDBOX in .env)
  .silo/wa/             — optional local WhatsApp sidecar state + snapshot.json
"""
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

DEFAULT_MODEL_URL = 'https://silo.idli.cc'
GOOGLE_CLIENT_NAME = 'io_oauth_client_gcp.json'
ACCESS_NAMES = ('silo.json', 'silo-access.json', 'muse-access.json')


def _validate_google_json(raw: bytes, label: str):
    try:
        data = json.loads(raw.decode('utf-8'))
    except Exception as e:
        raise SystemExit(f'{label} is not valid JSON ({e})')
    inst = data.get('installed') if isinstance(data, dict) else None
    if not isinstance(inst, dict) or not inst.get('client_id') or not inst.get('client_secret'):
        raise SystemExit(f'{label} is missing installed.client_id or installed.client_secret')
    return raw


def _normalize_access_json(raw: bytes, label: str) -> bytes:
    try:
        data = json.loads(raw.decode('utf-8'))
    except Exception as e:
        raise SystemExit(f'{label} is not valid JSON ({e})')
    if not isinstance(data, dict) or not data.get('client_id') or not data.get('client_secret'):
        raise SystemExit(f'{label} is missing client_id or client_secret')
    if not data.get('url'):
        data['url'] = DEFAULT_MODEL_URL
    return (json.dumps(data, indent=2) + '\n').encode('utf-8')


def _write_secret_atomic(target: Path, data: bytes):
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile(mode='wb', dir=target.parent, delete=False) as tmp:
        tmp.write(data)
        tmp_path = Path(tmp.name)
    tmp_path.chmod(0o600)
    os.replace(tmp_path, target)


def extract_config_bundle(bundle_path: Path):
    """Safely read io_oauth_client_gcp.json and silo.json/silo-access.json/muse-access.json from tar/zip."""
    if not bundle_path.is_file():
        raise SystemExit(f'Config bundle not found: {bundle_path}')
    google_raw = None
    access_raw = None
    access_name = None

    def _safe_basename(member_name: str):
        parts = Path(member_name).parts
        if not parts or any(p in ('..', '/', '\\') for p in parts) or member_name.startswith('/'):
            raise SystemExit(f'Unsafe path in config bundle: {member_name}')
        return parts[-1]

    if bundle_path.name.lower().endswith('.zip') or zipfile.is_zipfile(bundle_path):
        with zipfile.ZipFile(bundle_path, 'r') as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                base = _safe_basename(info.filename)
                if base == GOOGLE_CLIENT_NAME:
                    google_raw = zf.read(info)
                elif base in ACCESS_NAMES and access_raw is None:
                    access_raw = zf.read(info)
                    access_name = base
    else:
        try:
            with tarfile.open(bundle_path, 'r:*') as tf:
                for m in tf.getmembers():
                    if m.isdir():
                        continue
                    base = _safe_basename(m.name)
                    if not m.isfile():
                        continue
                    if base == GOOGLE_CLIENT_NAME:
                        fobj = tf.extractfile(m)
                        if fobj is not None:
                            google_raw = fobj.read()
                    elif base in ACCESS_NAMES and access_raw is None:
                        fobj = tf.extractfile(m)
                        if fobj is not None:
                            access_raw = fobj.read()
                            access_name = base
        except tarfile.TarError as e:
            raise SystemExit(f'Could not read config archive {bundle_path}: {e}')

    missing = []
    if google_raw is None:
        missing.append(GOOGLE_CLIENT_NAME)
    if access_raw is None:
        missing.append('silo.json (or muse-access.json)')
    if missing:
        raise SystemExit(f'Config bundle {bundle_path} is missing: {", ".join(missing)}')
    return google_raw, access_raw, access_name


def parse_existing_env(env_path: Path):
    vals = {}
    if not env_path.is_file():
        return vals
    for line in env_path.read_text().splitlines():
        s = line.strip()
        if not s or s.startswith('#'):
            continue
        if s.startswith('export '):
            s = s[7:].strip()
        if '=' not in s:
            continue
        k, v = s.split('=', 1)
        k = k.strip()
        v = v.strip()
        try:
            parts = shlex.split(v)
            v = parts[0] if parts else ''
        except ValueError:
            v = v.strip('"\'')
        vals[k] = v
    return vals


def write_env_file(env_path: Path, repo_root: Path, account: str, sandbox_dir: Path, silo_dir: Path):
    cfg_dir = silo_dir / 'config'
    wa_snap = silo_dir / 'wa' / 'snapshot.json'
    lines = [
        '# Silo repo-local environment (gitignored). Generated by ./setup.sh — edit as needed.',
        '# Source this file in a new shell:  source .env',
        '',
        '# Required: set your Google account email here (or re-run ./setup.sh --account you@example.org)',
        f'export IDLI_GOOGLE_ACCOUNT={shlex.quote(account)}',
        '',
        '# Repo-local sandbox & credentials (overrideable)',
        f'export IDLI_SANDBOX={shlex.quote(str(sandbox_dir))}',
        f'export IDLI_GOOGLE_CONFIG={shlex.quote(str(cfg_dir))}',
        f'export IDLI_HOME={shlex.quote(str(silo_dir))}',
        f'export IDLI_WHATSAPP_SNAPSHOT={shlex.quote(str(wa_snap))}',
        '',
        '# DGX-only private defaults (no OpenRouter key required)',
        'export IDLI_CHIPS=0',
        'export IDLI_JUDGE=nine_compressed',
        '',
        '# Put ./bin/idli on PATH for this shell',
        f'case ":$PATH:" in *":{repo_root / "bin"}:"*) ;; *) export PATH={shlex.quote(str(repo_root / "bin"))}:"$PATH" ;; esac',
        '',
    ]
    _write_secret_atomic(env_path, '\n'.join(lines).encode('utf-8'))


def write_launcher(launcher: Path, repo_root: Path, core_dir: Path, env_path: Path):
    launcher.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    script = f"""#!/usr/bin/env bash
set -euo pipefail
umask 077
REPO_ROOT={shlex.quote(str(repo_root))}
ENV_FILE={shlex.quote(str(env_path))}
if [ -f "$ENV_FILE" ]; then
  # Load repo-local defaults without clobbering explicit shell overrides
  while IFS= read -r _line; do
    case "$_line" in
      "export "*)
        _kv="${{_line#export }}"
        _k="${{_kv%%=*}}"
        if [ "$_k" != "PATH" ] && [ -z "${{!_k+x}}" ]; then
          eval "$_line"
        fi
        ;;
    esac
  done < "$ENV_FILE"
fi
if [ -z "${{IDLI_GOOGLE_ACCOUNT:-}}" ]; then
  case "${{1:-}}" in
    help|-h|--help|date) ;;
    *)
      echo "Error: IDLI_GOOGLE_ACCOUNT is not set." >&2
      echo "Set it in $ENV_FILE (e.g. export IDLI_GOOGLE_ACCOUNT='you@example.org') or re-run ./setup.sh --account you@example.org" >&2
      exit 2
      ;;
  esac
fi
cd {shlex.quote(str(core_dir))}
exec .venv/bin/python -m lib.idlicli "$@"
"""
    with tempfile.NamedTemporaryFile(mode='w', dir=launcher.parent, delete=False) as tmp:
        tmp.write(script)
        tmp_path = Path(tmp.name)
    tmp_path.chmod(0o700)
    os.replace(tmp_path, launcher)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, help='maintainer config tarball (.tar.gz/.tgz) or .zip containing io_oauth_client_gcp.json and silo.json (or muse-access.json)')
    parser.add_argument('--account', default='', help='Google account email (optional; can also be set later in .env)')
    parser.add_argument('--sandbox', '--sandbox-path', '--sandbox_path', dest='sandbox_path', type=Path,
                        help='custom sandbox directory path (default: <repo>/.silo/sandbox)')
    parser.add_argument('--bundle', type=Path, help='silo CLI source tarball (optional, if running outside a git clone)')
    parser.add_argument('--google-client', type=Path, help='Google Desktop client JSON (if not using --config)')
    parser.add_argument('--model-access', type=Path, help='Cloudflare Access JSON: silo.json or muse-access.json (if not using --config)')
    parser.add_argument('--root', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--skip-venv', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    os.umask(0o077)
    repo_root = (args.root.expanduser().resolve() if args.root else Path(__file__).resolve().parents[2])
    silo_dir = repo_root / '.silo'
    cfg_dir = silo_dir / 'config'
    cfg_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    env_path = repo_root / '.env'
    existing_env = parse_existing_env(env_path)

    account = (args.account or existing_env.get('IDLI_GOOGLE_ACCOUNT') or '').strip().lower()
    if account and not re.fullmatch(r'[a-z0-9._+%-]+@[a-z0-9.-]+\.[a-z]{2,}', account):
        parser.error(f'Invalid email address: {account}')

    if not args.skip_venv and not shutil.which('uv'):
        parser.error('Install uv and put it on PATH first: https://docs.astral.sh/uv/')

    # 1. Install/refresh credentials idempotently inside <repo>/.silo/config/
    google_target = cfg_dir / GOOGLE_CLIENT_NAME
    access_target = cfg_dir / 'silo.json'
    if args.config:
        g_raw, a_raw, a_name = extract_config_bundle(args.config.expanduser())
        _write_secret_atomic(google_target, _validate_google_json(g_raw, f'{args.config}:{GOOGLE_CLIENT_NAME}'))
        _write_secret_atomic(access_target, _normalize_access_json(a_raw, f'{args.config}:{a_name}'))
    else:
        if args.google_client:
            p = args.google_client.expanduser()
            _write_secret_atomic(google_target, _validate_google_json(p.read_bytes(), str(p)))
        elif not google_target.is_file():
            raise SystemExit(
                f'Missing {google_target.name}. Pass --config /path/to/silo-team-config.tar.gz '
                '(or --google-client and --model-access).'
            )
        if args.model_access:
            p = args.model_access.expanduser()
            _write_secret_atomic(access_target, _normalize_access_json(p.read_bytes(), str(p)))
        elif not any((cfg_dir / fn).is_file() for fn in ACCESS_NAMES):
            raise SystemExit(
                'Missing silo.json (Cloudflare Access token). Pass --config /path/to/silo-team-config.tar.gz '
                '(or --model-access /path/to/silo.json).'
            )

    # 2. Resolve core/ (either this checkout or extracted from --bundle into .silo/release/)
    if args.bundle:
        with tarfile.open(args.bundle.expanduser(), 'r:gz') as archive:
            prefix = 'core/'
            members = [m for m in archive if m.name.startswith(prefix) and not m.isdir()]
            if not members or any(not m.isfile() or '..' in Path(m.name).parts for m in members):
                parser.error('Invalid CLI bundle')
            rel_dir = silo_dir / 'release'
            if rel_dir.exists():
                shutil.rmtree(rel_dir)
            core_dir = rel_dir / 'core'
            for member in members:
                dest = rel_dir / member.name
                dest.parent.mkdir(parents=True, exist_ok=True)
                with dest.open('wb') as out:
                    shutil.copyfileobj(archive.extractfile(member), out)
    else:
        core_dir = repo_root / 'core'

    if not args.skip_venv:
        subprocess.run(['uv', 'venv', '--allow-existing', '-p', '3.12', str(core_dir / '.venv')], check=True)
        python = core_dir / '.venv/bin/python'
        subprocess.run(['uv', 'pip', 'install', '-p', str(python), '-r', str(core_dir / 'requirements.txt')], check=True)

    # 3. Sandbox dir (flag > existing .env > repo-local .silo/sandbox)
    if args.sandbox_path:
        sandbox_dir = args.sandbox_path.expanduser().resolve()
    elif existing_env.get('IDLI_SANDBOX'):
        sandbox_dir = Path(existing_env['IDLI_SANDBOX']).expanduser().resolve()
    else:
        sandbox_dir = silo_dir / 'sandbox'
    sandbox_dir.mkdir(parents=True, exist_ok=True, mode=0o700)

    # 4. Write repo-local .env and ./bin/idli
    write_env_file(env_path, repo_root, account, sandbox_dir, silo_dir)
    launcher = repo_root / 'bin' / 'idli'
    write_launcher(launcher, repo_root, core_dir, env_path)

    print(f'\nSilo CLI ready inside {repo_root} (nothing installed globally).')
    print(f'  Env file:  {env_path}')
    print(f'  Launcher:  {launcher}')
    print(f'  Sandbox:   {sandbox_dir}')
    if not account:
        print('\nNext step — set your Google email in .env:')
        print(f'  $EDITOR {env_path}   # set IDLI_GOOGLE_ACCOUNT="you@example.org"')
        print('  # or re-run: ./setup.sh --account you@example.org')
    print('\nTo use `idli` in this or any new shell:')
    print('  source .env')
    print('  idli help')
    print('  idli sync gmail -v')
    print('  idli sync gcalendar -v')
    print('  idli sync drive --in "<Folder Name>" -v')
    print('  idli sync whatsapp --in "<Group Name>" -v   # after pairing via ./setup.sh WhatsApp URL')
    print('  idli ask -v "how many emails did I get last week?"')
    return launcher


if __name__ == '__main__':
    main()
