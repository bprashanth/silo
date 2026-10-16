"""Operator assist: a person takes the farmer's call, the agent listens to both sides and helps.

Two channels go into one case record:
  farmer   - what the line delivered (bad 2G audio, so ASR is shaky): values are "heard, not confirmed"
  operator - what the operator said on a clean headset. Operators are trained to repeat key facts back
             ("Buffalo, not getting up since morning. Which village?"), and a repeated fact counts as
             confirmed. The operator is the authority; the agent never overrides them.

The agent's job, live: keep the checklist, say what to ask next, flag urgent signs, offer gazetteer
spellings for names and places, count phone digits, and point out where the line heard something
different from what the operator repeated. After the call: a review (checklist, QA, a full-transcript
re-read by the LLM, and the differences).

Pure apart from `interpret_operator` (an LLM call with a deadline and a rule fallback).
"""
import asyncio, json, re, time
import aiohttp
from rapidfuzz import fuzz
import intake as intake_mod, nlu

REQUIRED = intake_mod.REQUIRED
QUESTIONS = intake_mod.QUESTIONS
LABELS = {'animal_type': 'Animal', 'symptoms': 'Problem', 'can_stand': 'Can stand', 'breathing_ok': 'Breathing normal',
          'animals_affected': 'Animals sick', 'symptoms_since': 'Since', 'previous_treatment': 'Treatment given',
          'caller_name': 'Farmer name', 'village': 'Village', 'district': 'District', 'contact_details': 'Phone'}
ASKS = REQUIRED + ['greeting', 'summary', 'other']

# ---------- what the operator is asking: rules first (instant), so the farmer can answer without waiting on an LLM ----------
ASK_PATTERNS = [
    ('contact_details', r'\b(phone|mobile|number to call|contact number|call you (on|back))\b'),
    ('animals_affected', r'\bhow many\b'),
    ('symptoms_since', r'\b(since when|how long|how many days|when did (it|this|she|he) start|from when)\b'),
    ('previous_treatment', r'\b(medicine|treatment|injection|given anything|any (medicine|treatment)|doctor seen|vet seen)\b'),
    ('can_stand', r'\b(stand|get(ting)? up|lying down)\b.*\?|\b(able|can (she|he|it)) .*stand'),
    ('breathing_ok', r'\bbreath'),
    ('caller_name', r'\b(your name|who is (calling|speaking)|name please)\b'),
    ('village', r'\b(village|which place|where are you|calling from|which (ooru|area))\b'),
    ('district', r'\b(district|taluk)\b'),
    ('animal_type', r'\b(which|what) (animal|kind|type)\b|\bcow or buffalo\b|\bwhich animal\b'),
    ('symptoms', r'\b(what (is the )?problem|what happened|what is wrong|what are you seeing|symptom|tell me (what|about))\b'),
    ('summary', r'\b(read (it )?back|let me (repeat|confirm|read)|to confirm|summar)\b'),
    ('greeting', r'\b(namaste|namaskara|hello|helpline|good (morning|afternoon|evening))\b'),
]

def last_sentence(text):
    parts = [x for x in re.split(r'(?<=[.?!])\s+', text.strip()) if x.strip()]
    return parts[-1] if parts else ''

def is_question(sentence):
    """A yes/no check or a question, even when ASR dropped the "?" ("And your name, please.")."""
    t = sentence.lower().strip()
    return t.endswith('?') or bool(re.match(r'^(and )?(which|what|how|when|where|who|is|are|can|could|did|do|does|have|has|any|since when|tell me)\b', t)) \
        or bool(re.search(r'\b(right|correct|okay|ok)\s*\??$', t) and re.search(r',\s*(is that )?(right|correct)|is that (right|correct)', t)) \
        or bool(re.search(r'\b(please)\W*$', t))

def asked_slot(text):
    """The question is usually the operator's last sentence ("Kunigal, right? And which district?"), so read from the end."""
    t = text.lower()
    if re.search(dict(ASK_PATTERNS)['summary'], t): return 'summary'
    for sentence in reversed([x for x in re.split(r'(?<=[.?!])\s+', t) if x.strip()]):
        for slot, pat in ASK_PATTERNS:
            if re.search(pat, sentence): return slot
    return None

# ---------- facts the operator states or repeats back ----------
OP_SYSTEM = """You listen to the OPERATOR of a livestock helpline in Karnataka, India, on a call with a farmer.
The text is speech recognition of what the OPERATOR said (clean headset). Operators are trained to repeat key facts back
to the farmer, e.g. "Okay, buffalo, not getting up since morning. Which village?".
Output compact JSON on one line. Include a fact ONLY if the operator stated or repeated it as the farmer's information
in THIS utterance. A fact inside a question that the operator is checking ("Kunigal, right?" or "Is it Kunigal?") counts.
A question that only asks ("Which village?") gives NO fact. Never guess or invent.
- asking: what the operator is asking the farmer now: one of the slot names, or greeting / summary / other.
- animal_type (singular), animals_affected (integer), symptoms (short phrases, negations exact), symptoms_since,
  previous_treatment ("none" if they say none was given), caller_name, village, district, contact_details (digits only),
  can_stand / breathing_ok (true/false).
- urgent: warning signs the operator says ARE present."""

SCHEMA = {'type': 'object', 'properties': {**{k: v for k, v in nlu.SCHEMA['properties'].items()
                                               if k not in ('intent', 'dont_know', 'farmer_question')},
                                            'asking': {'enum': ASKS}}, 'required': ['asking']}

def operator_rules(text):
    """Fallback reading of an operator utterance: gazetteer words, animals, digits and numbers said aloud."""
    t = text.lower(); facts = {}
    a = re.search(r'\b(cow|buffalo|goat|sheep|calf|bullock|bull|ox|pig|hen|chicken|horse|heifer)s?\b', t)
    if a: facts['animal_type'] = a.group(1)
    d = re.sub(r'\D', '', t) or intake_mod.spoken_digits(t)
    if len(d) >= 6: facts['contact_details'] = d
    n = re.search(r'\b(\d+|one|two|three|four|five|six|seven|eight|nine|ten) (animals?|cows?|buffalo(es)?|goats?|sheep|calves|bullocks?)\b', t)
    if n:
        w = n.group(1); facts['animals_affected'] = int(w) if w.isdigit() else 'one two three four five six seven eight nine ten'.split().index(w) + 1
    s = re.search(r'\b(since|from) (yesterday|today|this morning|morning|last night|(one|two|three|four|five|\d+) (days?|weeks?))\b', t)
    if s: facts['symptoms_since'] = s.group(2)
    for kind, pool in (('village', nlu.POOLS['village']), ('district', nlu.POOLS['district']), ('caller_name', nlu.POOLS['caller_name'])):
        for term in pool:
            if re.search(r'\b' + re.escape(term.lower()) + r'\b', t): facts.setdefault(kind, term)
    if re.search(r'\b(not|cannot|can\'t|unable to) (stand|get(ting)? up)\b', t): facts['can_stand'] = False
    if re.search(r'\b(no|not any|nothing) (medicine|treatment|injection)?\s*(given|so far|yet)\b|\bno treatment\b', t): facts['previous_treatment'] = 'none'
    if re.search(r'\bbreath\w* (is )?(very )?(fast|heavy|hard|difficult|not normal)|difficult(y)? (in )?breathing|not breathing (normally|properly)', t):
        facts['breathing_ok'] = False
    elif re.search(r'\bbreath\w* (is )?(normal|fine|okay|ok)\b', t): facts['breathing_ok'] = True
    return facts

NUMBER_WORDS = 'zero one two three four five six seven eight nine ten'.split()
YES_NO_Q = re.compile(r"^(and |so |okay,? |ok,? |um,? |uh,? )*(is|are|can|could|does|do|did|has|have|was|were|will|any)\b")
BOOL_TOPIC = {'can_stand': r'stand|get(ting)? up|lying|fallen|\bdown\b', 'breathing_ok': r'breath'}

def said_by_operator(facts, text):
    """Keep only facts the operator's own words carry. Muse sees the farmer's last line for context and once credited
    the farmer's "since yesterday" to the operator's "Which village?"; it also put "Ramanagara" in both village and district."""
    t = text.lower(); out = {}
    # A yes/no question asks; it doesn't confirm. "is the breathing normal." (ASR dropped the "?") came back as
    # breathing_ok=True and showed as confirmed. A check worded as a statement still counts ("Not able to stand, right?").
    stated = ' '.join(x for x in re.split(r'(?<=[.?!])\s+', t) if x.strip() and not YES_NO_Q.match(x.strip()))
    for k, v in facts.items():
        if isinstance(v, bool): ok = bool(re.search(BOOL_TOPIC[k], stated)) if k in BOOL_TOPIC else True  # read-backs are worded too many ways to match the value
        elif k == 'contact_details': ok = len(re.sub(r'\D', '', t) or intake_mod.spoken_digits(t)) >= 4
        elif isinstance(v, int): ok = str(v) in t or (v <= 10 and re.search(r'\b' + NUMBER_WORDS[v] + r'\b', t))
        elif isinstance(v, list):
            v = [x for x in v if fuzz.partial_ratio(str(x).lower(), t) >= 80 and not nlu.NOT_A_SYMPTOM.search(str(x))]; ok = bool(v)
        else: ok = fuzz.partial_ratio(str(v).lower(), t) >= 80 or nlu._code(str(v)) in nlu._code(text)
        if ok: out[k] = v
    if out.get('village') and same(out.get('village'), out.get('district')): out.pop('village')
    return out

async def interpret_operator(text, last_farmer, backend='muse', session=None, deadline=3.0):
    t0 = time.perf_counter(); own = session is None
    session = session or aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))
    msgs = [{'role': 'system', 'content': OP_SYSTEM},
            {'role': 'user', 'content': f'The farmer last said (shaky speech recognition): "{last_farmer}"\nThe operator said: "{text}"'}]
    try:
        async def muse():
            async with session.post(nlu.MUSE + '/apply-template', json={'messages': msgs}) as r: p = (await r.json())['prompt']
            async with session.post(nlu.MUSE + '/completion', json={'prompt': p + ' to=user<|message|>', 'n_predict': 220, 'temperature': 0,
                                                                   'json_schema': SCHEMA, 'cache_prompt': True}) as r:
                return json.loads((await r.json())['content'])
        d = await asyncio.wait_for(muse(), deadline)
        facts = nlu._from_llm({**d, 'intent': 'answer'}, text)['facts']
        out = {'asking': d.get('asking'), 'facts': facts, 'urgent': d.get('urgent') or [], 'source': backend}
        # The rules catch what the LLM skipped (digits said in groups, a gazetteer name).
        for k, v in operator_rules(text).items(): out['facts'].setdefault(k, v)
    except Exception as e:
        out = {'asking': None, 'facts': operator_rules(text), 'urgent': [], 'source': f'rules ({type(e).__name__})'}
    finally:
        if own: await session.close()
    if (out['facts'].get('can_stand') is True) and not re.search(r'\bstand', text, re.I): out['facts'].pop('can_stand')
    out['urgent'] = nlu.urgent_with_evidence(out['urgent'], text)  # "I am marking this urgent" names no sign
    out['facts'] = said_by_operator(out['facts'], text)
    out['ms'] = round((time.perf_counter() - t0) * 1000)
    return out

# ---------- the shared case record ----------
def same(a, b):
    if a is None or b is None: return False
    if isinstance(a, list) or isinstance(b, list):  # symptoms: the operator confirmed it if they repeated any of them
        a = a if isinstance(a, list) else [a]; b = b if isinstance(b, list) else [b]
        return any(same(x, y) for x in a for y in b)
    if isinstance(a, (bool, int)) or isinstance(b, (bool, int)): return a == b
    a, b = str(a).lower(), str(b).lower()
    return a == b or fuzz.token_set_ratio(a, b) >= 85 or nlu._code(a) == nlu._code(b)

class Field:
    def __init__(self, name):
        self.name = name; self.farmer = None; self.operator = None; self.evidence = []
        self.edited = None  # typed by the operator (the ✎ button): wins over both, and later turns don't overwrite it
    @property
    def value(self):
        if self.edited is not None: return self.edited
        if self.name == 'symptoms' and self.operator and self.farmer:  # the operator's summary plus what else the farmer described
            # only short phrases: the farmer's whole sentences ("Only three months, poor thing, five others...") are in the call
            return self.operator + [x for x in self.farmer if len(str(x).split()) <= 7 and not any(same(x, o) for o in self.operator)]
        return self.operator if self.operator is not None else self.farmer
    @property
    def state(self):
        if self.edited is not None: return 'edited'
        if self.operator is not None and self.farmer is not None:
            if same(self.operator, self.farmer): return 'confirmed'
            # Symptoms in other words ("fever" for "hot ears and body") aren't a disagreement.
            return 'operator' if self.name == 'symptoms' else 'operator_differs'
        if self.operator is not None: return 'operator'
        if self.farmer is not None: return 'heard_only'
        return 'empty'
    def as_dict(self):
        return {'value': self.value, 'state': self.state, 'farmer': self.farmer, 'operator': self.operator, 'edited': self.edited,
                'evidence': self.evidence}

def candidates(kind, value, n=3):
    """Gazetteer spellings that sound like what was heard, for the operator to choose from."""
    if kind not in nlu.CODED or not value: return []
    v, code = nlu._flat(str(value)), nlu._code(str(value))
    scored = sorted(((.5 * fuzz.ratio(code, c) + .5 * fuzz.ratio(v, f), t) for t, c, f in nlu.CODED[kind]), reverse=True)
    return [t for s, t in scored[:n] if s >= 55]

class Assist:
    def __init__(self):
        self.fields = {k: Field(k) for k in REQUIRED}
        self.urgent = []; self.farmer_questions = []; self.asking = None; self.asked = []
        self.transcript = []  # {'role': 'farmer'|'operator', 'text', 't', ...}
        self.partial_phone = ''
        self.phone_mismatch = None       # a read-back with the wrong number of digits

    def _set(self, side, k, v, heard, audio=None):
        f = self.fields[k]
        if k == 'symptoms':
            v = v if isinstance(v, list) else [v]
            prev = getattr(f, side) or []
            v = list(dict.fromkeys(prev + [x for x in v if not any(same(x, p) for p in prev)]))
        if k == 'contact_details':
            v = re.sub(r'\D', '', str(v))
            v = re.sub(r'^(91|0)(?=\d{10}$)', '', v)
            have = getattr(f, side) or f.value
            if len(v) != 10 and have and len(str(have)) == 10:  # a mis-heard read-back must not replace a good number
                f.evidence.append({'side': side, 'heard': heard, 'ignored': v}); self.phone_mismatch = v; return
        setattr(f, side, v)
        f.evidence.append({'side': side, 'heard': heard, **({'audio': audio} if audio else {})})

    def on_farmer(self, heard, nlu_out, audio=None):
        """A farmer turn as the line delivered it, interpreted for the question the operator asked."""
        self.transcript.append({'role': 'farmer', 'text': heard, 'asked': self.asking, **({'audio': audio} if audio else {})})
        for k, v in (nlu_out.get('facts') or {}).items():
            if k in self.fields and v not in (None, '', [], 'UNKNOWN'): self._set('farmer', k, v, heard, audio)
        for k, v in (nlu_out.get('unsure') or {}).items():
            if k in self.fields and self.fields[k].value is None: self._set('farmer', k, v, heard + ' (doubtful)', audio)
        if self.asking == 'contact_details' and 'contact_details' not in (nlu_out.get('facts') or {}):
            d = intake_mod.spoken_digits(heard)
            if d: self.partial_phone = (self.partial_phone + d)[-12:]
        for s in nlu_out.get('urgent') or []: self._urgent(s)
        if self.fields['can_stand'].value is False: self._urgent('unable to stand')
        if self.fields['breathing_ok'].value is False: self._urgent('breathing difficulty')
        if nlu_out.get('farmer_question'): self.farmer_questions.append(nlu_out['farmer_question'])

    def on_operator(self, text, op, entry=None):
        """An operator turn: facts they repeated (confirmed), and what they are now asking."""
        if entry is None: entry = {'role': 'operator', 'text': text}; self.transcript.append(entry)
        entry.update(asking=op.get('asking'), urgent_known=bool(self.urgent), facts=op.get('facts') or {})
        for k, v in (op.get('facts') or {}).items():
            if k in self.fields and v not in (None, '', [], 'UNKNOWN'): self._set('operator', k, v, text)
        for s in op.get('urgent') or []: self._urgent(s)
        if self.fields['can_stand'].value is False: self._urgent('unable to stand')
        if self.fields['breathing_ok'].value is False: self._urgent('breathing difficulty')
        if op.get('asking'):
            self.asking = op['asking']; self.asked.append(op['asking'])

    def edit(self, k, raw):
        """The operator types the value where recognition failed. '' clears the edit (back to what was heard)."""
        f = self.fields[k]; v = parse_edit(k, raw)
        f.edited = v; f.evidence.append({'side': 'operator', 'heard': '(edited) ' + ('cleared' if v is None else fmt(v))})
        if k == 'contact_details': self.phone_mismatch = None
        return v

    def _urgent(self, s):
        if s not in self.urgent: self.urgent.append(s)

    # ---------- live help ----------
    def order(self):
        return intake_mod.URGENT_ORDER if self.urgent else intake_mod.NORMAL_ORDER

    def suggestions(self):
        """-> {'next': {...}, 'alerts': [...]}. The first pending item is the one big prompt on screen."""
        alerts = []
        if self.urgent:
            missing = [LABELS[k].lower() for k in ('village', 'contact_details') if self.fields[k].value is None]
            alerts.append({'level': 'urgent', 'text': 'URGENT: ' + ', '.join(self.urgent) + '.' +
                           (f' Get the {" and ".join(missing)} next.' if missing else ' Location and phone taken.')})
        for q in self.farmer_questions[-1:]:
            alerts.append({'level': 'info', 'text': f'Farmer asked: "{q}". Do not prescribe; say the vet team will advise when they call.'})
        for k in ('caller_name', 'village', 'district'):
            f = self.fields[k]; v = f.value
            if v and v not in nlu.POOLS[k]:
                c = candidates(k, v)
                if c: alerts.append({'level': 'check', 'slot': k, 'text': f'{LABELS[k]} "{v}" is not in the list. Did they mean: {", ".join(c)}?'})
        for k, f in self.fields.items():
            if f.state == 'operator_differs':
                alerts.append({'level': 'check', 'slot': k, 'text': f'{LABELS[k]}: you said "{fmt(f.operator)}", the line heard "{fmt(f.farmer)}". Check with the farmer.'})
        ph = self.fields['contact_details'].value
        if self.phone_mismatch:
            alerts.append({'level': 'check', 'slot': 'contact_details', 'text': f'Your read-back sounded like {len(self.phone_mismatch)} digits '
                           f'({self.phone_mismatch}); kept {ph}. Read it again slowly.'})
        if ph and len(str(ph)) != 10:
            alerts.append({'level': 'check', 'slot': 'contact_details', 'text': f'Phone has {len(str(ph))} digits, needs 10. Ask again, slowly.'})
        nxt = None
        for k in self.order():
            f = self.fields[k]
            if f.state == 'heard_only':
                nxt = {'slot': k, 'kind': 'repeat', 'text': f'Repeat back to confirm: "{say_back(k, f.farmer)}, right?"'}; break
            if f.state == 'empty':
                q = QUESTIONS[k][0].format(animal=self.fields['animal_type'].value or 'animal')
                nxt = {'slot': k, 'kind': 'ask', 'text': f'Ask: "{q}"'}; break
        if nxt is None:
            nxt = {'slot': 'summary', 'kind': 'summary', 'text': 'All taken. Read the whole case back to the farmer, then close the call.'}
        if ph and len(str(ph)) == 10 and not self._phone_read_back():
            alerts.append({'level': 'info', 'slot': 'contact_details', 'text': f'Read the phone number back digit by digit: {intake_mod.digits_spoken(ph)}.'})
        return {'next': nxt, 'alerts': alerts}

    def _phone_read_back(self):
        ph = self.fields['contact_details'].value
        if not ph: return False  # no number taken: the review crashed here
        return any(t['role'] == 'operator' and ph in (re.sub(r'\D', '', t['text']) or intake_mod.spoken_digits(t['text'])) for t in self.transcript)

    def record(self):
        f = {k: x.value for k, x in self.fields.items()}
        return {**f, 'symptoms': f['symptoms'] or [], 'urgent_warning_signs': list(self.urgent),
                'urgency': 'urgent' if self.urgent else 'routine', 'farmer_questions': self.farmer_questions,
                'fields': {k: x.as_dict() for k, x in self.fields.items()},
                'confirmed_fields': [k for k, x in self.fields.items() if x.state in ('confirmed', 'operator', 'edited')],
                'unconfirmed_fields': [k for k, x in self.fields.items() if x.state in ('heard_only', 'operator_differs')],
                'missing_fields': [k for k, x in self.fields.items() if x.state == 'empty']}

    # ---------- after the call ----------
    def qa(self):
        """Did the call do what the protocol asks? Plain checks a supervisor would make."""
        asked = set(self.asked); ops = [t['text'] for t in self.transcript if t['role'] == 'operator']
        urgent_ok = None
        if self.urgent:
            # Once urgent, village and phone should be asked within the next three operator turns.
            first = next((i for i, t in enumerate(x for x in self.transcript if x['role'] == 'operator') if t.get('urgent_known')), None)
            seq = [t.get('asking') for t in self.transcript if t['role'] == 'operator']
            urgent_ok = first is not None and {'village', 'contact_details'} <= set(seq[first:first + 4]) | {k for k in ('village', 'contact_details') if self.fields[k].value}
        checks = [
            ('Asked which animal', 'animal_type' in asked or self.fields['animal_type'].operator is not None),
            ('Asked if the animal can stand', 'can_stand' in asked),
            ('Asked about breathing', 'breathing_ok' in asked),
            ('Repeated the key facts back', sum(x.state in ('confirmed', 'operator', 'edited') for x in self.fields.values()) >= 6),
            ('Read the phone number back', self._phone_read_back()),
            ('Read the case back before closing', 'summary' in asked),
            ('Did not prescribe medicine', not any(re.search(r'\b(give (her|him|it) |you (should|can) give|apply|inject)\b', o, re.I) for o in ops)),
        ]
        if urgent_ok is not None: checks.append(('Urgent: took village and phone first', bool(urgent_ok)))
        return [{'check': c, 'ok': bool(ok)} for c, ok in checks]

def parse_edit(k, raw, kind=None):
    """Typed text -> the field's type: yes/no for the booleans, a number for the count, digits for the phone."""
    t = str(raw if raw is not None else '').strip()
    if not t: return None
    kind = kind or {'can_stand': 'boolean', 'breathing_ok': 'boolean', 'animals_affected': 'integer'}.get(k, 'string')
    if kind == 'boolean':
        if re.match(r'^(y|yes|true|haan|ha|normal|ok|fine)\b', t, re.I): return True
        if re.match(r'^(n|no|false|not|illa|nahi)\b', t, re.I): return False
        raise ValueError('yes or no')
    if kind == 'integer':
        m = re.search(r'\d+', t)
        if m: return int(m.group())
        w = t.lower().split()[0]
        if w in NUMBER_WORDS: return NUMBER_WORDS.index(w)
        raise ValueError('a number')
    if k == 'contact_details': return re.sub(r'\D', '', t) or None
    if k == 'symptoms': return [x.strip() for x in re.split(r'[,;\n]', t) if x.strip()]
    return t

def fmt(v):
    if isinstance(v, list): return ', '.join(map(str, v))
    if v is True: return 'yes'
    if v is False: return 'no'
    return str(v)

def say_back(k, v):
    if k == 'contact_details': return intake_mod.digits_spoken(v)
    if k == 'can_stand': return 'she can stand' if v else 'she cannot stand'
    if k == 'breathing_ok': return 'breathing is normal' if v else 'breathing is not normal'
    if k == 'animals_affected': return f'{intake_mod.number(v)} animal' + ('s' if v != 1 else '')
    if k == 'symptoms_since': return f'since {v}'
    return fmt(v)

REVIEW_SYSTEM = """You review a recorded livestock-helpline call between an OPERATOR and a FARMER in Karnataka, India.
Both sides were transcribed by speech recognition; the farmer side came over a bad phone line and has mis-heard words,
the operator side is clean. Operators repeat key facts back; prefer what the farmer agreed to.
Return the case record as compact JSON. Include a field only if the call establishes it; never invent."""

async def review(transcript, deadline=25.0):
    """Re-read the whole call at the end (local Muse): a second opinion on the record, without the live time pressure."""
    lines = '\n'.join(f'{t["role"].upper()}: {t["text"]}' for t in transcript)
    props = {k: v for k, v in nlu.SCHEMA['properties'].items() if k not in ('intent', 'dont_know', 'farmer_question')}
    # Bounded arrays: unbounded, Muse looped on "urgent" until the token limit cut the JSON off.
    props['urgent'] = {**props['urgent'], 'maxItems': 4}; props['symptoms'] = {**props['symptoms'], 'maxItems': 6}
    schema = {'type': 'object', 'properties': props, 'required': []}
    msgs = [{'role': 'system', 'content': REVIEW_SYSTEM}, {'role': 'user', 'content': lines}]
    t0 = time.perf_counter()
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=deadline)) as s:
            async with s.post(nlu.MUSE + '/apply-template', json={'messages': msgs}) as r: p = (await r.json())['prompt']
            async with s.post(nlu.MUSE + '/completion', json={'prompt': p + ' to=user<|message|>', 'n_predict': 400, 'temperature': 0,
                                                             'json_schema': schema, 'cache_prompt': False}) as r:
                d = json.loads((await r.json())['content'])
        facts = nlu._from_llm({**d, 'intent': 'answer'})['facts']
        return {'record': facts, 'urgent': list(dict.fromkeys(d.get('urgent') or [])), 'ms': round((time.perf_counter() - t0) * 1000), 'source': 'muse'}
    except Exception as e:
        return {'record': {}, 'urgent': [], 'error': f'{type(e).__name__}: {e}'[:200], 'ms': round((time.perf_counter() - t0) * 1000)}

def differences(live, offline):
    """Fields where the re-read disagrees with the live record, or found something the live record missed."""
    out = []
    if not offline: return out
    for k in REQUIRED:
        a, b = live.get(k), offline.get(k)
        if b in (None, []): continue
        if not same(a, b): out.append({'field': k, 'live': fmt(a) if a not in (None, []) else None, 'review': fmt(b) if b not in (None, []) else None})
    return out
