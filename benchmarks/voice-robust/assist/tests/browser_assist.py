"""Automated role-play of the operator: Chromium -> WebRTC -> assist server, operator clips injected as the mic.

  python assist/tests/browser_assist.py [--url http://127.0.0.1:8776] [--scenario buffalo-down] [--out DIR]

Plays assist/operator_script.json line by line (waiting for the farmer to finish answering each time),
ends the call, waits for the review, and checks the record against the scripted farmer's real answers.
"""
import argparse, json, time, urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent.parent

def get(url): return json.loads(urllib.request.urlopen(url, timeout=5).read())

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--url', default='http://127.0.0.1:8776'); ap.add_argument('--scenario', default='buffalo-down')
    ap.add_argument('--out', default='/mnt/seagate/silo/voice-robust/runs/assist/' + time.strftime('%Y%m%d-%H%M%S'))
    a = ap.parse_args(); out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    lines = json.loads((HERE / 'operator_script.json').read_text())['lines']
    with sync_playwright() as p:
        b = p.chromium.launch(args=['--use-fake-ui-for-media-stream', '--autoplay-policy=no-user-gesture-required'])
        page = b.new_page(viewport={'width': 1400, 'height': 950}); errors = []
        page.on('console', lambda m: m.type == 'error' and errors.append(m.text))
        page.goto(a.url); page.wait_for_function('document.querySelectorAll("#scenario option").length > 0')
        page.select_option('#scenario', a.scenario); page.check('#fixture')
        page.click('#call'); page.wait_for_function('window.currentSessionId', timeout=20000)
        api = f'{a.url}/api/sessions/' + page.evaluate('window.currentSessionId')
        t0 = time.time()
        while get(api)['status'] != 'on call' and time.time() - t0 < 20: time.sleep(.3)
        time.sleep(1)
        for i, (key, text) in enumerate(lines):
            n_farmer = sum(t['role'] == 'farmer' for t in get(api).get('transcript', []))
            page.evaluate(f'speakFixture("{key}.wav")')
            # wait for the farmer's answer to finish (or ~6 s if no answer is expected)
            t = time.time()
            while time.time() - t < 25:
                s = get(api)
                if s['status'] == 'ended' or (sum(x['role'] == 'farmer' for x in s.get('transcript', [])) > n_farmer and not s.get('farmer_speaking')): break
                time.sleep(.25)
            time.sleep(.5); page.screenshot(path=str(out / f'turn{i + 1:02d}-{key}.png'))
            if s['status'] == 'ended': break
        t = time.time()
        while get(api)['status'] != 'ended' and time.time() - t < 10: time.sleep(.5)
        if get(api)['status'] != 'ended': page.click('#end')
        page.wait_for_selector('#review:not([hidden])', timeout=60000); time.sleep(.5)
        page.screenshot(path=str(out / 'review.png'), full_page=True)
        s = get(api); b.close()
    r = s['review']
    result = {'session': s['id'], 'truth_check': r['truth_check'], 'passed': sum(r['truth_check'].values()), 'total': len(r['truth_check']),
              'qa': {q['check']: q['ok'] for q in r['qa']}, 'review_differences': r['differences'], 'review_ms': r['offline'].get('ms'),
              'farmer_starts_after_s': [m.get('farmer_starts_after_s') for m in s['metrics'] if m.get('farmer_starts_after_s') is not None],
              'asked': [(m.get('asked'), m.get('farmer_clip')) for m in s['metrics'] if m.get('heard')],
              'states': {k: f['state'] for k, f in s['record']['fields'].items()}, 'console_errors': errors}
    (out / 'session.json').write_text(json.dumps(s, indent=1)); (out / 'result.json').write_text(json.dumps(result, indent=1))
    print(json.dumps(result, indent=1))

if __name__ == '__main__':
    main()
