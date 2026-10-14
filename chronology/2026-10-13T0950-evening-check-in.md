# Morning list at 9, evening check-in at 5, todos carry over

**Asked:** a todo update automatically every morning at 9 and every evening at 5, with todos
carrying over. "Remind me to do X by 4" should still remind at 4, on top of the 9 and 5.

**Built (`todos.py`):**
- `users.evening` (default `TODO_EVENING`, 17:00) and `users.last_evening`, added by
  migration. Existing users get their first check-in today at 5.
- `due_messages()`:
  - **Evening check-in:** "🌇 Evening check-in. Done today: N (…)", then "Still open,
    carried over to tomorrow:" with the list. It's sent only if todos are open.
  - **Morning list:** unchanged. If the box was down until after the evening time, the
    morning list is skipped, so the two don't arrive together.
- **Carry-over:** open todos already stayed until done or removed. The messages now say so.
- `touch_user()`: a new user's first check-in waits for tomorrow if today's time has passed,
  the same as the morning list.
- `set_daily_time` takes `which: morning | evening`. The sort's prompt says the two come by
  themselves and reminders are extra.
- `direct.py`'s about-Silo help, the deployment doc and the v1 narrative are updated.

**Tested:**
- With a fake clock and a scratch DB:
  - 08:59: nothing.
  - 09:00: the morning list.
  - 16:00: the one-off reminder.
  - 17:00: "Done today: 1 (Call Shankar)" and 2 carried over.
  - 17:01: nothing.
  - Next day 09:00: the morning list again.
- Against the live model, on a scratch DB:
  - "Remind me to send the budget to Meera by 4": `remind_at` 16:00, also added as a todo.
  - "Send my evening check-in at 6 instead": `set_daily_time` 18:00, evening.
