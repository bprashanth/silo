import sys,asyncio,json,pathlib,subprocess,wave,io
HERE=pathlib.Path(__file__).resolve()
sys.path[:0]=[str(HERE.parents[1]),str(HERE.parents[3]/'tg-bridge')]
from candidates import OpenRouterAudio
import speech
root=pathlib.Path('/mnt/seagate/silo/livestock-voice/evidence')
async def main():
 history=[]; results=[]
 for i,text in enumerate(['My cow is sick. She has not eaten since yesterday.','Yes, she can stand. My name is Ramesh from Demo village in Demo district.']):
  ogg=speech.synth(text,voice='af_heart',lang='en-us')
  wav=subprocess.run(['ffmpeg','-loglevel','error','-i','pipe:0','-f','wav','-ar','16000','-ac','1','pipe:1'],input=ogg,capture_output=True,check=True).stdout
  (root/f'hosted-input-{i}.wav').write_bytes(wav)
  pcm=b''
  async for e in OpenRouterAudio().stream(wav,history,'You are a fictional livestock intake operator. Never diagnose or prescribe. Ask one short natural question at a time. Collect farmer name, village, district, animal count, symptoms, onset, treatment, warning signs and optional contact. Do not repeat answered questions. Keep each response below 25 words.'):
   if e['type']=='audio':pcm+=e['pcm']
   if e['type']=='done':results.append(e); print(json.dumps(e));history.extend([{'role':'user','content':text},{'role':'assistant','content':e['text']}])
  with wave.open(str(root/f'hosted-output-{i}.wav'),'wb') as f:f.setparams((1,2,24000,0,'NONE','NONE'));f.writeframes(pcm)
 (root/'openrouter-smoke.json').write_text(json.dumps(results,indent=2))
asyncio.run(main())
