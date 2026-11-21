import unittest

from bridges.signal.bridge import question


class NoteToSelfTest(unittest.TestCase):
    def setUp(self):
        self.sent = {"timestamp": 42, "destinationUuid": "self", "message": "/idli yes"}
        self.event = {"envelope": {"sourceUuid": "self", "syncMessage": {"sentMessage": self.sent}}}
        self.account = "+10000000000"

    def test_followup(self):
        self.assertEqual(question(self.event, self.account), (42, "yes"))

    def test_other_destination(self):
        self.sent["destinationUuid"] = "contact"
        self.assertIsNone(question(self.event, self.account))

    def test_group(self):
        self.sent["groupInfo"] = {"groupId": "group"}
        self.assertIsNone(question(self.event, self.account))

    def test_reply_loop(self):
        self.sent["message"] = "Idli\n/idli yes"
        self.assertIsNone(question(self.event, self.account))

    def test_incoming_dm(self):
        event = {"envelope": {"dataMessage": self.sent}}
        self.assertIsNone(question(event, self.account))
