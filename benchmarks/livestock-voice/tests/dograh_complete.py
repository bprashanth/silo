"""Native Dograh spoken test: real browser WebRTC, synthetic microphone/audio capture."""
import base64
import json
from pathlib import Path
import wave
import subprocess
from playwright.sync_api import sync_playwright
ROOT=Path('/mnt/seagate/silo/livestock-voice')
OUT=ROOT/'runs/dograh-browser-complete'; OUT.mkdir(parents=True,exist_ok=True)
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
    page.add_init_script("""window.receivedAudio=[];window.audioBytes=0;
    const Original=window.RTCPeerConnection;
    window.RTCPeerConnection=class extends Original {constructor(config){super(config);this.addEventListener('track',e=>{if(e.track.kind!=='audio')return;let recorder=new MediaRecorder(new MediaStream([e.track]));recorder.ondataavailable=async ev=>{window.audioBytes+=ev.data.size;let a=new Uint8Array(await ev.data.arrayBuffer());let s='';for(let i=0;i<a.length;i++)s+=String.fromCharCode(a[i]);window.receivedAudio.push(btoa(s));};recorder.start(1000);});}};
    navigator.mediaDevices.getUserMedia=async()=>{if(!window.mic){window.ctx=new AudioContext();window.mic=ctx.createMediaStreamDestination();await ctx.resume();}return mic.stream;};
    window.injectAudio=async b64=>{await ctx.resume();let bytes=Uint8Array.from(atob(b64),c=>c.charCodeAt(0));let audio=await ctx.decodeAudioData(bytes.buffer);let source=ctx.createBufferSource();source.buffer=audio;source.connect(mic);source.start();return audio.duration;};
    """)
    page.goto('http://127.0.0.1:13010/auth/login')
    credentials=json.loads(Path.home().joinpath('.local/share/silo-livestock/dograh/account.json').read_text())
    page.get_by_label('Email',exact=True).fill(credentials['email']);page.get_by_label('Password',exact=True).fill(credentials['password']);page.get_by_role('button',name='Sign in',exact=True).click();page.wait_for_timeout(2500)
    page.goto('http://127.0.0.1:13010/workflow/1');page.wait_for_timeout(3000)
    if page.get_by_role('button',name='Close',exact=True).count():page.get_by_role('button',name='Close',exact=True).click()
    page.get_by_role('button',name='Run Test',exact=True).click()
    samples=[]
    page.wait_for_timeout(22000)
    for name in ['out_of_order','warning','treatment','confirm']:
        duration=page.evaluate('window.injectAudio',base64.b64encode((ROOT/'fixtures'/(name+'.wav')).read_bytes()).decode())
        page.wait_for_timeout(int(duration*1000)+9000)
        body=page.locator('body').inner_text()
        # Allow a pending native reply to finish before the next farmer turn.
        for _ in range(8):
            if 'speaking...' not in body: break
            page.wait_for_timeout(1000);body=page.locator('body').inner_text()
        samples.append({'fixture':name,'body':body,'received_audio_bytes':page.evaluate('window.audioBytes')})
        print(json.dumps({'fixture':name,'body_tail':body[-2200:],'audio_bytes':samples[-1]['received_audio_bytes']}),flush=True)
    page.wait_for_timeout(8000)
    page.screenshot(path=str(OUT/'call.png'),full_page=True)
    (OUT/'ui.json').write_text(json.dumps(samples,indent=2))
    chunks=page.evaluate('window.receivedAudio');(OUT/'received.webm').write_bytes(b''.join(base64.b64decode(s) for s in chunks))
    browser.close()
