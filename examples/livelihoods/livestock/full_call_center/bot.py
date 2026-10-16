"""Buffalo Soldiers: English livestock voice notes. No imports from tg-bridge."""
import json
import logging
import os
from urllib.parse import urlencode
import sqlite3
import threading
import time
from contextlib import contextmanager
from . import speech
from .client import api,store,STATE
from .transport import Telegram,allowed_ids,transport_retry

LOG=logging.getLogger('buffalo')
DASHBOARD_URL=os.getenv('LIVESTOCK_DASHBOARD_URL','http://100.82.28.38:8766').rstrip('/')
STATE_DIR=STATE/'buffalo'
STATE_DIR.mkdir(parents=True,exist_ok=True,mode=0o700)
DATABASE=STATE_DIR/'updates.db'
LOCK=threading.RLock()

@contextmanager
def db():
    connection=sqlite3.connect(DATABASE,timeout=30)
    try:
        with connection:yield connection
    finally:connection.close()

def init_db():
    with db() as c:
        c.executescript('CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY,value TEXT); CREATE TABLE IF NOT EXISTS inbox(id INTEGER PRIMARY KEY,message TEXT,status TEXT DEFAULT "pending");')
    DATABASE.chmod(0o600)

def deliver(tg,actor_id,text,case_id=None,link_case=False):
    if str(actor_id) not in allowed_ids():raise ValueError('Recipient is not permitted')
    reply=text
    if link_case and case_id:
        reply += "\n\nView case: "+DASHBOARD_URL+"/?"+urlencode({"case":case_id})
    sent=tg.send(actor_id,reply)
    media=[]
    try:
        audio=speech.synth(text,'af_heart','en-us')
        asset=store(audio,'audio/ogg');media.append(asset)
        voiced=tg.upload_voice(actor_id,audio)
        asset['telegram_voice_message_id']=str(voiced['message_id'])
    except Exception as exc:
        LOG.warning('voice_text_fallback error=%s',type(exc).__name__)
    if case_id:api('reply',{'actor_id':str(actor_id),'case_id':case_id,'text':reply,'message_id':'buffalo:'+str(sent['message_id']),'media':media})


def handle(tg,msg):
    actor=str(msg['from']['id'])
    if actor not in allowed_ids() or msg['chat'].get('type')!='private':return
    text=(msg.get('text') or '').strip()
    command=text.split(maxsplit=1)[0].split('@')[0].lower() if text else ''
    if command in ('/start','/farmer','/vet','/livestock'):
        parts=text.split()
        role='vet' if command=='/vet' or command=='/livestock' and len(parts)>1 and parts[1]=='vet' else 'farmer'
        vet=next((part for part in parts if part.startswith('VET-')),'VET-01') if role=='vet' else None
        result=api('register',{'actor_id':actor,'role':role,'vet_id':vet})
        greeting='Hello. What is wrong with your animal? You can send a voice note in English.' if role=='farmer' else 'You are in vet mode. Assign a case to your vet in the case desk to continue. To report your own animal, send /farmer.'
        deliver(tg,actor,result.get('reply') or greeting)
        return
    if command=='/status':
        cases=api('actor/'+actor)
        deliver(tg,actor,'Open the case desk to view your case. Send a voice note to describe an animal problem.')
        return
    if command.startswith('/'):
        deliver(tg,actor,'Send /farmer for the farmer role or /vet for the vet role.')
        return
    if not api('actor/'+actor):api('register',{'actor_id':actor,'role':'farmer'})
    LOG.info('message_received type=%s','voice' if msg.get('voice') else 'media' if msg.get('photo') or msg.get('location') else 'text')
    media=[];metadata={**msg,'bot_username':tg.username,'language':'en'}
    voice=msg.get('voice') or msg.get('audio')
    try:tg.call('sendChatAction',chat_id=int(actor),action='typing')
    except Exception:pass
    if voice:
        raw=tg.download(voice['file_id']);media.append(store(raw,'audio/ogg'))
        quality=speech.transcribe(raw,with_quality=True,language="en")
        metadata['transcription']=quality
        text=quality['text'] if not quality['needs_clarification'] else '[Voice note unclear; please ask me to repeat.]'
    if msg.get('photo'):media.append(store(tg.download(msg['photo'][-1]['file_id']),'image/jpeg'))
    if msg.get('location'):media.append({'media_type':'application/location+json','storage_uri':None,'location':msg['location']})
    if msg.get('document'):
        document=msg['document']
        if document.get('file_size',0)>20*1024*1024:raise ValueError('Attachment exceeds 20MB')
        media.append(store(tg.download(document['file_id']),document.get('mime_type','application/octet-stream')))
    text=text or msg.get('caption') or ''
    try:
        result=api('message',{'actor_id':actor,'text':text,'message_id':'buffalo:'+str(msg['message_id']),
            'language':'en','metadata':metadata,'media':media})
    except ValueError as exc:
        if str(exc)!='No assignment is awaiting you.':raise
        deliver(tg,actor,'You are in vet mode, but no case is assigned to you. To report your animal, send /farmer and then describe the problem. To test as a vet, assign a case to your vet in the case desk first.')
        LOG.info('message_needs_farmer_role_or_assignment')
        return
    if result.get('reply'):
        if result.get('status')=='AWAITING_ASSIGNMENT':
            deliver(tg,actor,result['reply'],result.get('case_id'),link_case=True)
        else:
            deliver(tg,actor,result['reply'],result.get('case_id'))
    LOG.info('message_replied status=%s',result.get('status','unknown'))


def worker(tg):
    while True:
        with db() as c:row=c.execute('SELECT id,message FROM inbox WHERE status="pending" ORDER BY id LIMIT 1').fetchone()
        if not row:time.sleep(.3);continue
        try:
            with LOCK:handle(tg,json.loads(row[1]))
            with db() as c:c.execute('UPDATE inbox SET status="done" WHERE id=?',(row[0],))
        except Exception as exc:
            LOG.error('message_failed error=%s',type(exc).__name__)
            message=json.loads(row[1]);actor=str(message['from']['id'])
            if actor in allowed_ids():
                try:tg.send(actor,'Sorry, I could not finish processing this message. Please send it again. Your previous details are saved.')
                except Exception:pass
            with db() as c:c.execute('UPDATE inbox SET status="failed" WHERE id=?',(row[0],))


def notifications(tg):
    while True:
        try:
            for item in api('outbox',timeout=10):
                if str(item['actor_id']) not in allowed_ids():continue
                with LOCK:
                    deliver(tg,item['actor_id'],item['text'],item['case_id'])
                    api('outbox/'+str(item['id'])+'/delivered',{})
        except Exception as exc:LOG.warning('notification_retry error=%s',type(exc).__name__)
        time.sleep(3)


def main():
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(message)s')
    allowed_ids();init_db();tg=Telegram();identity=tg.call('getMe');tg.username=identity['username']
    # Public identity only; no token is ever logged.
    (STATE_DIR/'identity.json').write_text(json.dumps({'username':tg.username,'id':identity['id']}))
    tg.call('setMyCommands',commands=[{'command':'start','description':'Report an animal problem'},{'command':'farmer','description':'Farmer role'},{'command':'vet','description':'Vet role'}])
    threading.Thread(target=worker,args=(tg,),daemon=True).start()
    threading.Thread(target=notifications,args=(tg,),daemon=True).start()
    LOG.info('bot_ready username=%s language=en allowed_count=%d',tg.username,len(allowed_ids()))
    while True:
        with db() as c:
            row=c.execute('SELECT value FROM state WHERE key="offset"').fetchone();offset=int(row[0]) if row else 0
        try:
            updates=tg.call('getUpdates',offset=offset,timeout=40,allowed_updates=['message'])
            with db() as c:
                for update in updates:
                    message=update.get('message')
                    if message and str(message.get('from',{}).get('id')) in allowed_ids() and message['chat'].get('type')=='private':
                        c.execute('INSERT OR IGNORE INTO inbox(id,message) VALUES(?,?)',(update['update_id'],json.dumps(message)))
                    c.execute('INSERT OR REPLACE INTO state VALUES("offset",?)',(str(update['update_id']+1),))
        except Exception as exc:
            LOG.warning('poll_retry error=%s',type(exc).__name__);time.sleep(3)

if __name__=='__main__':main()
