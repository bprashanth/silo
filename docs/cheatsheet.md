# Cheatsheet

The main idli cli operations are summarized as follows 
1. Sync 
2. List
3. Search 
4. Inspect (Summarize/explain)
5. Ask

The cli is strcutured as `idli [verb] [resource] [REFERENCE] [FLAGS]` 
so for example: 
* `idli list messages` (verb, resource)
* `idli get message message-id` (verb, resource, ref)
* `idli summarise messages --in "group name'` (verb, resource, flag)

Sync 
```
idli sync drive --in "folder name" -v 
idli sync whatsapp --in "group name" --in "another group name" -v 
idli sync {gmail, gcalendar...}
```

List 

```
idli size 
idli list files --search "some words that will be OR'd" #"any of"
idli list files --search "'some words that will be AND'd'" # "exact phrase"
idli list chats # a chat is a group or individual
idli list messages --in "group name" --where "links <> ''" # sql query: where links are not null
```

Inspect 
```
idli summarise --search "some terms" # matches on terms, summarizes
idli summarise messages --in "group name" --search "some terms" # eg: summarize latest thinking on abc event from xyz group
idli get file "name" --outline 
```

Ask - this will be the most use cli command as it wraps many of the others into a llm planning call
```
idli ask -v "how many leads.. ?"
idli ask -vvv "there was something that ..."
idli ask --new "there was something that..." # starts a new history 
```

## Debugging 

* Run with `-v` or `-vv`
* See [cli.md](cli.md) and [cli.agent.md](cli.agent.md) for more commands (or just learn by looking at the output of `-vv`. 
* Inspect <sandbox>/log.jsonl 
* Ask about unknown groups or out-of-window dates like July 2026. 
