import unittest

from bridges.signal.bridge import question


class NoteToSelfTest(unittest.TestCase):
    def setUp(self):
        self.sent = {"timestamp": 42, "destinationUuid": "self", "message": "/idli yes"}
        self.event = {"envelope": {"sourceUuid": "self", "sourceDevice": 1, "syncMessage": {"sentMessage": self.sent}}}
        self.account = "+10000000000"

    def test_followup(self):
        self.assertEqual(question(self.event, self.account, 2), (42, "yes"))

    def test_other_destination(self):
        self.sent["destinationUuid"] = "contact"
        self.assertIsNone(question(self.event, self.account, 2))

    def test_group(self):
        self.sent["groupInfo"] = {"groupId": "group"}
        self.assertIsNone(question(self.event, self.account, 2))

    def test_reply_loop(self):
        self.event["envelope"]["sourceDevice"] = 2
        self.sent["message"] = "Idli\n/idli yes"
        self.assertIsNone(question(self.event, self.account, 2))

    def test_incoming_dm(self):
        event = {"envelope": {"dataMessage": self.sent}}
        self.assertIsNone(question(event, self.account, 2))

    def test_plain_note(self):
        self.sent["message"] = "Idli\nWhat is on my calendar?"
        self.assertEqual(question(self.event, self.account, 2), (42, self.sent["message"]))

    def test_plain_confirmation(self):
        self.sent["message"] = "yes"
        self.assertEqual(question(self.event, self.account, 2), (42, "yes"))

    def test_attachment_only(self):
        del self.sent["message"]
        self.assertIsNone(question(self.event, self.account, 2))


class DirectQuestionTest(unittest.TestCase):
    def test_only_paired_direct_text(self):
        from bridges.signal.bridge import direct_question
        data = {'timestamp': 42, 'message': 'hi'}
        envelope = {'sourceUuid': 'owner', 'dataMessage': data}
        self.assertEqual(direct_question({'envelope': envelope}, 'owner'), (42, 'hi'))
        self.assertIsNone(direct_question({'envelope': envelope}, 'stranger'))
        data['groupInfo'] = {}
        self.assertIsNone(direct_question({'envelope': envelope}, 'owner'))

    def test_paired_attachment_only(self):
        from bridges.signal.bridge import direct_question
        data = {'timestamp': 42, 'attachments': [{'contentType': 'image/png'}]}
        event = {'envelope': {'sourceUuid': 'owner', 'dataMessage': data}}
        self.assertEqual(direct_question(event, 'owner'), (42, ''))
        self.assertIsNone(direct_question(event, 'other'))


class MultiTesterBridgeTest(unittest.TestCase):
    def test_any_direct_message_filters_groups_and_deletes(self):
        from bridges.signal.bridge import any_direct_message
        ev = {'envelope': {'sourceUuid': 'u1', 'dataMessage': {'timestamp': 100, 'message': 'hello'}}}
        self.assertEqual(any_direct_message(ev), ('u1', 100, 'hello', False))
        ev_grp = {'envelope': {'sourceUuid': 'u1', 'dataMessage': {'timestamp': 100, 'message': 'hi', 'groupInfo': {}}}}
        self.assertIsNone(any_direct_message(ev_grp))
        ev_del = {'envelope': {'sourceUuid': 'u1', 'dataMessage': {'timestamp': 100, 'remoteDelete': {}}}}
        self.assertIsNone(any_direct_message(ev_del))

    def test_onboarding_status_and_attachment_handling(self):
        import tempfile
        from bridges.onboard.store import OnboardStore
        from bridges.signal.bridge import handle_multi_turn

        with tempfile.TemporaryDirectory() as tmp:
            store = OnboardStore(tmp)
            # First DM in open-onboarding mode sends a setup link
            r1 = handle_multi_turn(store, 'aci-1', 'hi', 'https://silo.example')
            self.assertIn('https://silo.example/setup/', r1)
            tok = r1.split('/setup/')[1].split()[0]
            store.update_tester(store.get_tester_by_aci('aci-1')['tester_id'],
                                google_email='a@example.com', selected_drive_folders=['Leads'])
            code = store.issue_confirm_code(tok)
            # Confirm activates
            r2 = handle_multi_turn(store, 'aci-1', f'confirm {code}', 'https://silo.example')
            self.assertIn('now active', r2)
            # Status reports coverage without calling CLI
            r3 = handle_multi_turn(store, 'aci-1', 'status', 'https://silo.example')
            self.assertIn('1 Drive folder(s)', r3)
            # Attachment explains read-only limitation
            r4 = handle_multi_turn(store, 'aci-1', 'upload this', 'https://silo.example', attachment=True)
            self.assertIn('upload or share', r4)
