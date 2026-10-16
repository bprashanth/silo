"""Telegram transport for Buffalo Soldiers, independent of the original Silo bot."""
import http.client
import json
import os
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

CONFIG=Path(os.getenv('LIVESTOCK_TELEGRAM_CONFIG','~/.config/idlisseus/telegram.json')).expanduser()
ALLOW=Path(os.getenv('LIVESTOCK_ALLOWED_FILE','~/.config/livestock/allowed.txt')).expanduser()

def allowed_ids():
    values={line.split('#')[0].strip() for line in ALLOW.read_text().splitlines()}
    values.discard('')
    if not values or any(not value.isdigit() for value in values):
        raise ValueError('A numeric livestock allow list is required')
    return values

def transport_retry(function,*args,**kwargs):
    for attempt in range(3):
        try:return function(*args,**kwargs)
        except (urllib.error.URLError,http.client.RemoteDisconnected,TimeoutError,ConnectionError) as exc:
            if isinstance(exc,urllib.error.HTTPError) and exc.code<500 and exc.code!=429:raise
            if attempt==2:raise
            time.sleep(attempt+1)

class Telegram:
    def __init__(self):
        config=json.loads(CONFIG.read_text())
        self.token=config['livestock_botfather_api_key']
        self.base='https://api.telegram.org/bot'+self.token
        self.username=None
    def call(self,method,**body):
        req=urllib.request.Request(self.base+'/'+method,json.dumps(body).encode(),{'Content-Type':'application/json'})
        with urllib.request.urlopen(req,timeout=75) as response:
            result=json.load(response)
        if not result.get('ok'):raise RuntimeError('Telegram rejected request')
        return result['result']
    def send(self,chat,text):
        return transport_retry(self.call,'sendMessage',chat_id=int(chat),text=text)
    def upload_voice(self,chat,audio):
        boundary=uuid.uuid4().hex
        body=(f'--{boundary}\r\nContent-Disposition: form-data; name="chat_id"\r\n\r\n{chat}\r\n'
              f'--{boundary}\r\nContent-Disposition: form-data; name="voice"; filename="reply.ogg"\r\nContent-Type: audio/ogg\r\n\r\n').encode()+audio+f'\r\n--{boundary}--\r\n'.encode()
        def upload():
            req=urllib.request.Request(self.base+'/sendVoice',body,{'Content-Type':'multipart/form-data; boundary='+boundary})
            with urllib.request.urlopen(req,timeout=120) as response:return json.load(response)['result']
        return transport_retry(upload)
    def download(self,file_id):
        path=transport_retry(self.call,'getFile',file_id=file_id)['file_path']
        with urllib.request.urlopen('https://api.telegram.org/file/bot'+self.token+'/'+path,timeout=90) as response:
            data=response.read(20*1024*1024+1)
        if len(data)>20*1024*1024:raise ValueError('Attachment exceeds 20MB')
        return data
