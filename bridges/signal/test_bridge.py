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
