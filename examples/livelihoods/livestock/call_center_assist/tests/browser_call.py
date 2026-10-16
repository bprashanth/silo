"""Real browser call: Chromium -> WebRTC -> server, farmer speech injected as the microphone.

  python3 tests/browser_call.py [--url http://127.0.0.1:8775] [--line] [--nlu muse] [--out DIR]

The page's test-audio mode mixes a WAV into the MediaStream sent over WebRTC (no transcript
text is injected). The driver answers whatever the agent is asking, waits for it to finish
speaking, and at the end checks the intake record, saves screenshots, the call JSON, and the
browser-measured speech-end -> first-audio latencies.
"""
import argparse, json, time, urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright

ANSWER = {None: 'opening', 'symptoms': 'opening', 'can_stand': 'stand_yes', 'breathing_ok': 'breath_yes', 'animals_affected': 'one',
          'symptoms_since': 'since', 'previous_treatment': 'treat_no', 'caller_name': 'name', 'village': 'village',
          'district': 'district', 'contact_details': 'phone', 'summary': 'yes', 'correction': 'yes'}
EXPECT = {'animal_type': 'buffalo', 'animals_affected': 1, 'caller_name': 'Basavaraju', 'village': 'Kunigal', 'district': 'Tumakuru',
          'contact_details': '9845672310', 'previous_treatment': 'none', 'confirmed_by_caller': True}

def get(url):
    return json.loads(urllib.request.urlopen(url, timeout=5).read())

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--url', default='http://127.0.0.1:8775'); ap.add_argument('--line', action='store_true')
    ap.add_argument('--nlu', default='muse'); ap.add_argument('--out', default='/mnt/seagate/silo/voice-robust/runs/browser/' + time.strftime('%Y%m%d-%H%M%S'))
    ap.add_argument('--interrupt', action='store_true', help='speak over the agent once, ~1 s into a question')
    a = ap.parse_args(); out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch(args=['--use-fake-ui-for-media-stream', '--autoplay-policy=no-user-gesture-required'])
        page = b.new_page(viewport={'width': 1280, 'height': 900}); errors = []
        page.on('console', lambda m: m.type == 'error' and errors.append(m.text))
        page.goto(a.url); page.wait_for_function('document.querySelectorAll("#nlu option").length > 0')
        page.select_option('#nlu', a.nlu); page.check('#fixture')
        if a.line: page.check('#line')
        page.click('#call'); page.wait_for_function('window.currentCallId', timeout=20000)
        cid = page.evaluate('window.currentCallId'); api = f'{a.url}/api/calls/{cid}'
        said = 0; seen = 0; t0 = time.time(); interrupted = False
        while time.time() - t0 < 300:
            c = get(api)
            if c['status'] == 'ended': break
            contents = [t for t in c.get('transcript', []) if t['role'] == 'agent' and t['kind'] == 'content']
            if len(contents) == seen or (c.get('playing') and not (a.interrupt and not interrupted and c.get('asking') == 'village')):
                time.sleep(.2); continue
            if c.get('playing'): interrupted = True; time.sleep(1.0)  # talk over the agent
            else: time.sleep(.6)
            seen = len(contents)
            slot = 'summary' if c.get('record', {}).get('call_status') == 'in_progress' and c.get('asking') == 'summary' else c.get('asking')
            name = ANSWER.get(slot, 'yes') if said else 'opening'
            if slot == 'confirm_phone':  # check the number read back, like a farmer would
                name = 'yes' if c['record'].get('slots', {}).get('contact_details', {}).get('value') == EXPECT['contact_details'] else 'no'
            try: page.evaluate(f'speakFixture("{name}.wav")'); said += 1
            except Exception: break  # the page ended the call underneath us
            page.screenshot(path=str(out / f'turn{said:02d}.png'))
            if said > 25: break
        time.sleep(1)
        try:
            page.screenshot(path=str(out / 'final.png'))
            if get(api)['status'] != 'ended': page.click('#end'); time.sleep(1)
        except Exception: pass
        c = get(api)
        b.close()
    rec = c['record']
    checks = {k: (str(rec.get(k)).lower() == str(v).lower()) for k, v in EXPECT.items()}
    lat = [e['speech_end_to_audible_ms'] for e in c.get('browser_events', []) if e.get('type') == 'browser_first_audio']
    result = {'call_id': cid, 'turns_spoken': said, 'checks': checks, 'passed': sum(checks.values()), 'total': len(checks),
              'browser_speech_end_to_audible_ms': lat, 'server_first_audio_s': [m.get('first_audio_after_s') for m in c['metrics'] if 'first_audio_after_s' in m],
              'server_reply_s': [m.get('response_s') for m in c['metrics'] if 'response_s' in m], 'console_errors': errors, 'line': a.line, 'nlu': a.nlu}
    (out / 'call.json').write_text(json.dumps(c, indent=1)); (out / 'result.json').write_text(json.dumps(result, indent=1))
    print(json.dumps(result, indent=1))

if __name__ == '__main__':
    main()
