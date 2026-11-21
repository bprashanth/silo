"""The light pieces of Minis the DGX router needs (it runs on plain Python without pandas): mapping a person's
question to one of a Mini's saved questions with the local 9B, the parameter check, and the visible-text rule.
lib/home.py re-exports these."""
import json
import math
import os
import re
import urllib.request

from lib import muse


def params_for(q, values):
    if not isinstance(values, dict) or values.keys() - q.get('params', {}).keys():
        raise ValueError('Unknown parameter')
    out = {}
    for key, desc in q.get('params', {}).items():
        if not isinstance(desc, dict) or desc.get('type') not in ('choice', 'number', 'text'):
            raise ValueError('Invalid parameter type')
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', key):
            raise ValueError('Invalid parameter name')
        value = values.get(key, desc.get('default'))
        if value is None:
            raise ValueError('Enter ' + key)
        if desc['type'] == 'choice' and value not in desc.get('choices', []):
            raise ValueError('Invalid choice for ' + key)
        if desc['type'] == 'number':
            import math
            if isinstance(value, bool) or not math.isfinite(float(value)):
                raise ValueError('Enter a finite number for ' + key)
            value = float(value)
            value = int(value) if value.is_integer() else value
        if not isinstance(value, (str, int, float)) or len(str(value)) > 2000:
            raise ValueError('Invalid parameter value')
        out[key] = value
    return out


def map_questions(questions, text, local_url=None):
    """The local 9B selects a saved question, or explicitly declines. Never guess on failure."""
    if not questions:
        raise ValueError('This Mini has no questions')
    brief = [{k: q[k] for k in ('id', 'question', 'params', 'asks') if q.get(k)} for q in questions]
    branches = []
    for q in questions:
        props = {}
        for key, desc in q.get('params', {}).items():
            props[key] = ({'type': 'string', 'enum': desc['choices']} if desc['type'] == 'choice'
                          else {'type': 'number'} if desc['type'] == 'number' else {'type': 'string'})
        branches.append({'type': 'object', 'properties': {'reason': {'type': 'string', 'maxLength': 160}, 'qid': {'const': q['id']},
                         'params': {'type': 'object', 'properties': props, 'required': list(props),
                                    'additionalProperties': False}},
                         'required': ['reason', 'qid', 'params'], 'additionalProperties': False})
    branches.append({'type': 'object', 'properties': {'reason': {'type': 'string', 'maxLength': 160}, 'qid': {'type': 'null'},
                     'params': {'type': 'object', 'properties': {}, 'additionalProperties': False}},
                     'required': ['reason', 'qid', 'params'], 'additionalProperties': False})
    schema = {'oneOf': branches}
    direct = local_url or os.environ.get('IDLI_9B_URL')
    payload = {'model': 'qwen3.5-9b' if direct else 'idli-9b', 'temperature': 0, 'max_tokens': 400,
               'chat_template_kwargs': {'enable_thinking': False}, 'messages': [
        {'role': 'system', 'content': 'Map the person\'s request to a saved question. Do not answer it. '
         'Choose qid null with params {} if the requested calculation is not supported, the topic is unrelated, '
         'or an explicitly named choice is unavailable. Do not substitute a different question. '
         'Match the requested calculation and measure exactly. A comparison of one measure cannot answer '
         'a comparison of a different measure. A numeric summary cannot explain causes or predict the future. '
         'Paraphrases are fine; asks lists ways people phrase each saved question. Use parameter defaults only when no value is given. '
         'In one short sentence in reason, state the requested measure and calculation and whether a saved question supports both. '
         'Then choose qid and params. Copy explicitly requested numbers and choices, matching choice case. Return JSON only.\n'
         + json.dumps(brief)}, {'role': 'user', 'content': str(text)[:4000]}],
        'response_format': {'type': 'json_schema', 'json_schema': {'name': 'mini_question', 'schema': schema}}}
    # The DGX chat router calls its local 9B; laptop pages use the configured spec router.
    url = (direct or muse.base_url()).rstrip('/')
    try:
        req = urllib.request.Request(url + '/v1/chat/completions', json.dumps(payload).encode(),
                                     {'Content-Type': 'application/json', **({} if direct else muse.headers())})
        with urllib.request.urlopen(req, timeout=60) as response:
            result = json.loads(json.load(response)['choices'][0]['message']['content'])
        if result['qid'] is None:
            return {'qid': None, 'params': {}, 'method': 'idli-9b'}
        q = next(q for q in questions if q['id'] == result['qid'])
        values = params_for(q, result['params'])
        # Check only the chosen question, without competing questions that share a word.
        # This catches unsupported measures/forecasts and checks explicit values against defaults.
        param_schema = next(b['properties']['params'] for b in branches if b['properties']['qid'].get('const') == q['id'])
        verification = {'type': 'object', 'properties': {'reason': {'type': 'string', 'maxLength': 160},
                        'supported': {'type': 'boolean'}, 'params': param_schema},
                        'required': ['reason', 'supported', 'params'], 'additionalProperties': False}
        payload['response_format']['json_schema']['schema'] = verification
        payload['messages'] = [
            {'role': 'system', 'content': 'Check one saved calculation against a request. Be strict about support. '
             'The saved question must support the exact requested measure, statistic, operation and time period. '
             'A numeric comparison cannot answer a request for causes. Current data cannot predict future data. '
             'A list cannot provide fields it does not list. Reject unavailable named choices and requests to change data. '
             'Use supported false if the calculation cannot answer the request. If it can, verify the parameters: '
             'correct explicit choices and numbers (including number words); use defaults only for unspecified values. '
             'State the check in one short sentence in reason, then supported and params. Return JSON only.'},
            {'role': 'user', 'content': json.dumps({'request': str(text)[:4000],
                                                  'saved_question': next(b for b in brief if b['id'] == q['id']),
                                                  'proposed_params': values})}]
        req = urllib.request.Request(url + '/v1/chat/completions', json.dumps(payload).encode(),
                                     {'Content-Type': 'application/json', **({} if direct else muse.headers())})
        with urllib.request.urlopen(req, timeout=60) as response:
            checked = json.loads(json.load(response)['choices'][0]['message']['content'])
        if checked.get('supported') is not True:
            return {'qid': None, 'params': {}, 'method': 'idli-9b'}
        return {'qid': q['id'], 'params': params_for(q, checked['params']), 'method': 'idli-9b'}
    except (OSError, ValueError, KeyError, TypeError, StopIteration):
        return {'qid': None, 'params': {}, 'method': 'unavailable'}


def plain(text):
    """Shared visible-text contract, including Mini script output and chart titles."""
    return re.sub('[\u2190-\u21ff\u27f0-\u27ff]', ' -> ', str(text)).replace('·', ' - ')


def mentions(text):
    """Keep quoted/escaped paths and ordinary picker paths with spaces.

    An extension or a folder's final slash ends an unquoted path. Extensionless
    file names are resolved against the index by fetch(), using the longest match.
    """
    # Paseo's @ picker inserts a path with spaces quoted and without the @: "Drive/My Drive/x.xlsx"
    # The picker also lists the team's downloaded copies ("drive/My Drive/x.png", "...x.png.csv"): those mean the
    # Drive original, so they are read again from Drive.
    pattern = r'(?:@?"[Dd]rive/([^"\n]+)"|@?\'[Dd]rive/([^\'\n]+)\'|@[Dd]rive/([^@\n<>"\'`]+))'
    paths = []
    for match in re.finditer(pattern, str(text)):
        quoted = match[1] or match[2]
        tail = (quoted or match[3]).replace('\\ ', ' ')
        if not quoted:
            end = re.search(r'/\s|\.[A-Za-z0-9]{1,10}(?=[\s,;!?)]|$)', tail)
            if end:
                tail = tail[:end.start() + 1] if end.group().startswith('/') else tail[:end.end()]
        paths.append('Drive/' + _original(tail.strip().rstrip('.,;!?')))
    return list(dict.fromkeys(paths))


def _original(rel):
    """A downloaded copy's name back to its Drive file: x.png.csv, x.png.table.csv, x.xlsx.source.json -> x.png ..."""
    rel = re.sub(r'\.source\.json$', '', rel)
    m = re.match(r'(.+\.(?:png|jpe?g|webp|tiff?|bmp|heic|pdf|docx?|pptx|txt|mp3|m4a|wav|ogg|opus|aac|amr|mp4|mov|avi|'
                 r'mkv|webm|3gp|xlsx))(?:\.[\w-]+)?\.csv$', rel, re.I)
    return m.group(1) if m else rel


def without_mentions(text, paths):
    for path in sorted(paths, key=len, reverse=True):
        text = text.replace('@"' + path + '"', '').replace("@'" + path + "'", '')
        text = text.replace('"' + path + '"', '').replace("'" + path + "'", '')
        text = text.replace('@' + path, '').replace('@' + path.replace(' ', '\\ '), '')
    text = re.sub(r'@?"drive/[^"\n]+"|@?\'drive/[^\'\n]+\'', '', text)  # downloaded copies (see mentions)
    return ' '.join(text.split()).strip(' ,:;') or 'Help me understand these files.'
