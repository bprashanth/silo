"""Telethon user login, two steps: `send <phone>` then `code <code> [2fa_password]`."""
import asyncio, json, os, sys
from telethon import TelegramClient
CFG = os.path.expanduser(os.environ.get("SILO_CONFIG", "~/.config/silo"))
TG = json.load(open(f"{CFG}/telegram.json"))
SESSION, STATE = f"{CFG}/telethon_user", f"{CFG}/telethon_login_state.json"

async def main():
    c = TelegramClient(SESSION, int(TG["telethon_ap_id"]), TG["telethon_app_hash"])
    await c.connect()
    if sys.argv[1] == "send":
        r = await c.send_code_request(sys.argv[2])
        json.dump({"phone": sys.argv[2], "hash": r.phone_code_hash}, open(STATE, "w"))
        print("code sent")
    else:
        st = json.load(open(STATE))
        try:
            await c.sign_in(st["phone"], sys.argv[2], phone_code_hash=st["hash"])
        except Exception as e:
            if "password" not in str(e).lower() or len(sys.argv) < 4:
                raise
            await c.sign_in(password=sys.argv[3])
        me = await c.get_me()
        print("logged in as", me.username or me.first_name, me.id)
        os.remove(STATE)
    await c.disconnect()
asyncio.run(main())
