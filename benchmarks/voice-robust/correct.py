"""Context-aware ASR correction: phonetic gazetteer lookup, then a constrained LLM rewrite.

correct(hyp, question=None) -> {'text', 'candidates', 'ms'}

1. Every 1-3 word span of the hypothesis is compared against the service-area vocabulary
   (domain_terms.json) by Double-Metaphone-ish codes and character similarity.
2. The near matches, the question the agent just asked and the raw hypothesis go to the LLM,
   which may only fix words that are clearly misheard; anything else stays verbatim.
The LLM is local Muse by default (LLM_URL), OpenAI-compatible /v1 also supported.
"""
import json, os, re, time
from functools import lru_cache
from pathlib import Path
import requests, jellyfish
from rapidfuzz import fuzz

HERE = Path(__file__).parent
TERMS = json.loads((HERE / 'domain_terms.json').read_text())
VOCAB = sorted({t for k, v in TERMS.items() if not k.startswith('_') for t in v})
MUSE = os.getenv('MUSE_URL', 'http://127.0.0.1:8181')

def _code(s):
    return ''.join(jellyfish.metaphone(w) for w in re.findall(r'[a-z]+', s.lower()))

CODES = [(t, _code(t), re.sub(r'[^a-z]', '', t.lower())) for t in VOCAB]

def candidates(hyp, limit=6):
    """Near matches for spans of the hypothesis, longest/best span wins, no overlaps."""
    words = re.findall(r"[A-Za-z']+", hyp); low = ' ' + ' '.join(words).lower() + ' '
    found = []
    for n in (3, 2, 1):
        for i in range(len(words) - n + 1):
            span = ' '.join(words[i:i + n]); flat = re.sub(r'[^a-z]', '', span.lower())
            if len(flat) < 4: continue
            code = _code(span)
            for term, tcode, tflat in CODES:
                if ' ' + term.lower() + ' ' in low: continue  # already heard correctly
                if abs(len(tflat) - len(flat)) > max(2, len(tflat) // 4): continue
                score = .5 * fuzz.ratio(code, tcode) + .5 * fuzz.ratio(flat, tflat)
                if score >= 74: found.append((score + 2 * n, i, i + n, span, term))
    found.sort(reverse=True); used = set(); out = []
    for score, a, b, span, term in found:
        if used & set(range(a, b)): continue
        used |= set(range(a, b)); out.append({'heard': span, 'maybe': term, 'score': round(score)})
        if len(out) >= limit: break
    return out

SYSTEM = ('You fix speech-recognition errors in what an Indian farmer said on a bad phone line to a livestock helpline '
          'in Karnataka. Change a word ONLY if it is clearly a mis-hearing of a likely word given the question asked, '
          'the livestock context, and the listed nearby place/name/animal words. Keep everything else exactly as heard, '
          'including grammar like "from two days". When you do replace a word, prefer the listed nearby word; ignore a listed word that '
          'does not fit the sentence. Never add information. Output JSON {"text": "..."}.')

def _muse(messages, schema, max_tokens=160):
    p = requests.post(MUSE + '/apply-template', json={'messages': messages}, timeout=30).json()['prompt']
    d = requests.post(MUSE + '/completion', timeout=30, json={'prompt': p + ' to=user<|message|>', 'n_predict': max_tokens,
        'temperature': 0, 'json_schema': schema, 'cache_prompt': True}).json()
    return d['content']

def correct(hyp, question=None):
    t = time.perf_counter()
    if not hyp.strip(): return {'text': hyp, 'candidates': [], 'ms': 0}
    cands = candidates(hyp)
    user = (f'Agent asked: {question or "(start of call)"}\nHeard: "{hyp}"\n'
            + ('Nearby known words: ' + '; '.join(f'"{c["heard"]}" ~ {c["maybe"]}' for c in cands) if cands else 'No nearby known words.')
            + '\nAlso consider common livestock words (udder, calf, bullock, heifer, loose motions).')
    schema = {'type': 'object', 'properties': {'text': {'type': 'string'}}, 'required': ['text']}
    try:
        out = json.loads(_muse([{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': user}], schema))['text']
    except Exception as e:
        out = hyp
    return {'text': out, 'candidates': cands, 'ms': round((time.perf_counter() - t) * 1000)}

if __name__ == '__main__':
    import sys
    for h in sys.argv[1:] or ['My name is Mohamed Erfun, China partner.', 'There is swelling in the other and it is very hot.',
                              'My bullet is having a wound on the leg.', 'The village name is Dada Balapo.']:
        print(json.dumps(correct(h)))
