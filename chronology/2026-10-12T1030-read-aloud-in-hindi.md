# Read aloud in Hindi, with /language

**Asked:**
- Can Silo read replies aloud in Hindi with Kokoro, keeping the written reply in English?
- Then: a `/language` command that sets the default, with Hindi as the default for now, and a
  single Read aloud button that speaks in that language.

**Feasibility first:**
- The local Muse translated a sample reply into spoken Hindi in 10.4 s; ₹4,52,300 became
  "चार लाख बावन हज़ार तीन सौ रुपये".
- Kokoro with `lang="hi"` and `hf_alpha` made 20.8 s of audio in 3.3 s.
- The sample was sent to the user.
- The first translation kept some English words in Latin script ("Word", "Week 4",
  "protocols"). The prompt now asks for Devanagari transliteration (प्रोटोकॉल), since
  Kokoro's Hindi mode may misread Latin script.

**Built:**
- `speech.py`: `synth(text, voice, lang)` speaks text that's already been prepared.
  `speak()` = `synth(speakable(text), …, "en-us")`.
- `todos.py`: a `users.language` column. Its default, `READ_ALOUD_LANGUAGE`, is `hi`, and
  existing rows got `hi` too. There are `language()` and `set_language()`, and `/reset`
  removes the row.
- `tg_bridge.py`:
  - `say(chat, text, user_id)` runs `speakable()` on the English, then for Hindi calls
    `to_hindi()` (always the local model, temperature 0, reasoning low) and `synth(…, "hi")`.
  - If the chat's `/voice` pick isn't a Hindi voice, Hindi falls back to `hf_alpha`.
  - The tap toast says "Translating to Hindi and making the audio…".
  - `/language` offers हिंदी (Hindi) or English, and is in the command menu.

**Tested live:** `/language` showed Hindi selected. Tapping 🔊 on `/todos` gave an
11-second Hindi voice note in 14.1 s.

**Not checked:**
- The translation's numbers against the English.
- How well Kokoro pronounces transliterated English terms. That's for the user's ears.
