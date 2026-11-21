# DB

## Terminology 

* View: is a database view (context: MVC). 
    - materialied view: build/deleted with a specific action, like opening / deleting a mini. In other words, it's a saved result with an owner. 
* Definition: is the definition of a rule used to make a judgement. 
* Workflow: is a chaining of `idli` commands that my contain transformation scripts inbetween. 

## Principles 

1. Each sandbox gets a db
2. Each article (eg: each mail in gmail, each appt in caldendar, each message in whatsapp) is a row with a column indicating things like the owner (which chat for example, or which group or which channel). 
3. Minis are allowed to define new tables they own. New tables reference existing records using an id (eg `file_id). Opening the mini rebuilds it, deleting the mini removes it. 

## What makes something a workflow vs judgement vs just a view? 

Eg: "Emails from everyone I've declined meetings with": "everyone I declined meetings with"
isn't a column in the sandbox db. The mapper (9b) has to decide what it means. Is it: 
a. The organiser? 
b. The guests? 
c. Events whose title matches an email subject? 

It can end up picking a different one each time. 

A view is how a sandbox picks up your vocabulary one word at a time. 

1. When the mapper has to supply a meaning, it states it in plain words with the answer: "I
took 'people you declined' as the guests of meetings where your response was Declined."
2. You say yes, or correct it.
3. On yes, that meaning is saved as a view named `declined_with`. From then on the question is
just list `declined_with`, with the same meaning every time.

In this case, the unknown (`declined`) is computable from available rows without looking at content. It doesn't need to open the emails and understand them. So it's a view. 

## Definitions/Judgements 

Say you just want to ask "show me all documents on economics". Economics isn't a column in the database, just like with the view.. but in this case the model has to actually open the docs, i.e. read the content of the rows of the db; so it's a definition + options + judgement. 

More realistic definitions/judgements are "which emails ask me for money", "emails where someone sounds unhappy", "photos with people in them". 

## View vs definition

|---------------------------------------------------------------------------------------|
|            |           Definition           |                  View                   |
|------------|--------------------------------|-----------------------------------------|
| Written as | an English question with fixed | a rule over the data (SQL)              |
|            |  answers                       |                                         |
|------------|--------------------------------|-----------------------------------------|
| Worked out | the 9B, row by row (slow and   | DuckDB                                  |
|  by        | fuzzy; saved as labels)        |                                         |
|------------|--------------------------------|-----------------------------------------|
| Example    | "Is this about economics?      | "declined_with = guests of events where |
|            | yes/no"                        |  my_response = declined"                |
|---------------------------------------------------------------------------------------|

Both these get a human judgement card, eg: 

- "I'll take 'declined with' to mean: guests of meetings you declined. Keep this?"
- "I'll take 'economics' to mean: documents the 9B reads and calls economics. That's about 
120 documents, about 2 minutes. Go ahead?"

## What turns into a table/row? 

* 1 spreadsheet -> 1 table, each row is a row in this table. Duckdb handles this easily. 
* All documents share one table. Each page in a doc is a row, so we can reference the right page during `--search`. 

