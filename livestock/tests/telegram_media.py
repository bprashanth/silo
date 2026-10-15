"""Send synthetic field media through the existing logged-in Telegram test account.
Explicit live Telegram transport; run only for an authorized demonstration.
"""
import argparse
import asyncio
import json
from pathlib import Path
from telethon import TelegramClient, types

async def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--photo',required=True)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    cfg=Path.home()/'.config/silo'
    config=json.loads((cfg/'telegram.json').read_text())
    records=[]
    async with TelegramClient(str(cfg/'telethon_user'),int(config['telethon_ap_id']),config['telethon_app_hash']) as client:
        bot=config['botfather_bot_name']
        async def wait(sent):
            seen=set(); quiet=0
            for _ in range(180):
                await asyncio.sleep(1)
                messages=[m async for m in client.iter_messages(bot,min_id=sent.id) if not m.out and m.id not in seen]
                for m in messages:
                    seen.add(m.id)
                    records.append({'message_id':m.id,'text':m.text,'voice':bool(m.voice)})
                    print('voice reply' if m.voice else m.text,flush=True)
                quiet=0 if messages else quiet+1
                if seen and quiet>=8: return
            raise RuntimeError('No completed bot response to field media')
        await wait(await client.send_file(bot,args.photo,caption='Synthetic demonstration field photograph.',force_document=False))
        await wait(await client.send_file(bot,types.InputMediaGeoPoint(types.InputGeoPoint(lat=19.1,long=73.0))))
    Path(args.output).write_text(json.dumps({'transport':'real Telegram','replies':records},indent=2))

if __name__=='__main__': asyncio.run(main())
