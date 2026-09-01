# INVALID audit: standard / single_pass

This audit re-read stored raw response files; it made no API calls and did not alter the frozen run rows. The cell has 62 INVALID rows: answerable_clear=48, answerable_multihop=12, unanswerable_contradictory=2.

Every inspected response has HTTP 200 and finish reason `stop`. The model itself returns a syntactically valid JSON object whose `output_type` is `ANSWER`, but `answer_text` is empty and `citations` is an empty list. That violates the pre-registered ANSWER contract; the harness correctly records `invalid_contract:answer_fields`. The repeated payload occurs 41 times in this cell. This is a genuine standard-tier format/contract failure, not a tier-specific parser bug, so no rows were re-scored.

The same standard tier has lower INVALID rates with the other workflows: self_check has 12/300 (4.0%) and escalation 13/300 (4.3%), versus 62/300 (20.7%) for single_pass. This is consistent with a second pass or escalation path avoiding the blank-ANSWER emission; it does not prove which component corrected each row.

## Stored examples

- `case_0006` (answerable_clear), parser result `invalid_contract:answer_fields`, raw `results/raw/full_r3_v1__standard__single_pass__1b1581710af2__beec0d744d65/case_0006/call-01-attempt-01.json`:

  `{"answer_text":"","citations":[],"confidence":0.99,"output_type":"ANSWER"}`

- `case_0012` (answerable_clear), parser result `invalid_contract:answer_fields`, raw `results/raw/full_r3_v1__standard__single_pass__1b1581710af2__beec0d744d65/case_0012/call-01-attempt-01.json`:

  `{"answer_text":"","citations":[],"confidence":0.98,"output_type":"ANSWER"}`

- `case_0022` (answerable_clear), parser result `invalid_contract:answer_fields`, raw `results/raw/full_r3_v1__standard__single_pass__1b1581710af2__beec0d744d65/case_0022/call-01-attempt-01.json`:

  `{"answer_text":"","citations":[],"confidence":0.98,"output_type":"ANSWER"}`

- `case_0024` (answerable_clear), parser result `invalid_contract:answer_fields`, raw `results/raw/full_r3_v1__standard__single_pass__1b1581710af2__beec0d744d65/case_0024/call-01-attempt-01.json`:

  `{"answer_text":"","citations":[],"confidence":0.98,"output_type":"ANSWER"}`

- `case_0034` (answerable_clear), parser result `invalid_contract:answer_fields`, raw `results/raw/full_r3_v1__standard__single_pass__1b1581710af2__beec0d744d65/case_0034/call-01-attempt-01.json`:

  `{"answer_text":"","citations":[],"confidence":0.98,"output_type":"ANSWER"}`

- `case_0035` (answerable_clear), parser result `invalid_contract:answer_fields`, raw `results/raw/full_r3_v1__standard__single_pass__1b1581710af2__beec0d744d65/case_0035/call-01-attempt-01.json`:

  `{"answer_text":"","citations":[],"confidence":0.98,"output_type":"ANSWER"}`

- `case_0043` (answerable_clear), parser result `invalid_contract:answer_fields`, raw `results/raw/full_r3_v1__standard__single_pass__1b1581710af2__beec0d744d65/case_0043/call-01-attempt-01.json`:

  `{"answer_text":"","citations":[],"confidence":0.99,"output_type":"ANSWER"}`

- `case_0047` (answerable_clear), parser result `invalid_contract:answer_fields`, raw `results/raw/full_r3_v1__standard__single_pass__1b1581710af2__beec0d744d65/case_0047/call-01-attempt-01.json`:

  `{"answer_text":"","citations":[],"confidence":0.98,"output_type":"ANSWER"}`

- `case_0051` (answerable_clear), parser result `invalid_contract:answer_fields`, raw `results/raw/full_r3_v1__standard__single_pass__1b1581710af2__beec0d744d65/case_0051/call-01-attempt-01.json`:

  `{"answer_text":"", "citations": [], "confidence": 0.99, "output_type": "ANSWER"}`

The row-level evidence is in `analysis/figures/standard_single_pass_invalid_audit.csv`; the full raw API envelopes remain under `results/raw/`.
