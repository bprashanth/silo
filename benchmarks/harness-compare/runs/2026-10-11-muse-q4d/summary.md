# Harness comparison: 2026-10-11-muse-q4d

| harness | jobs | correct | wrong | missing | median s | median actions | receipt clean | wrong answers caught by receipt | correct answers flagged | audit flags |
|---|---|---|---|---|---|---|---|---|---|---|
| codex | 134 | 131 | 3 | 0 | 88 | 7 | 128/134 | 2/3 | 4/131 | - |
| simple | 134 | 125 | 5 | 4 | 256 | 7 | 123/134 | 1/5 | 6/125 | - |

## Per case

| case | codex | simple |
|---|---|---|
| big_ledger | 12/12 | 8/12 |
| clean | 22/22 | 22/22 |
| field_log | 10/12 | 11/12 |
| formulas_no_cache | 14/14 | 14/14 |
| mixed_units | 15/16 | 13/16 |
| multi_file | 12/12 | 12/12 |
| offset_headers | 16/16 | 16/16 |
| subtotals | 16/16 | 16/16 |
| two_tables | 14/14 | 13/14 |

## Not correct

- `big_ledger.q1.simple.0` wrong: got '1337635700', want 1614773900; receipt clean; finish stop
- `big_ledger.q1.simple.1` wrong: got '1337635700', want 1614773900; receipt clean; finish max_steps
- `big_ledger.q2.simple.1` wrong: got '104203200', want 126270000; receipt clean; finish max_steps
- `big_ledger.q3.simple.0` wrong: got '0', want 3789; receipt BROKEN []; finish max_steps
- `field_log.q5.codex.0` wrong: got '30.56', want 30.62; receipt BROKEN [147.0, 147.0]; finish exit=0
- `field_log.q5.codex.1` wrong: got '30.56', want 30.62; receipt clean; finish exit=0
- `field_log.q5.simple.0` missing: got None, want 30.62; receipt BROKEN []; finish error: <HTTPError 500: 'Internal Server Error'>
- `mixed_units.q2.codex.1` wrong: got '1518000', want 2983000; receipt BROKEN [30.0]; finish exit=0
- `mixed_units.q2.simple.1` missing: got None, want 2983000; receipt BROKEN []; finish error: <HTTPError 500: 'Internal Server Error'>
- `mixed_units.q5.simple.0` missing: got None, want 19.882441; receipt BROKEN []; finish error: <HTTPError 500: 'Internal Server Error'>
- `mixed_units.q6.simple.0` wrong: got 'Maternal & Child Health', want 'Tribal Education'; receipt clean; finish max_steps
- `two_tables.q1_plain.simple.1` missing: got None, want 46700000; receipt BROKEN []; finish error: <HTTPError 500: 'Internal Server Error'>
