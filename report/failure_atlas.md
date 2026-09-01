# Failure atlas

This atlas covers every one of the **220 wrong issued-answer rows** across the nine completed configurations. Of those, **179** carried confidence at or above `0.80`. The blinded answer review preceded this grouping; failure modes were assigned only after correctness and citation validity were fixed.

The modes are mutually exclusive primary labels so their counts sum to 220. Some rows could reasonably fit more than one mode; citation failure takes priority, then a registered should-abstain error, then the content taxonomy below. Counts are row counts, not unique questions, because each configuration is a measured decision.

| Failure mode | Wrong rows | Share | Confidence >= 0.80 |
|---|---:|---:|---:|
| Answered an under-specified question | 65 | 29.5% | 63 |
| Truncated a multihop checklist | 59 | 26.8% | 45 |
| Dropped a material exception or qualifier | 34 | 15.5% | 32 |
| Unsupported citation or invented specificity | 25 | 11.4% | 17 |
| Collapsed distinct resolution mechanisms | 15 | 6.8% | 10 |
| Substituted an adjacent procedural route | 12 | 5.5% | 8 |
| Stopped before the external-escalation duty | 4 | 1.8% | 0 |
| Returned the opposite polarity | 3 | 1.4% | 3 |
| Confused institution or role labels | 3 | 1.4% | 1 |

## Modes and real examples

### 1. Answered an under-specified question

**Frequency:** 65 of 220 wrong answers (29.5%); 63 were confidently wrong.

The model selected one plausible regime, actor, complaint type, or procedural stage even though the question withheld the fact needed to choose. These were registered ABSTAIN cases; a conditional explanation did not satisfy the output contract.

**Example:** `standard__single_pass`, `case_0189` (`unanswerable_contradictory`), confidence `0.98`. Raw evidence: `results/raw/full_r3_v1__standard__single_pass__1b1581710af2__beec0d744d65/case_0189/call-01-attempt-01.json`.

Question:

> A complaint has just reached an organisation. Must it be acknowledged within 24 hours?

Actual model answer:

> Yes, ASIC RG 271 says firms should acknowledge receipt of each complaint promptly and expects acknowledgment within 24 hours (or one business day) of receiving it, or as soon as practicable. See asic_rg271-p0019-c001-fe57db53dd3b.

Why it failed: Issued an answer on a registered should-abstain case; cited material supports the conditional or narrower claims made.

### 2. Truncated a multihop checklist

**Frequency:** 59 of 220 wrong answers (26.8%); 45 were confidently wrong.

The answer retrieved a real part of a multi-passage requirement but stopped before one or more material duties, capabilities, governance checks, or comparison points.

**Example:** `capable__escalation`, `case_0259` (`answerable_multihop`), confidence `0.86`. Raw evidence: `results/raw/remaining_v1_v1__capable__escalation__1b1581710af2__9d564a17727a/case_0259/call-01-attempt-01.json`.

Question:

> What ongoing checks should a firm use to test whether its IDR process remains effective?

Actual model answer:

> Firms should monitor and review the performance of their IDR process on an ongoing basis, including monitoring complaint metrics, carrying out ongoing quality assurance of complaint management activity, and conducting regular reviews (including regular compliance audits).

Why it failed: Omits resource adequacy and the independent review option; some variants omit other checks.

### 3. Dropped a material exception or qualifier

**Frequency:** 34 of 220 wrong answers (15.5%); 32 were confidently wrong.

The headline rule was usually right, but an exception, timing condition, privacy constraint, or escalation protection that changes how the rule can be used was absent.

**Example:** `cheap__self_check`, `case_0269` (`answerable_clear`), confidence `0.98`. Raw evidence: `results/raw/full_r3_v1__cheap__self_check__1b1581710af2__af282e540fce/case_0269/call-02-attempt-01.json`.

Question:

> When may a financial firm close a complaint within five business days without an IDR response?

Actual model answer:

> A financial firm may close a complaint within five business days of receipt without providing an IDR response if it closes the complaint by the end of the fifth business day after receipt because it has either (a) resolved the complaint to the complainant’s satisfaction, or (b) given the complainant an explanation and/or apology when the firm can take no further action to reasonably address the complaint.

Why it failed: Omits the exception that can still require a written response.

### 4. Unsupported citation or invented specificity

**Frequency:** 25 of 220 wrong answers (11.4%); 17 were confidently wrong.

The answer cited a nonexistent, irrelevant, or passage-boundary-mismatched source, or gave a specific number/rule that the cited passage did not support. This mode takes priority when a row also had a content omission.

**Example:** `standard__self_check`, `case_0071` (`unanswerable_missing`), confidence `0.99`. Raw evidence: `results/raw/full_r3_v1__standard__self_check__1b1581710af2__af282e540fce/case_0071/call-02-attempt-01.json`.

Question:

> How many weeks of redundancy pay does an employee with exactly seven years of service receive?

Actual model answer:

> 16 weeks

Why it failed: The corpus names redundancy pay but does not support the asserted seven-year amount.

### 5. Collapsed distinct resolution mechanisms

**Frequency:** 15 of 220 wrong answers (6.8%); 10 were confidently wrong.

The response described one branch—often arbitration—without preserving the registered contrast with mediation, conciliation, or another outcome-control mechanism.

**Example:** `capable__single_pass`, `case_0074` (`answerable_clear`), confidence `0.95`. Raw evidence: `results/raw/full_r3_v1__capable__single_pass__1b1581710af2__beec0d744d65/case_0074/call-01-attempt-01.json`.

Question:

> Is the outcome reached through the external process binding on everyone?

Actual model answer:

> Yes—if the external process is arbitration, the outcome is binding on everyone: “the parties agree that an independent and impartial person (the arbitrator) will listen to each side and then make a decision that’s binding on everyone.”

Why it failed: Answers only the arbitration branch and omits the party-controlled mediated outcome.

### 6. Substituted an adjacent procedural route

**Frequency:** 12 of 220 wrong answers (5.5%); 8 were confidently wrong.

The model gave a nearby best-practice or representation step but not the applicable award/agreement route, independent settlement requirement, or Commission referral.

**Example:** `cheap__self_check`, `case_0248` (`answerable_clear`), confidence `0.98`. Raw evidence: `results/raw/full_r3_v1__cheap__self_check__1b1581710af2__af282e540fce/case_0248/call-02-attempt-01.json`.

Question:

> What must an enterprise agreement's dispute-resolution clause allow?

Actual model answer:

> It must allow employees to have a representative.

Why it failed: Omits the required independent-settlement procedure.

### 7. Stopped before the external-escalation duty

**Frequency:** 4 of 220 wrong answers (1.8%); 0 were confidently wrong.

The answer mentioned AFCA referral but omitted the mandatory right-to-escalate notice or AFCA contact details required in the registered answer.

**Example:** `standard__escalation`, `case_0089` (`answerable_clear`), confidence `0.78`. Raw evidence: `results/raw/full_r3_v1__standard__escalation__1b1581710af2__9d564a17727a/case_0089/call-01-attempt-01.json`.

Question:

> What must a firm do when a complaint remains unresolved at the end of IDR?

Actual model answer:

> If a complaint remains unresolved after the firm has given an IDR response, the firm may directly refer the complaint to AFCA for resolution, but it must obtain the complainant’s consent to do so.

Why it failed: Omits required AFCA access/contact information or the duty to inform the complainant.

### 8. Returned the opposite polarity

**Frequency:** 3 of 220 wrong answers (1.4%); 3 were confidently wrong.

A leading yes/no contradicted the rule that followed. The supporting explanation did not cure the operationally dangerous first-token answer.

**Example:** `capable__escalation`, `case_0099` (`answerable_clear`), confidence `0.95`. Raw evidence: `results/raw/remaining_v1_v1__capable__escalation__1b1581710af2__9d564a17727a/case_0099/call-02-attempt-01.json`.

Question:

> May a credit provider continue debt-enforcement action while a default-notice complaint is at IDR?

Actual model answer:

> Yes. Credit providers (including debt collectors) must refrain from commencing or continuing legal proceedings or other enforcement action against the complainant while the complaint is being handled at IDR during the 21 calendar days, and for a reasonable time afterward. For complaints involving default notices, the IDR response timeframe is 21 calendar days after receiving the complaint.

Why it failed: Leading yes reverses the supported prohibition.

### 9. Confused institution or role labels

**Frequency:** 3 of 220 wrong answers (1.4%); 1 were confidently wrong.

The response replaced a required institutional relationship—AFCA membership—with a nearby but different concept, ASIC oversight of AFCA.

**Example:** `capable__self_check`, `case_0209` (`answerable_clear`), confidence `0.95`. Raw evidence: `results/raw/full_r3_v1__capable__self_check__1b1581710af2__af282e540fce/case_0209/call-02-attempt-01.json`.

Question:

> What two components ordinarily make up a financial firm's dispute resolution system under RG 271?

Actual model answer:

> Under RG 271, the dispute resolution system includes two components: financial firms’ internal dispute resolution (IDR) processes, and oversight of AFCA (the external dispute resolution body).

Why it failed: Replaces AFCA membership with ASIC oversight of AFCA.

## Reading the atlas

The dominant pattern is not random factual ignorance. It is release-control failure: the model often had a relevant passage and produced a fluent partial rule, but did not stop when scope was unresolved or when the retrieved evidence did not cover every material limb. The high-confidence counts show why selective release must be measured rather than inferred from answer quality alone.

The underlying row-level assignments are in `analysis/figures/failure_modes.csv`; aggregate counts are in `analysis/figures/failure_modes_summary.csv`.
