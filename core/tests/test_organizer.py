import datetime as dt
import unittest

import duckdb

from lib import organizer, recstore


class OrganizerTest(unittest.TestCase):
    def test_busy_intervals_thread_state_and_source_links(self):
        con = duckdb.connect()
        self.addCleanup(con.close)
        con.execute(recstore.DDL)
        con.execute("""INSERT INTO events(id,account,start,"end",title,all_day,my_response) VALUES
            ('a','me','2026-11-23','2026-11-24','Visit',TRUE,'accepted'),
            ('b','me','2026-11-24 09:45','2026-11-24 10:20','Call',FALSE,'accepted'),
            ('c','me','2026-11-24 10:30','2026-11-24 11:30','Skipped',FALSE,'declined')""")
        con.execute("""INSERT INTO mail(id,thread_id,account,date,direction,subject,body_text,is_bulk,is_calendar_notice) VALUES
            ('1','a','me','2026-11-20','in','School visit','Which times work for you?',false,false),
            ('2','b','me','2026-11-20','in','Old request','Which times work?',false,false),
            ('3','b','me','2026-11-21','out','Re: Old request','Monday.',false,false),
            ('4','c','me','2026-11-21','in','Grant proposal','Please review.',false,false)""")
        now = dt.datetime(2026,11,22,9)
        reply = organizer.agenda(con, 'me', now, lambda resource,key: f'{resource}/{key}')
        for expected in ('School visit','mail/a','Grant proposal','mail/c','Tue 24 Nov at 10:30','Wed 25 Nov at 10:00'):
            self.assertIn(expected, reply)
        for excluded in ('Old request','Skipped','Mon 23 Nov at 10:00'):
            self.assertNotIn(excluded, reply)
        stale = organizer.agenda(con, 'me', now, lambda *args: '', failed=['Calendar'])
        self.assertNotIn('Open on your calendar', stale)
