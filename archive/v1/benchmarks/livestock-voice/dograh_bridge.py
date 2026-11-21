"""Post-call normalization only: native Dograh voice remains independent.

Fetches authenticated native transcript and timing events locally, strips artifact
capability URLs/credentials, then lets shared benchmark extractor apply the schema.
"""
import json
from pathlib import Path
import re
import time
from urllib.parse import urlparse
import aiohttp

BASE='http://127.0.0.1:18000'
STATE=Path.home()/'.local/share/silo-livestock/dograh'

async def latest_call(run_id=None):
    token=json.loads((STATE/'auth.json').read_text())['token']
    async with aiohttp.ClientSession() as session:
        async def get(path):
            async with session.get(BASE+path,headers={'Authorization':'Bearer '+token}) as response:
                response.raise_for_status()
                return await response.json()
        if run_id is None:
            result=await get('/api/v1/workflow/1/runs')
            runs=result['runs']
            completed=[run for run in runs if run.get('is_completed') and run.get('transcript_url')]
            if not completed:
                raise ValueError('No finished native Dograh call with a transcript yet. End the native call and retry.')
            run_id=max(completed,key=lambda row:row['id'])['id']
        run=await get(f'/api/v1/workflow/1/runs/{int(run_id)}')
        url=run.get('transcript_public_url')
        if not url:
            raise ValueError('Native call transcript is not available yet.')
        # Native local URL only. Capability path never reaches exported result.
        parsed=urlparse(url)
        if parsed.hostname and parsed.hostname not in ('localhost','127.0.0.1','100.82.28.38'):
            raise ValueError('Refusing a nonlocal Dograh artifact URL')
        async with session.get(BASE+parsed.path+('?' + parsed.query if parsed.query else '')) as response:
            response.raise_for_status(); raw=await response.text()
        transcript=[]
        for line in raw.splitlines():
            match=re.match(r'^\[([^]]+)\] (assistant|user): (.*)$',line)
            if match:
                stamp,role,text=match.groups()
                transcript.append({'role':role,'text':text,'timestamp':stamp,'final':True,'transcript_basis':'native_dograh_transcript'})
            elif line.strip() and transcript:
                transcript[-1]['text']+='\n'+line
        events=[]
        for event in (run.get('logs') or {}).get('realtime_feedback_events',[]):
            if event.get('type') in ('rtf-ttfb-metric','rtf-interruption','rtf-user-transcription','rtf-bot-transcription'):
                events.append(event)
        metrics=[]
        for event in events:
            if event['type']=='rtf-ttfb-metric':
                payload=event.get('payload',{})
                metrics.append({'turn':event.get('turn'),'native_stage':payload.get('kind'),'native_ttfb_ms':payload.get('ttfb_seconds',0)*1000,'scope':'Dograh processor TTFB, not speech-end-to-audible'})
        return {'id':f'dograh-{run_id}','backend':'dograh','status':'ended','created_at':time.time(),'ended_at':time.time(),
                'transcript':transcript,'metrics':metrics,'events':events,'fields':{},
                'native_run_id':run_id,'native_completed':run.get('is_completed',False),
                'extraction_path':'Shared local Muse extraction of native Dograh post-call transcript; not native extraction',
                'native_usage':run.get('usage_info')}
