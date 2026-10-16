# Buffalo English trial

Switched only the livestock adapter to English: Whisper language en, unlocalized English engine replies, English menu/greetings/errors, and Kokoro af_heart with en-us. af_alpha is absent from the installed voice pack; af_heart was verified available. Hindi engine helpers remain for later use. The dashboard connection instructions and public config reflect English.

Restarted Buffalo and the case API. Original io bot and existing case data are untouched. Runtime reports language=en with one permitted account. Existing unfinished intake is retained; the previously diagnosed extraction/clarification loop is not fixed by this language change.

Twenty-six regression tests pass. Actual Kokoro output was synthesized and recognized by Whisper as “What symptoms have you noticed? You can send a voice note in English.” Audio is stored on Seagate under livestock-v2/buffalo-tests/english-switch/reply.ogg. No test message was sent into the user's active case.
