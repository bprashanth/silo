#!/usr/bin/env python3
"""Sample host resources without importing inference packages or touching services."""
import argparse
import datetime
import json
from pathlib import Path
import subprocess
import time


def command(args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=8)
    return {"returncode": result.returncode, "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip()}


def sample():
    return {
        "utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "monotonic_ns": time.monotonic_ns(),
        "loadavg": Path('/proc/loadavg').read_text().strip(),
        "meminfo": Path('/proc/meminfo').read_text(),
        "cpu_ticks": Path('/proc/stat').read_text().splitlines()[0],
        "gpu": command(['nvidia-smi', '--query-gpu=name,utilization.gpu,utilization.memory,memory.used,memory.total,power.draw', '--format=csv,noheader,nounits']),
        "gpu_processes": command(['nvidia-smi', '--query-compute-apps=pid,process_name,used_gpu_memory', '--format=csv,noheader,nounits']),
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=float, default=120)
    parser.add_argument('--interval', type=float, default=2)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.interval <= 0 or args.seconds <= 0:
        parser.error('seconds and interval must be positive')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    end = time.monotonic() + args.seconds
    with args.output.open('a') as output:
        while time.monotonic() < end:
            output.write(json.dumps(sample()) + '\n')
            output.flush()
            time.sleep(min(args.interval, max(0, end - time.monotonic())))
