#!/usr/bin/env python3
"""WhatsApp Cloud API <-> LLM bridge.

Receives WhatsApp webhooks, sends the text to an OpenAI-compatible chat
endpoint (OpenRouter by default, or a local server), and replies via the
Graph API. Per-user history is kept in memory.

Env:
  WA_PHONE_NUMBER_ID  required
  WA_VERIFY_TOKEN     webhook verify token (default: idlisseus-verify)
  LLM_BASE_URL        default https://openrouter.ai/api/v1
  LLM_MODEL           default meta/muse-glimmer-30b
  LLM_API_KEY         default: api_key from ~/.config/idlisseus/openrouter.json
  PORT                default 8787
"""
import json
import os
import threading
import urllib.request
from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

CFG = os.path.expanduser("~/.config/idlisseus")
WA = json.load(open(f"{CFG}/wa.json"))
OR = json.load(open(f"{CFG}/openrouter.json"))

WA_TOKEN = WA["wa_access_token"]
PHONE_ID = os.environ.get("WA_PHONE_NUMBER_ID", WA.get("wa_phone_number_id"))
VERIFY_TOKEN = os.environ.get("WA_VERIFY_TOKEN", "idlisseus-verify")
LLM_BASE = os.environ.get("LLM_BASE_URL", "https://openrouter.ai/api/v1")
LLM_MODEL = os.environ.get("LLM_MODEL", "meta/muse-glimmer-30b")
LLM_KEY = os.environ.get("LLM_API_KEY", OR["api_key"])
PORT = int(os.environ.get("PORT", "8787"))
GRAPH = "https://graph.facebook.com/v21.0"
SYSTEM = os.environ.get(
    "SYSTEM_PROMPT",
    "You are a helpful assistant chatting over WhatsApp. Keep replies concise.",
)

history = defaultdict(lambda: deque(maxlen=20))
seen = deque(maxlen=1000)  # Meta retries webhooks; dedupe on message id
locks = defaultdict(threading.Lock)


def post_json(url, body, headers):
    req = urllib.request.Request(
        url, json.dumps(body).encode(), {"Content-Type": "application/json", **headers}
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def llm(user):
    msgs = [{"role": "system", "content": SYSTEM}, *history[user]]
    r = post_json(
        f"{LLM_BASE}/chat/completions",
        {"model": LLM_MODEL, "messages": msgs},
        {"Authorization": f"Bearer {LLM_KEY}"},
    )
    return r["choices"][0]["message"]["content"].strip()


def wa_send(to, text):
    for i in range(0, len(text), 4000):  # WA text limit is 4096
        post_json(
            f"{GRAPH}/{PHONE_ID}/messages",
            {"messaging_product": "whatsapp", "to": to, "type": "text",
             "text": {"body": text[i:i + 4000]}},
            {"Authorization": f"Bearer {WA_TOKEN}"},
        )


def handle(msg):
    user = msg["from"]
    if msg.get("type") != "text":
        wa_send(user, "Sorry, I only understand text messages for now.")
        return
    text = msg["text"]["body"]
    print(f"<- {user}: {text}", flush=True)
    with locks[user]:
        if text.strip().lower() == "/reset":
            history[user].clear()
            wa_send(user, "Conversation reset.")
            return
        history[user].append({"role": "user", "content": text})
        try:
            reply = llm(user)
        except Exception as e:
            print(f"LLM error: {e}", flush=True)
            history[user].pop()
            wa_send(user, "Sorry, the model failed to respond. Try again.")
            return
        history[user].append({"role": "assistant", "content": reply})
    print(f"-> {user}: {reply}", flush=True)
    wa_send(user, reply)


def safe_handle(msg):
    try:
        handle(msg)
    except Exception as e:
        body = getattr(e, "read", lambda: b"")().decode()
        print(f"handle error: {e} {body}", flush=True)


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        q = parse_qs(urlparse(self.path).query)
        if q.get("hub.mode") == ["subscribe"] and q.get("hub.verify_token") == [VERIFY_TOKEN]:
            self._reply(200, q["hub.challenge"][0])
        else:
            self._reply(200 if self.path == "/health" else 403, "ok" if self.path == "/health" else "forbidden")

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        self._reply(200, "ok")  # ack fast, process async
        for entry in body.get("entry", []):
            for ch in entry.get("changes", []):
                for st in ch.get("value", {}).get("statuses", []):
                    print(f"status {st.get('recipient_id')}: {st.get('status')} {st.get('errors', '')}", flush=True)
                for msg in ch.get("value", {}).get("messages", []):
                    if msg["id"] in seen:
                        continue
                    seen.append(msg["id"])
                    threading.Thread(target=safe_handle, args=(msg,), daemon=True).start()

    def _reply(self, code, text):
        self.send_response(code)
        self.end_headers()
        self.wfile.write(text.encode())

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print(f"bridge on :{PORT} model={LLM_MODEL} base={LLM_BASE}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
