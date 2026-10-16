"""Opt-in integration check: python -m examples.livelihoods.livestock.full_call_center.tests.test_live_model [--voice].

Calls actual local Muse (and Whisper/Kokoro with --voice). Only Telegram delivery
is a recording mock: no Telegram account receives these synthetic test messages.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

from examples.livelihoods.livestock.full_call_center.engine import Engine
from examples.livelihoods.livestock.full_call_center.model import Muse
from examples.livelihoods.livestock.full_call_center.storage import AssetStore


class MeasuredMuse(Muse):
    def __init__(self, evidence):
        super().__init__()
        self.evidence = evidence

    def extract(self, instruction, payload):
        start = time.monotonic()
        result = super().extract(instruction, payload)
        self.evidence.append({'instruction': instruction, 'payload': payload,
                              'result': result, 'seconds': round(time.monotonic()-start, 3)})
        return result


def run(voice=False):
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    output = Path('/mnt/seagate/silo/livestock-v2/tests') / stamp
    output.mkdir(parents=True, exist_ok=True)
    private = Path.home()/'.local/share/idli-bridge/livestock/tests'/stamp
    private.mkdir(parents=True, exist_ok=True, mode=0o700)
    result = {'started_at': stamp, 'transport': 'MOCK Telegram delivery; actual Engine and local Muse',
              'model_calls': [], 'turns': [], 'deliveries': [], 'checks': [], 'voice': None}
    def check(condition, label):
        assert condition, label
        result['checks'].append(label)
    engine = Engine(private/'cases.db', model=MeasuredMuse(result['model_calls']))
    assets = AssetStore(output/'assets')
    engine.register('synthetic-farmer', 'farmer')
    for n in (1,2,3,5):
        engine.register('synthetic-vet-'+str(n), 'vet', 'VET-'+str(n).zfill(2))
    def say(actor, text, media=None):
        start=time.monotonic()
        response=engine.message(actor,text,str(len(result['turns'])+1),media=media)
        result['turns'].append({'actor':actor,'text':text,'response':response,'seconds':round(time.monotonic()-start,3)})
        print(actor+': '+text+'\nSilo: '+response['reply'],flush=True)
        return response
    def deliver():
        for item in engine.pending_outbox():
            result['deliveries'].append({**item,'transport':'recording mock'})
            engine.record_reply(item['actor_id'],item['case_id'],item['text'],'mock-out-'+str(item['id']))
            engine.mark_delivered(item['id'])
    try:
        initial='My cow has been unwell since yesterday. She is not eating and looks weak.'
        media=None
        if voice:
            from examples.livelihoods.livestock.full_call_center import speech
            import onnxruntime as ort
            from kokoro_onnx import Kokoro
            options=ort.SessionOptions()
            options.intra_op_num_threads=4
            options.inter_op_num_threads=1
            session=ort.InferenceSession(str(Path(speech.MODELS)/'kokoro/kokoro-v1.0.onnx'),sess_options=options,providers=['CPUExecutionProvider'])
            speech._kokoro=Kokoro.from_session(session,str(Path(speech.MODELS)/'kokoro/voices-v1.0.bin'))
            begin=time.monotonic()
            audio=speech.synth(initial,voice='hf_alpha',lang='en-us')
            transcript=speech.transcribe(audio,language='en')
            result['voice']={'voice':'hf_alpha','language':'en-us','source_text':initial,'transcript':transcript,'seconds':round(time.monotonic()-begin,3)}
            media=[assets.put(audio,'audio/ogg')]
            check('cow' in transcript.lower(),'Whisper recovers animal from synthetic hf_alpha voice note')
            initial=transcript
        r=say('synthetic-farmer',initial,media)
        cid=r['case_id']
        check(r['status']=='INTAKE','First message creates intake draft')
        check('stand' in r['reply'].lower(),'Muse extracts initial animal/symptoms and asks missing urgency')
        r=say('synthetic-farmer','No. She can stand and walk, breathes normally, and is conscious. Only one cow is affected.')
        check(engine.case_detail(cid)['fields']['urgent_warning_signs']==[],'Negative warning answer retained as answered')
        r=say('synthetic-farmer',"I do not know whether she has had any treatment. My name is Anjali. I am in Rampur in Demo North district.")
        check(engine.case_detail(cid)['fields']['previous_treatment']=='unknown','Explicit unknown is preserved')
        r=say('synthetic-farmer','Correction: my village is Neemgaon, not Rampur. The symptoms began two days ago, not yesterday.')
        case=engine.case_detail(cid)
        check(case['fields']['village']=='Neemgaon','Village correction replaces old value')
        check('two' in str(case['fields']['symptoms_since']).lower() or '2' in str(case['fields']['symptoms_since']),'Duration correction replaces old value')
        check(case.get('confirming'),'Summary requested before case submission')
        r=say('synthetic-farmer','Yes, those details are correct. Please submit the case.')
        case=engine.case_detail(cid)
        check(r['status']=='AWAITING_ASSIGNMENT','Confirmed intake submitted in five farmer turns')
        check(case['protocol']['synthetic'] is True,'Approved demonstration protocol attached')
        vet=case['recommendation']['vet_id']
        check(vet in ('VET-01','VET-02'),'Muse recommends available local cattle vet')
        check(not engine.pending_outbox(),'Vet is not contacted before operator approval')
        engine.assign(cid,vet,'Synthetic ERC operator')
        deliver()
        vet_actor='synthetic-vet-'+str(int(vet.split('-')[1]))
        check(result['deliveries'][-1]['actor_id']==vet_actor,'Approved assignment queued to separate vet actor')
        say(vet_actor,'Yes, I accept this assignment.')
        check(engine.case_detail(cid)['status']=='ACCEPTED','Vet acceptance advances workflow')
        from PIL import Image, ImageDraw
        image=Image.new('RGB',(640,400),'#e4e9d9')
        ImageDraw.Draw(image).text((30,180),'SYNTHETIC FIELD PHOTO — TEST ONLY',fill='black')
        photo_path=output/'synthetic-field-photo.png'
        image.save(photo_path)
        photo=assets.put(photo_path.read_bytes(),'image/png')
        location={'media_type':'location','latitude':19.1,'longitude':73.0,'storage_uri':None,'synthetic':True}
        say(vet_actor,'Here is a photograph and the shared location.',[photo,location])
        check(engine.case_detail(cid)['status']=='ACCEPTED','Photo/location do not independently prove a visit')
        say(vet_actor,'I visited the cow today at 10 AM in Neemgaon. I observed reduced appetite and weakness. I examined the animal and gave no medication. No follow-up assistance is required.')
        check(engine.case_detail(cid).get('report_confirming'),'Vet report asks for confirmation')
        say(vet_actor,'Yes, the visit report is correct.')
        check(engine.case_detail(cid)['status']=='AWAITING_FEEDBACK','Confirmed vet report awaits independent feedback')
        deliver()
        check(result['deliveries'][-1]['actor_id']=='synthetic-farmer','Feedback request sent separately to farmer')
        try:
            engine.close(cid,'Synthetic ERC operator')
        except ValueError:
            check(True,'Closure rejected before farmer feedback')
        else:
            raise AssertionError('Premature closure permitted')
        say('synthetic-farmer','Yes, the vet visited and examined my cow. No medicine was given. She is eating again and has improved. I am satisfied, and I do not need any more assistance.')
        case=engine.case_detail(cid)
        check(case['feedback'].get('visit_confirmed') is True,'Farmer independently confirms visit')
        check(case['feedback'].get('further_help_required') is False,'Farmer explicitly declines further help')
        before=engine.metrics()
        engine.close(cid,'Synthetic ERC operator')
        after=engine.metrics()
        check(after['open_cases']==before['open_cases']-1,'Operator closure updates district open count')
        check(after['total_cases']==151 and after['synthetic_cases']==150 and after['live_cases']==1,'Historical and live provenance counted separately')
        result['analytics']=[]
        for question,qid in [('Which villages have the most unresolved cases?','unresolved'),('What percentage of visits were independently confirmed?','confirmed_visits')]:
            answer=engine.query(question)
            check(answer['query_id']==qid,'Muse selects '+qid+' query')
            cases=engine.list_cases()
            if qid=='unresolved':
                expected=Counter(c['village'] for c in cases if c['status'] not in ('CLOSED','INTAKE'))
                check({r['village']:r['unresolved'] for r in answer['rows']}==dict(expected),'Unresolved query matches independent count')
            else:
                visited=[c for c in cases if c.get('visited_at')]
                confirmed=sum(c['feedback'].get('visit_confirmed') is True for c in visited)
                row=answer['rows'][0]
                check(row['reported_visits']==len(visited) and row['confirmed_visits']==confirmed and row['confirmed_percent']==round(100*confirmed/len(visited),1),'Visit percentage matches independent computation')
            result['analytics'].append({'question':question,**answer})
        case=engine.case_detail(cid)
        check(all(e['case_id']==cid for e in case['evidence']),'All original evidence explicitly associated with common case ID')
        check(any(e['media_type']=='image/png' for e in case['evidence']) and any(e['media_type']=='location' for e in case['evidence']),'Photo and location retained in evidence timeline')
        check(bool(case['summary']['evidence_ids']),'Closure summary links underlying evidence')
        result['case']=case
        result['metrics']=after
        result['passed']=True
    except Exception as exc:
        result['passed']=False
        result['error']=str(exc)
        raise
    finally:
        (output/'evidence.json').write_text(json.dumps(result,indent=2))
        print('Evidence: '+str(output/'evidence.json'),flush=True)
    return output/'evidence.json'

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--voice',action='store_true')
    args=parser.parse_args()
    run(args.voice)
