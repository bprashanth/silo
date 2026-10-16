"""Livestock intake dialogue: slots, the order they are asked in, and what to say next.

Pure and synchronous: `Intake.update(nlu)` applies one interpreted farmer turn, and
`Intake.next_turn()` returns what the agent says. Code, not the LLM, decides what to ask,
so a required question can't be forgotten and a question can't be asked forever:
every slot gets at most MAX_ATTEMPTS, then it is marked unclear for human review.
"""
import re

MAX_ATTEMPTS = 2

# slot -> (first question, simpler re-ask). {animal} is filled with the animal named so far.
QUESTIONS = {
    'animal_type': ('Which animal is sick?', 'Is it a cow, buffalo, bullock, goat, sheep, or some other animal?'),
    'symptoms': ('What problem are you seeing in the {animal}?', 'Tell me what is wrong. Is it not eating, has fever, or something else?'),
    'can_stand': ('Is the {animal} able to stand up?', 'Can the {animal} stand? Please say yes or no.'),
    'breathing_ok': ('Is the {animal} breathing normally?', 'Is the breathing normal? Please say yes or no.'),
    'animals_affected': ('How many animals are sick?', 'Only one animal, or more than one?'),
    'symptoms_since': ('Since when is this problem there?', 'Did it start today, yesterday, or some days back?'),
    'previous_treatment': ('Have you given any medicine or treatment already?', 'Any injection or medicine given? Yes or no?'),
    'caller_name': ('What is your name?', 'Please tell me your name once more.'),
    'village': ('Which village are you calling from?', 'Please tell me the village name once more.'),
    'district': ('Which district is that in?', 'Which district? For example Tumakuru, Mandya, or Ramanagara.'),
    'contact_details': ('What phone number can the vet team call you on?', 'Please say the phone number slowly, digit by digit.'),
}
NORMAL_ORDER = ['animal_type', 'symptoms', 'can_stand', 'breathing_ok', 'animals_affected', 'symptoms_since',
                'previous_treatment', 'caller_name', 'village', 'district', 'contact_details']
# Once urgent, get the vet team to the farmer first; the rest only if the farmer stays on.
URGENT_ORDER = ['animal_type', 'symptoms', 'can_stand', 'breathing_ok', 'village', 'contact_details', 'caller_name',
                'district', 'animals_affected', 'symptoms_since', 'previous_treatment']
REQUIRED = NORMAL_ORDER
SPOKEN_LABEL = {'animal_type': 'animal', 'symptoms': 'problem', 'animals_affected': 'number of animals',
                'symptoms_since': 'since', 'previous_treatment': 'treatment given', 'caller_name': 'name',
                'village': 'village', 'district': 'district', 'contact_details': 'phone number'}

CALLER_ID = 'calling number'   # contact_details when the farmer says "this same number"
SAME_NUMBER = re.compile(r'\b(this|same|that|my)\s+(same\s+)?(phone|mobile|number)|\bcalling number|\bcall (me )?(on|back on) this', re.I)

GREETING = 'Namaste, this is the livestock helpline. Please tell me, what happened to your animal?'
SAFE_ADVICE = ('I am not a doctor, so I cannot tell you a treatment. I will pass this to the vet team, '
               'and they will call you.')

def digits_spoken(s):
    d = re.sub(r'\D', '', str(s))
    names = 'zero one two three four five six seven eight nine'.split()
    groups = [d[i:i + 3] for i in range(0, len(d), 3)] if len(d) != 10 else [d[:5], d[5:]]
    return ', '.join(' '.join(names[int(c)] for c in g) for g in groups)

def number(n):
    words = 'zero one two three four five six seven eight nine ten'.split()
    return words[n] if isinstance(n, int) and 0 <= n <= 10 else str(n)

def plural(a, n):
    if not isinstance(n, int) or n == 1 or a.endswith('s'): return a
    return {'sheep': 'sheep', 'calf': 'calves', 'ox': 'oxen'}.get(a, a + 's')

DIGIT_WORDS = {'zero': '0', 'oh': '0', 'o': '0', 'one': '1', 'two': '2', 'to': '2', 'too': '2', 'three': '3', 'four': '4',
               'for': '4', 'five': '5', 'six': '6', 'seven': '7', 'eight': '8', 'nine': '9'}

def spoken_digits(text):
    """'nine eight double four 5' -> '98445'. Only when the reply is mostly digits."""
    words = re.findall(r"[a-z]+|\d", text.lower()); out, double, n = '', False, 0
    for w in words:
        if w == 'double': double = True; continue
        if w == 'triple': double = 2; continue
        d = w if w.isdigit() else DIGIT_WORDS.get(w)
        if d is None: continue
        n += 1; out += d * (3 if double == 2 else 2 if double else 1); double = False
    return out if n and n >= len(words) / 2 else ''

class Slot:
    def __init__(self, name):
        self.name, self.value, self.state, self.attempts, self.evidence = name, None, 'empty', 0, []
    def done(self): return self.state in ('filled', 'unknown', 'unclear')
    def as_dict(self): return {'value': self.value, 'state': self.state, 'attempts': self.attempts, 'evidence': self.evidence}

class Intake:
    def __init__(self):
        self.slots = {k: Slot(k) for k in REQUIRED}
        self.asking = None            # slot of the question last spoken, or 'summary' / 'correction'
        self.phase = 'collect'        # collect -> summary -> closing -> ended
        self.urgent, self.urgent_announced = [], False
        self.summary_rounds, self.confirmed = 0, False
        self.notes = []               # farmer questions/remarks for the human team
        self.side_questions = {}      # slot -> how many times the farmer answered it with a question
        self.advised = False
        self.partial_phone = ''           # digits given so far, when a number comes in pieces
        self.prev_asking = None
        self.phone_confirmed = False
        self.same_in_row = 0
        self.waits = 0
        self.last_said = GREETING
        self.check = None                 # (slot, value) heard doubtfully: read back as a yes/no question first

    # ---------- applying one interpreted turn ----------
    def update(self, nlu, heard, audio=None):
        """Apply an NLU result: {'intent', 'facts': {slot: value|'UNKNOWN'}, 'urgent': [...], 'farmer_question'}."""
        events = []
        intent = nlu.get('intent', 'answer')
        facts = dict(nlu.get('facts') or {})
        # A phone number in pieces: keep the digits and ask for the rest.
        if self.asking == 'contact_details' and not self.slots['contact_details'].done():
            got = re.sub(r'\D', '', str(facts.get('contact_details', ''))) or spoken_digits(heard)
            got = re.sub(r'^(91|0)(?=\d{10}$)', '', got)
            if not got and SAME_NUMBER.search(heard):
                # "This number only": a phone line has caller ID, so the vet team calls back the calling number.
                facts['contact_details'] = CALLER_ID; self.partial_phone = ''
            elif got:
                restart = bool(self.partial_phone) and (got[:3] == self.partial_phone[:3]  # farmer started the number again
                                                        or intent == 'correction' or bool(re.match(r'^\W*(no|sorry|wrong|wait)\b', heard, re.I)))
                whole = got if (len(got) >= 10 or restart) else self.partial_phone + got
                if len(whole) > 10:
                    # Not a 10-digit mobile number: don't store a wrong number, ask again (this costs an attempt).
                    facts.pop('contact_details', None); self.partial_phone = ''
                    events.append(('bad_number', 'contact_details', None))
                elif len(whole) == 10: facts['contact_details'] = whole; self.partial_phone = ''
                else:
                    self.partial_phone = whole; facts.pop('contact_details', None)
                    events.append(('partial', 'contact_details', whole))
        # Doubtful readings are not stored until the farmer says yes to a read-back.
        for k, v in (nlu.get('unsure') or {}).items():
            if k in self.slots and not self.slots[k].done() and k not in facts: self.check = (k, v)
        if facts.get('animals_affected') not in (None, 'UNKNOWN') and not self.slots['animals_affected'].done():
            try:
                if int(facts['animals_affected']) >= 5: self.check = ('animals_affected', int(facts.pop('animals_affected')))
            except (TypeError, ValueError): pass
        nlu = {**nlu, 'facts': facts}
        if self.asking == 'check' and self.check:
            k, v = self.check; s = self.slots[k]
            yes = intent == 'yes' or re.match(r'^\W*(yes|yeah|yep|haan|ha|correct|right|ok|okay)\b', heard, re.I)
            no = intent in ('no', 'correction') or re.match(r'^\W*(no|nahi|illa|wrong|not)\b', heard, re.I)
            if k in facts or (no and not yes):  # rejected, or they gave the value again: take it as a fresh answer
                self.check = None
                s.evidence.append({'asked': self.last_said, 'heard': heard, 'rejected': v})
                if k not in facts:
                    if s.attempts >= MAX_ATTEMPTS: s.state = 'unclear'; return [('unclear', k, None)]
                    self.asking = k; return [('rejected_check', k, None)]
            elif yes:
                self.check = None; s.value, s.state = v, 'filled'
                s.evidence.append({'asked': self.last_said, 'heard': heard, **({'audio': audio} if audio else {})})
                return [('new', k, v)]
            else:
                return []  # unclear reply: the read-back is asked again (bounded by the repeat backstop)
        if self.asking == 'confirm_phone':
            s = self.slots['contact_details']
            said = re.sub(r'\D', '', str(facts.get('contact_details', ''))) or spoken_digits(heard)
            yes = intent == 'yes' or re.match(r'^\s*(yes|yeah|yep|haan|ha|correct|right|ok|okay)\b', heard, re.I)
            no = intent in ('no', 'correction') or re.match(r'^\s*(no|nahi|illa|wrong|not)\b', heard, re.I)
            if (yes and not no) or (said and said == s.value):
                self.phone_confirmed = True; return [('confirmed', 'contact_details', s.value)]
            if len(said) == 10:  # a different number: take it and read it back
                s.value = said; s.evidence.append({'asked': self.last_said, 'heard': heard}); return [('changed', 'contact_details', None, said)]
            if no:
                s.evidence.append({'asked': self.last_said, 'heard': heard, 'rejected': s.value})
                s.value = None; s.state = 'unclear' if s.attempts >= MAX_ATTEMPTS else 'empty'
                return [('rejected', 'contact_details', None)]
            return []  # unclear reply: the confirmation is asked again (bounded by the repeat backstop)
        for k, v in (nlu.get('facts') or {}).items():
            if k not in self.slots or v in (None, '', []): continue
            s = self.slots[k]; prev = s.value
            if v == 'UNKNOWN':
                s.state, s.value = 'unknown', None
            else:
                if k == 'symptoms':
                    v = v if isinstance(v, list) else [v]
                    v = list(dict.fromkeys((prev or []) + v)) if intent != 'correction' else v
                if k == 'animals_affected':
                    try: v = int(v)
                    except (TypeError, ValueError): continue
                if k in ('can_stand', 'breathing_ok'):
                    if not isinstance(v, bool): continue
                s.value, s.state = v, 'filled'
            if prev == s.value and intent != 'correction': continue  # the LLM re-stating an old fact
            s.evidence.append({'asked': self.last_said, 'heard': heard, **({'audio': audio} if audio else {})})
            if intent == 'correction' and prev == s.value and k in ('caller_name', 'village', 'district', 'contact_details'):
                # They corrected us but we heard the same thing again: don't loop, flag it for a human.
                s.state = 'unclear'; events.append(('unclear', k, s.value)); continue
            if prev not in (None, []) and prev != s.value: events.append(('changed', k, prev, s.value))
            elif s.state == 'filled' and prev != s.value: events.append(('new', k, s.value))
        signs = list(nlu.get('urgent') or [])
        if self.slots['can_stand'].value is False: signs.append('unable to stand')
        if self.slots['breathing_ok'].value is False: signs.append('breathing difficulty')
        # A later clear answer withdraws a sign (kept in the evidence; a human still reviews).
        if self.slots['can_stand'].value is True and 'unable to stand' in self.urgent and 'unable to stand' not in (nlu.get('urgent') or []):
            self.urgent.remove('unable to stand'); self.notes.append('withdrawn: unable to stand')
        if self.slots['breathing_ok'].value is True and 'breathing difficulty' in self.urgent and 'breathing difficulty' not in (nlu.get('urgent') or []):
            self.urgent.remove('breathing difficulty'); self.notes.append('withdrawn: breathing difficulty')
        for sign in signs:
            if sign not in self.urgent: self.urgent.append(sign)
        if nlu.get('farmer_question'): self.notes.append(nlu['farmer_question'])
        # An unanswered question costs an attempt; a hold request or a side question does not.
        target = self.slots.get(self.asking)
        if intent == 'question' and self.asking:
            self.side_questions[self.asking] = self.side_questions.get(self.asking, 0) + 1
        free = intent in ('wait', 'repeat') or (intent == 'question' and self.side_questions.get(self.asking, 0) <= 1)
        doubtful = bool(self.check) and self.check[0] == self.asking  # a read-back comes next, not a give-up
        if target and not target.done() and not free and not doubtful:
            if not any(e[1] == self.asking and e[0] != 'bad_number' for e in events if len(e) > 1):  # a partial number is progress
                if target.attempts >= MAX_ATTEMPTS:
                    target.state = 'unclear'; target.evidence.append({'asked': self.last_said, 'heard': heard})
        return events

    @property
    def topic(self):
        """The slot the farmer is answering about (a read-back is about the slot it checks), for ASR and NLU."""
        return self.check[0] if self.asking == 'check' and self.check else self.asking

    # ---------- deciding what to say ----------
    def animal(self):
        return self.slots['animal_type'].value or 'animal'

    def pending(self):
        order = URGENT_ORDER if self.urgent else NORMAL_ORDER
        out = []
        for k in order:
            s = self.slots[k]
            if s.done(): continue
            if k == 'breathing_ok' and self.slots['can_stand'].value is False and 'breathing difficulty' not in self.urgent:
                pass  # still ask: two different warning signs
            out.append(k)
        c = self.slots['contact_details']
        if c.state == 'filled' and not self.phone_confirmed and c.value != CALLER_ID:
            out.insert(0, 'confirm_phone')
        if self.check and not self.slots[self.check[0]].done(): out.insert(0, 'check')
        return out

    def question(self, slot):
        if slot == 'confirm_phone':
            return digits_spoken(self.slots['contact_details'].value) + '. Is that number right?'
        if slot == 'check':
            k, v = self.check
            if k == 'animals_affected': return f'{number(v).capitalize()} animals, is that right?'
            return f'Did you say {"an" if str(v)[:1] in "aeiou" else "a"} {v}?'
        s = self.slots[slot]
        first, again = QUESTIONS[slot]
        q = first if s.attempts == 0 else again
        return q.format(animal=self.animal())

    def echo(self, events):
        """Short read-back of what was just understood, so a mis-hearing can be corrected at once."""
        parts = []
        for e in events:
            k, v = e[1], e[-1]
            if e[0] in ('partial', 'bad_number') or v is None: continue
            if e[0] == 'unclear':
                parts.append(f'sorry, I cannot catch the {SPOKEN_LABEL.get(k, k)} clearly, the vet team will confirm it with you'); continue
            if k == 'animal_type': parts.append(f'a {v}' if not v.endswith('s') else str(v))
            elif k in ('caller_name', 'village', 'district'): parts.append(str(v))
            elif k == 'animals_affected': parts.append(f'{number(v)} animal' + ('s' if v != 1 else ''))
            elif k == 'symptoms_since': parts.append(f'since {v}' if not re.match(r'(since|from)\b', str(v)) else str(v))
            elif k == 'contact_details' and v == CALLER_ID: parts.append('okay, the vet team will call you back on this same number')
            elif k == 'contact_details': pass  # read back by the explicit confirmation question
        if not parts: return ''
        changed = any(e[0] == 'changed' for e in events)
        return ('Sorry, corrected: ' if changed else '') + ', '.join(parts).capitalize() + '.'

    def summary(self):
        f = self.slots; bits = []
        a = f['animal_type'].value; n = f['animals_affected'].value
        if a: bits.append(f'{number(n)} {plural(a, n)}' if n else f'your {a}')
        if f['symptoms'].value: bits.append(', '.join(f['symptoms'].value))
        if f['symptoms_since'].value: bits.append(f'since {f["symptoms_since"].value}')
        out = 'Let me read it back. ' + ', '.join(bits).capitalize() + '.'
        if self.urgent: out += ' Urgent: ' + ' and '.join(self.urgent) + '.'
        t = f['previous_treatment']
        if t.state == 'filled': out += ' No treatment given.' if str(t.value).lower() in ('none', 'no') else f' Treatment given: {t.value}.'
        who = []
        if f['caller_name'].state == 'filled': who.append(f'Your name is {f["caller_name"].value}')
        place = [str(f[k].value) for k in ('village', 'district') if f[k].state == 'filled']
        if place: who.append('from ' + ', '.join(place))
        if who: out += ' ' + ' '.join(who) + '.'
        if f['contact_details'].value == CALLER_ID: out += ' The vet team will call this same number.'
        elif f['contact_details'].state == 'filled': out += ' Phone ' + digits_spoken(f['contact_details'].value) + '.'
        elif f['contact_details'].state in ('unclear', 'unknown'): out += ' I could not get your phone number, so the vet team will call the number you are calling from.'
        return out + ' Is that correct?'

    def next_turn(self, nlu=None, events=()):
        """-> dict(text, asking, end). Called after update(), or with nlu=None for a re-prompt."""
        intent = (nlu or {}).get('intent', 'answer')
        pre = []
        if self.urgent and not self.urgent_announced:
            pre.append('This sounds serious. I am marking it urgent for the vet team right now.')
            self.urgent_announced = True
        if intent == 'question':
            pre.append('The vet team will advise you on that when they call.' if self.advised else SAFE_ADVICE)
            self.advised = True
        if intent == 'wait':
            self.waits += 1
            return self._say('Sure, take your time. I am here.' if self.waits == 1 else ['Okay.', 'Hmm.', 'Yes, I am here.'][self.waits % 3], self.asking, hold=True)
        self.waits = 0
        if intent == 'repeat' and not events:
            return self._say(' '.join(pre + [self.last_said]), self.asking)

        if self.phase == 'summary':
            if intent == 'yes' or (intent == 'answer' and nlu and nlu.get('confirm') is True):
                self.confirmed, self.phase = True, 'closing'
                return self._say(' '.join(pre + ['Thank you. I have registered this for the vet team. '
                                                  'This is a demo, so no vet is actually sent. Take care, goodbye.']), None, end=True)
            if events:  # a correction was given directly
                self.summary_rounds += 1
            elif intent in ('no', 'correction'):
                self.summary_rounds += 1
                if self.summary_rounds > 2:
                    self.phase = 'closing'
                    return self._say(' '.join(pre + ['Okay. I have noted everything you said, and the vet team will '
                                                      'check the details with you. Goodbye.']), None, end=True)
                return self._say(' '.join(pre + ['Sorry about that. What should I correct?']), 'correction')
            elif self.asking == 'correction' and not events:
                return self._say(' '.join(pre + ['Please tell me what is wrong, for example the village or the animal.']), 'correction')
            return self._say(' '.join(pre + [self.echo(events), self.summary()]).strip(), 'summary')

        if any(e[0] == 'bad_number' for e in events) and not self.slots['contact_details'].done():
            self.slots['contact_details'].attempts += 1
            return self._say(' '.join(pre + ['Sorry, I did not get the full number. Please say the ten digits slowly.']), 'contact_details')
        if any(e[0] == 'rejected' for e in events) and not self.slots['contact_details'].done():
            self.slots['contact_details'].attempts += 1
            return self._say(' '.join(pre + ['Sorry. Please tell me the number again, slowly.']), 'contact_details')
        if any(e[0] == 'partial' for e in events):
            return self._say(' '.join(pre + [digits_spoken(self.partial_phone) + '. Go on.']), 'contact_details')
        ack = self.echo(events)
        todo = self.pending()
        redo = [e[1] for e in events if e[0] == 'rejected_check']
        if redo and redo[0] in todo: todo.insert(0, redo[0])  # "No" to "Ten animals?": ask that again now
        if not todo:
            self.phase = 'summary'
            return self._say(' '.join(pre + [self.summary()]).strip(), 'summary')
        slot = todo[0]
        if slot == self.asking and not events and intent not in ('question',):
            lead = 'Sorry, the line is not clear.' if intent in ('unclear', 'answer') else ''
        else:
            lead = ''
        q = self.question(slot)
        if slot in self.slots: self.slots[slot].attempts += 1
        return self._say(' '.join(x for x in pre + [ack, lead, q] if x), slot)

    def reprompt(self):
        """The farmer went quiet after a question: ask again, more simply, without stacking prefixes."""
        if self.phase == 'summary': q = self.summary()
        elif self.asking in QUESTIONS: q = QUESTIONS[self.asking][1].format(animal=self.animal())
        elif self.asking == 'correction': q = 'What should I correct?'
        else: q = 'Please tell me, what happened to your animal?'
        out = self._say('Hello, are you there? ' + q, self.asking, hold=True)
        return out

    def _say(self, text, asking, end=False, hold=False):
        # Backstop against any loop: the same question may not be asked a third time in a row.
        if not end and not hold and asking == self.asking and asking and text == self.last_said:
            self.same_in_row += 1
            if self.same_in_row >= 2:
                self.same_in_row = 0
                if asking == 'confirm_phone': self.phone_confirmed = True; self.notes.append('phone number not confirmed by caller')
                elif asking == 'check' and self.check:
                    k, v = self.check; self.check = None; s = self.slots[k]; s.value, s.state = v, 'unclear'
                elif asking in self.slots: self.slots[asking].state = 'unclear'
                elif asking in ('summary', 'correction'): self.phase = 'closing'; return self._say('Okay. I have noted everything, and the vet team will check the details with you. Goodbye.', None, end=True)
                return self.next_turn({'intent': 'unclear'}, [])
        else:
            self.same_in_row = 0
        if asking != self.asking: self.prev_asking = self.asking
        self.asking = asking
        if not hold: self.last_said = text
        if end: self.phase = 'ended'
        return {'text': re.sub(r'\s+', ' ', text).strip(), 'asking': asking, 'end': end, 'hold': hold}

    # ---------- record ----------
    def record(self):
        f = {k: s.value for k, s in self.slots.items()}
        signs = list(self.urgent)
        return {
            'caller_name': f['caller_name'], 'village': f['village'], 'district': f['district'],
            'animal_type': f['animal_type'], 'animals_affected': f['animals_affected'], 'symptoms': f['symptoms'] or [],
            'symptoms_since': f['symptoms_since'], 'previous_treatment': f['previous_treatment'],
            'contact_details': f['contact_details'], 'urgent_warning_signs': signs,
            'needs_human_review': True, 'urgency': 'urgent' if signs else 'routine',
            'confirmed_by_caller': self.confirmed,
            'unknown_fields': [k for k, s in self.slots.items() if s.state == 'unknown'],
            'unclear_fields': [k for k, s in self.slots.items() if s.state == 'unclear'],
            'missing_fields': [k for k, s in self.slots.items() if s.state == 'empty'],
            'farmer_questions': self.notes,
            'call_status': 'completed' if self.confirmed else ('ended_unconfirmed' if self.phase == 'ended' else 'in_progress'),
            'slots': {k: s.as_dict() for k, s in self.slots.items()},
        }
