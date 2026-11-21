"""Single-account Signal Note to Self adapter for core/idli."""
import fcntl
import json
import os
import re
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

CLI = Path(__file__).resolve().parents[2] / "core/idli"
SIGNAL = ["docker", "exec", "-i", "silo-signal", "signal-cli", "-d", "/device"]


def question(event, account, local_device):
    envelope = event.get("envelope") or {}
    if envelope.get("sourceDevice") in (None, local_device):
        return
    sent = (envelope.get("syncMessage") or {}).get("sentMessage") or {}
    if sent.get("groupInfo") or sent.get("editMessage"):
        return
    # Signal authenticates sent transcripts as syncs from our own other devices.
    own_uuid = envelope.get("sourceUuid")
    if sent.get("destinationNumber") != account and not (
        own_uuid and sent.get("destinationUuid") == own_uuid
    ):
        return
    body = (sent.get("message") or "").strip()
    parts = body.split(maxsplit=1)
    if parts[:1] == ["/idli"] and len(parts) == 2:
        body = parts[1]
    timestamp = sent.get("timestamp")
    if body and isinstance(timestamp, int):
        return timestamp, body


def signal(*args, message=None):
    proc = subprocess.run(SIGNAL + list(args), input=message or "", text=True,
                          capture_output=True, timeout=90)
    if proc.returncode:
        raise RuntimeError("Signal operation failed")
    return proc.stdout


def ask(body):
    try:
        proc = subprocess.run([CLI, "ask", "--output", "humanize", "--", body], stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        return "Idli timed out. Check the sandbox log before retrying."
    if proc.returncode or not proc.stdout.strip():
        return "Idli could not complete this turn. Check the DGX sandbox log."
    return proc.stdout.strip()


def serve(account, db):
    devices = signal("-a", account, "listDevices")
    match = re.search(r"^- Device (\d+) \(this device\):", devices, re.MULTILINE)
    if not match:
        raise RuntimeError("Cannot identify the bridge device")
    local_device = int(match[1])
    # A process exit mid-ask leaves an ambiguous CLI turn. Never execute it twice.
    with db:
        db.execute("UPDATE turns SET reply=? WHERE started=1 AND reply IS NULL",
                   ("The bridge restarted during this turn. Check the last result before retrying.",))
    while True:
        row = db.execute("SELECT stamp, body, reply FROM turns WHERE delivered=0 ORDER BY stamp LIMIT 1").fetchone()
        if row:
            stamp, body, reply = row
            if reply is None:
                with db:
                    db.execute("UPDATE turns SET started=1 WHERE stamp=?", (stamp,))
                reply = ask(body)
                with db:
                    db.execute("UPDATE turns SET reply=? WHERE stamp=?", (reply, stamp))
            signal("-a", account, "send", "--note-to-self", "--message-from-stdin",
                   message=reply)
            with db:
                db.execute("UPDATE turns SET delivered=1, body=NULL, reply='' WHERE stamp=?", (stamp,))
            continue
        output = signal("-a", account, "-o", "json", "receive", "-t", "5",
                        "--max-messages", "16", "--ignore-attachments", "--ignore-avatars",
                        "--ignore-stickers", "--ignore-stories")
        with db:
            for line in output.splitlines():
                item = question(json.loads(line), account, local_device)
                if item:
                    db.execute("INSERT OR IGNORE INTO turns(stamp,body) VALUES (?,?)", item)


def main():
    os.umask(0o077)
    sandbox = Path(os.environ["IDLI_SANDBOX"])
    if not (sandbox / "store.duckdb").is_file():
        sys.exit("Set IDLI_SANDBOX to a private copy of a synced sandbox.")
    with (sandbox / "signal.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        db = sqlite3.connect(sandbox / "signal.sqlite3")
        db.execute("""CREATE TABLE IF NOT EXISTS turns(
            stamp INTEGER PRIMARY KEY, body TEXT, started INTEGER DEFAULT 0,
            reply TEXT, delivered INTEGER DEFAULT 0)""")
        while True:
            try:
                accounts = json.loads(signal("-o", "json", "listAccounts"))
                if len(accounts) > 1:
                    sys.exit("Use a dedicated container with one linked Signal account.")
                if accounts:
                    serve(accounts[0]["number"], db)
            except (RuntimeError, subprocess.TimeoutExpired):
                print("Signal transport unavailable. Retrying in ten seconds.", file=sys.stderr)
            time.sleep(10)


if __name__ == "__main__":
    main()
