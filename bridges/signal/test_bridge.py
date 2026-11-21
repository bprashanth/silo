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


class MorningDeliveryTest(unittest.TestCase):
    def test_schedule_restarts_pause_and_expiry(self):
        import datetime as dt
        import sqlite3
        from bridges.signal.bridge import enqueue_morning
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        db.execute('CREATE TABLE turns(stamp INTEGER PRIMARY KEY,body TEXT)')
        db.execute('CREATE TABLE organizer(id INTEGER PRIMARY KEY,paused INTEGER)')
        db.execute('INSERT INTO organizer VALUES (1,0)')
        until = dt.date(2026,11,27)
        for date in ('2026-11-22 09:00','2026-11-23 08:29','2026-11-23 08:30','2026-11-23 09:15',
                     '2026-11-24 12:00','2026-11-30 09:00'):
            enqueue_morning(db, dt.datetime.fromisoformat(date), until)
        db.execute('UPDATE organizer SET paused=1')
        enqueue_morning(db, dt.datetime(2026,11,24,9), until)
        self.assertEqual(db.execute('SELECT body FROM turns').fetchall(), [('my plan',)])
