"""Visual interaction checks with synthetic UI state; real WebRTC is covered by browser_assist.py."""
import json,sys
from pathlib import Path
from playwright.sync_api import sync_playwright
HERE=Path(__file__).resolve().parent.parent
sys.path[:0]=[str(HERE),str(HERE.parent)]
from protocol import Protocol
from assist import Assist
OUT=Path('/mnt/seagate/silo/voice-robust/ui-single-screen-20261017/layout');OUT.mkdir(parents=True,exist_ok=True)
record=Assist();record.fields['animal_type'].farmer='goat';record.fields['symptoms'].farmer=['weak','loose motions']
protocol=Protocol()
lines=['One goat died this morning. Some have sores.', 'They ate young jowar.', 'Two young goats are coughing.', 'One has loose motions and a swollen belly.', 'Another goat is straining to give birth.']
for line in lines:protocol.see(line,'farmer')
state={'id':'synthetic-layout','status':'on call','record':record.record(),'protocol':protocol.view(record.record(),[]),'transcript':[{'role':'operator','text':'Please tell me what happened.'},{'role':'farmer','text':lines[0]},{'role':'operator','text':'I have noted that. What have the others eaten?'},{'role':'farmer','text':lines[1]}]}
with sync_playwright() as p:
 browser=p.chromium.launch();page=browser.new_page(viewport={'width':1366,'height':768});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
 def update(route):
  group=route.request.url.rsplit('/',1)[-1];body=route.request.post_data_json
  protocol.set_cleared(group,body['cleared'],record.record());state['protocol']=protocol.view(record.record(),[])
  route.fulfill(json=state)
 page.route('**/api/sessions/synthetic-layout/advisories/*',update)
 page.goto('http://127.0.0.1:8776');page.wait_for_selector('#case option',state='attached')
 page.evaluate('(s)=>{last=s;sid=s.id;document.querySelector("#call").disabled=true;document.querySelector("#end").disabled=false;render(s)}',state)
 assert page.locator('.advisory').count()==5
 assert page.locator('.advisory-body').count()==1
 for width,height in [(1366,768),(1280,720),(1440,900)]:
  page.set_viewport_size({'width':width,'height':height})
  assert page.evaluate('document.documentElement.scrollHeight <= innerHeight'),(width,height)
  assert page.locator('.advisories').bounding_box()['x'] > page.locator('.care-record').bounding_box()['x']
  for locator in [page.locator('.advisory-heading').nth(i) for i in range(5)]+[page.locator('[data-clear]')]:
   box=locator.bounding_box();assert box['y']>=0 and box['y']+box['height']<=height,(width,height,box)
  assert 'Importance' not in page.locator('#cards').inner_text()
  page.screenshot(path=str(OUT/f'desktop-{width}.png'),full_page=True)
 page.set_viewport_size({'width':1366,'height':768})
 page.screenshot(path=str(OUT/'five-classes.png'),full_page=True)
 page.locator('[data-clear]').click();page.wait_for_function('document.querySelectorAll(".advisory").length===4')
 page.locator('#cleared-panel summary').click();assert page.locator('[data-restore]').count()==1
 page.screenshot(path=str(OUT/'first-cleared.png'),full_page=True)
 page.locator('[data-restore]').click();page.wait_for_function('document.querySelectorAll(".advisory").length===5')
 page.locator('.references summary').click()
 page.evaluate('render(last)')
 assert page.locator('.references[open]').count()==1
 assert page.locator('.references a').first.is_visible()
 page.locator('.references a').first.focus();assert page.locator('.references a').first.evaluate('(a)=>a.href').startswith('https://')
 page.screenshot(path=str(OUT/'sources.png'),full_page=True)
 assert page.locator('#fields').is_visible() and page.locator('#transcript').is_visible()
 left=page.locator('#transcript').bounding_box();right=page.locator('#fields').bounding_box()
 assert left['x']+left['width'] <= right['x']
 page.locator('.advisory-heading').first.focus();page.keyboard.press('Enter')
 assert page.locator('.advisory-body').count()==1
 # Polling must keep selection and scroll position while the operator reads older text.
 page.evaluate('last.transcript=Array.from({length:30},(_,i)=>({role:i%2?"farmer":"operator",text:"Synthetic transcript turn "+i}));render(last);document.querySelector("#transcript").scrollTop=0;last.transcript.push({role:"farmer",text:"A new observation"});render(last)')
 assert page.locator('#transcript').evaluate('(e)=>e.scrollTop')==0
 assert page.locator('#latest').is_visible();page.click('#latest')
 assert page.locator('#transcript').evaluate('(e)=>e.scrollTop')>0
 page.set_viewport_size({'width':390,'height':844})
 assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
 page.screenshot(path=str(OUT/'mobile.png'),full_page=True)
 assert not errors,errors
 (OUT/'result.json').write_text(json.dumps({'synthetic_ui_state':True,'classes':5,'clear_restore':True,'sources_disclosure':True,'dual_panels':True,'keyboard_card':True,'scroll_retained':True,'mobile_overflow':False,'page_errors':errors},indent=2))
 browser.close()
print('Layout checks passed: five classes, clear/restore, sources, keyboard, scroll retention, mobile.')
