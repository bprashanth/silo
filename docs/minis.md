# Minis spec 

A mini is a list of steps and each step is an idli command or script. Eg: 
```
idli list calendar --where "my_response='declined'" (cli command chosen by sandbox claude and recorded in the workflow)
- execute a sql view called declined_with (this can be done by an idli command) 
- run a script to parse attendance PDFs (created by sandbox claude before hand) 

idli judge --definition intent 
idli draft ...
```

now lets say out of these you want to ask follow up questions. Things like: "out of the emails in the workflow, tell me which ones have a deadline". That would be 
```
idli definition --name deadline "has a deadline" --options yes/no
idli judge --definition deadline
```

A suggested order of preference inside a Mini:
1. A SQL view. 
2. A script step. For what SQL can't do, eg drawing charts, calling a tool. It should write
 its output as a table, so later steps and the mapper can still query it rather than it
 being a black box.
3. `idli` Judge. Only for meaning.

So in the example above say the script read a PDF. Instead of outputting `X attended a, b and c` it would output a sql table into the duck db store with its own columns. 
