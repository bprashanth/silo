"""Grade the existing Idli command surface against the source snapshot; print only aggregate evidence."""
import json
import re
import sys
from pathlib import Path

from import_snapshot import urls

from lib import idlicli, recstore


def main():
    snap_file, sandbox, answers = map(Path, sys.argv[1:4])
    snap = json.loads(snap_file.read_text())
    groups = snap['groups']
    assert not any(g['failed'] for g in groups)
    assert all(g['id'].endswith('@g.us') for g in groups)
    jam, = [g for g in groups if 'jam buns' in g['name'].casefold()]
    cc, = [g for g in groups if 'cc og' in g['name'].casefold()]
    links = [r for r in jam['rows'] if urls(r['body'])]
    newest = max(links, key=lambda r: r['t'])
    latest_urls = urls(newest['body'])
    con = recstore.connect(sandbox, read_only=True)
    scope = "group_name ILIKE '%jam buns%'"
    with_links = scope + " AND links <> ''"

    def rows(*args):
        return idlicli.run_argv(con, list(args)).rows

    def count(*args):
        res = idlicli.run_argv(con, ['list', *args, '--count', '-o', 'json'])
        return int(json.loads(res.text)[0]['n'])

    checks = {
        'literal nature + walk search': len(rows('list', 'wa_messages', '--search', 'nature walk', '--where', scope))
        == sum(all(w in r['body'].casefold() for w in ('nature','walk')) for r in jam['rows']),
        'Tata + Trust author lookup': sorted(str(r[0]) for r in rows('list','wa_messages','--where',
               "group_name ILIKE '%cc og%'",'--search','Tata Trust','--fields','sender')) ==
        sorted(str(r['sender']) for r in cc['rows'] if all(w in r['body'].casefold() for w in ('tata','trust'))),
        'groups': count('wa_groups') == len(groups),
        'link-bearing message count': count('wa_messages','--where',with_links) == len(links),
        'latest link and sender': rows('list','wa_messages','--where',with_links,'--order','sent_at desc',
                                       '--limit','1','--fields','links,sender') == [(' '.join(latest_urls),newest['sender'])],
        'unseen phrase': rows('list','wa_messages','--search','"violet lighthouse 73"','--where',scope) == []
    }
    for label, ok in checks.items():
        print('PASS' if ok else 'FAIL', label)
    for line in answers.read_text().splitlines():
        result = json.loads(line)
        reply = result['reply'].casefold()
        cmd = ' '.join(result.get('commands',[])).casefold()
        task = result['task']
        if task in {'W03','W04','W05','W07'}:
            expected = {'W03':latest_urls,'W04':[str(len(groups))],'W05':[str(len(links))],
                        'W07':[newest['sender']]}.get(task)
            ok = any(v and re.search(r'(?<!\w)'+re.escape(v.casefold())+r'(?!\w)',reply) for v in expected)
            print(task, 'reference value present' if ok else 'reference value missing')
        else:
            print(task, 'WhatsApp source' if 'wa_messages' in cmd else 'other source',
                  'coverage qualified' if re.search('captur|cach|sync|available history|indexed', reply)
                  else 'coverage unqualified')
    if len(sys.argv) == 5:
        repeat = json.loads(Path(sys.argv[4]).read_text())
        def records(groups):
            return {(g['id'], r['id']): r for g in groups for r in g['rows']}
        same = records(groups) == records(repeat['groups'])
        covered = all(not g['failed'] and g['includesNewest'] and len(g['rows']) == g['cachedText']
                      for g in repeat['groups'])
        print('Same messages and content on repeat:', same, 'all cached text counts and newest IDs matched:', covered)
        checks['repeat'] = same and covered
    if not all(checks.values()):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
