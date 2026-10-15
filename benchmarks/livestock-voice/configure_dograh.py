"""Provision a native, entirely local Dograh livestock workflow after dograh.sh start.

Credentials are generated and retained only in chmod-600 NVMe files.
"""
import json
from pathlib import Path
import secrets
import time
import urllib.request
import urllib.error

STATE = Path.home() / '.local/share/silo-livestock/dograh'
BASE = 'http://127.0.0.1:18000/api/v1'


def main():
    STATE.mkdir(parents=True, exist_ok=True)
    for attempt in range(60):
        try:
            urllib.request.urlopen(BASE+'/health', timeout=2).close()
            break
        except (urllib.error.URLError, TimeoutError):
            if attempt == 59:
                raise RuntimeError('Dograh API did not become healthy within 60 seconds') from None
            time.sleep(1)

    def private(name, value):
        path = STATE / name
        path.write_text(json.dumps(value))
        path.chmod(0o600)
    if not (STATE/'account.json').exists():
        private('account.json', {'email':'livestock-demo@example.com', 'password':secrets.token_urlsafe(24), 'name':'Synthetic Livestock Benchmark'})
    credentials = json.loads((STATE/'account.json').read_text())
    token = None
    def api(path, body=None, method=None):
        headers = {'Content-Type':'application/json'}
        if token:
            headers['Authorization'] = 'Bearer ' + token
        req = urllib.request.Request(BASE+path, data=json.dumps(body).encode() if body is not None else None, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=90) as response:
            return json.load(response)
    try:
        auth = api('/auth/signup', credentials)
    except urllib.error.HTTPError as error:
        if error.code != 409:
            raise RuntimeError(f'Dograh signup failed: HTTP {error.code}') from None
        auth = api('/auth/login', {k:credentials[k] for k in ('email','password')})
    token = auth['token']
    private('auth.json', auth)
    if (STATE/'connection.json').exists():
        connection = json.loads((STATE/'connection.json').read_text())
    else:
        connection = api('/model-connections/provider-connections', {
            'name':'Local Muse Whisper Kokoro', 'provider':'openai',
            'credentials':{'api_key':'local-only'},
            'connection_settings':{'base_url':'http://host.docker.internal:18282/v1'}})
        private('connection.json', connection)
    if (STATE/'configuration.json').exists():
        configuration = json.loads((STATE/'configuration.json').read_text())
    else:
        def role(model, **settings):
            return {'provider_connection_uuid':connection['uuid'], 'settings':{'model':model, **settings}}
        configuration = api('/model-connections/model-configurations', {'name':'Private livestock pipeline', 'configuration':{
            'mode':'pipeline', 'llm':role('muse-glimmer-30b',temperature=0.3), 'stt':role('whisper-1'), 'tts':role('kokoro',voice='af_heart')}})
        private('configuration.json', configuration)
    api('/model-connections/default', {'model_configuration_uuid':configuration['uuid']}, 'PUT')
    questionnaire = json.loads(Path(__file__).with_name('questionnaire.json').read_text())
    prompt = ('You are a fictional livestock emergency intake operator, not a veterinarian. Never diagnose or prescribe. '
              'Begin with a brief greeting asking what happened. Ask ONE short natural question at a time. '
              'Collect caller name, village, district, animal type, count, symptoms, onset, previous treatment, urgent warning signs, optional contact. '
              'Remember facts and corrections; ask only missing information. Unknown answers are valid. '
              'Unable to stand, breathing difficulty or severe bleeding require urgent human review. '
              'Summarize all facts then ask confirmation. End only after confirmation. Keep spoken turns under 25 words except final summary. '
              'Shared questionnaire: '+json.dumps(questionnaire))
    graph = {'nodes':[
        {'id':'1','type':'startCall','position':{'x':0,'y':0},'data':{'name':'Livestock intake','prompt':prompt,'allow_interrupt':True}},
        {'id':'2','type':'endCall','position':{'x':300,'y':0},'data':{'name':'Confirmed completion','prompt':'Thank the caller. This is a synthetic demonstration; no real veterinarian was dispatched.'}}],
        'edges':[{'id':'e1','source':'1','target':'2','data':{'label':'Confirmed intake','condition':'The caller has confirmed the final summary and all known information has been collected.'}}]}
    graph['nodes'][0]['data'].update({
        'extraction_enabled': True,
        'extraction_prompt': 'Extract ONLY caller-stated facts. Keep unknown answers null. Do not infer name, place, onset, treatment or contact. Record confirmed_by_caller only after explicit confirmation. Needs human review is always true for this demo.',
        'extraction_variables': [
            {'name': name, 'type': 'number' if name == 'animals_affected' else 'boolean' if name in ('confirmed_by_caller','needs_human_review') else 'string', 'prompt': 'Caller-stated '+name+'; unknown when not answered.'}
            for name in questionnaire['required_fields'] + ['confirmed_by_caller','needs_human_review']
        ]
    })
    if (STATE/'workflow.json').exists():
        workflow = json.loads((STATE/'workflow.json').read_text())
        workflow = api('/workflow/'+str(workflow['id']), {'workflow_definition':graph}, 'PUT')
    else:
        workflow = api('/workflow/create/definition', {'name':'Synthetic livestock intake — local only','workflow_definition':graph})
    private('workflow.json', workflow)
    print('Native local workflow ready: http://127.0.0.1:13010/workflow/'+str(workflow['id']))

if __name__ == '__main__':
    main()
