"""Regressions for explicit evidence guards; no model or network required."""
import asyncio
import tempfile
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch
from server import urgency, validate_fields, new_fields, Intake, VADState, InputAudioRawFrame, FrameDirection, routing_hint, completion_reply, complete, completion_fingerprint

def call(*texts):
    return {'fields':new_fields(),'transcript':[{'role':'user','text':x} for x in texts]}

class IntakeEvidenceTests(unittest.TestCase):
    def test_positive_urgent_signs(self):
        self.assertEqual(urgency('She cannot stand and is breathing very fast.'),['unable to stand','breathing difficulty'])
    def test_negation(self):
        for text in ['She can stand.','She is not unconscious.','She is not unresponsive.','She is not breathing fast.','No difficulty breathing.']:
            with self.subTest(text=text): self.assertEqual(urgency(text),[])
    def test_corrected_warning_keeps_review_provenance(self):
        c=call('She cannot stand.','Sorry, she can stand now and is not unconscious.')
        data=validate_fields(c,new_fields())
        self.assertEqual(data['urgent_warning_signs'],[])
        self.assertTrue(data['needs_human_review'])
        self.assertTrue(data['evidence']['urgent_warning_signs']['later_corrections'])
    def test_contact_explicitly_unavailable(self):
        data=validate_fields(call('I do not have a contact number to share.'),new_fields())
        self.assertIn('contact_details',data['unknown_fields'])
        self.assertNotIn('contact_details',data['missing_fields'])
    def test_unknown_duration(self):
        data=validate_fields(call('I do not know when the symptoms started.'),new_fields())
        self.assertIn('symptoms_since',data['unknown_fields'])
        self.assertIsNone(data['symptoms_since'])
    def test_correction_overrides_known_value(self):
        c=call('It started three days ago.','Sorry, two days ago, not three.')
        c['fields']['symptoms_since']='three days ago'
        data=new_fields(); data['symptoms_since']='two days ago'
        self.assertEqual(validate_fields(c,data)['symptoms_since'],'two days ago')
    def test_actual_browser_correction_overrides_null(self):
        c=call('I do not know when the symptoms started.','Sorry, I got that wrong. It started two days ago, not three days ago.')
        data=validate_fields(c,new_fields())
        self.assertEqual(data['symptoms_since'],'two days ago')
        self.assertNotIn('symptoms_since',data['unknown_fields'])
    def test_known_value_survives_empty_extractor(self):
        c=call('My cow is sick.'); c['fields']['animal_type']='cow'
        self.assertEqual(validate_fields(c,new_fields())['animal_type'],'cow')
    def test_later_known_duration_replaces_unknown(self):
        c=call('I do not know when it started.','I remember: it started two days ago.')
        c['fields']['unknown_fields']=['symptoms_since']
        data=new_fields(); data['symptoms_since']='two days ago'
        self.assertEqual(validate_fields(c,data)['symptoms_since'],'two days ago')
        self.assertNotIn('symptoms_since',data['unknown_fields'])
class CompletionGuardTests(unittest.TestCase):
    def test_confirmation_ignores_empty_assistant_draft(self):
        c=call('My name is Ramesh. My cow is weak since yesterday in Demo Village in Demo District. She cannot stand. No previous treatment. No contact number.')
        c.update(backend='pipecat',summary_requested=True)
        c['transcript'] += [{'role':'assistant','text':'Let me check: one cow is weak. Is that summary correct?'},{'role':'user','text':'Yes, that summary is correct.'},{'role':'assistant','text':''}]
        hint=routing_hint(c)
        self.assertIn('has confirmed',hint)
        self.assertIn('demo request is recorded',completion_reply(c,hint))
        self.assertTrue(validate_fields(c,new_fields())['confirmed_by_caller'])
    def test_yes_without_summary_is_not_confirmation(self):
        c=call('Yes.'); c['backend']='pipecat'
        extracted=new_fields(); extracted['confirmed_by_caller']=True
        self.assertFalse(validate_fields(c,extracted)['confirmed_by_caller'])

class QuestionAwareDialogueTests(unittest.TestCase):
    def dialogue(self,*turns):
        c=call(); c['backend']='pipecat'
        for role,text in turns: c['transcript'].append({'role':role,'text':text,'final':True})
        return c
    def test_no_warning_answer_remains_answered_after_unclear_duration(self):
        c=self.dialogue(('user','My goat is vomiting.'),('assistant','Are there any urgent warning signs such as inability to stand or severe breathing trouble?'),('user','No.'),('assistant','When did the symptoms start?'),('user','Could you repeat the question?'))
        hint=routing_hint(c)
        self.assertEqual(c['fields']['urgent_warning_signs'],[])
        self.assertNotIn('urgent_warning_signs',c['fields']['missing_fields'])
        self.assertEqual(c['routing_target'],'symptoms_since')
        self.assertEqual(c['routing_action'],'clarify')
        self.assertIn('No.',str(c['fields']['evidence']['urgent_warning_signs']))
    def test_no_to_can_stand_is_positive_warning(self):
        c=self.dialogue(('assistant','Can the animal stand up?'),('user','No.'))
        data=validate_fields(c,new_fields())
        self.assertEqual(data['urgent_warning_signs'],['unable to stand'])
    def test_no_to_compound_normal_question_is_ambiguous(self):
        c=self.dialogue(('assistant','Is she able to stand, breathing normally, and conscious?'),('user','No.'))
        routing_hint(c)
        self.assertEqual(c['routing_action'],'clarify')
        self.assertEqual(c['routing_target'],'urgent_warning_signs')
        self.assertNotIn('urgent_warning_signs',c['answer_states'])
    def test_yes_to_warning_screen_requires_specific_sign(self):
        c=self.dialogue(('assistant','Are there any urgent warning signs?'),('user','Yes.'))
        routing_hint(c)
        self.assertEqual(c['routing_action'],'clarify')
        c['transcript'] += [{'role':'assistant','text':'Which warning sign have you noticed?'},{'role':'user','text':'She cannot stand.'}]
        self.assertEqual(validate_fields(c,new_fields())['urgent_warning_signs'],['unable to stand'])
    def test_short_unknown_then_later_correction(self):
        c=self.dialogue(('assistant','When did the symptoms start?'),('user',"I don't know."),('assistant','How many animals are affected?'),('user','Actually, it started two days ago.'))
        data=validate_fields(c,new_fields())
        self.assertEqual(data['symptoms_since'],'two days ago')
        self.assertNotIn('symptoms_since',data['unknown_fields'])
    def test_no_other_symptoms_preserves_initial_description(self):
        c=self.dialogue(('assistant','What symptoms have you noticed?'),('user','Vomiting.'),('assistant','Any other symptoms?'),('user','No.'))
        data=validate_fields(c,new_fields())
        self.assertTrue(data['symptoms'])
        self.assertNotIn('symptoms',data['missing_fields'])
    def test_missing_animal_type_is_actually_requested(self):
        c=call('The animal is very weak.')
        c['fields'].update(symptoms=['weakness'],urgent_warning_signs=[],evidence={'urgent_warning_signs':'Caller denied warning signs'})
        routing_hint(c)
        self.assertEqual(c['routing_target'],'animal_type')
    def test_field_mention_is_not_an_answer(self):
        c=self.dialogue(('assistant','Has any treatment been given?'),('user','What do you mean by treatment?'))
        routing_hint(c)
        self.assertEqual(c['routing_action'],'clarify')
        self.assertNotIn('previous_treatment',c['answer_states'])

class CompletionPersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_same_call_id_has_one_completion_file(self):
        request=type('Request',(),{})()
        request.json=AsyncMock(return_value={'call_id':'synthetic-test-call','fields':{'animal_type':'cow'}})
        with tempfile.TemporaryDirectory() as directory, patch('server.STATE',Path(directory)):
            first=await complete(request); second=await complete(request)
            self.assertEqual(first['id'],second['id'])
            self.assertEqual(len(list(Path(directory).glob('completion-*.json'))),1)
    async def test_evidence_paraphrase_does_not_change_fingerprint(self):
        first=new_fields(); first.update(animal_type='cow',evidence={'animal_type':'My cow'})
        second={**first,'evidence':{'animal_type':'A cow reported by caller'}}
        self.assertEqual(completion_fingerprint(first),completion_fingerprint(second))
        second['animal_type']='buffalo'
        self.assertNotEqual(completion_fingerprint(first),completion_fingerprint(second))

class InterruptedASRTests(unittest.IsolatedAsyncioTestCase):
    async def test_greeting_interruption_marks_queued_transcript(self):
        vad=type('FakeVAD',(),{'set_sample_rate':lambda self,n:None})()
        vad.analyze_audio=AsyncMock(return_value=VADState.SPEAKING)
        c=call(); c.update(status='speaking',events=[],metrics=[],transcript=[{'role':'assistant','text':'Hello, tell me what happened.'}])
        with patch('server.SileroVADAnalyzer',return_value=vad): intake=Intake(c)
        intake.push_frame=AsyncMock()
        await intake.process_frame(InputAudioRawFrame(audio=b'\x01\x00'*160,sample_rate=16000,num_channels=1),FrameDirection.DOWNSTREAM)
        self.assertTrue(c['transcript'][0]['interrupted'])
        self.assertEqual(c['transcript'][0]['transcript_basis'],'audio_queued_may_be_partially_played')

    async def test_resumed_speech_retains_uncommitted_audio(self):
        vad=type('FakeVAD',(),{'set_sample_rate':lambda self,n:None})()
        vad.analyze_audio=AsyncMock(return_value=VADState.SPEAKING)
        c=call(); c.update(status='thinking',events=[],metrics=[])
        with patch('server.SileroVADAnalyzer',return_value=vad): intake=Intake(c)
        intake.push_frame=AsyncMock(); intake.respond=AsyncMock()
        intake.job=asyncio.create_task(asyncio.sleep(20))
        prior=b'\x01\x00'*4000; preroll=b'\x02\x00'*160; resumed=b'\x03\x00'*160
        intake.asr_pending_pcm=prior; intake.pre.append(preroll)
        oldjob=intake.job
        await intake.process_frame(InputAudioRawFrame(audio=resumed,sample_rate=16000,num_channels=1),FrameDirection.DOWNSTREAM)
        await asyncio.gather(oldjob,return_exceptions=True)
        self.assertTrue(oldjob.cancelled())
        self.assertEqual(bytes(intake.buf),prior+preroll+resumed)
        vad.analyze_audio.return_value=VADState.QUIET
        silence=b'\x00\x00'*160
        await intake.process_frame(InputAudioRawFrame(audio=silence,sample_rate=16000,num_channels=1),FrameDirection.DOWNSTREAM)
        await intake.job
        self.assertEqual(intake.respond.await_args.args[0],prior+preroll+resumed+silence)
        self.assertEqual(c['events'][0]['event'],'resumed_caller_fragment')

if __name__=='__main__': unittest.main()
