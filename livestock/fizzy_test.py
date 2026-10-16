import tempfile
import unittest
from pathlib import Path
from livestock.fizzy_sync import Mirror, payload

class FizzyTests(unittest.TestCase):
    def test_payload_escapes_and_omits_private_evidence(self):
        case={'case_id':'CASE-T','status':'AWAITING_ASSIGNMENT','fields':{'animal_type':'<script>','symptoms':['कमजोरी']},'telegram_user_id':'PRIVATE_ID','transcript':['PRIVATE_VOICE'],'contact':'PRIVATE_PHONE'}
        result=str(payload(case,'http://localhost:8766'))
        self.assertIn('&lt;script&gt;',result)
        self.assertNotIn('PRIVATE',result)

    def test_closed_card_recovery_no_duplicates_and_skip_unsubmitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            class Fake(Mirror):
                def request(self,path,method='GET',body=None,source=False):
                    self.calls.append((method,path))
                    if source:
                        return [{'case_id':'CASE-T','status':'CLOSED','provenance':'live_demo'},
                                {'case_id':'CASE-INTAKE','status':'INTAKE','provenance':'live_demo'},
                                {'case_id':'CASE-SEED','status':'CLOSED','provenance':'synthetic_history'}],{}
                    if method=='GET':
                        return ([{'title':'CASE-T · Farmer','number':7}] if 'indexed_by=closed' in path else []),{}
                    return None,{}
            m=Fake({'account_slug':'/1','board_id':'b','source_public_url':'http://localhost:8766'},Path(tmp));m.calls=[]
            self.assertEqual(m.sync(),1)
            self.assertTrue(any(method=='PUT' and '/cards/7.json' in path for method,path in m.calls))
            self.assertFalse(any(method=='POST' and '/boards/' in path for method,path in m.calls))
            self.assertEqual(m.sync(),0)

if __name__=='__main__':unittest.main()
