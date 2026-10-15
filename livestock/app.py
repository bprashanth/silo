"""Idli Ops HTTP API. Telegram ingress is local and authenticated separately."""
import base64
import json
import os
import secrets
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from .engine import Engine
from .storage import AssetStore, ROOT

ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
key_path = ROOT / 'bridge.key'
if not key_path.exists():
    key_path.write_text(secrets.token_urlsafe(32)); key_path.chmod(0o600)
BRIDGE_KEY = key_path.read_text().strip()
engine = Engine()
assets = AssetStore()
app = FastAPI(title='Idli Ops')

@app.middleware('http')
async def boundaries(request, call_next):
    if request.url.path.startswith('/internal/'):
        if request.client.host not in ('127.0.0.1', '::1') or not secrets.compare_digest(request.headers.get('x-silo-bridge', ''), BRIDGE_KEY):
            return JSONResponse({'detail':'Local bridge only'}, status_code=403)
    if request.method not in ('GET','HEAD','OPTIONS'):
        origin = request.headers.get('origin')
        if origin and origin != str(request.base_url).rstrip('/'):
            return JSONResponse({'detail':'Cross-origin action blocked'}, status_code=403)
    try:
        return await call_next(request)
    except (ValueError, KeyError) as exc:
        return JSONResponse({'detail': str(exc)}, status_code=400)

@app.exception_handler(ValueError)
def invalid(request, exc):
    return JSONResponse({'detail':str(exc)},status_code=400)

@app.exception_handler(KeyError)
def missing(request, exc):
    return JSONResponse({'detail':str(exc)},status_code=404)

@app.get('/api/health')
def health():
    return {'ready': True}

@app.get('/api/config')
def config():
    try:
        cfg=json.loads((Path.home()/'.config/silo/telegram.json').read_text())
        name=cfg.get('botfather_bot_name','')
    except (OSError, ValueError): name=''
    return {'bot_username':name, 'voice':'hf_alpha'}

@app.get('/api/cases')
def cases(): return engine.list_cases()

@app.get('/api/cases/{case_id}')
def detail(case_id: str): return engine.case_detail(case_id)

@app.get('/api/vets')
def vets(): return engine.roster()

@app.post('/api/cases/{case_id}/assign')
def assign(case_id: str, body: dict):
    return engine.assign(case_id, body['vet_id'], 'ERC operator')

@app.post('/api/cases/{case_id}/close')
def close(case_id: str, body: dict):
    return engine.close(case_id, 'ERC operator')

@app.get('/api/metrics')
def metrics(): return engine.metrics()

@app.post('/api/query')
def query(body: dict):
    question=str(body.get('question','')).strip()
    if not question or len(question)>2000: raise ValueError('Enter a question under 2,000 characters.')
    return engine.query(question)

@app.get('/api/assets/{asset_id}')
def asset(asset_id: str):
    try: path=assets.get(asset_id)
    except (ValueError,FileNotFoundError): raise HTTPException(404, 'Asset not found')
    return FileResponse(path, headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'})

@app.get('/internal/actor/{actor_id}')
def actor(actor_id: str): return engine.actor(actor_id)

@app.post('/internal/register')
def register(body: dict):
    actor_id=str(body['actor_id'])
    result=engine.register(actor_id, body['role'], body.get('vet_id'))
    active=[c for c in engine.list_cases() if c['provenance']=='live_demo' and c['status']!='CLOSED'
            and (c['telegram_user_id']==actor_id if body['role']=='farmer' else c.get('assigned_vet')==body.get('vet_id'))]
    if active:
        c=active[0]
        if body['role']=='farmer':
            if c['status'] in ('AWAITING_FEEDBACK','NEEDS_REVIEW') and c.get('report'):
                result['reply']=c.get('feedback_question','Did the vet visit your animal? What did they do?')
            elif c['status']=='INTAKE': result['reply']=c.get('last_question','What is happening with your animal?')
            else: result['reply']=f"Your case {c['case_id']} is {c['status'].lower().replace('_',' ')}."
        elif c['status']=='ASSIGNED': result['reply']=f"Case {c['case_id']} is assigned to you. Can you accept it?"
        elif c['status']=='ACCEPTED': result['reply']='After your visit, send your observations, assistance provided and follow-up needs.'
        else: result['reply']='Your visit report is saved. The case is awaiting farmer feedback or operator review.'
    return result

@app.post('/internal/unregister')
def unregister(body: dict): return engine.unregister(str(body['actor_id']))

@app.post('/internal/message')
def message(body: dict): return engine.message(**body)

@app.post('/internal/assets')
def upload(body: dict):
    raw=base64.b64decode(body['data'],validate=True)
    if len(raw)>20*1024*1024: raise ValueError('File is too large')
    return assets.put(raw, body['media_type'])

@app.post('/internal/reply')
def reply(body: dict): return engine.record_reply(**body)

@app.get('/internal/outbox')
def outbox(): return engine.pending_outbox()

@app.post('/internal/outbox/{item_id}/delivered')
def delivered(item_id: int): return engine.mark_delivered(item_id)

app.mount('/',StaticFiles(directory=Path(__file__).parent/'static',html=True),name='ui')
