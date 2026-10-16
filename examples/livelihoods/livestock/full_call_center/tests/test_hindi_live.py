"""Opt-in actual local Muse test: python -m examples.livelihoods.livestock.full_call_center.tests.test_hindi_live."""
import json
from copy import deepcopy
from pathlib import Path
import tempfile
from examples.livelihoods.livestock.full_call_center.engine import Engine
from examples.livelihoods.livestock.full_call_center.model import Muse
from examples.livelihoods.livestock.full_call_center.config import QUESTIONS


def run():
    calls=[]; turns=[]
    class MeasuredMuse(Muse):
        def extract(self,instruction,payload):
            result=super().extract(instruction,payload)
            calls.append({'instruction':instruction,'payload':deepcopy(payload),'result':deepcopy(result)})
            return result
    output=Path('/mnt/seagate/silo/livestock-v2/tests/hindi-intake/actual-muse-human-progression.json')
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory() as folder:
        engine=Engine(Path(folder)/'cases.db',model=MeasuredMuse(),seed=False)
        def say(text):
            response=engine.message('synthetic-farmer',text,str(len(turns)),role='farmer',language='hi')
            case=engine.case_detail(response['case_id'])
            turns.append({'input':text,'response':response,'fields':case['fields']})
            output.write_text(json.dumps({'turns':turns,'calls':calls,'case':case},ensure_ascii=False,indent=2))
            print(text,'=>',response['reply'],flush=True)
            return case
        case=say('मेरी गाय खाना नहीं खा रही है और कमज़ोर है।')
        answers={'animal_type':'गाय।','symptoms':'खाना नहीं खा रही और कमज़ोर है।',
                 'urgent_warning_signs':'नहीं वह खड़ी हो सकती है और सांस सामान्य है।','symptoms_since':'मुझे नहीं पता।',
                 'animals_affected':'एक पशु।','previous_treatment':'नहीं।',
                 'farmer_name':'मेरा नाम अंजलि है।','village':'मेरा गाँव नीमगाँव है।',
                 'district':'डेमो नॉर्थ ज़िला।'}
        correction_done=False
        for _ in range(15):
            if case.get('confirming') and not correction_done:
                case=say('सुधार: गाय नहीं, भैंस है। दो दिन से बीमार है।')
                correction_done=True
                continue
            if case.get('confirming'):
                case=say('हाँ, सही है।')
            else:
                key=next(k for k,q in QUESTIONS.items() if q==case['last_question'])
                case=say(answers[key])
            if case['status']=='AWAITING_ASSIGNMENT': break
        assert case['status']=='AWAITING_ASSIGNMENT',case['status']
        assert case['fields']['animal_type']=='buffalo'
        assert case['fields']['urgent_warning_signs']==[]
        assert case['fields']['previous_treatment']=='none'
        assert case['fields']['village']=='Neemgaon'
        assert case['fields']['district'].strip().rstrip('.').removesuffix(' District').removesuffix(' district')=='Demo North'
        assert case['fields']['animals_affected']==1
        assert case['transcript'][0]['text']==turns[0]['input']
        assert all(any('\u0900'<=c<='\u097f' for c in t['response']['reply']) for t in turns)
        print('PASS Hindi actual Muse intake, unknown, No, correction, confirmation; evidence:',output)


if __name__=='__main__': run()
