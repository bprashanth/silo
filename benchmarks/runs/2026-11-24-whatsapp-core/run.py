"""End-to-end benchmark of unmodified core/idli ask over first-class chats/messages.
Zero per-question DB views, zero menu pre-search, zero case hints.
Compares `core_rrf` (IDLI_RERANK=0) vs `core_rerank` (IDLI_RERANK=1) on the frozen
2,783-message DGX snapshot and private 24-case bank (8 prior + 12 new + 4 controls),
plus a 12-case reverse-order repeat."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CLI = ROOT / 'core/idli'

fixture = Path(sys.argv[1]).expanduser()
bank_path = Path(sys.argv[2]).expanduser()
out_dir = Path(sys.argv[3]).expanduser()
arms = sys.argv[4:] or ['core_rrf', 'core_rerank']

os.umask(0o077)
out_dir.mkdir(parents=True, exist_ok=True)

snapshot_path = fixture / 'fresh.json'
snapshot_bytes = snapshot_path.read_bytes()
ref_meta = json.loads((ROOT / 'benchmarks/runs/2026-11-23-whatsapp-windows/reference.json').read_text())
if hashlib.sha256(snapshot_bytes).hexdigest() != ref_meta['sha256']:
    raise ValueError('Snapshot checksum mismatch')

groups = json.loads(snapshot_bytes)['groups']
rows = []
for g in groups:
    for r in sorted(g['rows'], key=lambda x: (x['t'], x['id'])):
        rows.append(dict(r, group=g['name'], ref=hashlib.sha256(r['id'].encode()).hexdigest()[:20]))

bank = json.loads(bank_path.read_text())

# Sync once into a clean base sandbox using the standard CLI.
base_sbx = out_dir / 'base_sandbox'
if not (base_sbx / 'store.duckdb').is_file():
    base_sbx.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, 'IDLI_SANDBOX': str(base_sbx), 'IDLI_9B_URL': 'http://127.0.0.1:8291',
           'IDLI_EMBED_URL': 'http://127.0.0.1:8293', 'IDLI_CHIPS': '0'}
    proc = subprocess.run(
        [str(CLI), 'sync', 'whatsapp', '--from-snapshot', str(snapshot_path), '-v'],
        env=env, capture_output=True, text=True, timeout=300,
    )
    if proc.returncode != 0:
        raise RuntimeError(f'sync failed: {proc.stderr}')
    print('SYNC:', proc.stdout.strip(), flush=True)


def run_arm(arm, cases, prefix=''):
    sbx = out_dir / f'sbx_{arm}{prefix}'
    if not (sbx / 'store.duckdb').is_file():
        if sbx.exists():
            shutil.rmtree(sbx)
        shutil.copytree(base_sbx, sbx)
    rerank = '0' if arm == 'core_rrf' else '1'
    env = {
        **os.environ,
        'IDLI_SANDBOX': str(sbx),
        'IDLI_9B_URL': 'http://127.0.0.1:8291',
        'IDLI_EMBED_URL': 'http://127.0.0.1:8293',
        'IDLI_RERANK_URL': 'http://127.0.0.1:8294',
        'IDLI_RERANK': rerank,
        'IDLI_CHIPS': '0',
    }
    log_path = sbx / 'log.jsonl'
    for idx, case in cases:
        out_file = out_dir / f'{arm}{prefix}-{idx:02}.json'
        if out_file.exists():
            continue
        before = log_path.stat().st_size if log_path.exists() else 0
        proc = subprocess.run(
            [str(CLI), 'ask', '--new', '--mapper', 'nine_compressed', '--judge', 'nine_compressed', case['q']],
            env=env, capture_output=True, text=True, timeout=240,
        )
        events = []
        if log_path.exists():
            with log_path.open('rb') as f:
                f.seek(before)
                events = [json.loads(line) for line in f if line.strip()]
        event = next((e for e in reversed(events) if e.get('verb') == 'ask'), {})
        shown = (event.get('steps_shown') or '') + '\n' + (event.get('reply') or '')
        visible_steps = [
            i for i, r in enumerate(rows)
            if r['ref'] in (event.get('steps_shown') or '')
            or (len(r['body']) >= 28 and r['body'][:70] in (event.get('steps_shown') or ''))
        ]
        visible_any = [
            i for i, r in enumerate(rows)
            if r['ref'] in shown or (len(r['body']) >= 28 and r['body'][:70] in shown)
        ]
        out_file.write_text(json.dumps({
            'idx': idx, 'stratum': case.get('stratum'), 'event': event,
            'visible': visible_steps, 'visible_any': visible_any,
            'returncode': proc.returncode, 'stdout': proc.stdout, 'stderr': proc.stderr[:500],
        }))
        print(f'{arm}{prefix} {idx:02} ({case.get("stratum")}) rc={proc.returncode} cmds={len(event.get("commands") or [])} t={event.get("seconds", {}).get("total_s")}s', flush=True)


for arm in arms:
    run_arm(arm, list(enumerate(bank)), prefix='')
    new_rev = [(i, c) for i, c in reversed(list(enumerate(bank))) if c.get('stratum') == 'new']
    run_arm(arm, new_rev, prefix='_repeat')
