"""Fictional demonstration routing protocols and roster; not clinical guidance."""
PROTOCOLS = [
 {'id':'DEMO-GENERAL','title':'General livestock illness intake','text':'Collect observations and arrange human veterinary review. No diagnosis or treatment advice.','synthetic':True},
 {'id':'DEMO-WEAKNESS','title':'Fever and weakness escalation','text':'Escalate reported fever or weakness for prompt veterinary assessment.','synthetic':True},
 {'id':'DEMO-URGENT','title':'Animal unable to stand','text':'Inability to stand, severe breathing difficulty or unconsciousness requires urgent human review.','synthetic':True},
 {'id':'DEMO-FOLLOWUP','title':'Follow-up after veterinary visit','text':'Obtain the farmer’s independent account; refer disagreements or continuing need to an operator.','synthetic':True},
]
VETS = [
 {'vet_id':'VET-01','name':'Dr Asha Rao','district':'Demo North','service_area':['Neemgaon','Rampur'],'specialization':'cattle','availability':True,'telegram_user_id':None},
 {'vet_id':'VET-02','name':'Dr Meera Das','district':'Demo North','service_area':['Sonapur','Neemgaon'],'specialization':'emergency livestock','availability':True,'telegram_user_id':None},
 {'vet_id':'VET-03','name':'Dr Ravi Sen','district':'Demo South','service_area':['Lotuspur','Rampur'],'specialization':'cattle','availability':True,'telegram_user_id':None},
 {'vet_id':'VET-04','name':'Dr Nila Shah','district':'Demo South','service_area':['Jasminpur'],'specialization':'small ruminants','availability':False,'telegram_user_id':None},
 {'vet_id':'VET-05','name':'Dr Dev Kumar','district':'Demo East','service_area':['Palashpur'],'specialization':'general livestock','availability':True,'telegram_user_id':None},
]
QUESTIONS = {
 'animal_type':'What animal is unwell?',
 'symptoms':'What symptoms have you noticed?',
 'urgent_warning_signs':'Is the animal unable to stand, struggling to breathe, or unconscious?',
 'symptoms_since':'When did the symptoms begin?',
 'animals_affected':'How many animals are affected?',
 'previous_treatment':'Has the animal received any treatment so far?',
 'farmer_name':'What is your name?',
 'village':'Which village are you in?',
 'district':'Which district is that in?',
}
