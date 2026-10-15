"""Native Dograh spoken test: real browser WebRTC, synthetic microphone/audio capture."""
import argparse
import datetime
import base64
import json
from pathlib import Path
import wave
import subprocess
from playwright.sync_api import sync_playwright
ROOT=Path('/mnt/seagate/silo/livestock-voice')
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=Path, default=ROOT/'runs'/('dograh-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S')))
args=parser.parse_args()
OUT=args.output; OUT.mkdir(parents=True,exist_ok=True)
# Feed isolated utterances, not a rapidly repeated fake mic loop that interrupts the agent.
def load(name):
    return subprocess.run(['ffmpeg','-loglevel','error','-i',str(ROOT/'fixtures'/name),'-f','s16le','-ar','16000','-ac','1','pipe:1'],capture_output=True,check=True).stdout

fixture=ROOT/'fixtures/dograh-multiturn.wav'
with wave.open(str(fixture),'wb') as f:
    f.setparams((1,2,16000,0,'NONE','NONE'))
    for part in [bytes(16000*2*20),load('missing.wav'),bytes(16000*2*15),load('out_of_order.wav'),bytes(16000*2*70)]:f.writeframes(part)
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True,args=['--no-sandbox','--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream',f'--use-file-for-fake-audio-capture={fixture}'])
    page=browser.new_page(permissions=['microphone'])
    page.add_init_script('''window.receivedAudio=[];window.audioBytes=0;
    const Original=window.RTCPeerConnection;
    window.RTCPeerConnection=class extends Original {constructor(config){super(config);this.addEventListener('track',e=>{if(e.track.kind!=='audio')return;let recorder=new MediaRecorder(new MediaStream([e.track]));recorder.ondataavailable=async ev=>{window.audioBytes+=ev.data.size;let a=new Uint8Array(await ev.data.arrayBuffer());let s='';for(let i=0;i<a.length;i++)s+=String.fromCharCode(a[i]);window.receivedAudio.push(btoa(s));};recorder.start(1000);});}};''')
    page.goto('http://127.0.0.1:13010/auth/login')
    credentials=json.loads(Path.home().joinpath('.local/share/silo-livestock/dograh/account.json').read_text())
    page.get_by_label('Email',exact=True).fill(credentials['email']);page.get_by_label('Password',exact=True).fill(credentials['password']);page.get_by_role('button',name='Sign in',exact=True).click();page.wait_for_timeout(2500)
    page.goto('http://127.0.0.1:13010/workflow/1');page.wait_for_timeout(3000)
    if page.get_by_role('button',name='Close',exact=True).count():page.get_by_role('button',name='Close',exact=True).click()
    page.get_by_role('button',name='Run Test',exact=True).click()
    samples=[]
    for seconds in [20,40,60,80]:
        page.wait_for_timeout(20000)
        body=page.locator('body').inner_text();samples.append({'seconds':seconds,'body':body,'received_audio_bytes':page.evaluate('window.audioBytes')})
        print(json.dumps({'seconds':seconds,'body_tail':body[-1600:],'audio_bytes':samples[-1]['received_audio_bytes']}),flush=True)
    page.screenshot(path=str(OUT/'call.png'),full_page=True)
    (OUT/'ui.json').write_text(json.dumps(samples,indent=2))
    chunks=page.evaluate('window.receivedAudio');(OUT/'received.webm').write_bytes(b''.join(base64.b64decode(s) for s in chunks))
    browser.close()
