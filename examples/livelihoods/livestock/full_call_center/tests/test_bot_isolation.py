"""The new bot cannot route through or broaden the original bot."""
import unittest
from unittest.mock import Mock,patch
from examples.livelihoods.livestock.full_call_center import bot

class Isolation(unittest.TestCase):
    def message(self, actor=7, kind='private'):
        return {'from':{'id':actor},'chat':{'id':actor,'type':kind},'message_id':21,'text':'My cow is sick.'}
    def test_unlisted_account_is_ignored(self):
        tg=Mock()
        with patch.object(bot,'allowed_ids',return_value={'7'}),patch.object(bot,'api') as api:
            bot.handle(tg,self.message(9))
        api.assert_not_called();tg.send.assert_not_called()
    def test_groups_are_ignored(self):
        tg=Mock()
        with patch.object(bot,'allowed_ids',return_value={'7'}),patch.object(bot,'api') as api:
            bot.handle(tg,self.message(kind='group'))
        api.assert_not_called();tg.send.assert_not_called()
    def test_plain_english_message_starts_farmer_intake(self):
        tg=Mock();tg.username='test_buffalo'
        def response(path,body=None,**kw):
            if path.startswith('actor/'):return None
            if path=='register':return {'role':'farmer'}
            if path=='message':return {'reply':'What animal is unwell?','case_id':'TEST','status':'INTAKE'}
        with patch.object(bot,'allowed_ids',return_value={'7'}),patch.object(bot,'api',side_effect=response) as api,patch.object(bot,'deliver') as deliver:
            bot.handle(tg,self.message())
        self.assertEqual(api.call_args_list[1].args[1]['role'],'farmer')
        sent=api.call_args_list[2].args[1]
        self.assertEqual(sent['language'],'en');self.assertEqual(sent['message_id'],'buffalo:21')
        deliver.assert_called_once_with(tg,'7','What animal is unwell?','TEST')

    def test_unassigned_vet_gets_actionable_reply(self):
        tg=Mock();tg.username='test_buffalo'
        def response(path,body=None,**kw):
            if path.startswith('actor/'):return {'role':'vet','vet_id':'VET-01'}
            if path=='message':raise ValueError('No assignment is awaiting you.')
        with patch.object(bot,'allowed_ids',return_value={'7'}),patch.object(bot,'api',side_effect=response),patch.object(bot,'deliver') as deliver:
            bot.handle(tg,self.message())
        reply=deliver.call_args.args[2]
        self.assertIn('/farmer',reply)
        self.assertIn('no case is assigned',reply)

    def test_submitted_case_includes_dashboard_link(self):
        tg=Mock();tg.username='test_buffalo'
        def response(path,body=None,**kw):
            if path.startswith('actor/'):return {'role':'farmer'}
            if path=='message':return {'reply':'Thank you. Case CASE-DEMO has been submitted.','case_id':'CASE-DEMO','status':'AWAITING_ASSIGNMENT'}
        with patch.object(bot,'allowed_ids',return_value={'7'}),patch.object(bot,'api',side_effect=response),patch.object(bot,'deliver') as deliver:
            bot.handle(tg,self.message())
        self.assertTrue(deliver.call_args.kwargs['link_case'])
        self.assertEqual(deliver.call_args.args[3],'CASE-DEMO')

    def test_dashboard_url_is_written_but_not_spoken(self):
        tg=Mock();tg.send.return_value={'message_id':1};tg.upload_voice.return_value={'message_id':2}
        text='Thank you. Your case has been submitted.'
        with patch.object(bot,'allowed_ids',return_value={'7'}),patch.object(bot,'DASHBOARD_URL','http://demo:9000'),patch.object(bot,'api') as api,patch.object(bot,'store',return_value={'asset_id':'test'}),patch.object(bot.speech,'synth',return_value=b'audio') as synth:
            bot.deliver(tg,'7',text,'CASE-DEMO',link_case=True)
        self.assertEqual(tg.send.call_args.args[1],text+'\n\nView case: http://demo:9000/?case=CASE-DEMO')
        synth.assert_called_once_with(text,'af_heart','en-us')
        self.assertIn('http://demo:9000/?case=CASE-DEMO',api.call_args.args[1]['text'])
