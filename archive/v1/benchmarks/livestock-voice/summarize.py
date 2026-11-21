#!/usr/bin/env python3
"""Summarize selected saved browser calls; retain each run's quality checks."""
import argparse
import json
from pathlib import Path


def percentile(values, p):
    if not values:
        return None
    values = sorted(values)
    pos = (len(values)-1)*p
    lo = int(pos)
    hi = min(lo+1, len(values)-1)
    return round(values[lo]*(hi-pos)+values[hi]*(pos-lo), 1) if hi != lo else round(values[lo], 1)


def summarize(path):
    record = json.loads((path/'record.json').read_text())
    browser = record.get('browser_metrics', []) or record.get('events', [])
    samples = [e['speech_end_to_audible_ms'] for e in browser
               if e.get('type') == 'browser_first_audio' and e.get('speech_end_to_audible_ms', -1) >= 0]
    metrics = record.get('metrics', [])
    checks = json.loads((path/'checks.json').read_text()) if (path/'checks.json').exists() else {}
    return {'run': path.name, 'backend': record.get('backend'), 'browser_onset_sample_ms': samples,
            'browser_p50_ms': percentile(samples, .50), 'browser_p90_ms': percentile(samples, .90),
            'browser_p95_ms': percentile(samples, .95),
            'asr_samples_ms': [m['asr_ms'] for m in metrics if 'asr_ms' in m],
            'observed_cost_usd': sum(m.get('observed_cost_usd') or 0 for m in metrics) if any(m.get('observed_cost_usd') is not None for m in metrics) else None,
            'checks': checks, 'fields': record.get('fields'),
            'measurement_scope': 'Synthetic browser received audio RMS onset, not physical speaker output. Selected call; inspect interrupted-turn events separately.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('runs', type=Path, nargs='+')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = [summarize(path) for path in args.runs]
    text = json.dumps(result, indent=2)+'\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text)
    else:
        print(text)
