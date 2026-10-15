"""Interpret one farmer turn: what they meant, given the question they were asked.

interpret(heard, asking, known, backend) -> {'intent', 'facts', 'urgent', 'farmer_question', 'ms', 'source'}

The LLM gets the question just spoken, the facts so far and the raw recognized text, and
returns grammar-constrained JSON. It does NOT rewrite the transcript (that proved harmful:
"not getting up" became "not eating"). Names and places are then snapped to the
service-area gazetteer only when the match is strong, and the agent reads them back.
If the LLM is slower than the deadline, a rule-based reading is used so a turn never hangs.
"""
import asyncio, json, os, re, time
from pathlib import Path
import aiohttp
import jellyfish
from rapidfuzz import fuzz

HERE = Path(__file__).parent
TERMS = json.loads((HERE / 'domain_terms.json').read_text())
MUSE = os.getenv('MUSE_URL', 'http://127.0.0.1:8181')
DEADLINE = float(os.getenv('NLU_DEADLINE_S', '3.5'))
SLOTS = ['animal_type', 'animals_affected', 'symptoms', 'symptoms_since', 'previous_treatment', 'caller_name',
         'village', 'district', 'contact_details', 'can_stand', 'breathing_ok']
INTENTS = ['answer', 'correction', 'question', 'repeat', 'wait', 'yes', 'no', 'unclear', 'goodbye']

S = lambda: {'type': ['string', 'null']}
SCHEMA = {'type': 'object', 'properties': {
    'intent': {'enum': INTENTS},
    'animal_type': S(), 'animals_affected': {'type': ['integer', 'null']},
    'symptoms': {'type': 'array', 'items': {'type': 'string'}}, 'symptoms_since': S(), 'previous_treatment': S(),
    'caller_name': S(), 'village': S(), 'district': S(), 'contact_details': S(),
    'can_stand': {'type': ['boolean', 'null']}, 'breathing_ok': {'type': ['boolean', 'null']},
    'dont_know': {'type': 'array', 'items': {'enum': SLOTS}},
    'urgent': {'type': 'array', 'items': {'enum': ['unable to stand', 'breathing difficulty', 'unconscious', 'heavy bleeding',
                                                   'convulsions', 'bloated and distressed', 'difficult delivery', 'sudden deaths']}},
    'farmer_question': S()},
    'required': ['intent']}  # everything else optional: only what was said is emitted (fewer tokens)

SYSTEM = """You interpret what a farmer said on a phone call to a livestock helpline in Karnataka, India.
The text comes from speech recognition on a bad line, so expect mis-heard words; read it in the context of the question asked.
Output compact JSON on one line. Include a field ONLY if the farmer stated it in THIS reply; omit every other field. Never guess or repeat old facts.
- intent: answer (gives information), correction (fixes something said earlier, e.g. "no, not three, two days"), question (asks you something, e.g. "what medicine should I give?"), repeat (asks you to say it again / did not understand), wait (asks you to hold on), yes / no (a bare yes or no), unclear (noise, cut off, or meaningless), goodbye.
- animal_type: singular common word: cow, buffalo, goat, sheep, calf, bullock, pig, hen, ...
- symptoms: short phrases in the farmer's words, e.g. "not eating", "loose motions", "blood in milk". Keep negations exact.
- symptoms_since: as said, e.g. "yesterday", "two days".
- previous_treatment: "none" if they say no treatment was given, otherwise what was given.
- contact_details: digits only.
- can_stand / breathing_ok: true/false if the farmer says so (a yes/no to "Is it able to stand?" counts).
- dont_know: fields the farmer says they do not know.
- urgent: warning signs the farmer says ARE present now.
- farmer_question: the farmer's question to you, if any."""

def _code(s):
    return ''.join(jellyfish.metaphone(w) for w in re.findall(r'[a-z]+', s.lower()))

def _flat(s): return re.sub(r'[^a-z]', '', s.lower())

POOLS = {'village': TERMS['villages'] + TERMS['taluks'], 'district': TERMS['districts'], 'caller_name': TERMS['names']}
CODED = {k: [(t, _code(t), _flat(t)) for t in v] for k, v in POOLS.items()}

def snap(kind, value):
    """Snap a heard name/place to the gazetteer by sound and spelling; the agent reads it back to confirm."""
    if kind not in CODED or not value: return value
    v = re.sub(r'\b(village|district|taluk|gram|nagar)\b', '', str(value), flags=re.I).strip(' .,')
    if not v: return value
    words = v.split()
    spans = {' '.join(words[i:j]) for i in range(len(words)) for j in range(i + 1, min(len(words), i + 3) + 1)} | {v}
    best = (0, None)
    for s in spans:  # "Tumakuru Distractor" -> try "Tumakuru" alone too
        code, flat = _code(s), _flat(s)
        if len(flat) < 4: continue
        best = max([best] + [(.5 * fuzz.ratio(code, c) + .5 * fuzz.ratio(flat, f), t) for t, c, f in CODED[kind]])
    return best[1] if best[0] >= 75 else v.title()

def rules(heard, asking):
    """Fallback reading: enough to move the call forward when the LLM is slow or down."""
    t = heard.lower().strip(); out = {'intent': 'answer', 'facts': {}, 'urgent': [], 'farmer_question': None}
    if not re.search(r'[a-z0-9]', t): out['intent'] = 'unclear'; return out
    if re.search(r'\b(wait|hold on|one minute|one second)\b', t): out['intent'] = 'wait'
    elif re.search(r"(say (that )?again|repeat|did not understand|didn't understand|pardon)", t): out['intent'] = 'repeat'
    elif re.match(r'^(yes|yeah|haan|ha|correct|right|ok)\b', t): out['intent'] = 'yes'
    elif re.match(r'^(no|nope|illa|nahi)\b', t): out['intent'] = 'no'
    if re.search(r"(don't|do not|dont) know|not sure", t) and asking in SLOTS: out['facts'][asking] = 'UNKNOWN'
    a = re.search(r'\b(cow|buffalo|goat|sheep|calf|bullock|bull|ox|pig|hen|chicken|horse)s?\b', t)
    if a: out['facts']['animal_type'] = a.group(1)
    if asking in ('can_stand', 'breathing_ok') and out['intent'] in ('yes', 'no'): out['facts'][asking] = out['intent'] == 'yes'
    d = re.sub(r'\D', '', t)
    if asking == 'contact_details' and len(d) >= 6: out['facts']['contact_details'] = d
    n = re.search(r'\b(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\b', t)
    if asking == 'animals_affected' and n:
        w = n.group(1); out['facts']['animals_affected'] = int(w) if w.isdigit() else 'one two three four five six seven eight nine ten'.split().index(w) + 1
    if asking in ('caller_name', 'village', 'district') and out['intent'] == 'answer':
        v = re.sub(r"^(hello|madam|sir|ok|okay|yes|so)[ ,.]+", '', t)
        lead = sorted(["my name is", "name is", "i am", "this is", "it is", "it's", "i am calling from", "calling from", "i am from",
                       "from", "the village is", "village is", "village name is", "the village name is", "district is", "in"], key=len, reverse=True)
        v = re.sub(r"^(" + "|".join(map(re.escape, lead)) + r")\s+", '', v)
        v = re.sub(r"\s+(village|district|taluk|gram)$", '', v.strip(' .,')).strip(' .,')
        if len(re.sub(r'[^a-z]', '', v)) >= 3 and v not in ('hmm', 'umm', 'yes', 'okay', 'what', 'hello'):
            out['facts'][asking] = snap(asking, v.title())
    if asking == 'previous_treatment' and out['intent'] == 'no': out['facts']['previous_treatment'] = 'none'
    return out

def _from_llm(d, heard=''):
    facts = {}
    for k in SLOTS:
        v = d.get(k)
        if v in (None, '', []): continue
        if k == 'contact_details':
            v = re.sub(r'\D', '', str(v))
            if len(v) < 6: continue
        if k in ('caller_name', 'village', 'district'): v = snap(k, str(v).strip().title())
        if k == 'animal_type': v = str(v).lower().strip()
        if k == 'symptoms_since': v = re.sub(r'^(since|from)\s+', '', str(v).strip(' .'), flags=re.I)
        facts[k] = v
    # Only believe "doesn't know" when the farmer actually said so (the LLM over-uses it).
    if re.search(r"(don'?t|do not|dont|didn'?t|not) (know|sure|remember)|no idea|pata nahi|gottilla", heard, re.I):
        for k in d.get('dont_know') or []: facts.setdefault(k, 'UNKNOWN')
    return {'intent': d.get('intent', 'answer'), 'facts': facts, 'urgent': d.get('urgent') or [], 'farmer_question': d.get('farmer_question')}

def _prompt(heard, asking, known, last_said):
    return (f'Agent just said: "{last_said}"\n(The agent was asking about: {asking or "the problem"})\n'
            f'Farmer replied (speech recognition): "{heard}"')

async def _muse(session, heard, asking, known, last_said):
    msgs = [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': _prompt(heard, asking, known, last_said)}]
    async with session.post(MUSE + '/apply-template', json={'messages': msgs}) as r:
        p = (await r.json())['prompt']
    async with session.post(MUSE + '/completion', json={'prompt': p + ' to=user<|message|>', 'n_predict': 220, 'temperature': 0,
                                                        'json_schema': SCHEMA, 'cache_prompt': True}) as r:
        return json.loads((await r.json())['content'])

async def _openrouter(session, heard, asking, known, last_said, model):
    key = json.load(open(Path.home() / '.config/idlisseus/openrouter.json'))['api_key']
    body = {'model': model, 'temperature': 0, 'max_tokens': 400,
            'response_format': {'type': 'json_schema', 'json_schema': {'name': 'turn', 'strict': True, 'schema': SCHEMA}},
            'reasoning': {'enabled': False},
            'messages': [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': _prompt(heard, asking, known, last_said)}]}
    async with session.post('https://openrouter.ai/api/v1/chat/completions', json=body, headers={'Authorization': 'Bearer ' + key}) as r:
        d = await r.json()
    c = d['choices'][0]['message']['content']
    return json.loads(c[c.index('{'):c.rindex('}') + 1])

async def _openrouter_audio(session, pcm16, heard, asking, last_said, model):
    """Direct speech: the model hears the farmer's audio itself (our transcript is only a hint)."""
    import base64, io, wave
    key = json.load(open(Path.home() / '.config/idlisseus/openrouter.json'))['api_key']
    b = io.BytesIO()
    with wave.open(b, 'wb') as w: w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(pcm16)
    text = (_prompt(heard, asking, {}, last_said).replace('Farmer replied (speech recognition)', 'A local speech recognizer heard (may be wrong)')
            + '\nThe farmer\'s actual audio is attached; trust the audio over the recognizer. Return the JSON.')
    body = {'model': model, 'temperature': 0, 'max_tokens': 400, 'reasoning': {'enabled': False},
            'response_format': {'type': 'json_schema', 'json_schema': {'name': 'turn', 'strict': True, 'schema': SCHEMA}},
            'messages': [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': [{'type': 'text', 'text': text},
                {'type': 'input_audio', 'input_audio': {'data': base64.b64encode(b.getvalue()).decode(), 'format': 'wav'}}]}]}
    async with session.post('https://openrouter.ai/api/v1/chat/completions', json=body, headers={'Authorization': 'Bearer ' + key}) as r:
        d = await r.json()
    c = d['choices'][0]['message']['content']
    return json.loads(c[c.index('{'):c.rindex('}') + 1])

async def interpret(heard, asking, known, last_said, backend='muse', session=None, pcm16=None, prev_asking=None):
    t = time.perf_counter(); own = session is None
    session = session or aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15))
    try:
        if backend == 'muse': call = _muse(session, heard, asking, known, last_said)
        elif backend.startswith('audio:'): call = _openrouter_audio(session, pcm16, heard, asking, last_said, backend.split(':', 1)[1])
        else: call = _openrouter(session, heard, asking, known, last_said, backend.split(':', 1)[1])
        d = await asyncio.wait_for(call, DEADLINE)
        out = _from_llm(d, heard); out['source'] = backend
        # Deterministic: a bare yes/no answers a yes/no question.
        if asking in ('can_stand', 'breathing_ok') and out['intent'] in ('yes', 'no') and asking not in out['facts']:
            out['facts'][asking] = out['intent'] == 'yes'
        # Safety net for the slot just asked: if the LLM left it empty, take the rule reading.
        if out['intent'] in ('answer', 'correction') and asking in SLOTS and asking not in out['facts']:
            r = rules(heard, asking)['facts']
            if asking in r: out['facts'][asking] = r[asking]; out['source'] += '+rules'
        # "No no, Hosahalli": a correction of the value we just read back, from the question before.
        if out['intent'] in ('correction', 'no') and not out['facts'] and prev_asking in ('caller_name', 'village', 'district') \
                and re.match(r'^\s*(no|nahi|illa|not)\b', heard, re.I):
            r = rules(re.sub(r'^\s*((no|nahi|illa|not)[ ,.]+)+', '', heard, flags=re.I), prev_asking)['facts']
            if prev_asking in r: out['facts'][prev_asking] = r[prev_asking]; out['intent'] = 'correction'; out['source'] += '+prev'
        if asking == 'previous_treatment' and out['intent'] == 'no' and 'previous_treatment' not in out['facts']:
            out['facts']['previous_treatment'] = 'none'
    except Exception as e:
        out = rules(heard, asking); out['source'] = f'rules ({type(e).__name__})'
    finally:
        if own: await session.close()
    out['ms'] = round((time.perf_counter() - t) * 1000)
    return out

if __name__ == '__main__':
    import sys
    async def main():
        backend = sys.argv[1] if len(sys.argv) > 1 else 'muse'
        cases = [('my buff a low is not taking feed from two days', None, {}),
                 ('no she is lying down only, not getting up', 'can_stand', {'animal_type': 'buffalo'}),
                 ('sorry not three days, two days back', 'previous_treatment', {'symptoms_since': 'three days'}),
                 ('what medicine should I give her?', 'symptoms_since', {}),
                 ('one minute madam, wait', 'contact_details', {}),
                 ('I am calling from Hakahali village', 'village', {}),
                 ('nine eight four five six seven two three one zero', 'contact_details', {}),
                 ('I do not know, my son was looking after', 'symptoms_since', {}),
                 ('yes', 'can_stand', {}), ('hmm', 'village', {})]
        for heard, asking, known in cases:
            r = await interpret(heard, asking, known, 'Question', backend)
            print(r['ms'], r['source'], r['intent'], r['facts'], r['urgent'], r['farmer_question'], '|', heard)
    asyncio.run(main())
