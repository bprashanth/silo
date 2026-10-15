"""Actual browser/WebRTC synthetic-audio smoke call (requires running server).

python3 tests/browser_audio.py --backend pipecat --output /mnt/seagate/silo/livestock-voice/runs/browser-local
Fixtures travel as audio, are transcribed by the candidate, and responses must contain audio.
"""
import argparse, base64, json, time, subprocess, array, math
from pathlib import Path
from playwright.sync_api import sync_playwright
p=argparse.ArgumentParser();p.add_argument('--url',default='http://127.0.0.1:8765');p.add_argument('--backend',default='pipecat');p.add_argument('--output',required=True);p.add_argument('--headed',action='store_true');p.add_argument('--barge',action='store_true');p.add_argument('--fixtures',default='missing,out_of_order,warning,treatment,confirm');args=p.parse_args()
out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
logs=[]
with sync_playwright() as pw:
 browser=pw.chromium.launch(headless=not args.headed,args=['--autoplay-policy=no-user-gesture-required','--no-sandbox'])
 page=browser.new_page(viewport={'width':1280,'height':1000})
 page.on('console',lambda msg:logs.append({'type':msg.type,'text':msg.text}))
 page.on('pageerror',lambda err:logs.append({'type':'pageerror','text':str(err)}))
 try:
  page.goto(args.url);page.locator('#backend').select_option(args.backend);page.locator('summary').click();page.locator('#fixture-mode').check();page.locator('#call').click()
  page.wait_for_function("document.querySelector('#end').disabled === false",timeout=60000)
  page.wait_for_function("document.querySelector('#remote-audio').srcObject !== null",timeout=60000)
  page.evaluate("""() => {window.testChunks=[];window.testRecorder=new MediaRecorder(document.querySelector('#remote-audio').srcObject);testRecorder.ondataavailable=e=>testChunks.push(e.data);testRecorder.start(250);} """)
  page.wait_for_function("document.querySelectorAll('.turn.agent').length > 0",timeout=60000)
  page.wait_for_timeout(650 if args.barge else 7000)
  observations=[]
  queue=args.fixtures.split(',');adaptations=0
  while queue:
   fixture=queue.pop(0)
   if fixture=='confirm' and adaptations<2 and any(phrase in page.locator('.turn.agent').last.inner_text().lower() for phrase in ['your name','farmer name','caller name']):
    queue.insert(0,'confirm');fixture='name';adaptations+=1
   before=page.locator('.turn.farmer').count();agents=page.locator('.turn.agent').count()
   page.locator('#fixture').select_option(fixture);t=time.monotonic();page.locator('#play-fixture').click()
   page.wait_for_function('(n) => document.querySelectorAll(".turn.farmer").length > n',arg=before,timeout=90000)
   page.wait_for_function('(n) => document.querySelectorAll(".turn.agent:not(.partial)").length > n && document.querySelector(".turn.agent:last-child")?.innerText.length > 10',arg=agents,timeout=90000)
   observations.append({'fixture':fixture,'wall_seconds_to_agent_transcript':time.monotonic()-t,'farmer':page.locator('.turn.farmer').last.inner_text(),'agent':page.locator('.turn.agent').last.inner_text()})
   page.wait_for_timeout(1500)
   page.screenshot(path=str(out/(fixture+'.png')),full_page=True)
   # Do not talk over the agent except in dedicated interruption tests.
   page.wait_for_function('!responsePending && lastRemoteMs > 0 && performance.now()-lastRemoteMs > 1100',timeout=60000)
  audio=page.evaluate("""async()=>{await new Promise(resolve=>{testRecorder.onstop=resolve;testRecorder.stop()});const blob=new Blob(testChunks,{type:'audio/webm'});return await new Promise(resolve=>{const r=new FileReader();r.onload=()=>resolve(r.result.split(',')[1]);r.readAsDataURL(blob);});}""")
  (out/'agent-response.webm').write_bytes(base64.b64decode(audio))
  page.locator('#end').click();page.wait_for_function("document.querySelector('#status').textContent==='Call ended'",timeout=60000)
  page.screenshot(path=str(out/'ended.png'),full_page=True)
  (out/'observations.json').write_text(json.dumps(observations,indent=2))
  # Read visible record via export flow rather than injecting transcript text.
  with page.expect_download() as dl:page.locator('#export-json').click()
  dl.value.save_as(str(out/'record.json'))
  record=json.loads((out/'record.json').read_text());fields=record.get('fields',{})
  decoded=subprocess.run(['ffmpeg','-v','error','-i',str(out/'agent-response.webm'),'-f','f32le','-ac','1','pipe:1'],capture_output=True,check=True).stdout
  samples=array.array('f');samples.frombytes(decoded);rms=math.sqrt(sum(v*v for v in samples)/max(1,len(samples)))
  checks={'received_non_silent_agent_audio':rms>.001,'agent_audio_rms':rms,'all_fixture_utterances_transcribed':len(observations)>=len(args.fixtures.split(',')),'caller_name_captured':bool(fields.get('caller_name')),'animal_cow':fields.get('animal_type')=='cow','urgent_flag':bool(fields.get('urgent_warning_signs')),'confirmed':fields.get('confirmed_by_caller') is True,'missing_fields':fields.get('missing_fields'),'browser_audible_metrics_count':len(record.get('browser_metrics',[]))}
  if {'out_of_order','warning','treatment','confirm'}.issubset(set(args.fixtures.split(','))):
   symptoms=' '.join(fields.get('symptoms',[])).lower();urgent=' '.join(fields.get('urgent_warning_signs',[])).lower()
   exact={'caller_name':fields.get('caller_name')=='Ramesh','village':fields.get('village')=='Demo Village','district':fields.get('district')=='Demo District','animal_type':fields.get('animal_type')=='cow','animals_affected':fields.get('animals_affected')==1,'symptoms':'not eating' in symptoms and 'weak' in symptoms,'symptoms_since':fields.get('symptoms_since')=='yesterday','previous_treatment':str(fields.get('previous_treatment','')).lower() in ['none','no treatment','no previous treatment'],'urgent_warning_signs':'stand' in urgent and 'breath' in urgent,'contact_details':fields.get('contact_details') is None and 'contact_details' in fields.get('unknown_fields',[])}
   checks['expected_fields_exact']=exact;checks['expected_fields_correct_count']=sum(exact.values());checks['expected_fields_total']=len(exact)
  (out/'checks.json').write_text(json.dumps(checks,indent=2))
  assert checks['received_non_silent_agent_audio'], 'No actual agent speech audio received'
  print(json.dumps({'passed':True,'output':str(out),'turns':len(observations)}))
 except Exception as e:
  page.screenshot(path=str(out/'failure.png'),full_page=True)
  (out/'failure.txt').write_text(str(e)+'\n'+page.locator('body').inner_text())
  raise
 finally:
  (out/'console.json').write_text(json.dumps(logs,indent=2));browser.close()
