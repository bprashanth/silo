"""Hindi text regression; --generate writes synthetic spoken fixtures and ASR evidence."""
import argparse
import json
from pathlib import Path
import time
import unittest
from examples.livelihoods.livestock.full_call_center import speech

FIXTURES = {
    'complaint': 'मेरी गाय कल से बीमार है। वह चारा नहीं खा रही है और कमज़ोर है।',
    'no_warning': 'नहीं। वह खड़ी हो सकती है और साँस सामान्य है।',
    'no': 'नहीं।',
    'one_animal': 'एक गाय बीमार है। अभी कोई इलाज नहीं किया है।',
    'identity': 'मेरा नाम अंजली है। गाँव नीमगाँव है। जिला डेमो नॉर्थ है।',
    'confirmation': 'हाँ, सब सही है।',
    'vet_report': 'मैंने गाय की जाँच की। कोई दवा नहीं दी। दोबारा आने की ज़रूरत नहीं है।',
    'feedback': 'डॉक्टर आए और जाँच की। गाय अब बेहतर है। मैं संतुष्ट हूँ। और मदद नहीं चाहिए।',
}

class HindiSpeechTest(unittest.TestCase):
    def test_devanagari_marks_survive(self):
        text='मेरी गाय बीमार है। साँस सामान्य है। कोई दवा नहीं दी।'
        self.assertEqual(speech.speakable(text), text)
    def test_markup_removed_without_damaging_hindi(self):
        self.assertEqual(speech.speakable('**कौन सा पशु बीमार है?** 🐄'), 'कौन सा पशु बीमार है?')

def generate(output):
    output.mkdir(parents=True, exist_ok=True)
    records=[]
    for name, text in FIXTURES.items():
        start=time.monotonic()
        data=speech.speak(text)
        synth_s=time.monotonic()-start
        path=output/(name+'.ogg'); path.write_bytes(data)
        duration=len(speech._decode(data))/16000
        start=time.monotonic()
        result=speech.transcribe(data, with_quality=True)
        record={'name':name,'input':text,'file':str(path),'duration_s':round(duration,3),
                'synthesis_s':round(synth_s,3),'transcription_s':round(time.monotonic()-start,3), **result}
        records.append(record)
        (output/'evidence.json').write_text(json.dumps({'synthetic':True,'voice':speech.VOICE,'language':'hi','model':speech.WHISPER_MODEL,'fixtures':records},ensure_ascii=False,indent=2))
        print(json.dumps(record,ensure_ascii=False),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--generate',type=Path)
    args,remaining=parser.parse_known_args()
    if args.generate: generate(args.generate)
    else: unittest.main(argv=['test_hindi_speech',*remaining])
