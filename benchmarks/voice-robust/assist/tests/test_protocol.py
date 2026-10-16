"""Protocol cards, no models:  python -m pytest assist/tests/test_protocol.py -q"""
import sys
from pathlib import Path
HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE.parent)); sys.path.insert(0, str(HERE))
import protocol

def rec(**k): return {'can_stand': None, 'breathing_ok': None, 'animals_affected': None, 'urgent_warning_signs': [], **k}

def test_cards_open_from_farmer_words_not_operator_questions():
    p = protocol.Protocol()
    assert p.see('Any sores in the mouth? Did they eat anything?', 'operator') == []
    assert p.see('My goats are shaking, they ate young jowar in the neighbour field.', 'farmer') == ['poisoning']
    assert set(p.see('One small one died this morning, and the new goats I bought at the santhe', 'farmer')) == {'sudden_death', 'spreading'}
    assert 'ate_what' in p.fields and 'new_animals' in p.fields

def test_operator_statement_opens_a_card():
    p = protocol.Protocol(); assert p.see('Okay, lumps all over the body. Which village?', 'operator') == ['skin_lumps']

def test_level_follows_rules_on_the_answers():
    p = protocol.Protocol(); p.see('they ate jowar sprouts', 'farmer')
    assert p.level(rec()) == 'D'
    assert p.level(rec(breathing_ok=False)) == 'E'
    p2 = protocol.Protocol(); p2.see('loose motions, bedi', 'farmer')
    assert p2.level(rec()) == 'C'
    p2.fields['blood_in_dung'].farmer = True
    assert p2.level(rec()) == 'D'

def test_lines_said_escalation_and_qa():
    p = protocol.Protocol(); p.see('my goat is trying to give birth, one leg showing', 'farmer')
    t = [{'role': 'operator', 'text': 'Please do not pull. I am connecting the vet now.'},
         {'role': 'operator', 'text': 'If it gets worse, call us again. Goodbye.'}]
    v = p.view(rec(), t)
    assert v['level'] == 'E' and v['escalated'] and v['cards'][0]['say'][0]['said'] and v['closing']['said']
    qa = {q['check']: q['ok'] for q in p.qa(rec(), t)}
    assert qa['Difficult birth: read the advice lines'] and not qa['Difficult birth: key questions answered (0/3)']
    assert qa['Did not name a disease to the farmer']
    assert not {q['check']: q['ok'] for q in p.qa(rec(), t + [{'role': 'operator', 'text': 'This looks like PPR.'}])}['Did not name a disease to the farmer']

def test_no_card_no_view():
    assert protocol.Protocol().view(rec(), []) is None

def test_handoff_names_the_reference():
    p = protocol.Protocol(); p.see('lumps all over her skin', 'farmer'); p.fields['milk_drop'].farmer = 'one litre, was four'
    h = p.handoff(rec(), [])
    assert h['cards'][0]['answers'] == {'Milk now vs before': 'one litre, was four'} and 'DAHD' in h['cards'][0]['reference']

def test_only_asked_fields_are_fillable():
    p = protocol.Protocol(); opened = p.see('they ate young jowar', 'farmer')
    assert p.fillable('farmer', 'Which animal?', opened, 'they ate young jowar') == ['ate_what']  # her words opened the card, and are about what they ate
    assert set(p.fillable('farmer', 'How long ago did they eat it?')) == {'ate_what', 'ate_when'}
    assert p.fillable('farmer', 'What is your name?') == []
    assert p.fillable('operator', '', text='Jowar, okay.') == []   # nothing from the farmer yet: the operator can't fill it alone
    p.fields['ate_what'].farmer = 'young jowar'
    assert p.fillable('operator', '', text='Young jowar, okay.') == ['ate_what']
    assert p.fillable('operator', '', text='How long ago did they eat it?') == []
    q = protocol.Protocol(); op = q.see('two of them are coughing', 'farmer')
    assert q.fillable('farmer', 'Is the breathing normal?', op, 'two of them are coughing') == []

def test_breathing_fast_alone_does_not_open_the_cough_card():
    assert 'breathing_young' not in protocol.Protocol().see('They are breathing so fast.', 'farmer')

def test_values_need_evidence_in_the_words():
    m = {'type': 'string'}
    assert not protocol.evidence(m, 'No', 'No, nothing. I am waiting for you.', None)
    assert not protocol.evidence(m, 'If it gets worse call us again', 'Did they eat?', None)
    assert protocol.evidence(m, 'young jowar sprouts', 'They ate young jowar sprouts from the neighbour field', None)
    assert not protocol.evidence({'type': 'string'}, 'Four goats', 'How old are they?', None) and not protocol.evidence({'type': 'integer'}, 4, 'Only three standing', None)
    assert protocol.evidence({'type': 'boolean'}, False, 'No blood', 'Any blood?') and not protocol.evidence({'type': 'boolean'}, False, 'No', None)
