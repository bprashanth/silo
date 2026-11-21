"""Copy one Google Drive folder (or file) into a chat's workspace.

Two ways in. A service account is used when its key is on the box, else a Google sign-in.

Service account (SILO_CONFIG/drive_sa.json): the folder's owner shares it with the account's
email as a Viewer, then pastes the link. The bot copies it with the account's own token. It
can read only what has been shared with it, and nobody signs in. sa_email() is that address.

Google sign-in flow: the user pastes a Drive link -> the bot replies with a "Sign in with Google" button
-> Google sends the browser back with a one-time code -> the bot swaps it for a short-lived
access token, copies that link only (with every subfolder), writes a manifest, then revokes
the token. Nothing is kept that could read their Drive again; to refresh the copy, they
send the link again.

The scope is drive.readonly, because it's the only Google scope that can read a folder the
app didn't create. Google's consent screen therefore says "see and download all your
Google Drive files"; the bot tells users first that it copies only the link they sent.

Only this module talks to Google. The agents that answer questions still have no network:
they read the copy.

Getting back from Google, two ways:
  OAUTH_REDIRECT is a public https URL that reaches OAUTH_PORT on this box (e.g. Tailscale
    Funnel): the callback server below finishes the sign-in by itself.
  OAUTH_REDIRECT is http://localhost:<port>/... (the default): the browser lands on a page
    that doesn't load; the user copies its address into the chat and paste() finishes it.

Env: SILO_CONFIG/drive_sa.json (a service account key), SILO_CONFIG/google_oauth.json (the OAuth client JSON from Google Cloud Console),
OAUTH_REDIRECT, OAUTH_PORT (default 8791), DRIVE_MAX_MB (default 500), DRIVE_MAX_FILES (2000).
"""
import base64
import csv
import hashlib
import http.server
import json
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

CFG = os.path.expanduser(os.environ.get("SILO_CONFIG", "~/.config/silo"))
PORT = int(os.environ.get("OAUTH_PORT", "8791"))
REDIRECT = os.environ.get("OAUTH_REDIRECT", f"http://localhost:{PORT}/oauth/callback")
MAX_BYTES = int(os.environ.get("DRIVE_MAX_MB", "500")) * 1_000_000
MAX_FILES = int(os.environ.get("DRIVE_MAX_FILES", "2000"))
SCOPE = "https://www.googleapis.com/auth/drive.readonly"
API = "https://www.googleapis.com/drive/v3"
PENDING_TTL = 15 * 60

LINK = re.compile(r"https?://(?:drive|docs)\.google\.com/\S+")
ID_PATTERNS = [r"/folders/([\w-]{10,})", r"/file/d/([\w-]{10,})",
               r"/(?:spreadsheets|document|presentation|drawings)/d/([\w-]{10,})", r"[?&]id=([\w-]{10,})"]
# Google's own formats have no file to download; export each to something the agents can read.
EXPORT = {
    "application/vnd.google-apps.spreadsheet":
        [("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".xlsx")],
    "application/vnd.google-apps.document": [("text/markdown", ".md"), ("text/plain", ".txt")],
    "application/vnd.google-apps.presentation": [("application/pdf", ".pdf")],
    "application/vnd.google-apps.drawing": [("image/png", ".png")],
}
FOLDER = "application/vnd.google-apps.folder"

pending = {}  # state -> {chat, user, file_id, verifier, at}
_lock = threading.Lock()


def client():
    """The OAuth client from Google Cloud Console (Web or Desktop type), or None."""
    try:
        c = json.load(open(os.path.join(CFG, "google_oauth.json")))
    except (OSError, ValueError):
        return None
    return c.get("web") or c.get("installed")


def sa():
    """The service account key from Google Cloud Console, or None."""
    try:
        k = json.load(open(os.path.join(CFG, "drive_sa.json")))
    except (OSError, ValueError):
        return None
    return k if k.get("type") == "service_account" and k.get("private_key") else None


def sa_email():
    return (sa() or {}).get("client_email", "")


def sa_token():
    """A one-hour read-only Drive token for the service account (a signed JWT, signed by openssl)."""
    k = sa()
    b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()
    now = int(time.time())
    body = b64(json.dumps({"alg": "RS256", "typ": "JWT"}).encode()) + "." + b64(json.dumps({
        "iss": k["client_email"], "scope": SCOPE, "aud": "https://oauth2.googleapis.com/token",
        "iat": now, "exp": now + 3600}).encode())
    with tempfile.TemporaryDirectory() as d:  # created 0700
        key = os.path.join(d, "key.pem")
        with open(key, "w") as f:
            f.write(k["private_key"])
        sig = subprocess.run(["openssl", "dgst", "-sha256", "-sign", key], input=body.encode(),
                             capture_output=True, check=True).stdout
    return _post("https://oauth2.googleapis.com/token", {
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": body + "." + b64(sig)})["access_token"]


def find_link(text):
    """(file_or_folder_id, url) for the first Drive link in text, else None."""
    for url in LINK.findall(text or ""):
        for p in ID_PATTERNS:
            m = re.search(p, url)
            if m:
                return m.group(1), url
    return None


def sign_in_url(chat, user, file_id):
    """Start a sign-in for one link; returns the Google URL to send the user to."""
    c = client()
    verifier = secrets.token_urlsafe(48)
    state = secrets.token_urlsafe(16)
    with _lock:
        for s in [s for s, p in pending.items() if time.time() - p["at"] > PENDING_TTL]:
            del pending[s]
        pending[state] = {"chat": chat, "user": user, "file_id": file_id, "verifier": verifier, "at": time.time()}
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "client_id": c["client_id"], "redirect_uri": REDIRECT, "response_type": "code", "scope": SCOPE,
        "state": state, "code_challenge": challenge, "code_challenge_method": "S256",
        "access_type": "online", "prompt": "consent", "include_granted_scopes": "false"})


def _post(url, data):
    req = urllib.request.Request(url, urllib.parse.urlencode(data).encode(),
                                 {"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def finish(state, code):
    """Swap the code for a token. Returns (pending request, token) or raises ValueError."""
    with _lock:
        p = pending.pop(state, None)
    if not p or time.time() - p["at"] > PENDING_TTL:
        raise ValueError("That sign-in link has expired. Send the Drive link again.")
    c = client()
    tok = _post("https://oauth2.googleapis.com/token", {
        "client_id": c["client_id"], "client_secret": c.get("client_secret", ""), "code": code,
        "code_verifier": p["verifier"], "grant_type": "authorization_code", "redirect_uri": REDIRECT})
    return p, tok["access_token"]


def revoke(token):
    try:
        _post("https://oauth2.googleapis.com/revoke", {"token": token})
    except Exception:
        pass  # it expires within the hour anyway


# ---- copying -------------------------------------------------------------------------------

def _get(token, path, params=None, raw=False):
    url = f"{API}/{path}?" + urllib.parse.urlencode({**(params or {}), "supportsAllDrives": "true"})
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.read() if raw else json.load(r)


def _safe(name):
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name).strip(" .") or "untitled"
    return name[:120]


class NoAccess(Exception):
    """The link itself can't be opened: not shared with this account, or deleted."""


def copy(token, file_id, dest_root, progress=lambda s: None):
    """Copy a folder tree (or one file) to dest_root/<name>. Returns a summary dict.
    Writes _drive_manifest.csv at the top: path, Drive link, type, modified, owner, note."""
    FIELDS = "id,name,mimeType,size,modifiedTime,webViewLink,owners(emailAddress),shortcutDetails"
    try:
        top = _get(token, f"files/{file_id}", {"fields": FIELDS})
    except urllib.error.HTTPError as e:
        if e.code in (403, 404):
            raise NoAccess(e.code)
        raise
    root = os.path.join(dest_root, _safe(top["name"]))
    if os.path.exists(root):
        shutil.rmtree(root) if os.path.isdir(root) else os.remove(root)
    rows, totals = [], {"files": 0, "bytes": 0, "folders": 0, "skipped": 0}

    def save(item, path):
        mime, note = item["mimeType"], ""
        if mime.startswith("application/vnd.google-apps.") and mime not in EXPORT:
            totals["skipped"] += 1
            return "skipped: no downloadable form", path
        if totals["files"] >= MAX_FILES or totals["bytes"] >= MAX_BYTES:
            totals["skipped"] += 1
            return "skipped: copy limit reached", path
        if mime in EXPORT:
            for target, ext in EXPORT[mime]:
                try:
                    data = _get(token, f"files/{item['id']}/export", {"mimeType": target}, raw=True)
                    path += ext
                    note = f"exported as {ext}"
                    break
                except urllib.error.HTTPError as e:
                    err = e
            else:
                totals["skipped"] += 1
                return f"skipped: export failed ({err.code})", path
        else:
            if int(item.get("size") or 0) + totals["bytes"] > MAX_BYTES:
                totals["skipped"] += 1
                return "skipped: too large for the copy limit", path
            data = _get(token, f"files/{item['id']}", {"alt": "media"}, raw=True)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
        totals["files"] += 1
        totals["bytes"] += len(data)
        if totals["files"] % 25 == 0:
            progress(f"Copied {totals['files']} files so far…")
        return note, path

    def walk(item, path):
        if item["mimeType"] == "application/vnd.google-apps.shortcut":
            note = "skipped: shortcut to something outside this link"
            totals["skipped"] += 1
        elif item["mimeType"] == FOLDER:
            os.makedirs(path, exist_ok=True)
            totals["folders"] += 1
            note, token_ = "", None
            while True:
                r = _get(token, "files", {"q": f"'{item['id']}' in parents and trashed=false",
                                          "fields": f"nextPageToken,files({FIELDS})", "pageSize": 1000,
                                          "includeItemsFromAllDrives": "true", "orderBy": "folder,name",
                                          **({"pageToken": token_} if token_ else {})})
                for child in r.get("files", []):
                    walk(child, os.path.join(path, _safe(child["name"])))
                token_ = r.get("nextPageToken")
                if not token_:
                    break
        else:
            note, path = save(item, path)
        rows.append([os.path.relpath(path, os.path.dirname(root)), item.get("webViewLink", ""),
                     "folder" if item["mimeType"] == FOLDER else item["mimeType"],
                     item.get("modifiedTime", ""), ",".join(o.get("emailAddress", "") for o in item.get("owners") or []),
                     note])

    walk(top, root)
    manifest_dir = root if top["mimeType"] == FOLDER else dest_root
    with open(os.path.join(manifest_dir, "_drive_manifest.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["path", "drive_link", "type", "modified", "owner", "note"])
        w.writerows(sorted(rows))
    return {"name": top["name"], "is_folder": top["mimeType"] == FOLDER, **totals,
            "skipped_items": [r[0] for r in rows if r[5].startswith("skipped")][:10]}


def summary_text(s, signed_in=False):
    mb = s["bytes"] / 1e6
    what = (f"the folder “{s['name']}”: {s['files']} files in {s['folders']} folders ({mb:.1f} MB)"
            if s["is_folder"] else f"“{s['name']}” ({mb:.1f} MB)")
    out = f"✓ Copied {what} from Google Drive to this box."
    if signed_in:
        out += " I've signed out of your Google account."
    if s["skipped"]:
        out += f"\nSkipped {s['skipped']} item(s): " + ", ".join(s["skipped_items"])
    return out + "\nAsk me anything about it. To refresh the copy later, send the link again."


# ---- getting back from Google ----------------------------------------------------------------

def parse_redirect(text):
    """(state, code) from a pasted redirect URL, else None."""
    m = re.search(r"\S*[?&]code=[^\s]+", text or "")
    if not m or "state=" not in m.group(0):
        return None
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(m.group(0)).query)
    return (qs["state"][0], qs["code"][0]) if "state" in qs and "code" in qs else None


def serve(on_code):
    """Callback server for a public OAUTH_REDIRECT: on_code(state, code) runs the copy."""
    path = urllib.parse.urlparse(REDIRECT).path or "/"

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            u = urllib.parse.urlparse(self.path)
            qs = urllib.parse.parse_qs(u.query)
            ok = u.path == path and "state" in qs and "code" in qs
            if ok:
                threading.Thread(target=on_code, args=(qs["state"][0], qs["code"][0]), daemon=True).start()
            body = ("<p style='font:20px sans-serif;margin:2em'>" +
                    ("Signed in. Go back to Telegram; your copy is on its way." if ok
                     else "Nothing to do here.") + "</p>").encode()
            self.send_response(200 if ok else 404)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass  # the query string holds the code

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv
