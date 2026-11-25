"""Run core/idli for Note to Self or one explicitly paired DM sandbox."""
import fcntl
import json
import os
import re
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
import uuid

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


BOT_SIGNAL = ["docker", "exec", "-i", "silo-signal-bot", "/opt/bot-cli/bin/signal-cli", "-d", "/device"]


def direct_question(event, peer):
    envelope = event.get("envelope") or {}
    data = envelope.get("dataMessage") or {}
    if envelope.get("sourceUuid") != peer or data.get("groupInfo") is not None:
        return
    if data.get("storyContext") or data.get("remoteDelete"):
        return
    body = (data.get("message") or "").strip()
    stamp = data.get("timestamp")
    if (body or data.get("attachments")) and isinstance(stamp, int):
        return stamp, body


def signal(*args, message=None, transport=SIGNAL):
    proc = subprocess.run(transport + list(args), input=message or "", text=True,
                          capture_output=True, timeout=90)
    if proc.returncode:
        raise RuntimeError("Signal operation failed")
    return proc.stdout


def ask(body, sandbox=None, extra_env=None):
    env = dict(os.environ)
    env.setdefault("IDLI_CHIPS", "0")
    if sandbox:
        env["IDLI_SANDBOX"] = str(sandbox)
    if extra_env:
        env.update({k: str(v) for k, v in extra_env.items() if v is not None})
    try:
        proc = subprocess.run([CLI, "ask", "--output", "humanize", "--", body], stdin=subprocess.DEVNULL,
                              env=env, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        return "Idli timed out. Check the sandbox log before retrying."
    if proc.returncode or not proc.stdout.strip():
        return "Idli could not complete this turn. Check the DGX sandbox log."
    return proc.stdout.strip()


def any_direct_message(event):
    """Extract (sender_aci, stamp, body, has_attachment) for any 1:1 DM to the bot."""
    envelope = event.get("envelope") or {}
    data = envelope.get("dataMessage") or {}
    sender = envelope.get("sourceUuid")
    if not sender or data.get("groupInfo") is not None:
        return None
    if data.get("storyContext") or data.get("remoteDelete"):
        return None
    body = (data.get("message") or "").strip()
    stamp = data.get("timestamp")
    has_att = bool(data.get("attachments"))
    if (body or has_att) and isinstance(stamp, int):
        return sender, stamp, body, has_att
    return None


def _coverage_summary(tester):
    cov = tester.get("coverage") or {}
    parts = []
    if tester.get("google_email"):
        folders = tester.get("selected_drive_folders") or []
        g_bits = [f"{len(folders)} Drive folder(s)"]
        if tester.get("sync_gmail"):
            g_bits.append("Gmail")
        if tester.get("sync_calendar"):
            g_bits.append("Calendar")
        parts.append(f"Google ({tester['google_email']}): " + ", ".join(g_bits))
    if tester.get("wa_connected"):
        chats = tester.get("selected_wa_chats") or []
        n_msgs = cov.get("wa_synced_messages", 0)
        parts.append(f"WhatsApp (read-only): {len(chats)} chat(s)" + (f", {n_msgs} messages" if n_msgs else ""))
    return "\n".join("• " + p for p in parts) if parts else "• No sources synced yet."


def handle_multi_turn(store, sender_aci, body, public_base, attachment=False, invite_only=False, ask_fn=ask):
    """Route one direct Signal message using per-tester onboarding bindings (deployment/alpha/signal.md)."""
    text = (body or "").strip()
    low = text.lower()
    base = public_base.rstrip("/")

    m_inv = re.fullmatch(r"(?:/?invite)\s+([A-Za-z0-9_-]+)", text, re.I)
    if m_inv:
        try:
            store.redeem_invite(m_inv.group(1), sender_aci)
        except ValueError as e:
            return str(e)
        tok, _ = store.create_setup_session(sender_aci)
        return (
            "Invite accepted. Open your private setup link to connect Google or WhatsApp and pick only the "
            f"folders or groups you want to share:\n{base}/setup/{tok}\n\n"
            "This link expires in 60 minutes and only works for your Signal account."
        )

    tester = store.get_tester_by_aci(sender_aci)
    if not tester:
        if invite_only:
            return None
        tok, _ = store.create_setup_session(sender_aci)
        return (
            "Hi! I'm Idli — your private, read-only workspace assistant.\n\n"
            "Open this personal setup link to connect Google and/or WhatsApp, choose only the specific "
            "folders or groups you want to share, and tell us how you plan to use Idli:\n"
            f"{base}/setup/{tok}\n\n"
            "Nothing is synced until you pick your scope and confirm back here."
        )

    m_conf = re.fullmatch(r"(?:/?confirm)\s+([0-9 -]+)", text, re.I)
    if m_conf:
        activated, err = store.confirm_from_signal(sender_aci, m_conf.group(1))
        if err:
            return err
        return (
            "You're all set — your private Idli workspace is now active.\n\n"
            + _coverage_summary(activated)
            + "\n\nTry asking a question about your shared folders or chats (or send `status` / `disconnect` anytime)."
        )

    if low in ("disconnect", "/disconnect"):
        store.disconnect_tester(tester["tester_id"], delete_data=True)
        return "Disconnected. Your accounts have been unlinked and your sandbox data was deleted."

    if low in ("setup", "/setup", "reconnect", "/reconnect"):
        tok, _ = store.create_setup_session(sender_aci)
        return f"Here is a fresh setup link to adjust your shared folders or groups:\n{base}/setup/{tok}"

    if tester["status"] != "active":
        if tester["status"] == "awaiting_confirm":
            return (
                "Your setup is almost complete — reply with the 6-digit confirmation code shown on your setup page "
                "(e.g. `confirm 482910`), or send `setup` for a fresh link."
            )
        tok, _ = store.create_setup_session(sender_aci)
        return (
            "Let's finish setting up your private workspace first. Open your setup link:\n"
            f"{base}/setup/{tok}"
        )

    if low in ("status", "/status"):
        return "Workspace active (read-only):\n" + _coverage_summary(tester) + "\n\nSend `setup` to change scope or `disconnect` to erase."

    if attachment:
        return "I can look up files already in your Drive and messages in your synced chats. I can’t upload or share this attachment."

    extra = {"IDLI_GOOGLE_ACCOUNT": tester["google_email"]} if tester.get("google_email") else None
    return ask_fn(text, sandbox=tester["sandbox_dir"], extra_env=extra)


def serve_multi(account, db, store, public_base, invite_only=False):
    """Multi-tester Signal bot loop backed by OnboardStore (one private sandbox per verified ACI)."""
    with db:
        db.execute("UPDATE turns SET reply=? WHERE started=1 AND reply IS NULL",
                   ("The bridge restarted during this turn. Check the last result before retrying.",))
    while True:
        row = db.execute(
            "SELECT sender, stamp, body, attachment, reply FROM turns WHERE delivered=0 ORDER BY stamp LIMIT 1"
        ).fetchone()
        if row:
            sender, stamp, body, attachment, reply = row
            if reply is None:
                with db:
                    db.execute("UPDATE turns SET started=1 WHERE sender=? AND stamp=?", (sender, stamp))
                reply = handle_multi_turn(
                    store, sender, body or "", public_base,
                    attachment=bool(attachment), invite_only=invite_only,
                )
                with db:
                    db.execute("UPDATE turns SET reply=? WHERE sender=? AND stamp=?", (reply or "", sender, stamp))
            if reply:
                signal("-a", account, "send", sender, "--message-from-stdin", message=reply, transport=BOT_SIGNAL)
            with db:
                db.execute("UPDATE turns SET delivered=1, body=NULL, reply='' WHERE sender=? AND stamp=?",
                           (sender, stamp))
            continue
        output = signal("-a", account, "-o", "json", "receive", "-t", "5",
                        "--max-messages", "16", "--ignore-attachments", "--ignore-avatars",
                        "--ignore-stickers", "--ignore-stories", transport=BOT_SIGNAL)
        with db:
            for line in output.splitlines():
                event = json.loads(line)
                item = any_direct_message(event)
                if item:
                    sender, stamp, body, has_att = item
                    db.execute(
                        "INSERT OR IGNORE INTO turns(sender,stamp,body,attachment) VALUES (?,?,?,?)",
                        (sender, stamp, body, 1 if has_att else 0),
                    )


def serve(account, db, peer=None):
    transport = BOT_SIGNAL if peer else SIGNAL
    if peer:
        recipient = [peer]
    else:
        recipient = ["--note-to-self"]
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
            signal("-a", account, "send", *recipient, "--message-from-stdin",
                   message=reply, transport=transport)
            with db:
                db.execute("UPDATE turns SET delivered=1, body=NULL, reply='' WHERE stamp=?", (stamp,))
            continue
        output = signal("-a", account, "-o", "json", "receive", "-t", "5",
                        "--max-messages", "16", "--ignore-attachments", "--ignore-avatars",
                        "--ignore-stickers", "--ignore-stories", transport=transport)
        with db:
            for line in output.splitlines():
                event = json.loads(line)
                item = direct_question(event, peer) if peer else question(event, account, local_device)
                if item:
                    attachment = peer and (event["envelope"].get("dataMessage") or {}).get("attachments")
                    reply = ("I can look up files already in your Drive. I can’t upload or share this attachment."
                             if attachment else None)
                    db.execute("INSERT OR IGNORE INTO turns(stamp,body,reply) VALUES (?,?,?)", (*item, reply))


def main():
    os.umask(0o077)
    onboard_state = os.environ.get("IDLI_ONBOARD_STATE")
    if onboard_state:
        from bridges.onboard.store import OnboardStore
        bot_aci = str(uuid.UUID(os.environ["IDLI_SIGNAL_BOT_ACI"]))
        public_base = os.environ.get("IDLI_ONBOARD_PUBLIC_BASE", "http://127.0.0.1:18770")
        invite_only = os.environ.get("IDLI_ONBOARD_INVITE_ONLY", "0") == "1"
        store = OnboardStore(onboard_state)
        state_path = Path(onboard_state).expanduser()
        with (state_path / "signal-multi.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            db = sqlite3.connect(state_path / "signal-multi.sqlite3")
            db.execute("""CREATE TABLE IF NOT EXISTS turns(
                sender TEXT NOT NULL, stamp INTEGER NOT NULL, body TEXT, attachment INTEGER DEFAULT 0,
                started INTEGER DEFAULT 0, reply TEXT, delivered INTEGER DEFAULT 0,
                PRIMARY KEY (sender, stamp))""")
            while True:
                try:
                    accounts = json.loads(signal("-o", "json", "listAccounts", transport=BOT_SIGNAL))
                    if len(accounts) > 1:
                        sys.exit("Use a dedicated container with one linked Signal account.")
                    if accounts:
                        if accounts[0].get("aci") != bot_aci:
                            sys.exit("Linked account does not match the configured bot.")
                        serve_multi(accounts[0]["number"] or accounts[0]["aci"], db, store, public_base,
                                    invite_only=invite_only)
                except (RuntimeError, subprocess.TimeoutExpired):
                    print("Signal transport unavailable. Retrying in ten seconds.", file=sys.stderr)
                time.sleep(10)
        return

    peer = os.environ.get("IDLI_SIGNAL_PEER_ACI")
    if peer:
        peer = str(uuid.UUID(peer))
        bot_aci = str(uuid.UUID(os.environ["IDLI_SIGNAL_BOT_ACI"]))
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
                accounts = json.loads(signal("-o", "json", "listAccounts", transport=BOT_SIGNAL if peer else SIGNAL))
                if len(accounts) > 1:
                    sys.exit("Use a dedicated container with one linked Signal account.")
                if accounts:
                    if peer and accounts[0].get("aci") != bot_aci:
                        sys.exit("Linked account does not match the configured bot.")
                    serve(accounts[0]["number"] or accounts[0]["aci"], db, peer)
            except (RuntimeError, subprocess.TimeoutExpired):
                print("Signal transport unavailable. Retrying in ten seconds.", file=sys.stderr)
            time.sleep(10)


if __name__ == "__main__":
    main()
