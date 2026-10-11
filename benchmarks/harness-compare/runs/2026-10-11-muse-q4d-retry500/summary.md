# Harness comparison: 2026-10-11-muse-q4d-retry500

| harness | jobs | correct | wrong | missing | median s | median actions | receipt clean | wrong answers caught by receipt | correct answers flagged | audit flags |
|---|---|---|---|---|---|---|---|---|---|---|
| simple | 4 | 3 | 1 | 0 | 183 | 9 | 4/4 | 0/1 | 0/3 | - |

## Per case

| case | simple |
|---|---|
| field_log | 0/1 |
| mixed_units | 2/2 |
| two_tables | 1/1 |

## Not correct

- `field_log.q5.simple.0` wrong: got '30.56', want 30.62; receipt clean; finish stop
