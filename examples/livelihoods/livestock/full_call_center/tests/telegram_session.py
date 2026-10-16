"""Authorized live Buffalo Soldiers test. Never sends to the original io bot."""
import argparse
import asyncio
import json
from pathlib import Path
from telethon import TelegramClient

async def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);parser.add_argument('steps',nargs='+');args=parser.parse_args()
    out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
    config=json.loads((Path.home()/'.config/idlisseus/telegram.json').read_text())
    identity=json.loads((Path.home()/'.local/share/idli-bridge/livestock/buffalo/identity.json').read_text())
    bot=identity['username'];assert bot.lower()=='buffalosoldiers_bot'
    records=[]
    async with TelegramClient(str(Path.home()/'.config/silo/telethon_user'),int(config['telethon_ap_id']),config['telethon_app_hash']) as client:
        for step in args.steps:
            print('>> '+step,flush=True)
            sent=await client.send_file(bot,step[6:],voice_note=True) if step.startswith('voice:') else await client.send_message(bot,step)
            record={'input':step,'message_id':sent.id,'replies':[]};seen=set();quiet=0
            for _ in range(240):
                await asyncio.sleep(1)
                replies=[m async for m in client.iter_messages(bot,min_id=sent.id) if not m.out and m.id not in seen]
                for message in sorted(replies,key=lambda m:m.id):
                    seen.add(message.id)
                    item={'message_id':message.id,'text':message.text,'voice':bool(message.voice)}
                    if message.voice:item['audio_path']=await message.download_media(file=str(out/('reply-'+str(message.id)+'.ogg')))
                    record['replies'].append(item)
                    print('<< [Hindi voice]' if message.voice else '<< '+(message.text or ''),flush=True)
                quiet=0 if replies else quiet+1
                if seen and quiet>=8 and (any(r['voice'] for r in record['replies']) and any(r['text'] for r in record['replies']) or quiet>=60):break
            else:raise RuntimeError('Buffalo Soldiers response timed out')
            if not seen:raise RuntimeError('No Buffalo Soldiers reply')
            records.append(record)
            (out/'session.json').write_text(json.dumps({'bot':bot,'transport':'real Telegram','steps':records},ensure_ascii=False,indent=2))

if __name__=='__main__':asyncio.run(main())
