# Todos: several steps in one message

**Reported:** a 28-second voice note: "scrap that to-do list… new to-dos… remind me at round 4
today. One is the form stuff… Shankar. Two is Inside Out… Three is the game for the summit."
The bot removed the three old todos but added nothing and set no reminder.

**Cause:** the model made only one tool call (`delete_todos [1,2,3]`). Replaying it twice
with `parallel_tool_calls` false and twice with it true gave the same single call every time.
Muse is trained to make a call, see its result, then decide the next one. The old code took
the first reply's calls as the whole plan. The earlier "several calls in one message work"
was wrong; the 9/9 phrase test had no multi-step message.

**Fix (`todos.py`):**
- `handle()` loops for up to `MAX_TURNS` = 5 turns.
- Each todo call is carried out by `run_call()`. Its result lines and the new numbered list
  go back to the model as a `tool` message: "If the message asked for anything else, make
  the next call; otherwise reply 'done'". Then the model is called again with
  `tool_choice="auto"`.
- The loop stops when the model makes no todo call.
- `rows` is refreshed after each turn, so numbers always refer to the list the model was
  just shown.
- The audit record lists every call that was carried out.

**Replayed against a scratch DB (`SILO_DB` in the scratchpad), not the user's:**
- The failing message: delete, add 3, then a 4 pm reminder. That's right, and took 21.7 s
  over 4 turns.
- "Add call the Swades Foundation…": add, 4.4 s.
- "I already did 1 and 3": complete, the right two, 7.0 s.
- "Add buy printer ink and remind me at 6 about it": add, then remind, with no duplicate
  todo, 10.5 s.
- "What are my todos?": show, 4.4 s.

Each single-step message now pays for one extra model turn, about 2–3 s, which returns no call.

**The user's real list:** the old three are deleted and the new three were never added.
I left it for the user to resend rather than writing their todos myself.
