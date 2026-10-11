"""Scripted session with the bot as the logged-in user.

Steps (args): text | file:<path>|<caption> | click:<button substring>
Waits for bot replies after each step, prints text, saves photos to $OUT.
"""
import asyncio, json, os, sys
from telethon import TelegramClient
CFG = os.path.expanduser(os.environ.get("SILO_CONFIG", "~/.config/silo"))
TG = json.load(open(f"{CFG}/telegram.json"))
BOT, OUT = TG["botfather_bot_name"], os.environ.get("OUT", ".")

async def collect(c, after_id, wait=2400, quiet=10):
    """Gather bot messages newer than after_id until `quiet`s pass with nothing new."""
    seen, idle, waited = {}, 0, 0
    while waited < wait:
        await asyncio.sleep(1); waited += 1
        new = [m async for m in c.iter_messages(BOT, min_id=after_id) if not m.out and m.id not in seen]
        for m in sorted(new, key=lambda m: m.id):
            seen[m.id] = m
            if m.photo:
                path = await m.download_media(file=f"{OUT}/bot_{m.id}.png")
                print(f"<< [photo saved {path}] {m.text or ''}")
            else:
                print("<<", m.text)
                if m.buttons:
                    print("   buttons:", [b.text for row in m.buttons for b in row])
        idle = 0 if new else idle + 1
        if seen and idle >= quiet:
            break
    if not seen:
        print("<< (no reply)")
    return max(seen, default=after_id)

async def main():
    async with TelegramClient(f"{CFG}/telethon_user", int(TG["telethon_ap_id"]), TG["telethon_app_hash"]) as c:
        last = None
        for step in sys.argv[1:]:
            print(">>", step)
            if step.startswith("click:"):
                msg = (await c.get_messages(BOT, ids=last)) if last else None
                await msg.click(text=lambda t: step[6:] in t)
                await asyncio.sleep(2)
                msg = await c.get_messages(BOT, ids=last)
                print("<< (edited)", msg.text)
                continue
            if step.startswith("file:"):
                path, _, caption = step[5:].partition("|")
                sent = await c.send_file(BOT, path, caption=caption, force_document=True)
            else:
                sent = await c.send_message(BOT, step)
            last = await collect(c, sent.id)
asyncio.run(main())
