"""Dialogue-policy guarantees, no models needed:  python -m pytest tests/test_intake.py -q"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from intake import Intake, REQUIRED, MAX_ATTEMPTS

def turn(i, heard, intent='answer', **facts):
    nlu = {'intent': intent, 'facts': facts, 'urgent': [], 'farmer_question': heard if intent == 'question' else None}
    ev = i.update(nlu, heard)
    return i.next_turn(nlu, ev)

def test_species_is_always_asked():
    i = Intake(); r = turn(i, 'she is not eating', symptoms=['not eating'])
    assert r['asking'] == 'animal_type'

def test_no_question_is_asked_forever():
    i = Intake(); asked = []
    for _ in range(40):
        r = turn(i, 'mmm', 'unclear'); asked.append(r['asking'])
        if i.phase != 'collect': break
    assert all(asked.count(s) <= MAX_ATTEMPTS for s in REQUIRED)
    assert i.phase == 'summary'
    assert set(i.record()['unclear_fields']) == set(REQUIRED)

def test_repeated_side_question_cannot_loop():
    i = Intake(); turn(i, 'my cow is not eating', animal_type='cow', symptoms=['not eating'])
    slot = i.asking; asked = 0
    for _ in range(10):
        r = turn(i, 'what medicine should I give?', 'question')
        if r['asking'] != slot: break
        asked += 1
    assert asked <= MAX_ATTEMPTS + 1
    assert 'not a doctor' in i.last_said or i.advised

def test_wait_and_repeat_do_not_cost_attempts():
    i = Intake(); turn(i, 'cow', animal_type='cow'); slot = i.asking; before = i.slots[slot].attempts
    r = turn(i, 'one minute', 'wait'); assert r['hold'] and r['asking'] == slot
    r = turn(i, 'say again?', 'repeat'); assert r['asking'] == slot
    assert i.slots[slot].attempts == before

def test_urgent_reorders_to_location_and_contact():
    i = Intake(); turn(i, 'buffalo lying down', animal_type='buffalo', symptoms=['lying down'])
    r = turn(i, 'no she cannot stand', 'no', can_stand=False)
    assert 'urgent' in r['text'].lower()
    order = []
    while i.phase == 'collect' and len(order) < 20:
        order.append(i.asking); turn(i, 'x', 'unclear')
    assert order.index('village') < order.index('animals_affected')
    assert i.record()['urgency'] == 'urgent'

def test_correction_heard_the_same_again_goes_to_human():
    i = Intake(); turn(i, 'cow', animal_type='cow')
    i.asking = 'village'; turn(i, 'Hassan', village='Hassan')
    r = turn(i, 'no no Hosahalli', 'correction', village='Hassan')
    assert i.slots['village'].state == 'unclear' and 'vet team will confirm' in r['text']

def test_correction_updates_value_and_says_so():
    i = Intake(); turn(i, 'cow three days', animal_type='cow', symptoms_since='three days')
    r = turn(i, 'sorry two days', 'correction', symptoms_since='two days')
    assert i.slots['symptoms_since'].value == 'two days' and r['text'].startswith('Sorry, corrected')

def test_dont_know_is_recorded_not_invented():
    i = Intake(); turn(i, 'cow', animal_type='cow'); i.asking = 'symptoms_since'
    turn(i, "I don't know", symptoms_since='UNKNOWN')
    assert 'symptoms_since' in i.record()['unknown_fields'] and i.record()['symptoms_since'] is None

def test_summary_confirmation_completes():
    i = Intake()
    for s in REQUIRED: i.slots[s].state = 'filled'; i.slots[s].value = {'can_stand': True, 'breathing_ok': True, 'animals_affected': 1, 'symptoms': ['fever']}.get(s, 'x')
    r = i.next_turn({'intent': 'answer'}, []); assert r['asking'] == 'summary' and r['text'].endswith('Is that correct?')
    r = turn(i, 'yes correct', 'yes'); assert r['end'] and i.record()['call_status'] == 'completed'

def test_summary_rejections_are_bounded():
    i = Intake()
    for s in REQUIRED: i.slots[s].state = 'filled'; i.slots[s].value = {'animals_affected': 1, 'symptoms': ['fever']}.get(s, 'x')
    i.next_turn({'intent': 'answer'}, [])
    for _ in range(6):
        r = turn(i, 'no', 'no')
        if r['end']: break
    assert r['end'] and not i.confirmed

def test_phone_number_in_pieces():
    i = Intake(); turn(i, 'cow', animal_type='cow'); i.asking = 'contact_details'
    r = turn(i, 'nine eight four five')
    assert r['asking'] == 'contact_details' and r['text'].endswith('Go on.')
    turn(i, 'six seven two three one zero')
    assert i.slots['contact_details'].value == '9845672310'

def test_spoken_digits():
    from intake import spoken_digits
    assert spoken_digits('nine eight double four 5') == '98445'
    assert spoken_digits('my cow is not eating') == ''

def test_eleven_digit_number_is_not_stored():
    i = Intake(); turn(i, 'cow', animal_type='cow'); i.asking = 'contact_details'
    r = turn(i, 'nine eight four four five six seven two three one zero', contact_details='98445672310')
    assert i.slots['contact_details'].value is None and 'ten digits' in r['text']
    turn(i, '+91 9845672310', contact_details='919845672310')
    assert i.slots['contact_details'].value == '9845672310'
