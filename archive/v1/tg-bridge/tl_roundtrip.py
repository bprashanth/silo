"""Send a message to the bot as the logged-in user and print the bot's reply."""
import asyncio, json, os, sys
from telethon import TelegramClient
CFG = os.path.expanduser(os.environ.get("SILO_CONFIG", "~/.config/silo"))
TG = json.load(open(f"{CFG}/telegram.json"))
BOT = TG["botfather_bot_name"]

async def main():
    async with TelegramClient(f"{CFG}/telethon_user", int(TG["telethon_ap_id"]), TG["telethon_app_hash"]) as c:
        for text in sys.argv[1:]:
            if text.startswith("file:"):  # file:<path>|<caption>
                path, _, caption = text[5:].partition("|")
                sent = await c.send_file(BOT, path, caption=caption, force_document=path.endswith(".pdf"))
            else:
                sent = await c.send_message(BOT, text)
            print(">>", text)
            for _ in range(60):
                await asyncio.sleep(1)
                msgs = [m async for m in c.iter_messages(BOT, min_id=sent.id) if not m.out]
                if msgs:
                    print("<<", msgs[0].text)
                    break
            else:
                print("<< (no reply in 60s)")
asyncio.run(main())
