"""Operator-assist logic, no models:  python -m pytest assist/tests/test_assist.py -q"""
import sys, json
from pathlib import Path
HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE.parent)); sys.path.insert(0, str(HERE))
import assist, farmer

SC = json.loads((HERE / 'scenarios.json').read_text())[0]

def test_question_is_the_last_sentence():
    assert assist.asked_slot('Kunigal, right? And which district?') == 'district'
    assert assist.asked_slot('She cannot stand okay, that is serious. Is she breathing normally?') == 'breathing_ok'
    assert assist.asked_slot('Let me read it back. One buffalo, phone nine eight. Is that correct?') == 'summary'

def test_operator_repeat_confirms_farmer_value():
    a = assist.Assist()
    a.on_farmer('Buffalo madam', {'facts': {'animal_type': 'buffalo'}})
    assert a.fields['animal_type'].state == 'heard_only' and a.suggestions()['next']['kind'] == 'repeat'
    a.on_operator('Buffalo, okay. What problem?', {'facts': {'animal_type': 'buffalo'}, 'asking': 'symptoms'})
    assert a.fields['animal_type'].state == 'confirmed'

def test_line_and_operator_disagree_is_flagged():
    a = assist.Assist()
    a.on_farmer('Hassan', {'facts': {'village': 'Hassan'}})
    a.on_operator('Hosahalli, right?', {'facts': {'village': 'Hosahalli'}, 'asking': None})
    assert a.fields['village'].state == 'operator_differs' and a.fields['village'].value == 'Hosahalli'
    assert any('the line heard' in x['text'] for x in a.suggestions()['alerts'])

def test_bad_read_back_does_not_replace_good_number():
    a = assist.Assist()
    a.on_farmer('nine eight four five six seven two three one zero', {'facts': {'contact_details': '9845672310'}})
    a.on_operator('phone nine eight four five six six seven two three one zero', {'facts': {'contact_details': '98456672310'}})
    assert a.fields['contact_details'].value == '9845672310'
    assert any('11 digits' in x['text'] for x in a.suggestions()['alerts'])

def test_urgent_moves_village_and_phone_up():
    a = assist.Assist(); a.on_farmer('she cannot stand', {'facts': {'animal_type': 'buffalo', 'symptoms': ['not getting up'], 'can_stand': False}})
    for k in ('animal_type', 'symptoms', 'can_stand'): a.fields[k].operator = a.fields[k].farmer
    a.fields['breathing_ok'].operator = False
    h = a.suggestions(); assert h['alerts'][0]['level'] == 'urgent' and h['next']['slot'] == 'village'

def test_gazetteer_candidates_for_unknown_place():
    a = assist.Assist(); a.on_operator('Hosali, right?', {'facts': {'village': 'Hosali'}})
    assert any('Hosahalli' in x['text'] for x in a.suggestions()['alerts'])

def test_breathing_fast_read_back():
    assert assist.operator_rules('Breathing fast, I am marking this urgent.')['breathing_ok'] is False

def test_scripted_farmer_corrects_a_wrong_read_back_and_undo():
    f = farmer.ScriptedFarmer(SC)
    assert f.reply('greeting', {}, 'Namaste') == 'opening'
    assert f.reply(None, {'village': 'Hassan'}, 'Hassan, right?') == 'no_village'
    assert f.reply('village', {}) == 'village'
    f.undo(); assert f.reply('village', {}) == 'village'  # undone: still the first answer
    assert f.reply('village', {}) == 'village_again'

def test_late_repeat_still_confirms():
    """The operator asks other things first and only later says "I have noted the goat problem": that confirms the animal."""
    a = assist.Assist()
    a.on_farmer('My goats are not well', {'facts': {'animal_type': 'goat'}})
    a.on_operator('How old was the small one?', {'facts': {}, 'asking': 'other'})
    a.on_farmer('Two months', {'facts': {}})
    a.on_operator('How many are sick now?', {'facts': {}, 'asking': 'animals_affected'})
    assert a.fields['animal_type'].state == 'heard_only'
    a.on_operator('Okay, I have noted the goat problem. What is your name?', {'facts': {'animal_type': 'goat'}, 'asking': 'caller_name'})
    assert a.fields['animal_type'].state == 'confirmed'
    assert assist.operator_rules('Okay, I have noted the goat problem.')['animal_type'] == 'goat'

def test_cases_have_what_the_live_farmer_needs():
    import farmer_ai
    persona, cases = farmer_ai.load()
    assert persona['name'] == 'Lakshmamma' and len(cases) >= 5
    for c in cases.values():
        assert c['opening'] and c['story'] and c['reveal_only_if_asked'] and c['source']
        assert set(c['truth']) == set(assist.REQUIRED), c['id']

def test_operator_facts_come_from_operator_words():
    """Live role-play: Muse credited the farmer's "since yesterday" to the operator's "Which village?"."""
    assert assist.said_by_operator({'symptoms_since': 'yesterday', 'caller_name': 'Lakshmamma'}, 'Which village?') == {}
    kept = assist.said_by_operator({'animal_type': 'goat', 'animals_affected': 5, 'symptoms': ['fever', 'cough'], 'symptoms_since': 'four days'},
                                   'Five goats, fever, and loose motions since four days?')
    assert kept == {'animal_type': 'goat', 'animals_affected': 5, 'symptoms': ['fever'], 'symptoms_since': 'four days'}
    assert assist.said_by_operator({'village': 'Ramanagara', 'district': 'Ramanagara'}, 'Lakshmema from Hasahali, Ramanagara District.') == {'district': 'Ramanagara'}
    assert assist.said_by_operator({'contact_details': '9900123456'}, '99001-23456') == {'contact_details': '9900123456'}

def test_symptoms_in_other_words_merge_not_differ():
    a = assist.Assist()
    a.on_farmer('very hot ears and body', {'facts': {'symptoms': ['hot ears and body']}})
    a.on_operator('Fever and loose motions, okay.', {'facts': {'symptoms': ['fever', 'loose motions']}})
    f = a.fields['symptoms']
    assert f.state == 'operator' and f.value == ['fever', 'loose motions', 'hot ears and body']

def test_qa_without_a_phone_number():
    assert {q['check']: q['ok'] for q in assist.Assist().qa()}['Read the phone number back'] is False
