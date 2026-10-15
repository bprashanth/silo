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
    for s in REQUIRED: i.slots[s].state = 'filled'; i.slots[s].value = {'can_stand': True, 'breathing_ok': True, 'animals_affected': 1, 'symptoms': ['fever'], 'contact_details': '9845672310'}.get(s, 'x')
    i.phone_confirmed = True
    r = i.next_turn({'intent': 'answer'}, []); assert r['asking'] == 'summary' and r['text'].endswith('Is that correct?')
    r = turn(i, 'yes correct', 'yes'); assert r['end'] and i.record()['call_status'] == 'completed'

def test_summary_rejections_are_bounded():
    i = Intake()
    for s in REQUIRED: i.slots[s].state = 'filled'; i.slots[s].value = {'animals_affected': 1, 'symptoms': ['fever']}.get(s, 'x')
    i.phone_confirmed = True
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

def test_later_standing_withdraws_urgent_sign():
    i = Intake(); turn(i, 'cow', animal_type='cow'); i.asking = 'can_stand'
    turn(i, 'no', 'no', can_stand=False); assert i.urgent == ['unable to stand']
    turn(i, 'sorry she is standing', 'correction', can_stand=True)
    assert i.urgent == [] and i.record()['urgency'] == 'routine'

def test_phone_is_confirmed_explicitly_and_rejection_reasks():
    i = Intake(); turn(i, 'cow', animal_type='cow'); i.asking = 'contact_details'
    r = turn(i, '9845672310', contact_details='9845672310')
    assert r['asking'] == 'confirm_phone' and r['text'].endswith('Is that number right?')
    r = turn(i, 'no that is wrong', 'no')
    assert r['asking'] == 'contact_details' and i.slots['contact_details'].value is None
    turn(i, '9845672310', contact_details='9845672310'); r = turn(i, 'yes', 'yes')
    assert i.phone_confirmed and r['asking'] != 'confirm_phone'

def test_restarted_number_replaces_partial():
    i = Intake(); turn(i, 'cow', animal_type='cow'); i.asking = 'contact_details'
    turn(i, 'nine eight four five six')
    turn(i, 'nine eight four five six seven two')
    assert i.partial_phone == '9845672'

def test_confirm_phone_yes_even_when_llm_restates_number():
    i = Intake(); turn(i, 'cow', animal_type='cow'); i.asking = 'contact_details'
    turn(i, '9845672310', contact_details='9845672310')
    r = turn(i, 'Yes, that is correct.', 'answer', contact_details='9845672310')
    assert i.phone_confirmed and r['asking'] != 'confirm_phone'

def test_backstop_never_asks_same_thing_three_times():
    i = Intake(); turn(i, 'cow', animal_type='cow'); i.asking = 'contact_details'
    turn(i, '9845672310', contact_details='9845672310')
    asked = [i.asking]
    for _ in range(6):
        r = turn(i, 'hmm', 'unclear'); asked.append(r['asking'])
    run = max(len(list(g)) for _, g in __import__('itertools').groupby(asked))
    assert run <= 3

def test_random_callers_always_finish():
    """Fuzz: whatever a caller says (garbled, contradictory, off-topic), the call ends and never repeats itself 3x."""
    import random, itertools
    rnd = random.Random(0)
    intents = ['answer', 'correction', 'question', 'repeat', 'wait', 'yes', 'no', 'unclear']
    values = {'animal_type': ['cow', 'goat', 'UNKNOWN'], 'animals_affected': [1, 3, 'UNKNOWN'], 'symptoms': [['fever'], ['not eating']],
              'symptoms_since': ['yesterday', 'two days', 'UNKNOWN'], 'previous_treatment': ['none', 'injection'],
              'caller_name': ['Ravi', 'Geeta'], 'village': ['Kunigal', 'Hosahalli'], 'district': ['Tumakuru', 'Mandya'],
              'contact_details': ['9845672310', '98456', '98445672310'], 'can_stand': [True, False], 'breathing_ok': [True, False]}
    for trial in range(2000):
        i = Intake(); asked = []; n = 0
        while i.phase != 'ended' and n < 150:
            intent = rnd.choice(intents); facts = {}
            for k in rnd.sample(list(values), rnd.choice([0, 0, 1, 1, 2])): facts[k] = rnd.choice(values[k])
            if i.asking in values and rnd.random() < .5: facts[i.asking] = rnd.choice(values[i.asking])
            nlu = {'intent': intent, 'facts': facts, 'urgent': [], 'farmer_question': 'q?' if intent == 'question' else None}
            r = i.next_turn(nlu, i.update(nlu, 'nine eight' if rnd.random() < .1 else 'x'))
            asked.append((r['asking'], r['text'])); n += 1
            if i.phase == 'summary' and rnd.random() < .3:
                r = turn(i, 'yes', 'yes'); n += 1
        assert i.phase == 'ended' or n < 150, f'trial {trial} did not finish'
        assert n < 150, f'trial {trial}: {n} turns'
        assert max(len(list(g)) for _, g in itertools.groupby(a for a in asked if a[0])) <= 3, f'trial {trial} repeated itself'
