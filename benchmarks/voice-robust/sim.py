"""Simulated farmer calls through the real Call engine (VAD, smart-turn, ASR, LLM, TTS), in real time.

  python sim.py [scenario ...] [--condition farm_phone] [--nlu muse] [--out DIR]

The farmer's speech is synthesized (Kokoro, Indian male voice, optionally lowered/"gruff"),
run through a degrade.py line condition, and streamed in 20 ms frames with line noise between
utterances. The farmer answers whatever the agent is currently asking, waits for the agent
to finish (or deliberately talks over it), pauses mid-sentence, goes quiet, asks for advice...
Each call is scored against the facts the farmer gave. Synthetic speech -> ASR is easier than
real people; these runs test the dialogue and timing, the ASR bake-off tests recognition.
"""
import argparse, asyncio, json, os, re, sys, time
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).parent))
import degrade, call as call_mod, speech as speech_mod
from rapidfuzz import fuzz

ART = Path(os.getenv('VR_ART', '/mnt/seagate/silo/voice-robust'))
FRAME = 320  # 20 ms at 16 kHz
OUTDIR = None

BASE = {  # what this farmer will say when asked about each slot
    'animal_type': 'It is a cow.', 'symptoms': 'She is not eating anything and she is very weak.',
    'can_stand': 'Yes, she is standing.', 'breathing_ok': 'Yes, breathing is normal.',
    'animals_affected': 'Only one cow.', 'symptoms_since': 'From yesterday.', 'previous_treatment': 'No, no treatment given.',
    'caller_name': 'My name is Basavaraju.', 'village': 'Hosahalli village.', 'district': 'Ramanagara district.',
    'contact_details': 'Nine eight four five six, seven two three one zero.', 'summary': 'Yes, that is correct.',
    'correction': 'Yes, correct.', None: 'My cow is sick.'}
EXPECT = {'animal_type': 'cow', 'animals_affected': 1, 'symptoms_since': 'yesterday', 'previous_treatment': 'none',
          'caller_name': 'Basavaraju', 'village': 'Hosahalli', 'district': 'Ramanagara', 'contact_details': '9845672310',
          'urgent': False, 'confirmed': True}

def sc(name, opening, answers=None, expect=None, **kw):
    return {'name': name, 'opening': opening, 'answers': {**BASE, **(answers or {})}, 'expect': {**EXPECT, **(expect or {})}, **kw}

SCENARIOS = [
    sc('straightforward', 'Hello madam, my cow is not eating since yesterday.'),
    sc('minimal', 'My cow is sick.'),
    sc('all_at_once', 'My name is Basavaraju from Hosahalli village, Ramanagara district. My cow is not eating from yesterday and she is very weak, only one cow.'),
    sc('correction', 'My cow is not eating.', {'symptoms_since': 'It started three days back.',
       'animals_affected': 'Only one. Sorry, not three days, it started two days back.'}, {'symptoms_since': 'two days'}),
    sc('interrupts', 'My cow is not eating since yesterday.', interrupt_on={'animals_affected', 'village'}),
    sc('urgent', 'My buffalo is lying down, she is not able to get up.', {'animal_type': 'Buffalo.', 'can_stand': 'No, she cannot get up at all.',
       'breathing_ok': 'No, she is breathing very fast.', 'animals_affected': 'Only one buffalo.'},
       {'animal_type': 'buffalo', 'urgent': True}),
    sc('unknown_onset', 'My cow is not eating.', {'symptoms_since': 'I do not know, my son was looking after her.'}, {'symptoms_since': None}),
    sc('hold_and_ask', 'My cow is not eating since yesterday.', {'contact_details': ['One minute madam, let me check the number.', None,
       'Nine eight four five six, seven two three one zero.'], 'previous_treatment': ['What medicine should I give her?', 'No, nothing given.']},
       {}),
    sc('hesitant_quiet', 'Hello? ... my cow ... is not eating ... since yesterday.', pause_on_dots=True, silent_first={'village'}),
    sc('noisy_gruff', 'My cow is not eating since yesterday.', gruff=True, condition='farm_phone', noise_bursts=True),
]

class FakeOut:
    """Plays nothing; tracks what would be heard and when, honouring stop()."""
    def __init__(self): self.played = []
    async def play(self, pcm, meta): self.played.append((time.monotonic(), meta))
    async def stop(self): self.played.append((time.monotonic(), {'stop': True}))

class Farmer:
    def __init__(self, sp, condition, gruff, key):
        from kokoro import KPipeline
        self.tts = KPipeline(lang_code='a', repo_id='hexgrad/Kokoro-82M', device='cuda')
        self.sp, self.cond, self.gruff, self.key, self.n = sp, condition, gruff, key, 0
        self.rng = np.random.default_rng(abs(hash(key)) % 2 ** 32)
    def audio(self, text, pause_on_dots=False):
        import librosa
        parts = text.split('...') if pause_on_dots else [text]
        out = []
        for p in parts:
            if not p.strip(): continue
            with self.sp.lock:
                a = np.concatenate([r.audio.numpy() for r in self.tts(p.strip(), voice='hm_omega', speed=.9)])
            a = librosa.resample(a.astype(np.float32), orig_sr=24000, target_sr=16000)
            out += [a, np.zeros(int(16000 * 1.1), np.float32)]  # a tired mid-sentence pause
        x = np.concatenate(out[:-1] if len(out) > 1 else out)
        if self.gruff: x = degrade.gruff(x)
        self.n += 1
        return degrade.CONDITIONS[self.cond](np.concatenate([np.zeros(1600, np.float32), x, np.zeros(1600, np.float32)]), f'{self.key}{self.n}').astype(np.float32)
    def floor(self, seconds):
        x = self.rng.standard_normal(int(16000 * seconds)).astype(np.float32) * (3e-3 if self.cond == 'farm_phone' else 3e-4)
        return x

def frames(x):
    pcm = (np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes()
    for i in range(0, len(pcm) - FRAME * 2 + 1, FRAME * 2): yield pcm[i:i + FRAME * 2]

async def stream(c, x, interrupt_check=None):
    t = time.monotonic()
    for i, f in enumerate(frames(x)):
        await c.feed(f)
        await asyncio.sleep(max(0, t + (i + 1) * .02 - time.monotonic()))

CORRECTABLE = {'animal_type': 'animal_type', 'caller_name': 'caller_name', 'village': 'village', 'district': 'district',
               'contact_details': 'contact_details', 'animals_affected': 'animals_affected'}

async def run(sc_, sp, nlu_backend, condition):
    cond = sc_.get('condition', condition)
    out = FakeOut(); c = call_mod.Call(sp, out, nlu_backend, audio_dir=str(OUTDIR / sc_['name']) if OUTDIR else None)
    farmer = Farmer(sp, cond, sc_.get('gruff', False), sc_['name'])
    await asyncio.to_thread(farmer.audio, 'Hello.')  # warm the farmer's voice before the call starts
    await c.start()
    asked, said_queue, t_start = {}, {}, time.monotonic()
    first, silent_done, corrected = True, set(), set()
    interrupted = set()
    async def idle(seconds): await stream(c, farmer.floor(seconds))
    def agent_contents(): return sum(1 for t in c.transcript if t['role'] == 'agent' and t['kind'] == 'content')
    seen = agent_contents()
    while not c.ended and time.monotonic() - t_start < 300:
        # Wait for the agent's real reply to what the farmer last said (acks and fillers don't count).
        waited = 0
        while agent_contents() == seen and not c.ended and waited < 12: await idle(.1); waited += .1
        seen = agent_contents()
        slot = None if first else c.intake.asking
        if not first and c.intake.phase == 'summary' and slot != 'correction': slot = 'summary'
        if sc_.get('interrupt_on') and slot in sc_['interrupt_on'] and slot not in interrupted:
            interrupted.add(slot); await idle(.9)  # talk over the agent about 1 s into its question
        else:
            while c.playing() and not c.ended: await idle(.1)
            if c.ended: break
            await idle(.6)
        if c.ended: break
        asked[slot] = asked.get(slot, 0) + 1
        if slot in sc_.get('silent_first', ()) and slot not in silent_done:
            silent_done.add(slot); await idle(call_mod.REPROMPT_S + 1); seen = agent_contents(); continue
        # A real farmer corrects a wrong read-back.
        fix = None
        for k, ek in CORRECTABLE.items():
            v = c.intake.slots[k].value; want = sc_['expect'].get(ek)
            if v is None or want is None or k in corrected: continue
            if (str(v) != str(want)) if k in ('contact_details', 'animals_affected') else (fuzz.ratio(str(v).lower(), str(want).lower()) < 85):
                fix = k; corrected.add(k); break
        if first: ans = sc_['opening']
        elif fix: ans = 'No no, ' + sc_['answers'][fix]
        else:
            ans = sc_['answers'].get(slot, 'Yes.')
            if isinstance(ans, list):
                i = said_queue.get(slot, 0); said_queue[slot] = i + 1; ans = ans[min(i, len(ans) - 1)]
        first = False
        if ans is None: await idle(9); seen = agent_contents(); continue
        if sc_.get('noise_bursts') and farmer.rng.random() < .4:
            burst = degrade.noise(1e-3 * farmer.rng.standard_normal(8000).astype(np.float32), 'b' + str(slot), -5)
            await stream(c, np.clip(burst, -1, 1) * .3); await idle(.5)
        x = await asyncio.to_thread(farmer.audio, ans, sc_.get('pause_on_dots'))
        await stream(c, x)
        if asked[slot] > 4: break  # the agent is looping: stop, the call fails its checks
    await asyncio.sleep(.5)
    return c, cond

def score(sc_, c):
    rec = c.intake.record(); e = sc_['expect']; checks = {}
    for k in ('animal_type', 'animals_affected', 'previous_treatment', 'contact_details'):
        checks[k] = rec[k] == e[k] or (e[k] is None and rec[k] in (None, 'none') and k in rec['unknown_fields'] + rec['unclear_fields'] + ['previous_treatment'])
    for k in ('caller_name', 'village', 'district'):
        checks[k] = bool(rec[k]) and fuzz.ratio(str(rec[k]).lower(), e[k].lower()) >= 85
    since = rec['symptoms_since']
    checks['symptoms_since'] = (since is None and 'symptoms_since' in rec['unknown_fields']) if e['symptoms_since'] is None else bool(since) and e['symptoms_since'] in str(since).lower()
    checks['symptoms'] = bool(rec['symptoms'])
    checks['urgent'] = bool(rec['urgent_warning_signs']) == e['urgent']
    checks['confirmed'] = rec['confirmed_by_caller'] == e['confirmed']
    asked = {}
    for m in c.metrics:
        if m.get('now_asking'): asked[m['now_asking']] = asked.get(m['now_asking'], 0) + 1
    checks['no_loops'] = all(v <= 3 for v in asked.values())
    resp = [m['response_s'] for m in c.metrics if 'response_s' in m]
    first = [m['first_audio_after_s'] for m in c.metrics if 'first_audio_after_s' in m]
    checks['never_stuck'] = all(r < 6 for r in resp) and not any(m.get('cancelled') is None and 'heard' in m and 'reply' not in m and not m.get('dropped') for m in c.metrics[:-1])
    return {'scenario': sc_['name'], 'passed': sum(checks.values()), 'total': len(checks), 'checks': checks,
            'turns': len([t for t in c.transcript if t['role'] == 'farmer']), 'response_s': resp, 'first_audio_s': first,
            'fillers': sum(bool(m.get('filler')) for m in c.metrics), 'barge_ins': sum(e['event'] == 'barge_in' for e in c.events),
            'reprompts': sum(e['event'] == 'reprompt' for e in c.events), 'record': {k: v for k, v in rec.items() if k != 'slots'}}

async def main():
    ap = argparse.ArgumentParser(); ap.add_argument('names', nargs='*'); ap.add_argument('--condition', default='gsm')
    ap.add_argument('--nlu', default='muse'); ap.add_argument('--out', default=str(ART / 'runs/sim' / time.strftime('%Y%m%d-%H%M')))
    a = ap.parse_args(); out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    global OUTDIR; OUTDIR = out
    sp = speech_mod.Speech()
    results = []
    for s in SCENARIOS:
        if a.names and s['name'] not in a.names: continue
        c, cond = await run(s, sp, a.nlu, a.condition)
        r = score(s, c); r['condition'] = cond; r['nlu'] = a.nlu; results.append(r)
        (out / f"{s['name']}.json").write_text(json.dumps({**r, **c.record()}, indent=1, default=str))
        print(f"{s['name']:16s} {cond:11s} {r['passed']}/{r['total']}  turns={r['turns']:2d} fillers={r['fillers']} barge={r['barge_ins']} "
              f"reprompt={r['reprompts']} resp_p50={np.median(r['response_s']) if r['response_s'] else float('nan'):.2f}s "
              f"first_audio_p50={np.median(r['first_audio_s']) if r['first_audio_s'] else float('nan'):.2f}s  "
              f"fail={[k for k, v in r['checks'].items() if not v]}", flush=True)
    allr = [x for r in results for x in r['response_s']]; alla = [x for r in results for x in r['first_audio_s']]
    summ = {'nlu': a.nlu, 'condition': a.condition, 'calls': len(results), 'checks_passed': sum(r['passed'] for r in results),
            'checks_total': sum(r['total'] for r in results),
            'response_s_p50_p90_p95': [round(float(np.percentile(allr, q)), 2) for q in (50, 90, 95)] if allr else None,
            'first_audio_s_p50_p90_p95': [round(float(np.percentile(alla, q)), 2) for q in (50, 90, 95)] if alla else None}
    (out / 'summary.json').write_text(json.dumps(summ, indent=1)); print(json.dumps(summ))

if __name__ == '__main__':
    asyncio.run(main())
