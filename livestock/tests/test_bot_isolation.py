"""The new bot cannot route through or broaden the original bot."""
import unittest
from unittest.mock import Mock,patch
from livestock import bot

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
