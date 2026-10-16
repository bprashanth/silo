import tempfile
import unittest
from pathlib import Path
from examples.livelihoods.livestock.full_call_center.engine import Engine
from examples.livelihoods.livestock.full_call_center.model import Muse
from examples.livelihoods.livestock.full_call_center.hindi import canonicalize_input, localize_reply, HINDI_QUESTIONS
from examples.livelihoods.livestock.full_call_center.config import QUESTIONS
from examples.livelihoods.livestock.full_call_center.tests.test_engine import FakeMuse


class HindiTest(unittest.TestCase):
    def test_model_receives_readable_hindi_not_unicode_escapes(self):
        class CaptureMuse(Muse):
            def _post(self, path, body):
                if path=='/apply-template':
                    self.messages=body['messages']
                    return {'prompt':'prompt'}
                return {'content':'{"translation":"cow"}'}
        model=CaptureMuse()
        model.extract('Translate',{'text':'गाय'})
        self.assertIn('गाय',model.messages[1]['content'])
        self.assertNotIn('\\u',model.messages[1]['content'])

    def test_fixed_polarity_and_unknown(self):
        for original, expected in [('नहीं।','No.'),('Nahi','No.'),('जी हाँ','Yes.'),('मुझे नहीं पता','I do not know.')]:
            self.assertEqual(canonicalize_input(original,FakeMuse()),expected)
        self.assertEqual(localize_reply(QUESTIONS['animal_type']), 'कौन सा पशु बीमार है?')

    def test_original_evidence_and_question_state(self):
        with tempfile.TemporaryDirectory() as folder:
            model=FakeMuse(); engine=Engine(Path(folder)/'cases.db',model=model,seed=False)
            model.responses=[{'translation':'My cow is weak.'},{'updates':{'animal_type':'cow','symptoms':['weak']}}]
            reply=engine.message('farmer','मेरी गाय कमज़ोर है।','1',role='farmer',language='hi')
            self.assertEqual(reply['reply'],HINDI_QUESTIONS[QUESTIONS['urgent_warning_signs']])
            model.responses=[{'updates':{}}]
            reply=engine.message('farmer','नहीं।','2',language='hi')
            case=engine.case_detail(reply['case_id'])
            self.assertEqual(case['fields']['urgent_warning_signs'],[])
            self.assertEqual(case['last_question'],QUESTIONS['symptoms_since'])
            self.assertEqual(case['transcript'][0]['text'],'मेरी गाय कमज़ोर है।')
            self.assertEqual(case['transcript'][0]['canonical_text'],'My cow is weak.')
            evidence=case['evidence'][0]['extracted_data']
            self.assertEqual(evidence['text'],'मेरी गाय कमज़ोर है।')
            self.assertEqual(evidence['metadata']['canonical_text'],'My cow is weak.')
            self.assertEqual(engine.message('farmer','नहीं।','2',language='hi'),reply)
            model.responses=[{'updates':{}}]
            reply=engine.message('farmer','मुझे नहीं पता','3',language='hi')
            self.assertEqual(engine.case_detail(reply['case_id'])['fields']['symptoms_since'],'unknown')
            model.responses=[{'translation':'Correction: she is a buffalo, not a cow. Symptoms began two days ago.'}, {'updates':{'animal_type':'buffalo','symptoms_since':'two days ago'}}]
            reply=engine.message('farmer','सुधार: गाय नहीं भैंस है। दो दिन से बीमार है।','4',language='hi')
            case=engine.case_detail(reply['case_id'])
            self.assertEqual(case['fields']['animal_type'],'buffalo')
            self.assertNotIn('symptoms_since',case['unknown_fields'])


if __name__=='__main__': unittest.main()
