# Voice in, read aloud, and todos: live

New code in `tg-bridge/`:
- `speech.py`: Whisper to listen, Kokoro to speak, both on the CPU.
- `todos.py`: SQLite, one local-model call with todo tools, and the morning and reminder loop.

In `tg_bridge.py`:
- Voice notes are transcribed, and the transcript is handled like typed text.
- Todos are tried first; anything else falls through to Codex and the checker.
- A voice note gets a voice reply, and every other reply gets a 🔊 Read aloud button.
- New commands: `/todos`, and `/how` for todo replies.
- `tl_session.py` gained a `voice:` step for testing.

**Todo understanding.** These were run directly against local Muse with reasoning low, taking 1.3–9.4 s per message,
and all were right:
- the long voice-note style "had a meeting… update the funds tracker… add to my todos" → add;
- "also add X and Y" → two adds;
- "what are my todos" → show;
- "I already updated the swades funder tracker" → completed the matching item;
- "I already did 1 2" → completed both;
- "send me a reminder at 6", said at 22:50 → tomorrow 18:00 IST;
- "send me my list at 8 every morning" → daily time 08:00;
- "What was our total spend in Q2?" and "hi, how are you?" → not about todos.

**End to end over Telegram, as the user.** The voice notes were made with Kokoro's `am_michael`
voice so the test used a different voice from the replies:
- each voice note came back with the transcript, the right list change, and a voice reply;
- typed adds worked, and the 🔊 button sent a voice note;
- `/how` showed the chosen tool calls;
- "remind me in 2 minutes to stretch" was confirmed for 22:58 and delivered on time.

The test todos and reminder were removed from the user's list afterwards.

**Fixed along the way:**
- **Names:** Whisper heard "Swades" as "SWAD's". `$SILO_CONFIG/glossary.txt` (Swades Foundation,
  Gadchiroli) plus the open todos are now given to Whisper as hints, and the same clip then came
  back as "Swades".
- **Emoji:** Kokoro read "➕" aloud as "heavy plus sign". Emoji and symbols are now dropped,
  and line ends become pauses.

**Voice.** The default is `af_heart`. Six samples (af_heart, af_bella, bf_emma, am_michael,
bm_george, hf_alpha) were sent to the user to choose from; `TTS_VOICE` changes it.

**Not done:** Indic languages (English only for now); a badge on todo replies (their list is
read back from storage); a confirmation step before marking several items done.
