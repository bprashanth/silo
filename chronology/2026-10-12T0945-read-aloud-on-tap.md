# Read aloud on tap, and a voice picker

**Asked:** read aloud as an optional, manual toggle. Make audio only when it's asked for,
because speaking replies back to back had backed the server up. Then try a few voices.
Later, maybe let the user ask for audio in words ("send me an audio response").

**Built (`tg_bridge.py`):**
- **The button:** `READ_ALOUD` (default on) puts 🔊 Read aloud on every reply, including
  todo replies, `/todos`, and the morning list and reminders. Audio is made only in the
  `say` callback.
  - A second tap within 120 s on the same message gets a toast; that dedupe was already there.
  - New: `speaking`, one read-aloud at a time per chat. A tap while one is being made gets
    "Still making the last one". On failure, the tap is forgotten so it can be retried.
  - Telegram shows "recording voice…" while it's made (`recording`, a subclass of `typing`).
  - Kokoro was already serialized by `speech._klock`.
- **Auto-speak:** `VOICE_REPLIES` now means only speaking every reply to a voice note,
  unasked. It stays off.
- **`/voice`:** a per-chat choice of 7 Kokoro voices: af_heart, af_bella, am_michael,
  bf_emma, bm_george, and the Hindi voices hf_alpha and hm_omega reading English.
  Picking one edits the menu and plays a short sample with a ₹ amount and "Gadchiroli".
  `/reset` clears the choice.

**Tested live:**
- `/todos` showed the button. Two taps produced one voice note; the read-aloud took 2.3 s.
- `/voice`, then Alpha, updated the menu and sent a 9-second sample.
- Not judged yet: how the voices sound. That's for the user.

**Committed before this:** `5b5fff3`. Checked: a clean tree, no keys or tokens in history,
and the largest tracked file is a 772 KB benchmark `.xlsx`.

## Later: Silo is the default voice, and /voice is hidden

- **Default voice:** `hf_alpha` (Kokoro's Hindi voice reading English), named "Silo" in
  `/voice`. Its sample says "Hi, this is Silo". `TTS_VOICE` now defaults to `hf_alpha`.
- **`/voice`:** removed from the command menu and `/start`, but it still works. The menu is
  now todos, files, drive, model, how, reset.
- **Fix:** tapping the voice that's already selected made `editMessageText` fail with
  "message is not modified", which skipped the sample. That error is now ignored.
- **Incident:** restarting the bot for this killed a question the user had just asked by voice
  (04:22, "Tell me about the scaffold conceptually…"); its answer was lost. Restarts drop
  in-flight answers. Check the log for a recent incoming message before restarting.
