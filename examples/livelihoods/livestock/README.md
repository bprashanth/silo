# Livestock helpline examples

Two ways to handle a farmer's call about a sick animal, with one hub page:

| example | what | ports |
|---|---|---|
| [`call_center_assist/`](call_center_assist/) | A paravet takes the call. The agent listens, fills the care record, confirms what the paravet repeats back, and opens protocol cards for urgent cases. Practice caller: Lakshmamma, a live AI farmer. | :8776 (and the agent-led call, :8775) |
| [`full_call_center/`](full_call_center/) | The whole workflow over Telegram (Buffalo Soldiers bot): intake, case desk, vet assignment, visit report, feedback. | case desk :8766, Fizzy :8767 |

```sh
examples/livelihoods/livestock/run.sh            # hub on :8770 with one card per example
examples/livelihoods/livestock/run.sh --dry-run  # what it would do
examples/livelihoods/livestock/run.sh --no-bot   # hub and assist only
examples/livelihoods/livestock/run.sh status
examples/livelihoods/livestock/run.sh stop       # hub, assist, bot; the case desk and Fizzy stay up
```

`run.sh start` does the following:
- **Assist.** Starts the assist, or restarts it if it is running from another checkout. It refuses to touch
  :8776 if a process it didn't start holds the port.
- **Case desk.** Starts the case desk only if it is down.
- **Bot.** Always restarts the Buffalo bot from this checkout, through `full_call_center/bot.sh` (the
  `silo-buffalo` user service). Any stray bot process outside that service is stopped by PID first, so only
  one bot polls the token.

It checks local Muse (:8181) but never starts it. It checks that the secret files exist
(`~/.config/idlisseus/{telegram,openrouter}.json`, `~/.config/livestock/allowed.txt`) and never reads them.

Hub: `http://127.0.0.1:8770`; over the tailnet, `http://100.82.28.38:8770`. The cards link to the same host,
so they work from either address.

Narratives: [call center assist](../../../narrative/call_center_assist.md),
[call center automation](../../../narrative/call_center_automation.md).
