"""Disable native Dograh's hardcoded public STUN in API and browser bundles.

Small explicit compatibility patch; no changes to speech/conversation pipeline.
Run after container creation, then restart API to reload its Python module.
"""
import subprocess

api_patch = '''from pathlib import Path
p=Path('/app/api/routes/webrtc_signaling.py')
s=p.read_text()
old='[] if FORCE_TURN_RELAY else [RTCIceServer(urls="stun:stun.l.google.com:19302")]'
if old in s:
 p.write_text(s.replace(old, '[]  # livestock benchmark: host-only ICE, no public STUN'))
elif 'stun:stun.l.google.com:19302' in s:
 raise RuntimeError('Dograh API STUN patch needs review')
'''
subprocess.run(['docker','exec','silo-livestock-dograh-api-1','python','-c',api_patch],check=True)
ui_patch = r'''const fs=require('fs');
function walk(d){for(const n of fs.readdirSync(d)){const f=d+'/'+n;
if(fs.statSync(f).isDirectory())walk(f);
else if(f.endsWith('.js')){let s=fs.readFileSync(f,'utf8');
if(s.includes('stun:stun.l.google.com:19302')){
s=s.replace(/\w+\.push\(\{urls:\["stun:stun\.l\.google\.com:19302"\]\}\)/g,'void 0');
if(s.includes('stun:stun.l.google.com:19302'))throw Error('Dograh browser STUN patch needs review');
fs.writeFileSync(f,s);
}}}}
walk('/app/.next/static/chunks');'''
subprocess.run(['docker','exec','silo-livestock-dograh-ui-1','node','-e',ui_patch],check=True)
print('Native API and browser STUN disabled; restart API and reload browser.')
