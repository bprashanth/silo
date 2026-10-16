"""Optional one-way local Fizzy mirror. No Telegram or case mutation privileges."""
import argparse
import fcntl
import hashlib
import html
import json
import os
from pathlib import Path
import time
import urllib.parse
import urllib.request

STATE = Path.home() / '.local/share/silo-livestock-fizzy'
LABELS = {'farmer_name':'किसान', 'animal_type':'पशु', 'animals_affected':'प्रभावित पशु',
          'village':'गाँव', 'district':'जिला', 'symptoms':'लक्षण', 'symptoms_since':'कब से',
          'urgent_warning_signs':'गंभीर लक्षण', 'previous_treatment':'पहले का उपचार'}
STATUSES = {'NEW':'नया मामला','AWAITING_ASSIGNMENT':'डॉक्टर की नियुक्ति बाकी',
            'ASSIGNED':'डॉक्टर नियुक्त','ACCEPTED':'डॉक्टर ने स्वीकार किया','VISITED':'भेंट हुई',
            'AWAITING_FEEDBACK':'किसान की प्रतिक्रिया बाकी','NEEDS_REVIEW':'समीक्षा ज़रूरी','CLOSED':'बंद'}

def payload(case, dashboard):
    fields = {**case, **case.get('fields', {})}
    def value(v):
        if isinstance(v, list): v = ', '.join(map(str, v)) or 'कोई नहीं'
        return html.escape(str(v))
    title = f"{case['case_id']} · {fields.get('farmer_name') or 'किसान'} · {fields.get('animal_type') or 'पशु'}"
    rows = ''.join(f'<p><strong>{label}:</strong> {value(fields[key])}</p>' for key, label in LABELS.items() if key in fields)
    status = STATUSES.get(case['status'], case['status'])
    rows = f'<p><strong>स्थिति:</strong> {value(status)}</p>' + rows
    if case.get('priority') == 'urgent': rows = '<p><strong>तत्काल समीक्षा</strong></p>' + rows
    rows += f'<p><a href="{html.escape(dashboard, quote=True)}">केस डेस्क खोलें</a></p>'
    return {'title': title, 'description': rows}

class Mirror:
    def __init__(self, config, state=STATE):
        self.config, self.state = config, state
        self.cache_file = state / 'sync.json'
        self.cache = json.loads(self.cache_file.read_text()) if self.cache_file.exists() else {}

    def request(self, path, method='GET', body=None, source=False):
        base = self.config['source_url'] if source else self.config['base_url']
        url = base + path
        headers = {'Accept': 'application/json'}
        if not source: headers['Authorization'] = 'Bearer ' + self.config['token']
        if body is not None: headers['Content-Type'] = 'application/json'
        req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=20) as response:
            data = response.read()
            return (json.loads(data) if data else None), dict(response.headers)

    def save(self):
        temp = self.cache_file.with_suffix('.tmp')
        temp.write_text(json.dumps(self.cache))
        temp.chmod(0o600)
        temp.replace(self.cache_file)

    def sync(self):
        cases, _ = self.request('/api/cases', source=True)
        slug = self.config['account_slug']
        board = self.config['board_id']
        # Recover creations interrupted before cache persistence without duplicating cards.
        existing = {}
        for index in ('all', 'closed', 'not_now'):
            page = 1
            while True:
                cards, headers = self.request(f'{slug}/cards.json?board_ids[]={board}&indexed_by={index}&page={page}')
                for card in cards:
                    existing[card['title'].split(' · ', 1)[0]] = card['number']
                if 'rel="next"' not in headers.get('link', headers.get('Link', '')): break
                page += 1
        count = 0
        for case in cases:
            if case.get('provenance') != 'live_demo' or case['status'] == 'INTAKE': continue
            body = payload(case, self.config['source_public_url'] + '?case=' + urllib.parse.quote(case['case_id']))
            digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
            key = case['case_id']
            prior = self.cache.get(key, {})
            number = existing.get(key)
            if prior.get('hash') == digest and prior.get('number') == number: continue
            if number is None:
                _, headers = self.request(f'{slug}/boards/{board}/cards.json', 'POST', {'card': body})
                number = int(urllib.parse.urlparse(headers.get('location', headers.get('Location'))).path.rsplit('/', 1)[-1].replace('.json', ''))
            else:
                self.request(f'{slug}/cards/{number}.json', 'PUT', {'card': body})
            # Persist only after all content updates. Close/reopen reflects authoritative desk status.
            self.request(f'{slug}/cards/{number}/closure.json', 'POST' if case['status'] == 'CLOSED' else 'DELETE')
            columns = self.config.get('columns', {})
            bucket = 'new' if case['status'] in ('NEW', 'AWAITING_ASSIGNMENT') else 'review' if case['status'] == 'NEEDS_REVIEW' else 'active'
            if case['status'] != 'CLOSED' and bucket in columns:
                self.request(f'{slug}/cards/{number}/triage.json', 'POST', {'column_id': columns[bucket]})
            self.cache[key] = {'number': number, 'hash': digest}
            self.save()
            count += 1
        return count

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (STATE / 'sync.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        mirror = Mirror(json.loads((STATE / 'config.json').read_text()))
        while True:
            try:
                count = mirror.sync()
                if count: print(f'Updated {count} Fizzy cards', flush=True)
            except Exception as exc:
                # Do not log headers, response bodies, credentials or private case content.
                print(f'Fizzy sync failed: {type(exc).__name__}', flush=True)
                if args.once: raise SystemExit(1)
            if args.once: break
            time.sleep(5)

if __name__ == '__main__': main()
