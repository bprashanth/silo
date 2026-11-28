"""Unified Jetson Orin Nano 8GB Quantization & Smaller-Model Shootout Runner.

Runs frozen `core/idli` identically across candidate local models on 3 frozen sandboxes:
  1. `wa_blind_v3`       — 20 strictly unseen WhatsApp cases (single, multi, controls)
  2. `google_owner_dev`  — 11 tasks / 19 turns (Drive PDFs/cards/summarise, Sheets, Gmail, Calendar)
  3. `google_heldout`    — 27 tasks / 32 turns (broad Mail, Calendar, Drive, Sheets, boundaries)
  4. `mixed_google_wa`   — 16 cross-routing cases in ONE combined Google + WhatsApp DuckDB sandbox

Each candidate model (except the existing DGX `idli-9b` baseline on :8291) is spun up in an isolated
llama.cpp container on 127.0.0.1:8299 with Jetson-realistic flags (-c 8192 -np 1 --cache-type-k q8_0
--cache-type-v q8_0, no mmproj), measured for idle & peak container RAM, and torn down cleanly afterward.
"""
import argparse
import hashlib
import json
import os
import shutil
import statistics
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CLI = ROOT / 'core' / 'idli'
VENV_PY = ROOT / 'core' / '.venv' / 'bin' / 'python'
BENCH_PY = ROOT / 'benchmarks' / 'bench.py'
LLAMA_IMAGE = 'ghcr.io/ggml-org/llama.cpp:server-cuda13'
MODELS_HOST = Path('/mnt/seagate/io-models')
TEMP_CONTAINER = 'idli-bench-model'
TEMP_PORT = 8299

ARMS = {
    'qwen35_9b_q5': {
        'label': 'Qwen3.5-9B-Q5_K_M (DGX baseline, 65k ctx)',
        'existing_url': 'http://127.0.0.1:8291',
        'existing_container': 'idli-9b',
        'gguf': 'Qwen3.5-9B-GGUF/Qwen3.5-9B-Q5_K_M.gguf',
        'ctx': 65536,
    },
    'qwen35_9b_q4': {
        'label': 'Qwen3.5-9B-Q4_K_M (Jetson 8k ctx, no mmproj)',
        'gguf': 'Qwen3.5-9B-GGUF/Qwen3.5-9B-Q4_K_M.gguf',
        'ctx': 8192,
        'qwen35_template': True,
    },
    'qwen35_9b_iq4xs': {
        'label': 'Qwen3.5-9B-IQ4_XS (Jetson 8k ctx, no mmproj)',
        'gguf': 'Qwen3.5-9B-GGUF/Qwen3.5-9B-IQ4_XS.gguf',
        'ctx': 8192,
        'qwen35_template': True,
    },
    'qwen35_4b_q5': {
        'label': 'Qwen3.5-4B-Q5_K_M (Jetson 8k ctx, fits w/ embed+rerank)',
        'gguf': 'Qwen3.5-4B-GGUF/Qwen3.5-4B-Q5_K_M.gguf',
        'ctx': 8192,
        'qwen35_template': True,
    },
    'gemma4_e4b_q5': {
        'label': 'Gemma-4-E4B-it-Q5_K_M (Jetson 8k ctx, native jinja)',
        'gguf': 'gemma-4-E4B-it-GGUF/gemma-4-E4B-it-Q5_K_M.gguf',
        'ctx': 8192,
        'qwen35_template': False,
    },
}


def docker_mem(container_name: str) -> dict:
    rss = 'unknown'
    gpu_mib = None
    try:
        out = subprocess.check_output(
            ['docker', 'stats', '--no-stream', '--format', '{{.MemUsage}}', container_name],
            text=True, timeout=15,
        ).strip()
        rss = out.split('/')[0].strip()
    except Exception:
        pass
    try:
        pid = subprocess.check_output(
            ['docker', 'inspect', '-f', '{{.State.Pid}}', container_name],
            text=True, timeout=10,
        ).strip()
        nv = subprocess.check_output(
            ['nvidia-smi', '--query-compute-apps=pid,used_memory', '--format=csv,noheader,nounits'],
            text=True, timeout=10,
        )
        for line in nv.splitlines():
            parts = [p.strip() for p in line.split(',')]
            if len(parts) == 2 and parts[0] == pid:
                gpu_mib = int(parts[1])
                break
    except Exception:
        pass
    return {'rss': rss, 'gpu_mib': gpu_mib}


def stop_temp_container():
    subprocess.run(['docker', 'rm', '-f', TEMP_CONTAINER], capture_output=True)


def start_arm_server(arm_key: str, spec: dict):
    """Return (url, container_name, warmup_info)."""
    gguf_path = MODELS_HOST / spec['gguf']
    if not gguf_path.is_file():
        raise FileNotFoundError(f'Missing GGUF for {arm_key}: {gguf_path}')
    size_gb = round(gguf_path.stat().st_size / (1024 ** 3), 2)

    if spec.get('existing_url'):
        url = spec['existing_url']
        cname = spec['existing_container']
    else:
        stop_temp_container()
        cmd = [
            'docker', 'run', '-d', '--name', TEMP_CONTAINER,
            '--gpus', 'all', '--network', 'host',
            '-v', f'{MODELS_HOST}:/m:ro',
            LLAMA_IMAGE,
            '-m', f'/m/{spec["gguf"]}',
            '--alias', 'qwen3.5-9b',
            '-ngl', '999',
            '-c', str(spec['ctx']),
            '-np', '1',
            '--host', '127.0.0.1',
            '--port', str(TEMP_PORT),
            '--jinja',
            '-fa', 'on',
            '--cache-type-k', 'q8_0',
            '--cache-type-v', 'q8_0',
        ]
        if spec.get('qwen35_template'):
            cmd += [
                '--chat-template-file', '/m/idli9b-bench/templates/qwen35-midsystem.jinja',
                '--chat-template-kwargs', '{"enable_thinking":false}',
            ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f'Failed to start {arm_key}: {proc.stderr}')
        url = f'http://127.0.0.1:{TEMP_PORT}'
        cname = TEMP_CONTAINER

        # Wait up to 90s for /health 200
        ready = False
        for _ in range(90):
            try:
                with urllib.request.urlopen(url + '/health', timeout=2) as r:
                    if r.status == 200:
                        ready = True
                        break
            except Exception:
                pass
            # Check container hasn't exited
            st = subprocess.check_output(
                ['docker', 'inspect', '-f', '{{.State.Running}}', cname], text=True
            ).strip()
            if st != 'true':
                logs = subprocess.check_output(['docker', 'logs', '--tail', '40', cname], text=True, stderr=subprocess.STDOUT)
                raise RuntimeError(f'Container exited early for {arm_key}:\n{logs}')
            time.sleep(1)
        if not ready:
            raise RuntimeError(f'Timed out waiting for {arm_key} health')

    # Smoke-test strict JSON schema compliance (exact same format recstore._nine uses)
    schema = {'type': 'object', 'properties': {'commands': {'type': 'array', 'items': {'type': 'string'}}}, 'required': ['commands']}
    body = {
        'model': 'qwen3.5-9b',
        'temperature': 0,
        'stream': False,
        'max_tokens': 64,
        'messages': [
            {'role': 'system', 'content': 'Return JSON {"commands":["idli help"]}.'},
            {'role': 'user', 'content': 'help'},
        ],
        'response_format': {'type': 'json_schema', 'json_schema': {'name': 'answer', 'schema': schema}},
        'chat_template_kwargs': {'enable_thinking': False},
    }
    t0 = time.time()
    req = urllib.request.Request(url + '/v1/chat/completions', json.dumps(body).encode(), {'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=60) as r:
        resp = json.load(r)
    txt = resp['choices'][0]['message']['content']
    parsed = json.loads(txt)
    warmup_s = round(time.time() - t0, 2)
    mem_idle = docker_mem(cname)
    return url, cname, {
        'arm': arm_key,
        'label': spec['label'],
        'gguf': spec['gguf'],
        'file_size_gb': size_gb,
        'ctx': spec['ctx'],
        'mem_after_warmup': mem_idle,
        'warmup_s': warmup_s,
        'warmup_json_ok': isinstance(parsed.get('commands'), list),
    }


def prepare_base_sandboxes(work_dir: Path, wa_snapshot: Path, google_src: Path):
    base_wa = work_dir / 'base_wa'
    base_google = work_dir / 'base_google'
    base_mixed = work_dir / 'base_mixed'
    env_sync = {
        **os.environ,
        'IDLI_9B_URL': 'http://127.0.0.1:8291',
        'IDLI_EMBED_URL': 'http://127.0.0.1:8293',
        'IDLI_RERANK_URL': 'http://127.0.0.1:8294',
        'IDLI_CHIPS': '0',
    }
    if not (base_wa / 'store.duckdb').is_file():
        base_wa.mkdir(parents=True, exist_ok=True, mode=0o700)
        p = subprocess.run(
            [str(CLI), 'sync', 'whatsapp', '--from-snapshot', str(wa_snapshot), '-v'],
            env={**env_sync, 'IDLI_SANDBOX': str(base_wa)}, capture_output=True, text=True, timeout=300,
        )
        if p.returncode != 0:
            raise RuntimeError(f'base_wa sync failed: {p.stderr}')
        print('Prepared base_wa:', p.stdout.strip(), flush=True)

    if not (base_google / 'store.duckdb').is_file():
        base_google.mkdir(parents=True, exist_ok=True, mode=0o700)
        shutil.copy2(google_src / 'store.duckdb', base_google / 'store.duckdb')
        print('Prepared base_google from', google_src, flush=True)

    if not (base_mixed / 'store.duckdb').is_file():
        base_mixed.mkdir(parents=True, exist_ok=True, mode=0o700)
        shutil.copy2(google_src / 'store.duckdb', base_mixed / 'store.duckdb')
        p = subprocess.run(
            [str(CLI), 'sync', 'whatsapp', '--from-snapshot', str(wa_snapshot), '-v'],
            env={**env_sync, 'IDLI_SANDBOX': str(base_mixed)}, capture_output=True, text=True, timeout=300,
        )
        if p.returncode != 0:
            raise RuntimeError(f'base_mixed sync failed: {p.stderr}')
        print('Prepared base_mixed:', p.stdout.strip(), flush=True)

    return base_wa, base_google, base_mixed


def fresh_copy(src: Path, dst: Path):
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True, exist_ok=True, mode=0o700)
    shutil.copy2(src / 'store.duckdb', dst / 'store.duckdb')


def load_wa_rows(wa_snapshot: Path):
    groups = json.loads(wa_snapshot.read_text())['groups']
    rows = []
    for g in groups:
        for r in sorted(g['rows'], key=lambda x: (x['t'], x['id'])):
            rows.append(dict(r, group=g['name'], ref=hashlib.sha256(r['id'].encode()).hexdigest()[:20]))
    return rows


def run_wa_bank(arm_dir: Path, base_wa: Path, bank_path: Path, wa_rows, url: str):
    out_dir = arm_dir / 'wa_blind_v3'
    out_dir.mkdir(parents=True, exist_ok=True)
    sbx = arm_dir / 'sbx_wa'
    if not (sbx / 'store.duckdb').is_file():
        fresh_copy(base_wa, sbx)
    bank = json.loads(bank_path.read_text())
    env = {
        **os.environ,
        'IDLI_SANDBOX': str(sbx),
        'IDLI_9B_URL': url,
        'IDLI_EMBED_URL': 'http://127.0.0.1:8293',
        'IDLI_RERANK_URL': 'http://127.0.0.1:8294',
        'IDLI_RERANK': '1',
        'IDLI_CHIPS': '0',
    }
    log_path = sbx / 'log.jsonl'
    for idx, case in enumerate(bank):
        out_file = out_dir / f'case-{idx:02}.json'
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
        shown_steps = event.get('steps_shown') or ''
        shown_all = shown_steps + '\n' + (event.get('reply') or '')
        visible = [
            i for i, r in enumerate(wa_rows)
            if r['ref'] in shown_steps or (len(r['body']) >= 28 and r['body'][:70] in shown_steps)
        ]
        visible_any = [
            i for i, r in enumerate(wa_rows)
            if r['ref'] in shown_all or (len(r['body']) >= 28 and r['body'][:70] in shown_all)
        ]
        out_file.write_text(json.dumps({
            'idx': idx, 'stratum': case.get('stratum'), 'event': event,
            'visible': visible, 'visible_any': visible_any,
            'returncode': proc.returncode, 'stderr': proc.stderr[:400],
        }, ensure_ascii=False))
        t_s = (event.get('seconds') or {}).get('total_s')
        print(f'  [wa] {idx:02} ({case.get("stratum")}) rc={proc.returncode} cmds={len(event.get("commands") or [])} err={len(event.get("errors") or [])} t={t_s}s', flush=True)


def run_google_bank(arm_dir: Path, base_google: Path, suite_name: str, tasks_path: Path, url: str):
    out_file = arm_dir / f'{suite_name}.jsonl'
    if out_file.exists() and sum(1 for l in out_file.open() if l.strip()) > 0:
        print(f'  [{suite_name}] already completed ({out_file.name})', flush=True)
        return
    sbx = arm_dir / f'sbx_{suite_name}'
    fresh_copy(base_google, sbx)
    env = {
        **os.environ,
        'IDLI_SANDBOX': str(sbx),
        'IDLI_9B_URL': url,
        'IDLI_EMBED_URL': 'http://127.0.0.1:8293',
        'IDLI_RERANK_URL': 'http://127.0.0.1:8294',
        'IDLI_CHIPS': '0',
    }
    proc = subprocess.run(
        [str(VENV_PY), str(BENCH_PY), 'run',
         '--tasks', str(tasks_path),
         '--mapper', 'nine_compressed', '--judge', 'nine_compressed', '--no-yes',
         '--sandbox', str(sbx), '--out', str(out_file)],
        env=env, capture_output=True, text=True, timeout=1800,
    )
    if proc.returncode != 0:
        print(f'  [{suite_name}] WARN rc={proc.returncode}: {proc.stderr[-300:]}', flush=True)
    else:
        n = sum(1 for l in out_file.open() if l.strip())
        print(f'  [{suite_name}] done ({n} turns)', flush=True)


def run_mixed_bank(arm_dir: Path, base_mixed: Path, bank_path: Path, url: str):
    out_dir = arm_dir / 'mixed_google_wa'
    out_dir.mkdir(parents=True, exist_ok=True)
    sbx = arm_dir / 'sbx_mixed'
    if not (sbx / 'store.duckdb').is_file():
        fresh_copy(base_mixed, sbx)
    bank = json.loads(bank_path.read_text())
    env = {
        **os.environ,
        'IDLI_SANDBOX': str(sbx),
        'IDLI_9B_URL': url,
        'IDLI_EMBED_URL': 'http://127.0.0.1:8293',
        'IDLI_RERANK_URL': 'http://127.0.0.1:8294',
        'IDLI_RERANK': '1',
        'IDLI_CHIPS': '0',
    }
    log_path = sbx / 'log.jsonl'
    for idx, case in enumerate(bank):
        out_file = out_dir / f'case-{idx:02}.json'
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
        out_file.write_text(json.dumps({
            'idx': idx, 'id': case.get('id'), 'stratum': case.get('stratum'),
            'expected_source': case.get('expected_source'), 'event': event,
            'returncode': proc.returncode, 'stderr': proc.stderr[:400],
        }, ensure_ascii=False))
        t_s = (event.get('seconds') or {}).get('total_s')
        print(f'  [mixed] {idx:02} ({case.get("stratum")}) rc={proc.returncode} cmds={len(event.get("commands") or [])} err={len(event.get("errors") or [])} t={t_s}s', flush=True)


def compute_arm_telemetry(arm_dir: Path, wa_bank_path: Path):
    meta = json.loads((arm_dir / 'meta.json').read_text()) if (arm_dir / 'meta.json').is_file() else {}
    wa_bank = json.loads(wa_bank_path.read_text())

    # WA evidence + errors + latency
    wa_pos_ok, wa_pos_tot = 0, 0
    wa_errs, wa_fallbacks, wa_times, prompt_chars = 0, 0, [], []
    for idx, case in enumerate(wa_bank):
        f = arm_dir / 'wa_blind_v3' / f'case-{idx:02}.json'
        if not f.is_file():
            continue
        d = json.loads(f.read_text())
        ev = d.get('event') or {}
        if ev.get('errors'):
            wa_errs += 1
        if ev.get('compose_fallback'):
            wa_fallbacks += 1
        t_s = (ev.get('seconds') or {}).get('total_s')
        if isinstance(t_s, (int, float)):
            wa_times.append(t_s)
        if ev.get('prompt_chars'):
            prompt_chars.append(int(ev['prompt_chars']))
        gold = case.get('gold') or []
        if gold:
            wa_pos_tot += 1
            vis = set(d.get('visible') or [])
            if all(any(r in vis for r in grp) for grp in gold):
                wa_pos_ok += 1

    def _jsonl_stats(path: Path):
        if not path.is_file():
            return {'turns': 0, 'errors': 0, 'mapper_failed': 0, 'fallbacks': 0, 'median_s': 0}
        recs = [json.loads(l) for l in path.open() if l.strip()]
        ts = [r['total_s'] for r in recs if isinstance(r.get('total_s'), (int, float))]
        for r in recs:
            if r.get('prompt_chars'):
                prompt_chars.append(int(r['prompt_chars']))
        return {
            'turns': len(recs),
            'errors': sum(1 for r in recs if r.get('errors')),
            'mapper_failed': sum(1 for r in recs if r.get('needs') == 'mapper_failed'),
            'fallbacks': sum(1 for r in recs if r.get('compose_fallback') and r.get('compose_fallback') not in ('prose_result', 'chat_result')),
            'median_s': round(statistics.median(ts), 2) if ts else 0,
        }

    # Mixed stats
    m_errs, m_map_fail, m_fb, m_times = 0, 0, 0, []
    for f in sorted((arm_dir / 'mixed_google_wa').glob('case-*.json')):
        d = json.loads(f.read_text())
        ev = d.get('event') or {}
        if ev.get('errors'):
            m_errs += 1
        if ev.get('needs') == 'mapper_failed':
            m_map_fail += 1
        if ev.get('compose_fallback') and ev.get('compose_fallback') not in ('prose_result', 'chat_result'):
            m_fb += 1
        t_s = (ev.get('seconds') or {}).get('total_s')
        if isinstance(t_s, (int, float)):
            m_times.append(t_s)
        if ev.get('prompt_chars'):
            prompt_chars.append(int(ev['prompt_chars']))

    return {
        **meta,
        'wa_evidence': f'{wa_pos_ok}/{wa_pos_tot}',
        'wa_errors': wa_errs,
        'wa_fallbacks': wa_fallbacks,
        'wa_median_s': round(statistics.median(wa_times), 2) if wa_times else 0,
        'google_owner_dev': _jsonl_stats(arm_dir / 'google_owner_dev.jsonl'),
        'google_heldout': _jsonl_stats(arm_dir / 'google_heldout.jsonl'),
        'mixed_errors': m_errs,
        'mixed_mapper_failed': m_map_fail,
        'mixed_fallbacks': m_fb,
        'mixed_median_s': round(statistics.median(m_times), 2) if m_times else 0,
        'peak_prompt_chars': max(prompt_chars) if prompt_chars else 0,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--work-dir', required=True)
    ap.add_argument('--wa-snapshot', default='~/.local/share/silo-owner-pilot/windows-xTcFis/fresh.json')
    ap.add_argument('--google-sandbox', default='~/idli-sbx/silo-smoke')
    ap.add_argument('--arms', nargs='*', default=list(ARMS.keys()))
    a = ap.parse_args()

    os.umask(0o077)
    work_dir = Path(a.work_dir).expanduser().resolve()
    wa_snapshot = Path(a.wa_snapshot).expanduser().resolve()
    google_src = Path(a.google_sandbox).expanduser().resolve()
    wa_bank = work_dir / 'wa_blind_v3.json'
    mixed_bank = work_dir / 'mixed_google_wa.json'

    base_wa, base_google, base_mixed = prepare_base_sandboxes(work_dir, wa_snapshot, google_src)
    wa_rows = load_wa_rows(wa_snapshot)

    # Temporarily pause unused idli-9b-bf16 (18 GB CUDA) if we need to spawn candidate containers
    need_temp = any(not ARMS[k].get('existing_url') for k in a.arms)
    paused_bf16 = False
    if need_temp:
        st = subprocess.run(['docker', 'inspect', '-f', '{{.State.Running}}', 'idli-9b-bf16'],
                            capture_output=True, text=True)
        if st.returncode == 0 and st.stdout.strip() == 'true':
            print('Temporarily stopping unused idli-9b-bf16 to free ~24 GiB unified memory for shootout...', flush=True)
            subprocess.run(['docker', 'stop', 'idli-9b-bf16'], check=True)
            paused_bf16 = True
            time.sleep(2)

    summary = {}
    try:
        for arm_key in a.arms:
            spec = ARMS[arm_key]
            arm_dir = work_dir / 'arms' / arm_key
            arm_dir.mkdir(parents=True, exist_ok=True)
            print(f'\n==================== ARM: {arm_key} ({spec["label"]}) ====================', flush=True)
            url, cname, meta = start_arm_server(arm_key, spec)
            print('Server ready:', json.dumps(meta), flush=True)
            (arm_dir / 'meta.json').write_text(json.dumps(meta, indent=2))

            run_wa_bank(arm_dir, base_wa, wa_bank, wa_rows, url)
            run_google_bank(arm_dir, base_google, 'google_owner_dev', ROOT / 'benchmarks/bank/tasks_owner_dev.json', url)
            run_google_bank(arm_dir, base_google, 'google_heldout', ROOT / 'benchmarks/bank/tasks_heldout.json', url)
            run_mixed_bank(arm_dir, base_mixed, mixed_bank, url)

            meta['mem_after_run'] = docker_mem(cname)
            (arm_dir / 'meta.json').write_text(json.dumps(meta, indent=2))
            summary[arm_key] = compute_arm_telemetry(arm_dir, wa_bank)
            print('Telemetry:', json.dumps(summary[arm_key]), flush=True)
            if not spec.get('existing_url'):
                stop_temp_container()
    finally:
        stop_temp_container()
        if paused_bf16:
            print('Restoring idli-9b-bf16...', flush=True)
            subprocess.run(['docker', 'start', 'idli-9b-bf16'], capture_output=True)

    (work_dir / 'telemetry_summary.json').write_text(json.dumps(summary, indent=2))
    print('\n=== ALL ARMS COMPLETE ===', flush=True)


if __name__ == '__main__':
    main()
