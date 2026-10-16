"""Automated role-play of the operator: Chromium -> WebRTC -> assist server, operator clips injected as the mic.

  python assist/tests/browser_assist.py                                   # recorded farmer, buffalo-down, operator_script.json
  python assist/tests/browser_assist.py --script operator_script_lk.json  # live AI Lakshmamma, that script's case
  [--url http://127.0.0.1:8776] [--out DIR]

Plays the operator script line by line (waiting for the farmer to finish answering each time), ends the call,
waits for the review, and checks the record against the farmer's real answers.
"""
import argparse, json, time, urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent.parent

def get(url): return json.loads(urllib.request.urlopen(url, timeout=5).read())

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--url', default='http://127.0.0.1:8776'); ap.add_argument('--scenario', default='buffalo-down')
    ap.add_argument('--script', default='operator_script.json')
    ap.add_argument('--out', default='/mnt/seagate/silo/voice-robust/runs/assist/' + time.strftime('%Y%m%d-%H%M%S'))
    a = ap.parse_args(); out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    op = json.loads((HERE / a.script).read_text()); lines = op['lines']; clip_dir = '/clips/' + op.get('dir', 'operator') + '/'
    ai = 'case' in op
    with sync_playwright() as p:
        b = p.chromium.launch(args=['--use-fake-ui-for-media-stream', '--autoplay-policy=no-user-gesture-required'])
        page = b.new_page(viewport={'width': 1400, 'height': 950}); errors = []
        page.on('console', lambda m: m.type == 'error' and errors.append(m.text))
        page.goto(a.url + '/?test=1'); page.wait_for_function('document.querySelectorAll("#case option").length > 0')
        if ai: page.select_option('#case', op['case']); page.select_option('#mode', 'ai')
        else: page.select_option('#case', 'rec:' + a.scenario)
        page.check('#fixture')
        page.click('#call'); page.wait_for_function('window.currentSessionId', timeout=20000)
        api = f'{a.url}/api/sessions/' + page.evaluate('window.currentSessionId')
        t0 = time.time()
        while get(api)['status'] != 'on call' and time.time() - t0 < 20: time.sleep(.3)
        time.sleep(1)
        for i, (key, text) in enumerate(lines):
            n_farmer = sum(t['role'] == 'farmer' for t in get(api).get('transcript', []))
            n_turns = len(get(api).get('metrics', []))
            page.evaluate(f'speakFixture("{clip_dir}{key}.wav")')
            # wait for the farmer's answer to finish (or ~6 s if no answer is expected)
            t = time.time()
            while time.time() - t < 25:
                s = get(api)
                if s['status'] == 'ended' or (sum(x['role'] == 'farmer' for x in s.get('transcript', [])) > n_farmer and not s.get('farmer_speaking')): break
                if any(m.get('farmer_clip') == '(quiet)' for m in s.get('metrics', [])[n_turns:]): break  # the live farmer chose to stay quiet
                time.sleep(.25)
            time.sleep(.5); page.screenshot(path=str(out / f'turn{i + 1:02d}-{key}.png'))
            if s['status'] == 'ended': break
        t = time.time()
        while get(api)['status'] != 'ended' and time.time() - t < 10: time.sleep(.5)
        if get(api)['status'] != 'ended': page.click('#end')
        page.wait_for_selector('#review:not([hidden])', timeout=60000); time.sleep(.5)
        page.screenshot(path=str(out / 'review.png'), full_page=True)
        # The operator fixes a field by hand (✎): typed values win and show as "edited".
        page.click('dd[data-k="animals_affected"] button.edit'); page.fill('dd[data-k="animals_affected"] .edit-input', '4')
        page.press('dd[data-k="animals_affected"] .edit-input', 'Enter'); time.sleep(.8)
        edited = get(api)['record']['fields']['animals_affected']
        edit_ok = edited['state'] == 'edited' and edited['value'] == 4 and 'edited' in page.inner_text('dd[data-k="animals_affected"]')
        page.screenshot(path=str(out / 'edited.png'), full_page=True)
        s = get(api); b.close()
    r = s['review']
    result = {'session': s['id'], 'truth_check': r['truth_check'], 'passed': sum(r['truth_check'].values()), 'total': len(r['truth_check']),
              'qa': {q['check']: q['ok'] for q in r['qa']}, 'review_differences': r['differences'], 'review_ms': r['offline'].get('ms'),
              'farmer_starts_after_s': [m.get('farmer_starts_after_s') for m in s['metrics'] if m.get('farmer_starts_after_s') is not None],
              'asked': [(m.get('asked'), m.get('farmer_clip')) for m in s['metrics'] if m.get('heard')],
              'farmer_llm_ms': [m['farmer_llm_ms'] for m in s['metrics'] if m.get('farmer_llm_ms')],
              'conversation': [(t['role'], t.get('said') or t['text'], t['text']) for t in s['transcript']],
              'states': {k: f['state'] for k, f in s['record']['fields'].items()}, 'edit_ok': edit_ok, 'console_errors': errors}
    (out / 'session.json').write_text(json.dumps(s, indent=1)); (out / 'result.json').write_text(json.dumps(result, indent=1))
    print(json.dumps(result, indent=1))

if __name__ == '__main__':
    main()
