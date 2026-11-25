"""Where Muse / Idli's private models are, and the Cloudflare Access headers to reach them.

With $IDLI_HOME/config/muse-access.json ({"url", "client_id", "client_secret"}: a Cloudflare Access service
token for the person, optionally plus "embed_url" / "rerank_url") models are reached over HTTPS through
Cloudflare, e.g. https://silo.idli.cc. Without it, the DGX-local loopback services are used directly.
"""
import json
import os

IDLI = os.environ.get("IDLI_HOME") or os.path.expanduser("~/idli-insights")
ACCESS = os.path.join(IDLI, "config", "muse-access.json")
LOCAL = "http://127.0.0.1:8181"
LOCAL_EMBED = "http://127.0.0.1:8293"
LOCAL_RERANK = "http://127.0.0.1:8294"


def _access_path():
    home = os.environ.get("IDLI_HOME")
    if home:
        return os.path.join(os.path.expanduser(home), "config", "muse-access.json")
    return ACCESS


def access():
    try:
        with open(_access_path()) as f:
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
    return {
        "CF-Access-Client-Id": a["client_id"],
        "CF-Access-Client-Secret": a["client_secret"],
        "User-Agent": "idli",
    }


def _service_headers(url, acc):
    if not acc:
        return {}
    base = acc["url"].rstrip("/")
    if url.rstrip("/").startswith(base):
        return {
            "CF-Access-Client-Id": acc["client_id"],
            "CF-Access-Client-Secret": acc["client_secret"],
            "User-Agent": "idli",
        }
    return {}


def embed_upstream():
    """Return (base_url, headers) for /v1/embeddings.
    Uses IDLI_EMBED_URL if set; otherwise routes via muse-access.json (Cloudflare Access) when present,
    falling back to DGX-local 127.0.0.1:8293."""
    acc = access()
    env_url = os.environ.get("IDLI_EMBED_URL")
    if env_url:
        u = env_url.rstrip("/")
        return u, _service_headers(u, acc)
    if acc:
        u = (acc.get("embed_url") or acc["url"]).rstrip("/")
        return u, _service_headers(u, acc)
    return LOCAL_EMBED, {}


def rerank_upstream():
    """Return (base_url, headers) for /v1/rerank.
    Uses IDLI_RERANK_URL if set; otherwise routes via muse-access.json (Cloudflare Access) when present,
    falling back to DGX-local 127.0.0.1:8294."""
    acc = access()
    env_url = os.environ.get("IDLI_RERANK_URL")
    if env_url:
        u = env_url.rstrip("/")
        return u, _service_headers(u, acc)
    if acc:
        u = (acc.get("rerank_url") or acc["url"]).rstrip("/")
        return u, _service_headers(u, acc)
    return LOCAL_RERANK, {}
