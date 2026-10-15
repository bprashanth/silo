"""Opt-in livestock Telegram route; ordinary Silo chats keep their existing behavior."""
import base64
import http.client
import json
import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from collections import defaultdict

BASE = os.environ.get('LIVESTOCK_URL','http://127.0.0.1:8766')
STATE = Path(os.environ.get('LIVESTOCK_STATE','~/.local/share/idli-bridge/livestock')).expanduser()
_locks=defaultdict(threading.Lock)
_enrolled={}


def api(path, body=None, timeout=180):
    key=(STATE/'bridge.key').read_text().strip()
    req=urllib.request.Request(BASE+'/internal/'+path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={'Content-Type':'application/json','X-Silo-Bridge':key})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response: return json.load(response)
    except urllib.error.HTTPError as error:
        try: detail=json.load(error).get('detail','Could not update this case.')
        except Exception: detail='Could not update this case.'
        raise ValueError(str(detail)) from None


def store(data, media_type):
    return api('assets', {'data':base64.b64encode(data).decode(),'media_type':media_type})


def transport_retry(function, *args, **kwargs):
    for attempt in range(3):
        try:
            return function(*args, **kwargs)
        except (urllib.error.URLError, http.client.RemoteDisconnected, TimeoutError, ConnectionError) as exc:
            if isinstance(exc, urllib.error.HTTPError) and exc.code < 500 and exc.code != 429:
                raise
            if attempt == 2:
                raise
            time.sleep(attempt + 1)


def deliver(bridge, actor_id, text, case_id=None):
    sent=transport_retry(bridge.tg,'sendMessage',chat_id=int(actor_id),text=text)
    message_id=str(sent.get('result',{}).get('message_id',''))
    media=[]
    try:
        audio=bridge.speech.synth(bridge.speech.speakable(text),'hf_alpha','en-us')
        saved=store(audio,'audio/ogg')
        transport_retry(bridge.send_file,int(actor_id),audio,'reply.ogg',method='sendVoice',field='voice',mime='audio/ogg')
        media.append(saved)
    except Exception as exc:
        # Text above is the explicit fallback if speech or media delivery fails.
        print(f'livestock speech fallback: {type(exc).__name__}',flush=True)
    if case_id:
        api('reply',{'actor_id':str(actor_id),'case_id':case_id,'text':text,'message_id':message_id,'media':media})


def handle(bridge, msg):
    actor_id=str(msg['from']['id'])
    text=(msg.get('text') or '').strip()
    command=text.split(maxsplit=1)[0].split('@')[0].lower() if text else ''
    if command!='/livestock':
        if actor_id not in _enrolled:
            try: _enrolled[actor_id]=bool(api('actor/'+actor_id,timeout=2))
            except Exception: return False
        if not _enrolled[actor_id]: return False
    if msg['chat'].get('type','private')!='private':
        bridge.send(msg['chat']['id'],'Please use livestock mode in a private chat with Silo.')
        return True
    with _locks[actor_id]:
        try:
            if command=='/livestock':
                args=text.split()[1:]
                if not args:
                    bridge.send(msg['chat']['id'],'Use /livestock farmer to report an animal, /livestock vet VET-01 to join as a demo vet, or /livestock off to return to Silo.')
                    return True
                if args[0].lower()=='off':
                    api('unregister',{'actor_id':actor_id}); _enrolled[actor_id]=False
                    bridge.send(msg['chat']['id'],'Livestock mode is off. Your case history is saved.')
                    return True
                role=args[0].lower()
                if role not in ('farmer','vet'):
                    bridge.send(msg['chat']['id'],'Choose /livestock farmer or /livestock vet VET-01.'); return True
                result=api('register',{'actor_id':actor_id,'role':role,'vet_id':args[1] if len(args)>1 else None})
                _enrolled[actor_id]=True
                reply=(result or {}).get('reply') or ('Please tell me what is happening with your animal. You can send a voice note or type.' if role=='farmer' else 'You are connected as a demo vet. I will send your assignment here.')
                deliver(bridge,actor_id,reply)
                return True
            # Other commands retain normal Silo behavior while the case stays associated.
            if command.startswith('/'): return False
            print(f'<- livestock {actor_id}: message',flush=True)
            media=[]
            metadata=dict(msg)
            voice=msg.get('voice') or msg.get('audio')
            if voice:
                raw=bridge.download(voice['file_id']); media.append(store(raw,'audio/ogg'))
                with bridge.typing(msg['chat']['id']): quality=bridge.speech.transcribe(raw,with_quality=True)
                metadata['transcription']=quality
                text=quality['text']
                if quality['needs_clarification']:
                    text='[Voice note unclear; please ask me to repeat.]'
            if msg.get('photo'):
                media.append(store(bridge.download(msg['photo'][-1]['file_id']),'image/jpeg'))
            if msg.get('document'):
                doc=msg['document']
                if doc.get('file_size',0)>20*1024*1024: raise ValueError('Please send an attachment under 20 MB.')
                media.append(store(bridge.download(doc['file_id']),doc.get('mime_type','application/octet-stream')))
            text=text or msg.get('caption') or ''
            if msg.get('location'):
                media.append({'media_type':'application/location+json','storage_uri':None,'location':msg['location']})
            with bridge.typing(msg['chat']['id']):
                result=api('message',{'actor_id':actor_id,'text':text,'message_id':str(msg['message_id']),
                    'media':media,'metadata':metadata})
                if result.get('reply'): deliver(bridge,actor_id,result['reply'],result.get('case_id'))
            print(f'-> livestock {actor_id}: reply',flush=True)
        except ValueError as exc:
            bridge.send(msg['chat']['id'],str(exc))
            print(f'-> livestock {actor_id}: validation reply',flush=True)
        except Exception as exc:
            print(f'-> livestock {actor_id}: {type(exc).__name__}',flush=True)
            bridge.send(msg['chat']['id'],'The livestock service could not finish that message. Please try again shortly; /livestock off returns to Silo.')
    return True


def start(bridge):
    def loop():
        while True:
            try:
                for item in api('outbox',timeout=10):
                    with _locks[str(item['actor_id'])]:
                        deliver(bridge,item['actor_id'],item['text'],item['case_id'])
                        api('outbox/'+str(item['id'])+'/delivered',{})
            except Exception as exc:
                # Avoid printing URLs, tokens, original messages, or API response bodies.
                if not isinstance(exc,(FileNotFoundError,urllib.error.URLError)):
                    print(f'livestock delivery retry: {type(exc).__name__}',flush=True)
            time.sleep(3)
    threading.Thread(target=loop,daemon=True).start()
