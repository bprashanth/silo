"""A live farmer for role-playing the operator: an LLM on OpenRouter plays Lakshmamma from a case sheet.

The scripted farmer (farmer.py) can only answer the questions its clips cover, in that order. This one holds a
conversation: the operator can take any route through the case, ask follow-ups the checklist doesn't have
("did you buy any new goats?"), and the farmer only reveals what was asked. The case sheets
(lakshmamma.json) are built from Indian field reports; each one names its source.

Only synthetic role-play goes to OpenRouter: the case sheet and the operator's recognised words.
"""
import json, os, re, time
from pathlib import Path
import aiohttp

MODEL = os.getenv('FARMER_LLM', 'google/gemini-3.1-flash-lite')
KEY_FILE = Path.home() / '.config/idlisseus/openrouter.json'

SYSTEM = """You are {name}, a livestock farmer in {village} village, {taluk} taluk, {district} district, Karnataka, India.
You are calling the government animal helpline (like 1962) from your basic phone, on a bad line. A helpline operator answers.
{about}

YOUR SITUATION (the truth; never contradict it):
{story}
Details you give ONLY when the operator asks about that thing:
{reveal}
How you are on this call: {manner}
Your name: {name}. Village: {village}. Taluk: {taluk}. District: {district}. Phone: {phone}. {phone_how}

HOW TO TALK
- You are speaking on the phone, not writing. One short sentence, sometimes two. Never more than about 20 words.
- Answer what was asked, and only that. Never describe the whole problem in one go; give one sign at a time,
  the most worrying first. Never use veterinary terms or disease names (no "PPR", "enterotoxaemia", "dystocia", "pneumonia").
- Plain Indian English with an occasional Kannada word from your list. No stage directions, no emojis, no quotes.
  Never spell words letter by letter. Asked for the village, say the village only; give the taluk or district only when asked.
- If the operator repeats something back WRONGLY (wrong animal, number, village, name, phone digit), correct it at once ("No madam, Hosahalli").
  If they repeat it back correctly, a short yes ("Haan, correct") and nothing more, unless they also asked something.
- If the operator only says something like "okay" or "I am noting it" and asks nothing, say nothing (empty) or just "Haan".
- If the operator's words look garbled or make no sense, say "Sorry? The line is bad." Do not guess what they meant.
- If they ask something you don't know, say so as a farmer would ("I don't know madam, maybe two days").
- Do not ask about the operator. You may ask once whether you should give some medicine.
- When the operator says goodbye or that the vet team will call, thank them briefly and set "hangup" to true.

Reply as JSON: {{"say": "<your words, or empty to stay quiet>", "hangup": false}}"""

def load(path=Path(__file__).resolve().parent / 'lakshmamma.json'):
    d = json.loads(Path(path).read_text())
    return d['persona'], {c['id']: c for c in d['cases']}

class AIFarmer:
    def __init__(self, persona, case, model=MODEL):
        self.persona, self.case, self.model = persona, case, model
        self.system = SYSTEM.format(**persona, story=case['story'], manner=case['manner'],
                                    reveal='\n'.join('- ' + r for r in case['reveal_only_if_asked']))
        self.history = []; self.opened = False; self._saved = None; self.calls = []
        self.key = json.loads(KEY_FILE.read_text())['api_key']

    def undo(self):
        """The operator kept talking before the farmer answered: forget that exchange."""
        if self._saved is not None: self.history, self.opened = self._saved; self._saved = None

    async def reply(self, operator_text, session, deadline=6.0):
        """-> {'say': str, 'hangup': bool, 'ms': int}. operator_text None means a long silence on the line."""
        self._saved = (list(self.history), self.opened)
        if not self.opened and operator_text is not None:
            self.opened = True
            self.history += [{'role': 'user', 'content': operator_text}, {'role': 'assistant', 'content': json.dumps({'say': self.case['opening'], 'hangup': False})}]
            return {'say': self.case['opening'], 'hangup': False, 'ms': 0, 'source': 'opening'}
        user = operator_text if operator_text is not None else '(silence on the line for several seconds)'
        msgs = [{'role': 'system', 'content': self.system}, *self.history, {'role': 'user', 'content': user}]
        body = {'model': self.model, 'temperature': 0.6, 'max_tokens': 120, 'messages': msgs, 'reasoning': {'enabled': False},
                'response_format': {'type': 'json_object'}}
        t0 = time.perf_counter()
        try:
            async with session.post('https://openrouter.ai/api/v1/chat/completions', json=body,
                                    headers={'Authorization': 'Bearer ' + self.key}, timeout=aiohttp.ClientTimeout(total=deadline)) as r:
                d = await r.json()
            c = d['choices'][0]['message']['content']
            out = json.loads(c[c.index('{'):c.rindex('}') + 1])
            say = re.sub(r'[*_"#]|\(.*?\)', '', str(out.get('say') or '')).strip()
            # She hangs up only after a goodbye; the LLM once hung up on "I am sending the van" mid-call.
            bye = re.search(r'\b(good ?bye|bye|thank you for calling)\b', operator_text or '', re.I)
            out = {'say': say, 'hangup': bool(out.get('hangup')) and bool(bye), 'source': self.model}
        except Exception as e:  # a farmer who didn't hear: the call goes on
            out = {'say': 'Hello? Sorry, I could not hear.', 'hangup': False, 'source': f'fallback ({type(e).__name__})'}
        out['ms'] = round((time.perf_counter() - t0) * 1000)
        self.history += [{'role': 'user', 'content': user}, {'role': 'assistant', 'content': json.dumps({'say': out['say'], 'hangup': out['hangup']})}]
        self.calls.append({'operator': operator_text, **out})
        return out
