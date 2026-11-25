"""Populate a new private benchmark sandbox and expose two ordinary Idli views."""
import hashlib
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'core'))
from lib import idlicli, recstore

ZONE = ZoneInfo('Asia/Kolkata')


def local(ts):
    return datetime.fromtimestamp(ts, ZONE).replace(tzinfo=None)


def urls(body):
    return [u.rstrip('.,;!') for u in re.findall(r'https?://[^\s<>"\u200b]+', body, re.I)]


def main():
    src, dest = map(Path, sys.argv[1:])
    os.umask(0o077)
    dest.mkdir()
    snap = json.loads(src.read_text())
    con = recstore.connect(dest)
    try:
        con.execute('BEGIN')
        con.execute('CREATE TABLE snapshot_messages (ref VARCHAR PRIMARY KEY, group_name VARCHAR, sent_at TIMESTAMP, '
                    'sender VARCHAR, body VARCHAR, links VARCHAR)')
        con.execute('CREATE TABLE snapshot_groups (group_name VARCHAR, active_at TIMESTAMP, text_count INTEGER, '
                    'fetched INTEGER, hit_cap BOOLEAN, failed BOOLEAN)')
        for g in snap['groups']:
            records = [(hashlib.sha256(r['id'].encode()).hexdigest()[:20], g['name'], local(r['t']), r['sender'],
                        r['body'], ' '.join(urls(r['body']))) for r in g['rows']]
            if records:
                con.executemany('INSERT INTO snapshot_messages VALUES (?,?,?,?,?,?)', records)
            con.execute('INSERT INTO snapshot_groups VALUES (?,?,?,?,?,?)',
                        [g['name'], local(g['active_at']), len(records), g['fetched'], g['fetched'] >= snap['cap'], g['failed']])
        for resource, tbl, description in [
                ('wa_messages', 'snapshot_messages', 'WhatsApp group text messages and links in cached history; timestamps in IST'),
                ('wa_groups', 'snapshot_groups', 'WhatsApp groups active in the last calendar month and captured text counts')]:
            idlicli.run_argv(con, ['view', resource, '--on', 'message', '--sql', 'SELECT * FROM '+tbl, '--about', description])
        con.execute('COMMIT')
    finally:
        con.close()


if __name__ == '__main__':
    main()
