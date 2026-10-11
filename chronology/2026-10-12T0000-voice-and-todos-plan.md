# Voice in, read aloud, and todos (plan and first measurements)

The request: talk to the bot in English by voice, have replies read aloud in a human-sounding
voice, and keep a personal todo list by voice. Examples:
- "add to my todos: update the Swades funds tracker";
- "I already did 1 2";
- "send me a reminder at 6", which means 6 pm IST;
- a morning message listing open todos.

**Speech runs on the CPU, on purpose.** The GB10's memory pool is shared with Muse and
other projects (`../GPU_COORDINATION.md`: two hard freezes from uncapped GPU jobs). Both
models are small enough for the 20 ARM cores, and nothing leaves the box.

- **Listening:** Whisper large-v3-turbo through faster-whisper, int8, 8 threads. 17 s of speech
  transcribes in about 5 s; loading takes 2.4 s once cached.
  - Ordinary words come out right. Proper nouns don't: "Swades" became "SWADS" or "SWAD's", and
    "Gadchiroli" became "GADKai Rally".
  - Plan: prime Whisper with the user's open todos and a glossary file.
  - faster-whisper's own audio decoding fails with the installed PyAV (the `metadata_errors`
    argument), so audio is decoded with ffmpeg instead.
- **Speaking:** Kokoro v1.0 (82M) through kokoro-onnx. 17 s of speech is made in 2.8 s,
  about 6× faster than real time, and the model loads in 0.6 s. Its 54 voices include
  American, British and "Hindi" English voices. Six samples were sent to the user's chat to choose from.
- **Models** live in `/mnt/seagate/models/{kokoro,whisper}`.

**Todos plan.**
- Storage: SQLite on the box, per Telegram user.
- Understanding: one local Muse call with tools (add, complete by number or by description,
  edit, delete, remind at, daily time). The bot executes the calls and writes the
  confirmation itself, so the list you see is always the stored list, not the model's prose.
- Reminders: a background thread sends a morning list (default 09:00 IST) and one-off reminders.
- Routing: messages that aren't about todos go on to Codex and the checker as before.
