"""Regressions from the user's own browser calls on 2026-10-16 (07:05-07:16 IST). No models needed.

  python -m pytest tests/test_live_calls.py -q
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import nlu
from intake import Intake, CALLER_ID

def llm(d, heard, asking, prev=None, backend='muse'):
    """What interpret() does after the LLM answers, without calling one."""
    out = nlu._from_llm(d, heard); out.setdefault('unsure', {})
    if asking == 'animal_type' and 'animal_type' not in out['facts'] and 'animal_type' not in out['unsure']:
        a, sure = nlu.snap_animal(heard)
        if a: (out['facts'] if sure else out['unsure'])['animal_type'] = a
    if asking in (None, 'symptoms') and not out['facts'].get('symptoms') and out['intent'] in ('answer', 'correction'):
        c = nlu.complaint(heard)
        if c and not nlu.GENERIC_SYMPTOM.match(c) and not nlu.snap_animal(c)[1]: out['facts']['symptoms'] = [c]
    return nlu._guard(out, heard, asking, prev, backend)

def say(i, out, heard):
    return i.next_turn(out, i.update(out, heard))

def test_misheard_bullock_is_read_back_not_stored():
    # "Bullock" was heard as "Ballroo." and the agent asked "What problem are you seeing in the ballroo?"
    i = Intake(); i.asking = 'animal_type'
    r = say(i, llm({'intent': 'answer', 'animal_type': 'ballroo'}, 'Ballroo.', 'animal_type'), 'Ballroo.')
    assert i.slots['animal_type'].value is None and r['asking'] == 'check' and r['text'] == 'Did you say a bull?'
    r = say(i, llm({'intent': 'no'}, 'No, bullock.', i.topic), 'No, bullock.')
    assert i.slots['animal_type'].value == 'bullock' and r['asking'] != 'check'

def test_doubtful_animal_yes_fills():
    i = Intake(); i.asking = 'animal_type'
    say(i, llm({'intent': 'answer'}, 'The ball rolls.', 'animal_type'), 'The ball rolls.')
    assert i.asking == 'check'
    say(i, llm({'intent': 'yes'}, 'Yes.', i.topic), 'Yes.')
    assert i.slots['animal_type'].value == 'bull'

def test_kannada_animal_words():
    assert nlu.snap_animal('emme') == ('buffalo', True) and nlu.snap_animal('nanna hasu') == ('cow', True)
    assert nlu.snap_animal('Something else.') == (None, False)

def test_ten_animals_is_confirmed():
    # "One" was heard as "Ten." and the summary said "Ten ballroos".
    i = Intake(); i.slots['animal_type'].value = 'cow'; i.slots['animal_type'].state = 'filled'; i.asking = 'animals_affected'
    r = say(i, {'intent': 'answer', 'facts': {'animals_affected': 10}}, 'Ten.')
    assert r['text'] == 'Ten animals, is that right?' and i.slots['animals_affected'].value is None
    r = say(i, {'intent': 'no', 'facts': {}}, 'No, one.')
    assert r['asking'] == 'animals_affected'
    say(i, {'intent': 'answer', 'facts': {'animals_affected': 1}}, 'One.')
    assert i.slots['animals_affected'].value == 1

def test_not_lying_down_does_not_mean_it_can_stand():
    out = llm({'intent': 'answer', 'can_stand': True}, "Hi, uh it's not lying down.", None)
    assert 'can_stand' not in out['facts'] and out['facts']['symptoms'] == ['not lying down']

def test_something_else_is_not_a_symptom():
    out = llm({'intent': 'answer', 'symptoms': ['something else']}, 'Something else.', 'symptoms')
    assert 'symptoms' not in out['facts']

def test_restarted_number_after_no_no():
    # "Eight, nine, seven, six, three." then "No, no. One, eight, nine, seven, six, three, five, two." became 13 digits.
    i = Intake(); i.slots['animal_type'].value = 'cow'; i.slots['animal_type'].state = 'filled'; i.asking = 'contact_details'
    say(i, {'intent': 'answer', 'facts': {}}, 'Eight, nine, seven, six, three.')
    assert i.partial_phone == '89763'
    r = say(i, {'intent': 'correction', 'facts': {}}, 'No, no. One, eight, nine, seven, six, three, five, two.')
    assert i.partial_phone == '18976352' and r['text'].endswith('Go on.')

def test_this_phone_number_uses_caller_id():
    i = Intake(); i.slots['animal_type'].value = 'cow'; i.slots['animal_type'].state = 'filled'; i.asking = 'contact_details'
    r = say(i, {'intent': 'answer', 'facts': {}}, 'This phone number.')
    assert i.slots['contact_details'].value == CALLER_ID and r['asking'] != 'confirm_phone'
    assert 'same number' in r['text']

def test_audio_model_cannot_invent_a_district_while_asked_the_animal():
    out = llm({'intent': 'answer', 'district': 'Ballari'}, 'Ballari.', 'animal_type', backend='audio:google/gemini-3.5-flash-lite')
    assert 'district' not in out['facts']

def test_missing_phone_is_said_in_summary():
    i = Intake()
    for s in i.slots.values(): s.state, s.value = 'filled', 'x'
    i.slots['animals_affected'].value = 1; i.slots['symptoms'].value = ['fever']
    i.slots['contact_details'].state, i.slots['contact_details'].value = 'unclear', None
    assert 'could not get your phone number' in i.summary()
