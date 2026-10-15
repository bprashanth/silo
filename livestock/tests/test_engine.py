import tempfile
import unittest
from pathlib import Path
from livestock.engine import Engine

FIELDS={'animal_type':'cow','symptoms':['weak'],'urgent_warning_signs':[],'symptoms_since':'yesterday','animals_affected':1,'previous_treatment':'none','farmer_name':'Demo Farmer','village':'Neemgaon','district':'Demo North'}

class FakeMuse:
    def __init__(self): self.responses=[]
    def extract(self,instruction,payload):
        if not self.responses: raise AssertionError('Unexpected model request')
        result=self.responses.pop(0)
        if 'message' in payload: result.setdefault('evidence',{k:payload['message'] for k in result.get('updates',result.get('report',{}))})
        return result

class EngineTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.m=FakeMuse()
        self.e=Engine(Path(self.tmp.name)/'cases.db',model=self.m,seed=False)
        self.e.register('farmer','farmer'); self.e.register('vet','vet','VET-01')
        self.seq=0
    def tearDown(self): self.tmp.cleanup()
    def send(self,role,text,response,**kw):
        self.seq+=1; self.m.responses.append(response)
        return self.e.message(role,text,str(self.seq),**kw)
    def submit(self):
        r=self.send('farmer','My one cow is weak since yesterday. No warning signs; she can stand and breathe. No previous treatment. My name is Demo Farmer, village Neemgaon, district Demo North.',{'updates':FIELDS}); cid=r['case_id']
        self.m.responses.extend([{'confirmed':True},{'protocol_id':'DEMO-WEAKNESS','vet_id':'VET-01','reason':'Coverage and availability','category':'weakness'}])
        self.seq+=1; self.e.message('farmer','Yes',str(self.seq))
        return cid
    def report(self,cid):
        self.e.assign(cid,'VET-01','Operator')
        self.send('vet','I accept',{'accepted':True})
        self.send('vet','Visited; weak. No treatment. No follow-up.',{'report':{'visit_status':'visited','observations':'weak','treatment_reported':'none','follow_up_required':False}},media=[{'media_type':'photo','storage_uri':'photo.jpg'},{'media_type':'location','latitude':12.1,'longitude':77.1}])
        self.send('vet','Correct',{'confirmed':True})
    def test_complete_workflow_evidence_and_atomic_notifications(self):
        cid=self.submit(); self.assertEqual(self.e.case_detail(cid)['status'],'AWAITING_ASSIGNMENT')
        self.assertEqual(self.e.pending_outbox(),[])
        self.report(cid)
        out=self.e.pending_outbox(); self.assertEqual([x['actor_id'] for x in out],['vet','farmer'])
        self.e.mark_delivered(out[0]['id']); self.assertEqual(len(self.e.pending_outbox()),1)
        self.send('farmer','Visited and helped, improved, satisfied, no help needed',{'updates':{'visit_confirmed':True,'farmer_reported_service':'checked animal','farmer_reported_condition':'improved','service_satisfaction':'satisfied','further_help_required':False}})
        self.e.close(cid,'ERC')
        c=self.e.case_detail(cid)
        self.assertEqual(c['status'],'CLOSED'); self.assertEqual(self.e.metrics()['open_cases'],0)
        self.assertTrue(c['summary']['evidence_ids'])
        self.assertEqual(sum(e['media_type']=='photo' for e in c['evidence']),1)
        transitions=[x['data']['to'] for x in c['events'] if x['type']=='status']
        self.assertEqual(transitions,['NEW','AWAITING_ASSIGNMENT','ASSIGNED','ACCEPTED','VISITED','AWAITING_FEEDBACK','CLOSED'])
    def test_metrics_count_missing_outcomes_and_known_district_aliases(self):
        cid=self.submit()
        with self.e.db() as db:
            c=self.e.case_detail(cid); c['district']='Demo North district'; self.e._save(db,c)
        metrics=self.e.metrics()
        self.assertEqual(metrics['outcomes'],[{'label':'unknown','value':1}])
        self.assertEqual(metrics['by_district'],[{'label':'Demo North','value':1}])

    def test_dispute_and_further_help_prevent_closure(self):
        cid=self.submit(); self.report(cid)
        self.send('farmer','Nobody visited, still sick',{'updates':{'visit_confirmed':False,'farmer_reported_condition':'ill','further_help_required':True}})
        self.assertEqual(self.e.case_detail(cid)['status'],'NEEDS_REVIEW')
        with self.assertRaises(ValueError): self.e.close(cid,'ERC')
    def test_unknown_correction_no_repetition_and_deduplication(self):
        self.m.responses=[{'updates':{'animal_type':'cow','symptoms':['weak'],'urgent_warning_signs':[]},'unknown_fields':['symptoms_since']}]
        r=self.e.message('farmer','Cow weak; no warning signs; onset unknown','telegram:15',metadata={'update_id':9,'original':{'text':'original'}})
        c=self.e.case_detail(r['case_id']); self.assertEqual(c['fields']['symptoms_since'],'unknown')
        self.assertEqual(c['last_question'],'How many animals are affected?')
        self.assertEqual(self.e.message('farmer','Cow weak; no warning signs; onset unknown','telegram:15'),r)
        self.assertEqual(len(self.e.case_detail(r['case_id'])['evidence']),1)
        self.send('farmer','Actually a goat; two days',{'updates':{'animal_type':'goat','symptoms_since':'two days'}})
        c=self.e.case_detail(r['case_id']); self.assertEqual(c['animal_type'],'goat'); self.assertNotIn('symptoms_since',c['unknown_fields'])
    def test_permissions_and_workflow_guards(self):
        cid=self.submit()
        with self.assertRaises(ValueError): self.e.close(cid,'ERC')
        with self.assertRaises(ValueError): self.e.assign(cid,'VET-02','ERC')
        self.e.assign(cid,'VET-01','ERC')
        with self.assertRaises(ValueError): self.e.assign(cid,'VET-01','ERC')
        self.e.register('other','farmer')
        with self.assertRaises(ValueError): self.e.message('other','yes','99',case_id=cid)
    def test_photo_is_not_visit_and_report_needs_confirmation(self):
        cid=self.submit(); self.e.assign(cid,'VET-01','ERC')
        self.send('vet','accept',{'accepted':True})
        r=self.send('vet','photo',{'report':{}},media=[{'media_type':'photo','storage_uri':'a.jpg'}])
        self.assertEqual(r['status'],'ACCEPTED'); self.assertIn('visited',r['reply'])
        self.assertEqual(len(self.e.pending_outbox()),1)
    def test_model_hallucinations_and_negative_answer_are_grounded(self):
        self.m.responses=[{'updates':{'animal_type':'cow','symptoms':['not eating','weak'],'animals_affected':1,'previous_treatment':'none'},'unknown_fields':['farmer_name','village','district','urgent_warning_signs'],'evidence':{'animal_type':'cow','symptoms':['not eating','weak'],'animals_affected':'cow','previous_treatment':'weak'}}]
        r=self.e.message('farmer','My cow is not eating and looks weak','a')
        self.assertIn('unable to stand',r['reply'])
        fields=self.e.case_detail(r['case_id'])['fields']
        self.assertNotIn('previous_treatment',fields); self.assertNotIn('village',fields)
        self.m.responses=[{'updates':{'animals_affected':'Only one cow is affected.'},'evidence':{'animals_affected':'Only one cow is affected.'}}]
        r=self.e.message('farmer','No. Only one cow is affected.','b')
        fields=self.e.case_detail(r['case_id'])['fields']
        self.assertEqual(fields['urgent_warning_signs'],[]); self.assertEqual(fields['animals_affected'],1)
        self.assertIn('When',r['reply'])

    def test_single_account_roleplay_keeps_binding_but_not_independence(self):
        self.e.unregister('vet')
        with self.e.db() as db: db.execute('DELETE FROM vet_bindings')
        self.e.register('farmer','vet','VET-01'); self.e.register('farmer','farmer')
        self.assertEqual(self.e.roster()[0]['telegram_user_id'],'farmer')
        cid=self.submit(); self.e.assign(cid,'VET-01','ERC')
        self.e.register('farmer','vet','VET-01')
        self.send('farmer','accept',{'accepted':True})
        self.send('farmer','visited',{'report':{'visit_status':'visited','observations':'weak','treatment_reported':'none','follow_up_required':False}})
        self.send('farmer','correct',{'confirmed':True})
        self.e.register('farmer','farmer')
        self.send('farmer','visited; improved; no help',{'updates':{'visit_confirmed':True,'farmer_reported_service':'checked','farmer_reported_condition':'improved','service_satisfaction':'satisfied','further_help_required':False}})
        c=self.e.close(cid,'ERC')
        self.assertIn('single-account roleplay',c['summary']['text'])
        self.assertEqual(self.e.metrics()['farmer_confirmed_visits'],1)
        self.assertEqual(self.e.metrics()['independently_confirmed_visits'],0)
        self.m.responses=[{'query_id':'confirmed_visits'}]
        self.assertEqual(self.e.query('independent confirmation')['rows'][0]['confirmed_visits'],0)

    def test_unclear_voice_preserves_evidence_without_model_facts(self):
        result=self.e.message('farmer','[Voice note unclear; please ask me to repeat.]','voice-1',metadata={'transcript':'uncertain source','avg_logprob':-1.5})
        case=self.e.case_detail(result['case_id'])
        self.assertEqual(case['fields'],{})
        self.assertIn('repeat',result['reply'])
        self.assertEqual(case['evidence'][0]['extracted_data']['metadata']['transcript'],'uncertain source')

    def test_feedback_yes_cannot_fabricate_recovery_or_no_help(self):
        cid=self.submit(); self.report(cid)
        self.send('farmer','Yes',{'updates':{'visit_confirmed':True,'farmer_reported_condition':'recovered','farmer_reported_service':'treated','service_satisfaction':'satisfied','further_help_required':False}})
        c=self.e.case_detail(cid)
        self.assertTrue(c['feedback']['visit_confirmed'])
        self.assertNotIn('farmer_reported_condition',c['feedback'])
        self.assertNotIn('further_help_required',c['feedback'])
        with self.assertRaises(ValueError): self.e.close(cid,'ERC')

    def test_report_requires_grounding_and_boolean_followup(self):
        cid=self.submit(); self.e.assign(cid,'VET-01','ERC')
        self.send('vet','accept',{'accepted':True})
        self.send('vet','Here is a photo',{'report':{'visit_status':'visited','observations':'healthy','follow_up_required':'false'},'evidence':{'visit_status':'I visited','observations':'healthy','follow_up_required':'Here is a photo'}},media=[{'media_type':'photo','storage_uri':'x'}])
        c=self.e.case_detail(cid)
        self.assertEqual(c['pending_report'],{})
        self.assertEqual(c['status'],'ACCEPTED')

    def test_animal_colour_is_not_animal_type(self):
        self.send('farmer','Hello',{'updates':{}})
        r=self.send('farmer','It is black',{'updates':{'animal_type':'cow'},'evidence':{'animal_type':'It is black'}})
        self.assertNotIn('animal_type',self.e.case_detail(r['case_id'])['fields'])
        self.assertEqual(r['reply'],'What animal is unwell?')

    def test_seed_and_real_sql(self):
        self.e.seed(); self.e.seed(); self.assertEqual(len(self.e.list_cases()),150)
        self.m.responses=[{'query_id':'unresolved'},{'query_id':'confirmed_visits'},{'query_id':'urgent_resolution'}]
        r=self.e.query('Where are unresolved cases?'); self.assertEqual(sum(row['unresolved'] for row in r['rows']),self.e.metrics()['open_cases'])
        r=self.e.query('What percentage confirmed?'); self.assertEqual(r['rows'][0]['reported_visits'],self.e.metrics()['reported_visits'])
        self.assertEqual(len(self.e.query('Urgent slower?')['rows']),2)

if __name__=='__main__': unittest.main()
