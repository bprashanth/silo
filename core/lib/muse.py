"""Where Muse (Idli's private model) is, and the headers to reach it.

With ~/idli-insights/config/muse-access.json ({"url", "client_id", "client_secret"}: a Cloudflare Access service
token for the person, made by desktop/muse-connect.py) Muse is reached over HTTPS through Cloudflare, e.g.
https://silo.idli.cc. Without it, the old dev route: http://127.0.0.1:8181 through the ssh tunnel.
"""
import json
import os

IDLI = os.environ.get("IDLI_HOME") or os.path.expanduser("~/idli-insights")
ACCESS = os.path.join(IDLI, "config", "muse-access.json")
LOCAL = "http://127.0.0.1:8181"


def access():
    try:
        with open(ACCESS) as f:
            a = json.load(f)
        return a if a.get("url") and a.get("client_id") and a.get("client_secret") else None
    except (OSError, ValueError):
        return None


def base_url():
    if os.environ.get("MUSE_URL"):
        return os.environ["MUSE_URL"].rstrip("/")
    a = access()
    return a["url"].rstrip("/") if a else LOCAL


def headers():
    a = None if os.environ.get("MUSE_URL") else access()
    if not a:
        return {}
    return {"CF-Access-Client-Id": a["client_id"], "CF-Access-Client-Secret": a["client_secret"],
            "User-Agent": "idli"}
