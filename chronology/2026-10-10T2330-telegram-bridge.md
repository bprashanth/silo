# Telegram bridge

`tg-bridge/tg_bridge.py` long-polls the Telegram Bot API (`getUpdates`). There
is no webhook and no listening port, so nothing on the internet can reach the
model server; the bridge only makes outbound requests.

Supported inputs: text, PDF (pdftotext), xlsx/xls (openpyxl; soffice converts
.xls), txt/md/csv, and png/jpeg as images. Anything else gets an "unsupported"
reply instead of a guess. Access is limited by `TG_ALLOWED` (currently the
owner only: `redpig,7196436554`).

End-to-end tests run as the owner's Telegram account through Telethon
(`tl_login.py`, `tl_roundtrip.py`, `tl_session.py`), so the bot is tested exactly
as a person uses it. A round trip and every file type passed.

The bridge runs as a background process (`tg_bridge.pid`), not a service; it
does not restart after a reboot and chat history is in memory.
