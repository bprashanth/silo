"""Isolated, local Pipecat/SmallWebRTC livestock voice experiment."""
import asyncio, collections, hashlib, io, json, os, re, time, uuid, wave
from contextlib import asynccontextmanager
from pathlib import Path
import aiohttp
import numpy as np
import soundfile as sf
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from urllib.parse import quote
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams, VADState
from pipecat.frames.frames import Frame, InputAudioRawFrame, OutputAudioRawFrame, TTSAudioRawFrame, TTSStoppedFrame, InterruptionFrame, BotStartedSpeakingFrame, BotStoppedSpeakingFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.task import PipelineTask, PipelineParams
from pipecat.pipeline.runner import PipelineRunner
from pipecat.processors.frame_processor import FrameProcessor, FrameDirection
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport

HERE=Path(__file__).resolve().parent
ART=Path('/mnt/seagate/silo/livestock-voice')
STATE=Path.home()/'.local/share/silo-livestock-voice'
Q=json.loads((HERE/'questionnaire.json').read_text())
MUSE=os.getenv('MUSE_URL','http://127.0.0.1:8181')
CALLS={}; RUNTIME={}; READY=False
MODELS=Path.home()/'.local/share/idli-bridge/models'
whisper=kokoro=None
asr_lock=asyncio.Lock(); tts_lock=asyncio.Lock()

def load_models():
    global whisper,kokoro
    from faster_whisper import WhisperModel
    from kokoro_onnx import Kokoro
    import onnxruntime as ort
    whisper=WhisperModel(os.getenv('WHISPER_MODEL','/mnt/seagate/silo/livestock-voice/models/whisper-base.en'),device='cpu',compute_type='int8',cpu_threads=8,download_root=str(MODELS/'whisper'),local_files_only=True)
    opts=ort.SessionOptions(); opts.intra_op_num_threads=4; opts.inter_op_num_threads=1
    sess=ort.InferenceSession(str(MODELS/'kokoro/kokoro-v1.0.onnx'),sess_options=opts,providers=['CPUExecutionProvider'])
    kokoro=Kokoro.from_session(sess,str(MODELS/'kokoro/voices-v1.0.bin'))
    kokoro.create('Hello.',voice='af_heart',speed=1.1,lang='en-us')
    list(whisper.transcribe(np.zeros(16000,dtype=np.float32),language='en',beam_size=1)[0])

def asr(pcm):
    segs,_=whisper.transcribe(np.frombuffer(pcm,np.int16).astype(np.float32)/32768,language='en',beam_size=1,vad_filter=False,condition_on_previous_text=False,initial_prompt='A farmer is reporting a sick cow. Livestock, village, district. Common names: Ramesh, Suresh, Lakshmi, Geeta, Ravi.')
    return ' '.join(s.text.strip() for s in segs).strip()

async def muse(messages, max_tokens=160, json_mode=False):
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=90)) as s:
        async with s.post(MUSE+'/apply-template',json={'messages':messages}) as r:
            r.raise_for_status(); prompt=(await r.json())['prompt']
        async with s.post(MUSE+'/completion',json={'prompt':prompt+' to=user<|message|>','stream':True,'n_predict':max_tokens,'temperature':0.2,'stop':['<|eot|>','<|start|>','<|eom|>'],'cache_prompt':True,**({'json_schema':{'type':'object'}} if json_mode else {})}) as r:
            r.raise_for_status()
            async for line in r.content:
                if line.startswith(b'data: '):
                    d=json.loads(line[6:])
                    if d.get('content'): yield d['content']
                    if d.get('stop'): break

def new_fields():
    return {**{k:None for k in Q['required_fields']},'symptoms':[],'urgent_warning_signs':[],'needs_human_review':True,'confirmed_by_caller':False,'missing_fields':Q['required_fields'][:],'call_status':'in_progress','unknown_fields':[],'evidence':{}}

def save(c):
    STATE.mkdir(parents=True,exist_ok=True)
    path=STATE/(c['id']+'.json'); path.write_text(json.dumps(c,indent=2)); path.chmod(0o600)

def urgency(text):
    """Classify explicit positive warning phrases, retaining quote evidence elsewhere."""
    low=text.lower(); found=[]
    patterns=[(r"(?:cannot|can't|unable to|not able to) (?:stand|get up)","unable to stand"),
      (r"(?:breathing (?:very )?fast|struggling to breathe|difficulty breathing|severe breathing)","breathing difficulty"),
      (r"(?:unconscious|unresponsive)","unresponsive")]
    for pattern,label in patterns:
        for match in re.finditer(pattern,low):
            prefix=low[max(0,match.start()-25):match.start()]
            if re.search(r"(?:\bnot|\bno|isn't|is not|wasn't)\s+(?:currently\s+|now\s+|showing\s+|any\s+)?$",prefix): continue
            found.append(label); break
    return found

def validate_fields(c,data):
    callers=[x['text'] for x in c['transcript'] if x['role']=='user']
    signs=[]; quotes=[]; resolved=[]
    for text in callers:
        detected=urgency(text)
        if detected: signs.extend(detected); quotes.append(text)
        low=text.lower()
        clear=[]
        if re.search(r"(?:\bcan|\bable to) stand",low) and 'unable to stand' not in detected: clear.append('unable to stand')
        if re.search(r"breathing (?:is )?(?:normal|normally)|not breathing fast",low): clear.append('breathing difficulty')
        if re.search(r"not (?:unconscious|unresponsive)|is conscious|is responsive",low): clear.append('unresponsive')
        for label in clear:
            if label in signs: resolved.append({'sign':label,'correction_quote':text})
            signs=[sign for sign in signs if sign!=label]
    if signs or resolved:
        data['urgent_warning_signs']=list(dict.fromkeys(signs)); data['needs_human_review']=True
        data.setdefault('evidence',{})['urgent_warning_signs']={'positive_quotes':quotes,'later_corrections':resolved}
        data['inferred_classifications']={'urgency':'urgent veterinary review' if signs else 'human review of corrected warning report','basis':'explicit caller warning signs and subsequent corrections; not a diagnosis'}
    evidence=data.setdefault('evidence',{})
    for text in callers:
        if re.search(r'(?:do not|don.t|no).{0,25}(?:contact|phone).{0,15}(?:number|details)',text,re.I):
            data['contact_details']=None; evidence['contact_details']=text
            data.setdefault('unknown_fields',[]).append('contact_details')
        if re.search(r"(?:do not|don.t) know when|not sure when",text,re.I):
            data['symptoms_since']=None; evidence['symptoms_since']=text
            data.setdefault('unknown_fields',[]).append('symptoms_since')
        onset=re.search(r"(?:started|began|since|sorry,?)\s+(?:about\s+)?(yesterday|today|last night|last week|(?:one|two|three|four|five|six|seven|eight|nine|ten|a|an|\d+)\s+(?:hours?|days?|weeks?|months?)\s+ago)",text,re.I)
        if onset:
            data['symptoms_since']=onset.group(1); evidence['symptoms_since']=text
            data['unknown_fields']=[k for k in data.get('unknown_fields',[]) if k!='symptoms_since']
    data['unknown_fields']=[key for key in dict.fromkeys(data.get('unknown_fields',[])) if re.search(r"(?:don't know|do not know|unknown|not sure|unavailable|no contact|do not have|not available)",str(evidence.get(key,'')),re.I)]
    for key in Q['required_fields']:
        if data.get(key) in (None, [], '') and key not in data['unknown_fields'] and c['fields'].get(key) not in (None, [], '') and not (key=='urgent_warning_signs' and resolved):
            data[key]=c['fields'][key]
            if key in c['fields'].get('evidence',{}): evidence[key]=c['fields']['evidence'][key]
    data['missing_fields']=[key for key in Q['required_fields'] if (data.get(key) is None or data.get(key)==[] or data.get(key)=='') and key not in data['unknown_fields']]
    if 'urgent_warning_signs' in evidence and 'urgent_warning_signs' in data['missing_fields']: data['missing_fields'].remove('urgent_warning_signs')
    if c.get('backend')=='pipecat':
        data['confirmed_by_caller']=bool(c.get('confirmed_summary'))
        data['call_status']='completed' if data['confirmed_by_caller'] else 'in_progress'
    return data

def routing_hint(c):
    """Lightweight dialog guard; extraction still supplies values and provenance."""
    text=' '.join(x['text'] for x in c['transcript'] if x['role']=='user').lower()
    f=c['fields']; known={k for k in Q['required_fields'] if f.get(k) not in (None, [], '')}|set(f.get('unknown_fields',[]))
    cues={'caller_name':r'my name is|i am called', 'village':r'village', 'district':r'district',
      'animal_type':r'cow|buffalo|goat|sheep|calf|bull', 'animals_affected':r'my cow|one cow|one animal|[0-9]+ (?:cows|animals)',
      'symptoms':r'not (?:been )?eating|weak|fever|breath|cannot stand|diarrh',
      'symptoms_since':r'yesterday|days? ago|since |symptoms started|do not know when|started two|started three',
      'previous_treatment':r'treatment|medicine|medication', 'urgent_warning_signs':r'stand|breath|unconscious|unresponsive',
      'contact_details':r'contact|phone|mobile|number to share'}
    known|={key for key,pattern in cues.items() if re.search(pattern,text)}
    priority=['symptoms','urgent_warning_signs','symptoms_since','animals_affected','caller_name','village','district','previous_treatment','contact_details']
    missing=[k for k in priority if k not in known]
    if missing: return 'Your ONLY next question must ask for '+missing[0]+'. The following are already addressed; do not ask again: '+', '.join(sorted(known))+'.'
    previous=[x['text'] for x in c['transcript'] if x['role']=='assistant' and x.get('text')]
    latest=[x['text'] for x in c['transcript'] if x['role']=='user'][-1]
    if previous and re.search(r'correct|confirm|right|accurate',previous[-1],re.I) and re.search(r'^(yes|correct|that.s right)',latest,re.I):
        return 'The caller has confirmed your summary. Thank them, say the demo request is recorded and no real dispatch occurs, and end politely. Do not ask another question.'
    return 'All required information has been addressed. Briefly summarize the actual facts from this conversation and ask if that summary is correct. Ask NO other question.'

def completion_reply(c,hint):
    if hint.startswith('The caller has confirmed') and c.get('summary_requested'):
        c['confirmed_summary']=True
        return 'Thank you. Your demo request is recorded for human review. This demonstration does not dispatch a veterinarian. Goodbye.'
    if not hint.startswith('All required'): return None
    f=validate_fields(c,json.loads(json.dumps(c['fields'])))
    parts=[]
    for key,label in [('caller_name','Caller'),('village','village'),('district','district'),('animal_type','animal'),('animals_affected','number affected'),('symptoms','symptoms'),('symptoms_since','started'),('previous_treatment','previous treatment')]:
        value=f.get(key)
        if value not in (None,[], ''): parts.append(label+': '+(', '.join(value) if isinstance(value,list) else str(value)))
    users=' '.join(x['text'] for x in c['transcript'] if x['role']=='user')
    if f.get('previous_treatment') is None and re.search(r'no previous treatment|no treatment',users,re.I): parts.append('no previous treatment')
    if 'contact_details' in f.get('unknown_fields',[]): parts.append('contact details unavailable')
    if f.get('urgent_warning_signs'): parts.append('flagged for urgent human review')
    return 'Let me check the details. '+'. '.join(parts)+'. Is that summary correct?'

def completion_fingerprint(fields):
    canonical={key:fields.get(key) for key in [*Q['required_fields'],'confirmed_by_caller','call_status']}
    return hashlib.sha256(json.dumps(canonical,sort_keys=True).encode()).hexdigest()

async def extract(c):
    c['extracting']=True
    revision=len(c['transcript'])
    prompt='You are a data extraction engine, not the intake operator. Populate fields using actual caller statements; do not copy empty template values. Example: My cow is sick means animal_type cow, animals_affected 1, symptoms [sick]. Extract a JSON record from this livestock intake conversation. Output ONLY JSON. Do not invent facts. Values explicitly unknown go in unknown_fields, with the value null. Missing fields excludes explicitly unknown fields. previous_treatment may be "none" when denied. urgent_warning_signs [] when caller explicitly denies them. Preserve latest corrections. confirmed_by_caller true ONLY after caller confirms an agent summary. call_status completed ONLY after that confirmation, otherwise in_progress. Include evidence mapping each collected field to a short caller quote. Schema: '+json.dumps(new_fields())
    content='';
    try:
        async for x in muse([{'role':'system','content':prompt},{'role':'user','content':json.dumps(c['transcript'])}],650,json_mode=True): content+=x
        data=validate_fields(c,json.loads(content[content.index('{'):content.rindex('}')+1]))
        if revision>=c.get('fields_revision',0):
            c['fields']={**new_fields(),**data}; c['fields_revision']=revision; c.pop('extraction_error',None)
            fingerprint=completion_fingerprint(c['fields'])
            if data.get('confirmed_by_caller') and data.get('call_status')=='completed' and c.get('completion_fingerprint')!=fingerprint:
                async with aiohttp.ClientSession() as session:
                    async with session.post('http://127.0.0.1:'+os.getenv('PORT','8765')+'/api/completions',json={'call_id':c['id'],'fields':c['fields'],'transcript':c['transcript']}) as response:
                        response.raise_for_status(); c['completion']=await response.json(); c['completion_fingerprint']=fingerprint
                save(c)
    except Exception as e: c['extraction_error']=str(e)
    finally: c['extracting']=False

class Intake(FrameProcessor):
    def __init__(self,c):
        super().__init__(); self.c=c; self.vad=SileroVADAnalyzer(params=VADParams(start_secs=.12,stop_secs=.45,confidence=.65,min_volume=.4)); self.vad.set_sample_rate(16000)
        self.active=False; self.buf=bytearray(); self.pre=collections.deque(maxlen=12); self.job=None; self.last_voice=None; self.current=None; self.extract_task=None; self.asr_pending_pcm=None
    async def process_frame(self,frame,direction):
        await super().process_frame(frame,direction)
        if isinstance(frame,BotStartedSpeakingFrame): self.c['status']='speaking'
        elif isinstance(frame,BotStoppedSpeakingFrame): self.c['status']='listening'
        if not isinstance(frame,InputAudioRawFrame):
            await self.push_frame(frame,direction); return
        state=await self.vad.analyze_audio(frame.audio)
        speaking=state in (VADState.SPEAKING,VADState.STARTING)
        if speaking: self.last_voice=time.monotonic()
        if state==VADState.SPEAKING and not self.active:
            was_speaking=self.c.get('status')=='speaking'
            self.active=True; self.buf=bytearray(b''.join(self.pre)); self.c['status']='listening'
            if self.job and not self.job.done():
                if self.asr_pending_pcm is not None:
                    self.buf=bytearray(self.asr_pending_pcm)+self.buf
                    self.c['events'].append({'event':'resumed_caller_fragment','monotonic':time.monotonic()})
                    self.asr_pending_pcm=None
                self.job.cancel()
            if was_speaking:
                if self.current: self.current['interrupted']=True
                if self.c['transcript'] and self.c['transcript'][-1]['role']=='assistant':
                    self.c['transcript'][-1]['interrupted']=True; self.c['transcript'][-1]['transcript_basis']='audio_queued_may_be_partially_played'
            await self.push_frame(InterruptionFrame())
            self.c.setdefault('events',[]).append({'event':'speech_start','monotonic':time.monotonic()})
        if self.active:
            self.buf.extend(frame.audio)
            if state==VADState.QUIET or len(self.buf)>16000*2*40:
                self.active=False; pcm=bytes(self.buf); self.buf.clear()
                if len(pcm)>6400: self.job=asyncio.create_task(self.respond(pcm,self.last_voice or time.monotonic()))
        self.pre.append(frame.audio)
    async def say(self,text,metric=None):
        async with tts_lock:
            t=time.monotonic(); audio,sr=await asyncio.to_thread(kokoro.create,text,voice='af_heart',speed=1.1,lang='en-us')
        if metric is not None:
            metric.setdefault('tts_first_chunk_ms',(time.monotonic()-t)*1000)
            metric.setdefault('server_first_audio_ms',(time.monotonic()-metric['speech_end_monotonic'])*1000)
        pcm=(np.clip(audio,-1,1)*32767).astype(np.int16).tobytes()
        await self.push_frame(TTSAudioRawFrame(audio=pcm,sample_rate=sr,num_channels=1))
    async def greet(self):
        text=Q['greeting']; self.c['transcript'].append({'role':'assistant','text':text,'final':True}); await self.say(text); await self.push_frame(TTSStoppedFrame())
    async def hosted(self,pcm,m):
        from candidates import OpenRouterAudio
        c=self.c
        history=[{'role':x['role'],'content':x['text']} for x in c['transcript']]
        user={'role':'user','text':'Transcribing…','final':False}
        entry={'role':'assistant','text':'','final':False,'transcript_basis':'provider_audio_transcript'}
        c['transcript'].extend([user,entry])
        async def transcribe():
            t=time.monotonic()
            async with asr_lock: user['text']=await asyncio.to_thread(asr,pcm)
            user['final']=True; m['local_transcript_asr_ms']=(time.monotonic()-t)*1000
        transcription=asyncio.create_task(transcribe())
        wav=io.BytesIO(); sf.write(wav,np.frombuffer(pcm,np.int16),16000,format='WAV',subtype='PCM_16')
        try:
            async for ev in OpenRouterAudio().stream(wav.getvalue(),history,Q['instructions']):
                if ev['type']=='audio':
                    m.setdefault('server_first_audio_ms',(time.monotonic()-m['speech_end_monotonic'])*1000)
                    await self.push_frame(TTSAudioRawFrame(audio=ev['pcm'],sample_rate=ev['sample_rate'],num_channels=1))
                elif ev['type']=='transcript_delta': entry['text']+=ev['text']
                elif ev['type']=='done': entry['text']=ev['text']; m.update(ev.get('timing',{})); m['usage']=ev.get('usage'); m['observed_cost_usd']=ev.get('observed_cost_usd')
            await self.push_frame(TTSStoppedFrame())
            await transcription
            m['generation_complete_ms']=(time.monotonic()-m['speech_end_monotonic'])*1000
            entry['final']=True
            if self.extract_task and not self.extract_task.done(): self.extract_task.cancel()
            self.extract_task=asyncio.create_task(extract(c)); save(c)
        finally:
            if not transcription.done(): await transcription

    async def respond(self,pcm,speech_end):
        c=self.c; m={'turn':len(c['metrics'])+1,'speech_end_monotonic':speech_end,'end_of_turn_monotonic':time.monotonic()}; self.current=m
        m['vad_ms']=(m['end_of_turn_monotonic']-speech_end)*1000; c['metrics'].append(m); c['status']='thinking'
        try:
            if c['backend']=='openrouter':
                await self.hosted(pcm,m); return
            t=time.monotonic(); self.asr_pending_pcm=pcm
            async with asr_lock: text=await asyncio.to_thread(asr,pcm)
            self.asr_pending_pcm=None
            m['asr_ms']=(time.monotonic()-t)*1000
            if not text: c['status']='listening'; return
            c['transcript'].append({'role':'user','text':text,'final':True}); hist=[{'role':x['role'],'content':x['text']} for x in c['transcript']]
            if self.extract_task and not self.extract_task.done(): self.extract_task.cancel()
            # Defer extraction until speech is queued so it cannot contend with first-token latency.
            entry={'role':'assistant','text':'','generated_text':'','final':False,'transcript_basis':'audio_queued'}; c['transcript'].append(entry)
            t=time.monotonic(); first=True
            pending=''; speech_queue=asyncio.Queue()
            async def speak_queue():
                while True:
                    sentence=await speech_queue.get()
                    if sentence is None: break
                    await self.say(sentence,m)
                    entry['text']+=(' ' if entry['text'] else '')+sentence
            speaker=asyncio.create_task(speak_queue())
            if urgency(text) and not c.get('urgent_notified'):
                await speech_queue.put('This needs urgent veterinary attention.'); c['urgent_notified']=True
            try:
                known={k:v for k,v in c['fields'].items() if k in Q['required_fields'] and v not in (None,[], '')}
                last=hist[-1]['content']
                hint=routing_hint(c); c['routing_hint']=hint
                guarded_reply=completion_reply(c,hint)
                hist[-1]={**hist[-1],'content':last+'\n\n[Operator reminder: Respond to the farmer above. Already collected: '+json.dumps(known)+'. '+hint+(' Urgent veterinary attention has ALREADY been spoken; do not repeat that warning.' if c.get('urgent_notified') else '')+' Follow the ONLY next-action instruction above exactly.]'}
                async def reply_chunks():
                    if guarded_reply:
                        c['dialogue_policy']='field-backed deterministic summary/completion guard'
                        for sentence in re.split(r'(?<=[.!?])\s+',guarded_reply): yield sentence+' '
                    else:
                        async for piece in muse([{'role':'system','content':Q['instructions']},*hist]): yield piece
                async for chunk in reply_chunks():
                    if first: m['llm_first_token_ms']=(time.monotonic()-t)*1000; first=False
                    entry['generated_text']+=chunk; pending+=chunk
                    if re.search(r'[.!?](?:\s|$)',pending) and len(pending.strip())>12:
                        await speech_queue.put(pending.strip()); pending=''
                if pending.strip(): await speech_queue.put(pending.strip())
                await speech_queue.put(None); await speaker; await self.push_frame(TTSStoppedFrame())
            finally:
                if not speaker.done(): speaker.cancel()
            if guarded_reply and guarded_reply.startswith('Let me check'):
                c['summary_requested']=True; c['summary_fields']=json.loads(json.dumps(c['fields']))
            entry['final']=True; m['generation_complete_ms']=(time.monotonic()-speech_end)*1000
            if self.extract_task and not self.extract_task.done(): self.extract_task.cancel()
            self.extract_task=asyncio.create_task(extract(c)); save(c)
        except asyncio.CancelledError:
            if c['transcript'] and c['transcript'][-1]['role']=='assistant': c['transcript'][-1]['interrupted']=True; c['transcript'][-1]['transcript_basis']='audio_queued_may_be_partially_played'; c['transcript'][-1]['final']=True
            raise
        except Exception as e:
            c['error']=str(e); c['status']='error'; import traceback; traceback.print_exc()

@asynccontextmanager
async def lifespan(app):
    global READY
    await asyncio.to_thread(load_models); READY=True
    yield
    for r in list(RUNTIME.values()): await r['connection'].disconnect()
app=FastAPI(lifespan=lifespan)
@app.get('/api/backends')
async def backends():
    return {'backends':[{'id':'pipecat','label':'Pipecat local','available':READY,'description':'Local Whisper → Muse → Kokoro; continuous WebRTC','model':'Muse Glimmer 30B / Whisper base.en / Kokoro'}, {'id':'openrouter','label':'OpenRouter audio','available':True,'description':'Non-private synthetic data only. Turn-based speech-to-speech over WebRTC.','model':'openai/gpt-audio-mini'},{'id':'dograh','label':'Dograh (native UI)','available':True,'description':'Opens native Dograh UI in a separate tab. Import its latest call afterward.','model':'Muse / local Whisper / Kokoro adapters'}]}
@app.get('/api/dograh/open')
async def open_dograh(req:Request):
    path=Path.home()/'.local/share/silo-livestock/dograh/auth.json'
    if not path.exists(): raise HTTPException(503,'Dograh local demo authentication is not configured')
    auth=json.loads(path.read_text())
    hostname=req.url.hostname or '127.0.0.1'
    if hostname not in ('localhost','127.0.0.1'): hostname='127.0.0.1'
    response=RedirectResponse('http://'+hostname+':13010/workflow/1')
    response.set_cookie('dograh_auth_token',auth['token'],httponly=True,samesite='lax',path='/')
    response.set_cookie('dograh_auth_user',quote(json.dumps(auth['user'])),httponly=True,samesite='lax',path='/')
    return response
@app.post('/api/dograh/import')
async def import_dograh(req:Request):
    from dograh_bridge import latest_call
    try:
        body=await req.json()
        c=await latest_call(body.get('run_id'))
    except Exception as error:
        raise HTTPException(502,str(error))
    c.setdefault('metrics',[]); c.setdefault('events',[]); c['fields']=new_fields()
    CALLS[c['id']]=c
    await extract(c); c['status']='ended'
    if not c['fields'].get('confirmed_by_caller'): c['fields']['call_status']='ended_unconfirmed'
    save(c); return c
@app.post('/api/calls')
async def create(req:Request):
    body=await req.json(); backend=body.get('backend','pipecat')
    if backend not in ('pipecat','openrouter'): raise HTTPException(400,'Backend is not available')
    ident=str(uuid.uuid4()); c={'id':ident,'backend':backend,'status':'connecting','created_at':time.time(),'transcript':[],'fields':new_fields(),'metrics':[],'events':[]}; CALLS[ident]=c; return c
@app.get('/api/calls/{ident}')
async def state(ident:str):
    if ident not in CALLS: raise HTTPException(404,'Call not found')
    return CALLS[ident]
@app.post('/api/offer')
async def offer(req:Request,call_id:str):
    if call_id not in CALLS: raise HTTPException(404,'Call not found')
    body=await req.json(); conn=SmallWebRTCConnection(ice_servers=[])
    await conn.initialize(sdp=body['sdp'],type=body['type'])
    transport=SmallWebRTCTransport(conn,TransportParams(audio_in_enabled=True,audio_out_enabled=True,audio_in_sample_rate=16000,audio_out_sample_rate=24000))
    intake=Intake(CALLS[call_id]); task=PipelineTask(Pipeline([transport.input(),intake,transport.output()]),params=PipelineParams(audio_in_sample_rate=16000,audio_out_sample_rate=24000))
    @transport.event_handler('on_client_connected')
    async def connected(t,c):
        CALLS[call_id]['status']='listening'; intake.job=asyncio.create_task(intake.greet())
    @transport.event_handler('on_client_disconnected')
    async def disconnected(t,c): await task.cancel()
    runner=asyncio.create_task(PipelineRunner(handle_sigint=False).run(task))
    RUNTIME[call_id]={'connection':conn,'task':task,'runner':runner,'intake':intake}
    return conn.get_answer()
@app.post('/api/calls/{ident}/end')
async def end(ident:str):
    if ident not in CALLS: raise HTTPException(404,'Call not found')
    c=CALLS[ident]
    if ident in RUNTIME:
        r=RUNTIME.pop(ident)
        if r['intake'].job: r['intake'].job.cancel()
        if r['intake'].extract_task and not r['intake'].extract_task.done():
            r['intake'].extract_task.cancel()
            await asyncio.gather(r['intake'].extract_task,return_exceptions=True)
        if r['intake'].job: await asyncio.gather(r['intake'].job,return_exceptions=True)
        await r['connection'].disconnect(); await r['task'].cancel()
    c['status']='ended'; c['ended_at']=time.time()
    await extract(c)
    if not c['fields'].get('confirmed_by_caller'): c['fields']['call_status']='ended_unconfirmed'
    save(c); return c
@app.post('/api/completions')
async def complete(req:Request):
    body=await req.json(); ident=str(uuid.uuid5(uuid.NAMESPACE_URL,'silo-livestock-completion:'+str(body['call_id']))) if body.get('call_id') else str(uuid.uuid4()); path=STATE/('completion-'+ident+'.json'); path.write_text(json.dumps(body,indent=2)); path.chmod(0o600)
    return {'id':ident,'mock':True,'dispatched':False}
@app.post('/api/calls/{ident}/events')
async def events(ident:str,req:Request):
    CALLS[ident]['events'].append(await req.json()); return {'ok':True}
@app.get('/api/results')
async def results():
    out={}; all_calls={}
    for path in STATE.glob('*.json'):
        try:
            item=json.loads(path.read_text())
            if item.get('id') and item.get('backend') and 'transcript' in item: all_calls[item['id']]=item
        except (ValueError,OSError): pass
    all_calls.update(CALLS)
    percentile=lambda samples: {str(q):float(np.percentile(samples,q)) for q in (50,90,95)} if samples else None
    for backend in ('pipecat','openrouter','dograh'):
        calls=[c for c in all_calls.values() if c['backend']==backend]
        samples=[m['server_first_audio_ms'] for c in calls for m in c.get('metrics',[]) if 'server_first_audio_ms' in m and not m.get('interrupted') and 'generation_complete_ms' in m]
        browser=[ev['speech_end_to_audible_ms'] for c in calls for ev in c.get('events',[]) if ev.get('type')=='browser_first_audio' and isinstance(ev.get('speech_end_to_audible_ms'),(int,float))]
        out[backend]={'calls':len(calls),'turn_samples':len(samples),'server_first_audio_ms':percentile(samples),'browser_audible_samples':len(browser),'browser_speech_end_to_audible_ms':percentile(browser),'interrupted_turns':sum(bool(m.get('interrupted')) for c in calls for m in c.get('metrics',[])),'note':'Includes persisted synthetic experiments across revisions. Server samples exclude interrupted/incomplete turns. Browser events lack turn IDs, so their aggregate is unjoined and may include interrupted turns. Consult raw run reports for controlled comparisons. No human microphone measurement claimed.'}
    return out
@app.get('/api/health')
async def health(): return {'ready':READY}
if (ART/'fixtures').exists(): app.mount('/fixtures',StaticFiles(directory=ART/'fixtures'),name='fixtures')
if (HERE/'static').exists(): app.mount('/',StaticFiles(directory=HERE/'static',html=True),name='static')
if __name__=='__main__':
    import uvicorn
    uvicorn.run(app,host=os.getenv('HOST','127.0.0.1'),port=int(os.getenv('PORT','8765')))
