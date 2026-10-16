"""Authenticated local case API client, shared by the independent bot and tests."""
import base64
import json
import os
from pathlib import Path
import urllib.request
import urllib.error

STATE=Path(os.getenv('LIVESTOCK_STATE','~/.local/share/idli-bridge/livestock')).expanduser()
BASE=os.getenv('LIVESTOCK_URL','http://127.0.0.1:8766')

def api(path,body=None,timeout=180):
    key=(STATE/'bridge.key').read_text().strip()
    request=urllib.request.Request(BASE+'/internal/'+path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={'Content-Type':'application/json','X-Silo-Bridge':key})
    try:
        with urllib.request.urlopen(request,timeout=timeout) as response:return json.load(response)
    except urllib.error.HTTPError as error:
        if error.code<500:
            try:detail=json.load(error).get('detail','Request rejected')
            except Exception:detail='Request rejected'
            raise ValueError(str(detail)) from None
        raise

def store(data,media_type):
    return api('assets',{'data':base64.b64encode(data).decode(),'media_type':media_type})
