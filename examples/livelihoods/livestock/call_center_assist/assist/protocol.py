"""Protocol cards for the operator assist (prototype; switch off with ASSIST_PROTOCOL=0).

The pattern real dispatch systems use for non-clinical call-takers (MPDS, NHS Pathways, the 1962 ERC flow):
the call-taker doesn't diagnose or prescribe. A card, opened by what the caller says, adds
  - key questions (here: more fields in the care record, with the same confirmed / heard-only states),
  - a priority level from fixed rules on the answers (E dispatch now and bring the vet on, D, C, A),
  - a few pre-approved lines to read to the caller (keep them apart, don't pull, don't pour anything in the mouth),
  - and escalation to a clinician, who gives the medical direction.
The clinical layer (DAHD's Standard Veterinary Treatment Guidelines) is only named in the vet's handoff.

Deterministic on purpose: triggers and levels are rules from protocol_cards.json. The LLM (local Muse) only
fills a card's fields from what was said; it never sets the level or writes advice.
"""
import asyncio, json, os, re, time
from pathlib import Path
import aiohttp
import nlu
from assist import Field, is_question, same

ENABLED = os.getenv('ASSIST_PROTOCOL', '1') != '0'
CARDS_FILE = Path(__file__).resolve().parent / 'protocol_cards.json'
ORDER = 'ACDE'  # lowest to highest priority

def load(path=CARDS_FILE):
    return json.loads(Path(path).read_text())

def statements(text):
    """The operator's statements, not their questions: "Any sores in the mouth?" must not open the sores card."""
    return ' '.join(s for s in re.split(r'(?<=[.?!])\s+', text or '') if s.strip() and not is_question(s))

NUMBER_WORDS = 'zero one two three four five six seven eight nine ten'.split()
STOP = set('the a an and or of to in on at is are was were it its they them their she her he his some any very not no yes okay ok madam sir haan'.split())

def evidence(meta, v, text, asked):
    """Is the value actually in the words? Muse answered "No" into string fields and "four goats" into "Age".
    Strings need their own words in the line, numbers must be said, and yes/no only answers the question asked."""
    t = text.lower(); words = set(re.findall(r"[a-z]+", t))
    if isinstance(v, bool): return bool(asked)
    if isinstance(v, int): return str(v) in t or (0 <= v <= 10 and NUMBER_WORDS[v] in words)
    content = [w for w in re.findall(r"[a-z]+", str(v).lower()) if len(w) > 2 and w not in STOP]
    return bool(content) and sum(w in words for w in content) >= max(1, len(content) // 2)

def _match(v, want):
    if v is None or v == []: return False
    if isinstance(want, bool): return v is want
    if isinstance(want, str) and want.startswith('>='):
        try: return int(v) >= int(want[2:])
        except (TypeError, ValueError): return False
    return v == want

class Protocol:
    def __init__(self, spec=None):
        self.spec = spec or load(); self.cards = {c['id']: c for c in self.spec['cards']}
        self.open = []                 # card ids, in the order they opened
        self.fields = {}               # card field id -> Field (shared when two cards ask the same thing)
        self.meta = {}                 # card field id -> {'label', 'ask', 'type'}
        self.extract_log = []

    # ---------- opening cards ----------
    def see(self, text, side):
        """A turn: farmer words (as the line delivered them) or the operator's statements. -> newly opened card ids."""
        t = text if side == 'farmer' else statements(text); new = []
        for cid, c in self.cards.items():
            if cid not in self.open and re.search(c['triggers'], t, re.I):
                self.open.append(cid); new.append(cid)
                for f in c['fields']:
                    self.fields.setdefault(f['id'], Field(f['id'])); self.meta.setdefault(f['id'], f)
        return new

    # ---------- filling the cards' fields (local Muse) ----------
    def _schema(self, keys):
        t = {'integer': {'type': ['integer', 'null']}, 'boolean': {'type': ['boolean', 'null']}, 'string': {'type': ['string', 'null']}}
        return {'type': 'object', 'properties': {k: t[self.meta[k]['type']] for k in keys}, 'required': []}

    def fillable(self, side, context, opened=(), text=''):
        """Which card fields this turn may fill. Offered every open field, Muse filled "Ate what" with the operator's
        goodbye and "Age" with "four goats". So: a farmer answer fills the fields the operator just asked about (or
        the fields of a card her own words just opened), and an operator line only confirms what the farmer gave."""
        if side == 'operator':
            # "How old was the small one?" asks; it doesn't repeat "one died". Repeats are statements or "X, right?".
            if re.match(r"^(and |so |okay,? |ok,? )?(how|what|which|when|where|who|why)\b", text.strip().lower()): return []
            return [k for k, f in self.fields.items() if f.farmer is not None]
        new = {f['id'] for c in opened for f in self.cards[c]['fields']}
        # Fields of a card her words just opened, only when her words are about them ("two of them are coughing" is not an age).
        return [k for k, m in self.meta.items() if (context and re.search(m['asked_if'], context, re.I))
                or (k in new and re.search(m['asked_if'], text, re.I))]

    async def extract(self, text, side, context, session=None, deadline=6.0, opened=()):  # off the critical path; Muse is shared
        """Fill open card fields from ONE turn. context: the operator's last question, for a farmer turn."""
        keys = self.fillable(side, context, opened, text)
        if not keys or not text: return {}
        lines = '\n'.join(f'- {k}: {self.meta[k]["ask"]}' for k in keys)
        who = 'FARMER (bad phone line; speech recognition may be wrong)' if side == 'farmer' else 'OPERATOR (repeating or stating facts)'
        msgs = [{'role': 'system', 'content': 'You fill extra fields of a livestock helpline case record. Return compact JSON with ONLY the '
                 'fields this one line answers; leave the rest out. Never guess. Fields:\n' + lines},
                {'role': 'user', 'content': (f'The operator had asked: "{context}"\n' if context else '') + f'{who} said: "{text}"'}]
        t0 = time.perf_counter(); own = session is None
        session = session or aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))
        try:
            async def call():
                async with session.post(nlu.MUSE + '/apply-template', json={'messages': msgs}) as r: p = (await r.json())['prompt']
                async with session.post(nlu.MUSE + '/completion', json={'prompt': p + ' to=user<|message|>', 'n_predict': 160, 'temperature': 0,
                                                                       'json_schema': self._schema(keys), 'cache_prompt': True}) as r:
                    return json.loads((await r.json())['content'])
            d = {k: v for k, v in (await asyncio.wait_for(call(), deadline)).items() if k in keys and v not in (None, '', [])}
        except Exception as e:
            d = {}; self.extract_log.append({'error': type(e).__name__})
        finally:
            if own: await session.close()
        d = {k: v for k, v in d.items()
             if evidence(self.meta[k], v, text, re.search(self.meta[k]['asked_if'], (context if side == 'farmer' else text) or '', re.I))}
        if side == 'operator':  # a repeat of the farmer's answer, or a line about that very thing; not the goodbye
            d = {k: v for k, v in d.items() if same(v, self.fields[k].farmer) or re.search(self.meta[k]['asked_if'], text, re.I)}
        for k, v in d.items():
            setattr(self.fields[k], side, v); self.fields[k].evidence.append({'side': side, 'heard': text})
        self.extract_log.append({'side': side, 'text': text, 'facts': d, 'ms': round((time.perf_counter() - t0) * 1000)})
        return d

    # ---------- priority, lines to read, escalation ----------
    def values(self, record):
        return {**{k: record.get(k) for k in ('can_stand', 'breathing_ok', 'animals_affected')}, **{k: f.value for k, f in self.fields.items()}}

    def card_level(self, cid, record):
        c = self.cards[cid]; v = self.values(record); lvl = c['level']
        for r in c['rules']:
            if all(_match(v.get(k), want) for k, want in r['when'].items()) and ORDER.index(r['level']) > ORDER.index(lvl): lvl = r['level']
        return lvl

    def level(self, record):
        lv = [self.card_level(c, record) for c in self.open]
        if record.get('urgent_warning_signs'): lv.append('D')
        return max(lv, key=ORDER.index) if lv else None

    def _said(self, pattern, transcript):
        return any(t['role'] == 'operator' and re.search(pattern, t['text'], re.I) for t in transcript)

    def view(self, record, transcript):
        lvl = self.level(record)
        if not lvl: return None
        L = self.spec['levels'][lvl]
        cards = []
        for cid in self.open:
            c = self.cards[cid]
            cards.append({'id': cid, 'title': c['title'], 'level': self.card_level(cid, record), 'notifiable': c['notifiable'],
                          'fields': [{'id': f['id'], 'label': f['label'], 'ask': f['ask'], 'type': f['type'], **self.fields[f['id']].as_dict()} for f in c['fields']],
                          'say': [{'text': s['text'], 'said': self._said(s['heard_if'], transcript)} for s in c['say']]})
        return {'level': lvl, 'label': L['label'], 'response': L['response'], 'escalate': L['escalate'],
                'escalated': L['escalate'] and self._said(self.spec['escalated_if'], transcript),
                'cards': cards, 'closing': {'text': self.spec['closing']['text'], 'said': self._said(self.spec['closing']['heard_if'], transcript)},
                'status': self.spec['status']}

    # ---------- after the call ----------
    def qa(self, record, transcript):
        v = self.view(record, transcript)
        if not v: return []
        out = []
        for c in v['cards']:
            n = sum(f['state'] != 'empty' for f in c['fields'])
            out.append({'check': f'{c["title"]}: key questions answered ({n}/{len(c["fields"])})', 'ok': n == len(c['fields'])})
            out.append({'check': f'{c["title"]}: read the advice lines', 'ok': all(s['said'] for s in c['say'])})
        if v['escalate']: out.append({'check': f'Priority {v["level"]}: brought in the vet / dispatch', 'ok': v['escalated']})
        out.append({'check': 'Gave the call-back-if-worse advice', 'ok': v['closing']['said']})
        out.append({'check': 'Did not name a disease to the farmer',
                    'ok': not self._said(self.spec['never_say'], transcript)})
        return out

    def handoff(self, record, transcript):
        """What the vet gets: the level, the cards and their answers, notifiable flags, and where to look."""
        v = self.view(record, transcript)
        if not v: return None
        return {'level': v['level'], 'label': v['label'], 'response': v['response'],
                'cards': [{'title': c['title'], 'level': c['level'], 'notifiable': c['notifiable'],
                           'answers': {f['label']: f['value'] for f in c['fields'] if f['value'] not in (None, [])},
                           'reference': self.cards[c['id']]['for_vet']} for c in v['cards']]}
