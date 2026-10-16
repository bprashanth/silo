"""SQLite domain engine. Public methods are synchronous; call from a worker thread."""
import json
import os
import random
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from .config import PROTOCOLS, VETS, QUESTIONS
from .model import Muse
from .hindi import canonicalize_input, localize_reply


def now():
    return datetime.now(timezone.utc).isoformat()


def ident(prefix):
    return prefix + '-' + uuid.uuid4().hex[:10].upper()


class Engine:
    def __init__(self, db_path=None, model=None, seed=True):
        self.path = Path(db_path or os.getenv('LIVESTOCK_DB', str(Path.home()/'.local/share/idli-bridge/livestock/cases.db')))
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.model = model or Muse()
        self.lock = threading.RLock()
        with self.db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS cases(id TEXT PRIMARY KEY,data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS actors(id TEXT PRIMARY KEY,role TEXT,vet_id TEXT);
            CREATE TABLE IF NOT EXISTS vet_bindings(vet_id TEXT PRIMARY KEY,actor_id TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS messages(actor TEXT,message_id TEXT,response TEXT,PRIMARY KEY(actor,message_id));
            CREATE TABLE IF NOT EXISTS evidence(id TEXT PRIMARY KEY,case_id TEXT,data TEXT);
            CREATE TABLE IF NOT EXISTS outbox(id INTEGER PRIMARY KEY,actor_id TEXT,case_id TEXT,text TEXT,delivered INTEGER DEFAULT 0);
            ''')
        self.path.chmod(0o600)
        if seed:
            self.seed()

    def db(self):
        db = sqlite3.connect(self.path, timeout=180)
        db.row_factory = sqlite3.Row
        return db

    def actor(self, actor_id):
        with self.db() as db:
            row = db.execute('SELECT * FROM actors WHERE id=?',(str(actor_id),)).fetchone()
            return dict(row) if row else None

    def register(self, actor_id, role, vet_id=None):
        if role not in ('farmer','vet'):
            raise ValueError('Choose farmer or vet.')
        if role == 'vet' and vet_id not in [v['vet_id'] for v in VETS]:
            raise ValueError('Choose a vet from the roster.')
        with self.lock, self.db() as db:
            if role == 'vet':
                existing=db.execute('SELECT actor_id FROM vet_bindings WHERE vet_id=? AND actor_id<>?',(vet_id,str(actor_id))).fetchone()
                if existing:
                    raise ValueError('This demonstration vet is already registered to another chat.')
            if role=='vet': db.execute('INSERT OR REPLACE INTO vet_bindings VALUES(?,?)',(vet_id,str(actor_id)))
            db.execute('INSERT OR REPLACE INTO actors VALUES(?,?,?)',(str(actor_id),role,vet_id if role=='vet' else None))
        return self.actor(actor_id)

    def unregister(self, actor_id):
        with self.db() as db:
            db.execute('DELETE FROM actors WHERE id=?',(str(actor_id),))

    def _save(self, db, case):
        case['updated_at']=now()
        db.execute('INSERT OR REPLACE INTO cases VALUES(?,?)',(case['case_id'],json.dumps(case)))

    def _event(self, case, kind, text, actor='system', data=None):
        case['events'].append({'timestamp':now(),'type':kind,'text':text,'actor':str(actor),'data':data or {}})

    def _status(self, case, status):
        old=case['status']; case['status']=status
        self._event(case,'status',f'{old} → {status}',data={'from':old,'to':status})

    def list_cases(self):
        with self.db() as db:
            return [json.loads(row['data']) for row in db.execute('SELECT data FROM cases ORDER BY json_extract(data,"$.updated_at") DESC')]

    def case_detail(self, case_id):
        with self.db() as db:
            row=db.execute('SELECT data FROM cases WHERE id=?',(case_id,)).fetchone()
            if not row: raise ValueError('Case not found.')
            case=json.loads(row['data'])
            case['evidence']=[json.loads(r['data']) for r in db.execute('SELECT data FROM evidence WHERE case_id=? ORDER BY rowid',(case_id,))]
            return case

    def evidence(self, evidence_id):
        with self.db() as db:
            row=db.execute('SELECT data FROM evidence WHERE id=?',(evidence_id,)).fetchone()
            if not row: raise ValueError('Evidence not found.')
            return json.loads(row['data'])

    def _evidence(self, db, case, actor, message_id, text, media=None, metadata=None):
        items=[{'media_type':'text','text':text,'metadata':metadata or {}}]+(media or [])
        for item in items:
            e={'evidence_id':ident('EV'),'case_id':case['case_id'],'source_actor':str(actor),'source_message_id':str(message_id),'timestamp':now(),'media_type':item.get('media_type','file'),'storage_uri':item.get('storage_uri'),'extracted_data':item}
            db.execute('INSERT INTO evidence VALUES(?,?,?)',(e['evidence_id'],case['case_id'],json.dumps(e)))
            self._event(case,'evidence',text if item.get('media_type','file')=='text' else item.get('media_type','file'),actor,{'evidence_id':e['evidence_id']})

    def record_reply(self, actor_id, case_id, text, message_id, media=None):
        with self.lock, self.db() as db:
            c=self.case_detail(case_id)
            self._evidence(db,c,'silo',message_id,text,media,{'recipient':str(actor_id)})
            self._save(db,c)

    def roster(self):
        cases=self.list_cases()
        with self.db() as db:
            actors={r['vet_id']:r['actor_id'] for r in db.execute('SELECT * FROM vet_bindings')}
        return [{**v,'telegram_user_id':actors.get(v['vet_id']),'workload':sum(c.get('assigned_vet')==v['vet_id'] and c['status']!='CLOSED' and c['provenance']=='live_demo' for c in cases)} for v in VETS]

    def _new(self, actor_id):
        return {'case_id':ident('CASE'),'telegram_user_id':str(actor_id),'status':'INTAKE','provenance':'live_demo','created_at':now(),'updated_at':now(),'fields':{},'unknown_fields':[],'transcript':[],'events':[],'assigned_vet':None,'priority':'routine','category':'general illness','protocol':None,'recommendation':None,'report':{},'feedback':{}}

    def _model(self, instruction, payload):
        result=self.model.extract(instruction,payload)
        if not isinstance(result,dict): raise ValueError('Muse returned invalid structured data. Please retry.')
        return result

    def message(self, actor_id, text, message_id, role=None, media=None, case_id=None, metadata=None, language="en"):
        actor_id=str(actor_id); message_id=str(message_id)
        with self.lock, self.db() as db:
            duplicate=db.execute('SELECT response FROM messages WHERE actor=? AND message_id=?',(actor_id,message_id)).fetchone()
            if duplicate: return json.loads(duplicate['response'])
            actor=self.actor(actor_id)
            if not actor:
                if role: actor=self.register(actor_id,role)
                else: raise ValueError('Register as farmer or vet first.')
            available=[c for c in self.list_cases() if c['provenance']=='live_demo' and c['status']!='CLOSED' and (c['telegram_user_id']==actor_id if actor['role']=='farmer' else c.get('assigned_vet')==actor['vet_id'])]
            if case_id:
                c=self.case_detail(case_id)
                if c not in available and not any(x['case_id']==case_id for x in available): raise ValueError('This case is not active for your role.')
            elif available: c=available[0]
            elif actor['role']=='farmer': c=self._new(actor_id)
            else: raise ValueError('No assignment is awaiting you.')
            original_text=text
            if language=='hi':
                text=canonicalize_input(text,self.model)
                metadata={**(metadata or {}),'source_language':'hi','canonical_text':text,'translation_model':'local Muse; fixed short-answer vocabulary'}
                c['language']='hi'
            self._evidence(db,c,actor_id,message_id,original_text,media,metadata)
            entry={'actor':actor['role'],'text':original_text,'timestamp':now(),'message_id':message_id}
            if language=='hi': entry.update({'language':'hi','canonical_text':text})
            c['transcript'].append(entry)
            if text=='[Voice note unclear; please ask me to repeat.]':
                reply='I could not hear that clearly. Please repeat or send a text message. '+c.get('last_question','')
            elif actor['role']=='vet': reply=self._vet(db,c,text,media)
            elif c['status'] in ('AWAITING_FEEDBACK','NEEDS_REVIEW') and c.get('report'): reply=self._feedback(db,c,text)
            elif c['status']=='INTAKE': reply=self._intake(db,c,text)
            else: reply=f"Your case {c['case_id']} is {c['status'].lower().replace('_',' ')}. Your message has been added for the operator."
            canonical_reply=reply
            if language=='hi': reply=localize_reply(reply,self.model)
            entry={'actor':'silo','text':reply,'timestamp':now()}
            if language=='hi': entry.update({'language':'hi','canonical_text':canonical_reply})
            c['transcript'].append(entry)
            self._save(db,c)
            response={'reply':reply,'case_id':c['case_id'],'status':c['status']}
            if language=='hi': response.update({'language':'hi','canonical_reply':canonical_reply})
            db.execute('INSERT INTO messages VALUES(?,?,?)',(actor_id,message_id,json.dumps(response)))
            return response

    def _intake(self, db, c, text):
        result=self._model('Extract only facts explicitly stated by the farmer in the latest message, interpreting short answers against last_question. Return {"updates":{field:value},"unknown_fields":[],"evidence":{field:"exact quote from latest message"},"confirmed":boolean,"ambiguous":boolean}. Fields: '+', '.join(QUESTIONS)+', contact. animals_affected MUST be a JSON integer (e.g. 1), NOT a sentence. symptoms and urgent_warning_signs MUST be JSON arrays of strings. No warning signs is []. No treatment is "none". Preserve corrections. Unknown is explicit "I do not know", not missing. Missing information MUST be omitted, NEVER labeled unknown. Do not assume no prior treatment or no urgent signs. Include an exact message quote in evidence for each updated field. confirmed only when explicitly agreeing to the summary. Never infer animal type, name or district.',{'fields':c['fields'],'last_question':c.get('last_question'),'message':text,'confirming':c.get('confirming',False)})
        updates=result.get('updates',{})
        if not isinstance(updates,dict): updates={}
        updates={k:v for k,v in updates.items() if k in {*QUESTIONS,'contact'} and v is not None}
        latest=text.lower(); last=c.get('last_question','')
        previous_fields=dict(c['fields'])
        negative=bool(re.match(r'^(no|nope|none|not at all)\b',latest.strip()))
        explicit_warning=bool(re.search(r"can't stand|cannot stand|unable to stand|struggling to breathe|is unconscious",latest))
        if last==QUESTIONS['urgent_warning_signs'] and negative and not explicit_warning:
            updates['urgent_warning_signs']=[]
        if last==QUESTIONS['previous_treatment'] and negative:
            updates['previous_treatment']='none'
        if re.search(r"don't know|do not know|not sure|unknown|cannot recall|can't recall",latest):
            current=next((k for k,q in QUESTIONS.items() if q==last),None)
            if current and current not in updates and len(latest.split())<=12:
                result['unknown_fields']=list(set(result.get('unknown_fields',[])+[current]))
                updates.pop(current,None)
        evidence=result.get('evidence',{})
        if not isinstance(evidence,dict): evidence={}
        # Preserve simple explicit observations when the model returns no fields.
        # Questions and negated statements are left to contextual extraction.
        if '?' not in text and not re.search(r"\b(?:not|no|never|isn't|isnt|isn’t)\b",latest):
            animals=re.findall(r'\b(?:my|our|the|a|one|big|small)\s+(cow|buffalo|goat|sheep|calf|ox|pig|horse)\b',latest)
            if len(set(animals))==1 and 'animal_type' not in updates:
                updates['animal_type']=animals[0]; evidence['animal_type']=animals[0]
            if 'symptoms' not in updates and re.search(r'\b(?:looks?|is|seems?)\s+weak\b',latest):
                updates['symptoms']=['weak']; evidence['symptoms']='weak'
        for k in list(updates):
            quote=evidence.get(k)
            if isinstance(quote,list): quote=next((q for q in quote if isinstance(q,str) and q.strip() and q.lower() in latest),None)
            contextual=last==QUESTIONS.get(k)
            if not contextual and (not isinstance(quote,str) or not quote.strip() or quote.lower() not in latest):
                updates.pop(k); continue
            if isinstance(updates[k],str) and updates[k].lower() in ('unknown','not known') and not re.search(r"don't know|do not know|not sure|unknown",latest):
                updates.pop(k); continue
            if k=='previous_treatment' and last!=QUESTIONS[k] and not re.search(r'\b(treat\w*|medicine|medication|injection|remedy|remedies)\b',latest): updates.pop(k)
            elif k=='urgent_warning_signs' and last!=QUESTIONS[k] and not re.search(r'\b(stand|standing|breath\w*|conscious|unconscious|warning)\b',latest): updates.pop(k)
            elif k=='animals_affected' and last!=QUESTIONS[k] and not re.search(r'\b(\d+|one|two|three|four|five|six|seven|eight|nine|ten|single)\s+(cow|calf|calves|goat|sheep|buffalo|animal|ox|pig|horse|chicken|are affected|is affected)',latest): updates.pop(k)
            elif k in ('animal_type','farmer_name','village','district') and str(updates[k]).lower() not in latest: updates.pop(k)
        for k,v in updates.items():
            if k in ('symptoms','urgent_warning_signs') and not isinstance(v,list): v=[str(v)]
            if k=='animals_affected':
                try: v=int(v)
                except (ValueError,TypeError):
                    number=re.search(r'\b(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\b',str(v).lower())
                    if not number: continue
                    token=number.group(1); v=int(token) if token.isdigit() else ['zero','one','two','three','four','five','six','seven','eight','nine','ten'].index(token)
                if v<1: continue
            c['fields'][k]=v
            if k in c['unknown_fields']: c['unknown_fields'].remove(k)
        explicit_unknown=bool(re.search(r"don't know|do not know|not sure|unknown|cannot recall|can't recall",latest))
        for k in result.get('unknown_fields',[]):
            if explicit_unknown and k in QUESTIONS and k not in updates and (last==QUESTIONS[k] or k.replace('_',' ') in latest or (k=='symptoms_since' and ('onset' in latest or 'when' in latest)) or (k=='previous_treatment' and 'treatment' in latest)):
                c['fields'][k]='unknown'; c['unknown_fields']=list(set(c['unknown_fields']+[k]))
        missing=[k for k in QUESTIONS if k not in c['fields'] or c['fields'][k] in (None,'',[]) and k not in ('urgent_warning_signs',)]
        self._event(c,'extraction','Intake observations updated',data={'updates':{k:v for k,v in c['fields'].items() if previous_fields.get(k)!=v},'unknown_fields':c['unknown_fields'],'model':'muse-glimmer-30b'})
        c.update({k:c['fields'].get(k) for k in QUESTIONS})
        warnings=c['fields'].get('urgent_warning_signs',[])
        c['priority']='urgent' if isinstance(warnings,list) and warnings else 'routine'
        if result.get('ambiguous') and not updates and not result.get('unknown_fields'):
            return 'Could you clarify that? '+c.get('last_question','What animal is unwell?')
        if missing:
            c['confirming']=False
            c['last_question']=QUESTIONS[missing[0]]
            warning='I will flag this for urgent human review. ' if c['priority']=='urgent' and not c.get('urgent_notified') else ''
            if warning: c['urgent_notified']=True
            return warning+c['last_question']
        if c.get('confirming') and result.get('confirmed') and c['fields']==previous_fields:
            self._status(c,'NEW'); self._recommend(c); self._status(c,'AWAITING_ASSIGNMENT')
            return f"Thank you. Case {c['case_id']} has been submitted for an operator to arrange veterinary assistance."
        c['confirming']=True
        f=c['fields']
        summary='; '.join(f"{k.replace('_',' ')}: {', '.join(map(str,v)) if isinstance(v,list) and v else ('none reported' if v==[] else v)}" for k,v in f.items())
        c['last_question']='Are these details correct?'
        return summary+'. Are these details correct?'

    def _recommend(self,c):
        roster=self.roster()
        result=self._model('Select relevant demonstration routing protocol and recommend a vet using geographic coverage, availability, specialization and workload. Return {"protocol_id":string,"vet_id":string,"reason":string,"category":string}. Use only provided IDs; no medical treatment advice.',{'case':c['fields'],'protocols':PROTOCOLS,'roster':roster})
        protocol=next((p for p in PROTOCOLS if p['id']==result.get('protocol_id')),None)
        vet=next((v for v in roster if v['vet_id']==result.get('vet_id') and v['availability'] and v['workload']==0),None)
        c['protocol']=protocol or PROTOCOLS[0]
        c['category']=str(result.get('category','general illness'))[:100]
        c['recommendation']={'vet_id':vet['vet_id'] if vet else None,'name':vet['name'] if vet else None,'reason':str(result.get('reason','Operator selection needed.')) if vet else 'No eligible model recommendation. Select an available vet.','model':'muse-glimmer-30b'}
        self._event(c,'recommendation','Protocol and vet recommendation prepared',data=c['recommendation'])

    def assign(self,case_id,vet_id,operator):
        if not str(operator).strip(): raise ValueError('Operator identity is required.')
        with self.lock,self.db() as db:
            c=self.case_detail(case_id)
            if c['status']!='AWAITING_ASSIGNMENT': raise ValueError('Case is not awaiting assignment.')
            v=next((v for v in self.roster() if v['vet_id']==vet_id),None)
            if not v or not v['availability'] or v['workload']: raise ValueError('Vet is unavailable or already assigned.')
            if not v['telegram_user_id']: raise ValueError('The vet must register in Telegram before assignment.')
            c['assigned_vet']=vet_id; c['assigned_at']=now(); c['assigned_vet_actor']=v['telegram_user_id']
            self._event(c,'approval','Assignment approved',operator,{'vet_id':vet_id})
            self._status(c,'ASSIGNED')
            self._notify(db,v['telegram_user_id'],c,f"You have been assigned {case_id} in {c.get('village','unknown village')}. {c.get('animal_type','Animal')}: {', '.join(c['fields'].get('symptoms',[]))}. Can you accept this case?")
            self._save(db,c)
            return c

    def _notify(self,db,actor,c,text):
        db.execute('INSERT INTO outbox(actor_id,case_id,text) VALUES(?,?,?)',(str(actor),c['case_id'],text))
        c['transcript'].append({'actor':'silo','recipient':str(actor),'text':text,'timestamp':now()})
        self._event(c,'notification','Message queued',data={'recipient':str(actor),'text':text})

    def pending_outbox(self):
        with self.db() as db: return [dict(r) for r in db.execute('SELECT * FROM outbox WHERE delivered=0 ORDER BY id')]

    def mark_delivered(self,ident):
        with self.db() as db: db.execute('UPDATE outbox SET delivered=1 WHERE id=?',(ident,))

    @staticmethod
    def _grounded(result, field, text, contextual=False):
        """Reject fields sourced from old state or a bare answer to another question."""
        bare=bool(re.fullmatch(r'\s*(yes|yeah|yes please|no|nope|none|correct|no thanks)[.! ]*',text.lower()))
        if bare: return contextual and field in ('visit_confirmed','further_help_required','service_satisfaction','follow_up_required','visit_status','treatment_reported')
        evidence=result.get('evidence',{})
        if not isinstance(evidence,dict): return contextual
        quotes=evidence.get(field,[])
        if isinstance(quotes,str): quotes=[quotes]
        if not isinstance(quotes,list): return contextual
        return contextual or bool(quotes) and all(isinstance(q,str) and q.strip() and q.lower() in text.lower() for q in quotes)

    def _vet(self,db,c,text,media):
        r=self._model('Extract the vet message into {"accepted":boolean,"declined":boolean,"report":{visit_status,visit_time,reported_location,observations,treatment_reported,follow_up_required},"evidence":{field:"exact quote from latest message"},"confirmed":boolean}. Include evidence for every report field. follow_up_required MUST be boolean, never string. Report values only if explicitly stated. visit_status must be "visited" only if explicitly reporting a visit, never from photo/location alone. confirmed only explicit confirmation of pending report. No invented clinical information.',{'status':c['status'],'pending_report':c.get('pending_report'),'last_question':c.get('report_question'),'message':text,'media_types':[m.get('media_type') for m in media or []]})
        if c['status']=='ASSIGNED':
            if r.get('declined'):
                self._status(c,'NEEDS_REVIEW'); return 'Decline recorded. The operator will review this assignment.'
            if not r.get('accepted'): return 'Please confirm whether you accept this assignment.'
            self._status(c,'ACCEPTED'); c['accepted_at']=now()
            return 'Assignment accepted. After your visit, send your observations, treatment provided and follow-up needs. You can also send a photo and location.'
        if c['status'] not in ('ACCEPTED','VISITED','AWAITING_FEEDBACK','NEEDS_REVIEW'): return 'Your evidence has been saved for operator review.'
        updates=r.get('report',{})
        if not isinstance(updates,dict): updates={}
        updates={k:v for k,v in updates.items() if k in ('visit_status','visit_time','reported_location','observations','treatment_reported','follow_up_required') and v is not None and v!=''}
        updates={k:v for k,v in updates.items() if self._grounded(r,k,text,c.get('report_question')==k) and (k!='follow_up_required' or isinstance(v,bool))}
        previous_report=dict(c.get('pending_report',{}))
        pending=c.get('pending_report',{}); pending.update(updates); c['pending_report']=pending
        if c.get('report') and pending==previous_report:
            return 'Your evidence has been added to the visit report.'
        if r.get('confirmed') and c.get('report_confirming') and pending==previous_report and pending.get('visit_status')=='visited' and all(k in pending for k in ('observations','treatment_reported','follow_up_required')):
            c['report']={**pending,'vet_confirmation':True,'reported_at':now(),'verification':'vet-reported'}
            c['visited_at']=now(); self._status(c,'VISITED'); self._status(c,'AWAITING_FEEDBACK')
            c['report_confirming']=False
            self._notify(db,c['telegram_user_id'],c,'The vet has reported a visit. Did the vet visit your animal? What did they do?')
            return 'Visit report saved as vet-reported. We will ask the farmer to confirm what happened.'
        missing=[k for k in ('visit_status','observations','treatment_reported','follow_up_required') if k not in pending]
        if missing:
            c['report_question']=missing[0]
            return 'Evidence saved. '+{'visit_status':'Have you visited the animal?','observations':'What did you observe during the visit?','treatment_reported':'What treatment or assistance did you provide? Say none if none.','follow_up_required':'Is follow-up assistance required?'}[missing[0]]
        if pending['visit_status']!='visited': return 'Visit status recorded. Send a report when the visit has taken place.'
        c['report_confirming']=True
        return 'Your report: '+ '; '.join(f'{k.replace("_"," ")}: {"yes" if v is True else "no" if v is False else v}' for k,v in pending.items())+'. Is this correct?'

    def _feedback(self,db,c,text):
        r=self._model('Extract farmer feedback only from their message, contextualized by last_question. Return {"updates":{visit_confirmed:boolean,farmer_reported_service:string,farmer_reported_condition:string,service_satisfaction:string,further_help_required:boolean},"evidence":{field:"exact quote from latest message"},"disagreement":boolean}. Include evidence for every updated field. Do not infer satisfaction, visit or improvement from the vet report. disagreement only explicit contradiction. Omit unknown fields.',{'existing':c['feedback'],'last_question':c.get('feedback_question','Did the vet visit your animal? What did they do?'),'message':text,'vet_report':c['report']})
        allowed={'visit_confirmed','farmer_reported_service','farmer_reported_condition','service_satisfaction','further_help_required'}
        f=c['feedback']; updates=r.get('updates',{})
        qs={'visit_confirmed':'Did the vet visit your animal?','farmer_reported_service':'What did the vet do?','farmer_reported_condition':'How is the animal doing now?','further_help_required':'Do you need additional assistance?','service_satisfaction':'Were you satisfied with the assistance?'}
        last=c.get('feedback_question','Did the vet visit your animal? What did they do?')
        contextual=next((k for k,q in qs.items() if last==q),None)
        if last.startswith('Did the vet visit'): contextual='visit_confirmed'
        yn=re.fullmatch(r'\s*(yes|yeah|yes please|no|nope|no thanks)[.! ]*',text.lower())
        if yn and contextual in ('visit_confirmed','further_help_required'):
            updates={contextual:yn.group(1).startswith(('yes','yeah'))}
        if isinstance(updates,dict):
            for k,v in updates.items():
                if k in allowed and v is not None and self._grounded(r,k,text,contextual==k) and (k not in ('visit_confirmed','further_help_required') or isinstance(v,bool)): f[k]=v
        f['feedback_timestamp']=now()
        f['verification']='single-account roleplay' if c.get('assigned_vet_actor')==c['telegram_user_id'] else 'independent farmer account'
        if f.get('visit_confirmed') is False or r.get('disagreement') or f.get('further_help_required') is True:
            c['disputed']=f.get('visit_confirmed') is False or bool(r.get('disagreement')); self._status(c,'NEEDS_REVIEW')
        qs={'visit_confirmed':'Did the vet visit your animal?','farmer_reported_service':'What did the vet do?','farmer_reported_condition':'How is the animal doing now?','further_help_required':'Do you need additional assistance?','service_satisfaction':'Were you satisfied with the assistance?'}
        missing=[k for k in qs if k not in f]
        if f.get('visit_confirmed') is False: missing=[k for k in missing if k not in ('farmer_reported_service','service_satisfaction')]
        if missing: c['feedback_question']=qs[missing[0]]; return c['feedback_question']
        return 'Thank you. Your feedback is saved for operator review.'

    def close(self,case_id,operator):
        if not str(operator).strip(): raise ValueError('Operator identity is required.')
        with self.lock,self.db() as db:
            c=self.case_detail(case_id); f=c['feedback']
            if c['status']!='AWAITING_FEEDBACK' or c.get('disputed') or f.get('visit_confirmed') is not True or f.get('further_help_required') is not False or not f.get('farmer_reported_condition'):
                raise ValueError('Cannot close an unresolved or disputed case. Independent farmer confirmation and no further help are required.')
            self._status(c,'CLOSED'); c['closed_at']=now()
            c['summary']={'text':f"{c['case_id']}: {c.get('animal_type')} in {c.get('village')}. Vet-reported visit confirmed ({f.get('verification','independent farmer account')}). Farmer condition: {f['farmer_reported_condition']}. No further help requested.",'evidence_ids':[e['evidence_id'] for e in c.get('evidence',[])],'closed_by':str(operator)}
            self._event(c,'closure',c['summary']['text'],operator,c['summary']); self._save(db,c)
            return c

    def seed(self):
        rng=random.Random(42)
        with self.lock,self.db() as db:
            for n in range(150):
                cid=f'HIST-{n+1:03}'
                if db.execute('SELECT 1 FROM cases WHERE id=?',(cid,)).fetchone(): continue
                c=self._new('synthetic-farmer-'+str(n)); c['case_id']=cid; c['provenance']='synthetic_history'
                created=datetime.now(timezone.utc)-timedelta(days=rng.randint(7,90),hours=rng.randint(0,23))
                assigned=created+timedelta(hours=rng.randint(1,18)); accepted=assigned+timedelta(hours=rng.randint(1,10)); visited=accepted+timedelta(hours=rng.randint(1,24))
                status=rng.choice(['CLOSED']*6+['ASSIGNED','ACCEPTED','AWAITING_FEEDBACK','NEEDS_REVIEW'])
                c.update(farmer_name=f'Demo farmer {n+1}',village=rng.choice(['Neemgaon','Rampur','Sonapur','Lotuspur','Jasminpur','Palashpur']),district=rng.choice(['Demo North','Demo South','Demo East']),animal_type='cow',animals_affected=1,category=rng.choice(['weakness','appetite loss','mobility']),priority=rng.choice(['routine','routine','urgent']),status=status,assigned_vet=rng.choice(VETS)['vet_id'],created_at=created.isoformat(),assigned_at=assigned.isoformat(),updated_at=visited.isoformat())
                if status!='ASSIGNED': c['accepted_at']=accepted.isoformat()
                if status in ('CLOSED','AWAITING_FEEDBACK','NEEDS_REVIEW'): c['visited_at']=visited.isoformat(); c['report']={'verification':'vet-reported','observations':'Synthetic historical observation'}
                if status=='CLOSED': c['closed_at']=(visited+timedelta(hours=rng.randint(2,72))).isoformat(); c['feedback']={'visit_confirmed':True,'further_help_required':False,'farmer_reported_condition':rng.choice(['improved','recovered','stable'])}
                if status=='NEEDS_REVIEW': c['feedback']={'visit_confirmed':False,'further_help_required':True,'farmer_reported_condition':'not improved'}
                c['fields']={k:c.get(k,'unknown') for k in QUESTIONS}; c['events']=[{'timestamp':created.isoformat(),'type':'seed','text':'Synthetic historical case','actor':'seed','data':{}}]
                db.execute('INSERT INTO cases VALUES(?,?)',(cid,json.dumps(c)))

    def _sql(self,sql):
        with self.db() as db: return [dict(r) for r in db.execute(sql)]

    def metrics(self):
        cases=self.list_cases(); submitted=[c for c in cases if c['status']!='INTAKE']
        def counts(key):
            out={}
            for c in submitted:
                value=c.get(key,'unknown')
                if key=='district' and isinstance(value,str):
                    normalized=re.sub(r'\s+district$','',value.strip(),flags=re.I).casefold()
                    value=next((v['district'] for v in VETS if v['district'].casefold()==normalized),value)
                out[value]=out.get(value,0)+1
            return [{'label':k,'value':v} for k,v in sorted(out.items(),key=lambda x:-x[1])]
        def mean_hours(end,start):
            vals=[(datetime.fromisoformat(c[end])-datetime.fromisoformat(c[start])).total_seconds()/3600 for c in submitted if c.get(end) and c.get(start)]
            return round(sum(vals)/len(vals),2) if vals else None
        assigned=sum(bool(c.get('assigned_at')) for c in submitted); visits=sum(bool(c.get('visited_at')) for c in submitted)
        return {'total_cases':len(submitted),'open_cases':sum(c['status']!='CLOSED' for c in submitted),'synthetic_cases':sum(c['provenance']=='synthetic_history' for c in submitted),'live_cases':sum(c['provenance']=='live_demo' for c in submitted),'reported_visits':visits,'farmer_confirmed_visits':sum(c['feedback'].get('visit_confirmed') is True for c in submitted),'independently_confirmed_visits':sum(c['feedback'].get('visit_confirmed') is True and c['feedback'].get('verification')!='single-account roleplay' for c in submitted),'unresolved_cases':sum(c['status']!='CLOSED' for c in submitted),'assignment_hours':mean_hours('assigned_at','created_at'),'resolution_hours':mean_hours('closed_at','created_at'),'acceptance_rate':round(100*sum(bool(c.get('accepted_at')) for c in submitted)/assigned,1) if assigned else 0,'by_status':counts('status'),'by_category':counts('category'),'by_priority':counts('priority'),'by_village':counts('village'),'by_district':counts('district'),'outcomes':[{'label':k,'value':sum(c['feedback'].get('farmer_reported_condition','unknown')==k for c in submitted)} for k in sorted(set(c['feedback'].get('farmer_reported_condition','unknown') for c in submitted))]}

    def query(self,question):
        queries={
          'unresolved':('Villages with unresolved cases',"SELECT json_extract(data,'$.village') AS village, count(*) AS unresolved FROM cases WHERE json_extract(data,'$.status') NOT IN ('CLOSED','INTAKE') GROUP BY village ORDER BY unresolved DESC"),
          'urgent_resolution':('Resolution time by priority (closed cases only)',"SELECT json_extract(data,'$.priority') AS priority,count(*) AS closed_cases,round(avg((julianday(json_extract(data,'$.closed_at'))-julianday(json_extract(data,'$.created_at')))*24),2) AS mean_hours FROM cases WHERE json_extract(data,'$.status')='CLOSED' GROUP BY priority"),
          'pending_vets':('Pending assignments by vet',"SELECT json_extract(data,'$.assigned_vet') AS vet_id,count(*) AS pending FROM cases WHERE json_extract(data,'$.status')='ASSIGNED' GROUP BY vet_id ORDER BY pending DESC"),
          'confirmed_visits':('Independent visit confirmation',"SELECT count(*) AS reported_visits,sum(CASE WHEN json_extract(data,'$.feedback.visit_confirmed')=1 AND coalesce(json_extract(data,'$.feedback.verification'),'independent farmer account')!='single-account roleplay' THEN 1 ELSE 0 END) AS confirmed_visits,round(100.0*sum(CASE WHEN json_extract(data,'$.feedback.visit_confirmed')=1 AND coalesce(json_extract(data,'$.feedback.verification'),'independent farmer account')!='single-account roleplay' THEN 1 ELSE 0 END)/nullif(count(*),0),1) AS confirmed_percent FROM cases WHERE json_extract(data,'$.visited_at') IS NOT NULL"),
          'outcomes':('Farmer-reported outcomes by month',"SELECT substr(json_extract(data,'$.created_at'),1,7) AS month,json_extract(data,'$.feedback.farmer_reported_condition') AS condition,count(*) AS cases FROM cases WHERE json_extract(data,'$.feedback.farmer_reported_condition') IS NOT NULL GROUP BY month,condition ORDER BY month,condition")}
        selected=self._model('Choose the best supported analytical query. Return {"query_id": one provided ID or "unsupported"}. Select by meaning; never invent a query. Recovery/cause questions use outcomes; causal explanations require more evidence.',{'question':question,'queries':{k:v[0] for k,v in queries.items()}}).get('query_id')
        if selected not in queries: return {'answer':'Ask about unresolved villages, urgent resolution time, pending vets, confirmed visits, or monthly outcomes.','query_id':'unsupported','rows':[],'sql':None,'chart':None}
        title,sql=queries[selected]; rows=self._sql(sql)
        answer=title+'. '+ ' '.join(', '.join(f'{k}: {v}' for k,v in row.items())+'.' for row in rows)
        if selected=='outcomes': answer+=' These are descriptive patterns; the data does not establish why outcomes changed.'
        return {'answer':answer,'query_id':selected,'sql':sql,'rows':rows,'chart':{'type':'bar','title':title},'provenance':'Includes synthetic historical and live demonstration cases; intake drafts excluded where relevant.'}
