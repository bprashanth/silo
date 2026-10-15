
### final-muse

| scenario | line | checks | turns | first sound p50 | reply p50 | fillers | barge-ins | re-prompts | missed |
|---|---|---|---|---|---|---|---|---|---|
| all_at_once | gsm | 12/13 | 12 | 0.35 s | 1.93 s | 2 | 0 | 0 | village |
| correction | gsm | 12/13 | 12 | 0.33 s | 1.71 s | 0 | 0 | 0 | village |
| hesitant_quiet | gsm | 12/13 | 18 | 0.35 s | 1.73 s | 1 | 3 | 2 | village |
| hold_and_ask | gsm | 12/13 | 14 | 0.34 s | 1.95 s | 3 | 0 | 0 | village |
| interrupts | gsm | 12/13 | 13 | 0.35 s | 2.02 s | 2 | 2 | 0 | village |
| minimal | gsm | 12/13 | 14 | 0.37 s | 2.05 s | 5 | 0 | 0 | village |
| noisy_gruff | farm_phone | 11/13 | 16 | 0.37 s | 2.02 s | 1 | 1 | 2 | village, district |
| straightforward | gsm | 12/13 | 12 | 0.36 s | 1.87 s | 2 | 0 | 0 | village |
| unknown_onset | gsm | 12/13 | 13 | 0.35 s | 1.95 s | 1 | 0 | 0 | village |
| urgent | gsm | 12/13 | 13 | 0.35 s | 2.04 s | 1 | 0 | 0 | village |

10 calls, 10 completed and confirmed, 119/130 checks. First sound p50/p90/p95 0.35 / 0.96 / 0.98 s; reply 1.95 / 3.94 / 4.14 s; interpretation p50 1099 ms (p95 2077 ms).

### final-or_deepseek_deepseek-v4-flash

| scenario | line | checks | turns | first sound p50 | reply p50 | fillers | barge-ins | re-prompts | missed |
|---|---|---|---|---|---|---|---|---|---|
| all_at_once | gsm | 12/13 | 7 | 0.35 s | 1.99 s | 1 | 0 | 0 | village |
| correction | gsm | 12/13 | 12 | 0.36 s | 1.84 s | 2 | 0 | 0 | village |
| hesitant_quiet | gsm | 12/13 | 16 | 0.36 s | 1.78 s | 2 | 4 | 2 | village |
| hold_and_ask | gsm | 12/13 | 14 | 0.36 s | 1.88 s | 0 | 0 | 0 | village |
| interrupts | gsm | 12/13 | 12 | 0.35 s | 2.03 s | 3 | 2 | 0 | village |
| minimal | gsm | 12/13 | 14 | 0.35 s | 1.89 s | 2 | 0 | 0 | village |
| noisy_gruff | farm_phone | 12/13 | 11 | 0.35 s | 2.00 s | 1 | 0 | 0 | village |
| straightforward | gsm | 11/13 | 13 | 0.36 s | 1.96 s | 1 | 0 | 0 | village, symptoms_since |
| unknown_onset | gsm | 13/13 | 12 | 0.35 s | 1.79 s | 1 | 0 | 0 | — |
| urgent | gsm | 12/13 | 13 | 0.35 s | 1.70 s | 0 | 0 | 0 | village |

10 calls, 10 completed and confirmed, 120/130 checks. First sound p50/p90/p95 0.35 / 0.93 / 1.00 s; reply 1.93 / 3.37 / 4.15 s; interpretation p50 1068 ms (p95 2285 ms).

### final-audio_google_gemini-3.5-flash-lite

| scenario | line | checks | turns | first sound p50 | reply p50 | fillers | barge-ins | re-prompts | missed |
|---|---|---|---|---|---|---|---|---|---|
| all_at_once | gsm | 13/13 | 7 | 0.35 s | 2.19 s | 2 | 0 | 0 | — |
| correction | gsm | 13/13 | 11 | 0.35 s | 2.19 s | 3 | 0 | 0 | — |
| hesitant_quiet | gsm | 13/13 | 13 | 0.35 s | 3.83 s | 7 | 5 | 2 | — |
| hold_and_ask | gsm | 12/13 | 14 | 0.35 s | 2.89 s | 6 | 0 | 0 | village |
| interrupts | gsm | 13/13 | 11 | 0.35 s | 3.92 s | 8 | 2 | 0 | — |
| minimal | gsm | 12/13 | 12 | 0.36 s | 4.11 s | 7 | 0 | 0 | never_stuck |
| noisy_gruff | farm_phone | 13/13 | 15 | 0.34 s | 2.42 s | 7 | 0 | 3 | — |
| straightforward | gsm | 13/13 | 11 | 0.34 s | 3.93 s | 8 | 0 | 0 | — |
| unknown_onset | gsm | 12/13 | 12 | 0.36 s | 3.47 s | 6 | 0 | 0 | never_stuck |
| urgent | gsm | 13/13 | 12 | 0.35 s | 2.61 s | 5 | 0 | 0 | — |

10 calls, 10 completed and confirmed, 127/130 checks. First sound p50/p90/p95 0.35 / 0.97 / 0.99 s; reply 3.45 / 4.72 / 4.83 s; interpretation p50 1831 ms (p95 2315 ms).
