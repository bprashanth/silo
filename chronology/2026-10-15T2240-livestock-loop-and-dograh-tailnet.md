# Livestock follow-up loop and Dograh remote access

Reviewed the latest private human call locally. A short negative warning-sign answer produced an empty list which routing treated as unanswered; unclear onset recognition then returned to warnings. Added question-aware answer states, polarity checks, and same-field clarification. Private caller material was not copied or committed.

Verified 23 unit tests, synthetic audio reproduction before and after, and a full confirmed browser intake with 10/10 semantic fields. Screenshots were inspected and actual received audio checked for non-silence. The first post-fix attempt hit overlapping server restarts; a clean restart and repeated test passed. Audio/screenshots stay on Seagate; small synthetic evidence is in benchmarks/livestock-voice/runs/2026-10-15-question-aware.

Dograh UI now binds all interfaces on 13010 and its API on 18000 with host networking for Tailscale ICE. Database/storage remain loopback. Main app authentication redirect preserves the Tailscale hostname. Tested native spoken exchanges and redirect at 100.82.28.38. Both browser origins require the development secure-origin exception for microphone use over HTTP. No Tailscale Serve/HTTPS configured. Images pinned, Python compiled, compose validated with the existing private environment, and diff whitespace checked.
