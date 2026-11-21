"""A short, source-backed agenda for the paired pilot account."""
import datetime as dt
import re

from lib import recstore as rs


def refresh(con, account):
    failed = []
    for name, sync in [('Calendar', rs.sync_events), ('Gmail', rs.sync_mail), ('Drive', rs.sync_files)]:
        con.execute('BEGIN')
        try:
            sync(con, account)
            con.execute('COMMIT')
        except Exception:
            con.execute('ROLLBACK')
            failed.append(name)
    return failed


def open_slots(events, now):
    """Offer one half-hour on each of two weekdays, checking full event intervals."""
    slots = []
    for offset in range(1, 8):
        day = now.date() + dt.timedelta(days=offset)
        if day.weekday() >= 5:
            continue
        for half_hour in range(20, 34):
            start = dt.datetime.combine(day, dt.time(half_hour // 2, 30 * (half_hour % 2)))
            end = start + dt.timedelta(minutes=30)
            if all(end <= ev_start or start >= ev_end for ev_start, ev_end, *_ in events):
                slots.append(start.strftime('%a %d %b at %H:%M'))
                break
        if len(slots) == 2:
            break
    return slots


REQUEST = re.compile(r'\b(?:which|what) times? (?:work|suit)|\b(?:send|suggest|share|offer) (?:me |us )?(?:a few |some |available )?(?:times|slots)\b', re.I)
PROPOSAL = re.compile(r'\b(?:proposal|concept note)s?\b', re.I)


def agenda(con, account, now, link, failed=(), draft=False):
    end = dt.datetime.combine(now.date() + dt.timedelta(days=8), dt.time())
    events = con.execute("""SELECT start, "end", title, all_day, location FROM events
        WHERE account=? AND lower(coalesce(my_response,'')) != 'declined'
        AND "end">? AND start<? ORDER BY start, title""", [account, now, end]).fetchall()
    threads = con.execute("""WITH latest AS (
        SELECT *, row_number() OVER (PARTITION BY thread_id ORDER BY date DESC, id DESC) AS rn
        FROM mail WHERE account=? AND date<=?)
        SELECT thread_id, subject, body_text, snippet FROM latest WHERE rn=1 AND direction='in'
        AND NOT is_bulk AND NOT is_calendar_notice AND date>=? ORDER BY date DESC, id DESC""",
        [account, now, now - dt.timedelta(days=14)]).fetchall()
    request = None
    proposals = []
    for tid, subject, body, snippet in threads:
        # Only the new part of the email can supply an outstanding request.
        content = re.split(r'(?im)^\s*(?:On .+wrote:|>+|-----Original Message-----)', body or snippet or '')[0]
        if not request and REQUEST.search(content):
            sentences = re.split(r'(?<=[.!?])\s+|\n+', content)
            sentence = next((x for x in sentences if REQUEST.search(x)), content)
            request = (subject, sentence.strip()[:180], link('mail', tid))
        if PROPOSAL.search(subject or ''):
            proposals.append(f'• {subject}\n{link("mail", tid)}')
    for fid, name in con.execute("""SELECT id,name FROM files WHERE account=? AND kind!='folder'
            AND modified BETWEEN ? AND ? ORDER BY modified DESC,id""",
            [account, now - dt.timedelta(days=14), now]).fetchall():
        if PROPOSAL.search(name):
            proposals.append(f'• {name}\n{link("files", fid)}')

    slots = open_slots(events, now) if request and 'Calendar' not in failed else []
    if draft:
        if 'Gmail' in failed:
            return 'I couldn’t refresh Gmail to verify the latest request. Try again shortly.'
        if not request:
            return 'I found no recent scheduling request to draft a reply for.'
        if not slots:
            return 'I couldn’t verify a free half hour. Check your calendar before offering times.'
        return (f'Draft for “{request[0]}”\n\nThanks for getting in touch. Would '
                + ' or '.join(slots) + f' IST work for a 30-minute call?\n\n{request[2]}')
    lines = [f'Looking ahead · {now:%a %d %b} · IST', '', 'On your calendar']
    for start, finish, title, all_day, location in events[:5]:
        when = start.strftime('%a %d %b') + (' · all day' if all_day else start.strftime(' · %H:%M'))
        lines.append(f'• {when}  {title}' + (f' · {location}' if location else ''))
    if len(events) > 5:
        lines.append(f'Plus {len(events) - 5} later in the week.')
    if not events:
        lines.append('No upcoming meetings in the synced week.')
    if request:
        subject, quote, url = request
        lines.extend(['', 'A conversation to pick up', f'{subject} — “{quote}”', url])
        if slots:
            lines.extend(['', 'Open on your calendar for 30 min: ' + ' or '.join(slots) + ' IST.',
                          'Reply “draft times” for a message you can send.'])
    lines.extend(['', 'Recent proposals', *(proposals[:3] or ['No recent proposal or concept note in the synced titles.'])])
    if failed:
        lines.append('\nRefresh unavailable for ' + ', '.join(failed) + '. Showing saved records.')
    return '\n'.join(lines)
