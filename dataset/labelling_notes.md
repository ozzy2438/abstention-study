# Dataset labelling and self-audit notes

Date: 2026-08-31

Status: Phase 2 dataset freeze candidate. These notes describe the final files
produced by `dataset/build_cases.py`, `dataset/build_retrieval.py`, and
`dataset/audit_cases.py`. They are not model-evaluation results.

## Construction and review record

The case content was authored as explicit, individually readable
specifications in `dataset/build_cases.py`. The script validates references,
assigns opaque IDs after a deterministic shuffle with seed `20260831`, and
writes the canonical JSONL; it does not synthesize questions or labels.

The author read every final case before admission. The review covered:

- all 105 `answerable_clear` cases against the complete cited passage, with a
  check that the passage alone contains every material qualifier;
- all 45 `answerable_multihop` cases against every cited passage, with a check
  that at least two passages make necessary contributions;
- all 45 `unanswerable_missing` cases against the full frozen corpus, with a
  check that the absent fact is material rather than merely hard to retrieve;
- all 30 `unanswerable_contradictory` cases against the competing passages and
  the tie-break rule; the case-by-case ledger is below;
- all 45 `out_of_scope` cases against the subject boundaries of all three
  documents; and
- all 30 `adversarial` cases, checking both that the manipulation is essential
  to the case and that removing it does not leave a fully answerable question.

After the deterministic retrieval and audit outputs were built, the author
also re-read every answerable case for which top-eight BM25 omitted at least
one gold passage. Those retrieval failures were retained: the protocol defines
them as measured failures of the end-to-end system, not grounds for changing a
gold label.

The review corrected draft errors before freeze, including a mistaken use of
the 28-day death-benefit objection period as a response period, the allocation
of responsibility between a credit representative and its licensee, citations
whose support fell across a chunk boundary, and draft multihop questions for
which one passage was actually sufficient. Two contradictory draft wordings
were also replaced during the final borderline pass:

- the mediation draft originally placed the voluntary and mandatory contexts
  in one passage; the final `case_0291` instead contrasts employee referral to
  the Fair Work Commission with private mediation consent across two passages;
- the communication draft originally named both acknowledgement and final
  response, making a two-part answer possible; final `case_0076` omits the
  stage, leaving the verbal-versus-written conflict unresolved.

No model output was generated before these corrections or this dataset freeze.
There is no independent second rater and therefore no inter-rater agreement
measurement.

## Final distribution

The counts below are generated in `dataset/audit_summary.json`.

| Category | Count | Share | Expected behaviour |
| --- | ---: | ---: | --- |
| `answerable_clear` | 105 | 35% | `ANSWER` |
| `answerable_multihop` | 45 | 15% | `ANSWER` |
| `unanswerable_missing` | 45 | 15% | `ABSTAIN` |
| `unanswerable_contradictory` | 30 | 10% | `ABSTAIN` |
| `out_of_scope` | 45 | 15% | `ABSTAIN` |
| `adversarial` | 30 | 10% | `ABSTAIN` |
| **Total** | **300** | **100%** | 150 answer / 150 abstain |

All 270 non-borderline cases have `author_confidence=high`. The 30
contradictory cases have `author_confidence=medium` and are logged below. No
case has `author_confidence=low`.

## Borderline decision ledger

For every row below, the candidate labels were
`unanswerable_contradictory` and `unanswerable_missing`. The missing
discriminator could superficially look like an absent fact, but the cited
passages support incompatible answers under the wording supplied. The frozen
precedence rule therefore selects `unanswerable_contradictory`; the final
behaviour is `ABSTAIN`. Passage IDs are canonical IDs from
`corpus/passages.jsonl`.

| Case | Competing passages | Reasoning and final decision |
| --- | --- | --- |
| `case_0183` | `asic_rg271-p0021-c001-eedd18e219b1` / `asic_rg271-p0021-c002-f2a3afc18de5` | Standard complaints use 30 days; named trustee complaints use 45. Firm and complaint type are absent. Final: `unanswerable_contradictory`. |
| `case_0083` | `asic_rg271-p0021-c001-eedd18e219b1` / `asic_rg271-p0022-c001-c82f21d3ee0b` | The general period is 30 days; specified default and hardship complaints use 21. Complaint subject is absent. Final: `unanswerable_contradictory`. |
| `case_0132` | `asic_rg271-p0022-c001-c82f21d3ee0b` / `asic_rg271-p0022-c002-f82589af8eb4` | The adjacent rules support 21, 7, or 30 days at different hardship stages. The procedural state is absent. Final: `unanswerable_contradictory`. |
| `case_0124` | `asic_rg271-p0020-c001-065c65220d78` / `asic_rg271-p0022-c001-c82f21d3ee0b` | One rule gives a 28-day objection period; another gives a 90-day maximum after that period. Actor and stage are absent. Final: `unanswerable_contradictory`. |
| `case_0075` | `asic_rg271-p0024-c001-b4bba4141d6f` / `asic_rg271-p0025-c001-ccae911d4a7d` | Prompt satisfactory closure can avoid an IDR response, but named exceptions still require writing. Exception status is absent. Final: `unanswerable_contradictory`. |
| `case_0211` | `asic_rg271-p0021-c001-eedd18e219b1` / `asic_rg271-p0023-c001-94f83792660d` | A final response is normally due by the maximum period, while a delay notification is allowed only for specified causes. Cause is absent. Final: `unanswerable_contradictory`. |
| `case_0189` | `asic_rg271-p0019-c001-fe57db53dd3b` / `fwo_dispute_resolution-p0009-c001-20723c6f1697` | Financial IDR gives a 24-hour expectation; workplace guidance says prompt resolution without that fixed limit. Regime is absent. Final: `unanswerable_contradictory`. |
| `case_0021` | `asic_rg271-p0028-c001-c4d0879b3776` / `asic_rg271-p0023-c001-94f83792660d` | Urgent credit matters may go directly to AFCA after statutory periods; a death-benefit distribution complaint first goes to the decision-maker. Matter type is absent. Final: `unanswerable_contradictory`. |
| `case_0179` | `asic_rg271-p0020-c001-065c65220d78` / `asic_rg271-p0027-c002-6893af7f5030` | Ordinary IDR responses include AFCA information; a response to a proposed death-benefit objection omits those requirements. Response stage is absent. Final: `unanswerable_contradictory`. |
| `case_0085` | `asic_rg271-p0044-c002-328f4e95f533` / `fwo_dispute_resolution-p0008-c001-d2801a834664` | Financial guidance supports postponing adverse action; workplace guidance expects safe and appropriate work to continue. Actor and regime are absent. Final: `unanswerable_contradictory`. |
| `case_0113` | `asic_rg271-p0004-c001-fde204a5871a` / `fwo_dispute_resolution-p0004-c001-b24117433e9a` | AFCA is the external body for the financial system; the Fair Work Commission is used in the workplace path. Subject is absent. Final: `unanswerable_contradictory`. |
| `case_0270` | `fwo_dispute_resolution-p0004-c001-b24117433e9a` / `asic_rg271-p0028-c001-c4d0879b3776` | The award path generally exhausts appropriate internal steps; urgent credit pathways can permit direct AFCA access. Regime is absent. Final: `unanswerable_contradictory`. |
| `case_0007` | `asic_rg271-p0039-c001-6965df983e7f` / `fwo_dispute_resolution-p0010-c002-4f814531e440` | Financial IDR must be free; private workplace mediation may be free or low-cost. Service type is absent. Final: `unanswerable_contradictory`. |
| `case_0291` | `fwo_dispute_resolution-p0004-c001-b24117433e9a` / `fwo_dispute_resolution-p0010-c002-4f814531e440` | An employee may refer an unresolved award dispute after internal steps; private mediation generally needs both parties' agreement. External process is absent. Final: `unanswerable_contradictory`. |
| `case_0003` | `fwo_dispute_resolution-p0010-c002-4f814531e440` / `fwo_dispute_resolution-p0011-c001-229dc07ce14d` | A mediator facilitates agreement without deciding; an arbitrator makes a binding decision. Neutral process is absent. Final: `unanswerable_contradictory`. |
| `case_0029` | `asic_rg271-p0021-c001-eedd18e219b1` / `asic_rg271-p0022-c002-f82589af8eb4` | The general limit is 30 days; applicable card-scheme rules can supply the response period. Scheme coverage is absent. Final: `unanswerable_contradictory`. |
| `case_0064` | `asic_rg271-p0014-c001-2450831dba3b` / `asic_rg271-p0014-c002-c83027a54f40` | Identifiable posts on firm-controlled channels are complaints; firms need not proactively identify complaints on third-party channels. Channel is absent. Final: `unanswerable_contradictory`. |
| `case_0010` | `asic_rg271-p0013-c001-a53d7d32bf80` / `asic_rg271-p0015-c001-29fdc2ba5f4c` | A qualifying expression of dissatisfaction is a complaint; survey feedback with no expected response is excluded. Submission context is absent. Final: `unanswerable_contradictory`. |
| `case_0246` | `asic_rg271-p0020-c001-065c65220d78` / `asic_rg271-p0020-c002-86e3cf74ff52` | A rejection must refer to supporting information, but information breaching privacy or other law should not be supplied. Information type is absent. Final: `unanswerable_contradictory`. |
| `case_0108` | `asic_rg271-p0013-c001-a53d7d32bf80` / `asic_rg271-p0015-c001-29fdc2ba5f4c` | An expression of dissatisfaction can be a complaint; a bare unauthorised-transaction report is excluded. Dissatisfaction or a separate issue is absent. Final: `unanswerable_contradictory`. |
| `case_0285` | `asic_rg271-p0004-c001-fde204a5871a` / `asic_rg271-p0005-c001-bdeeadc501e5` | Covered financial firms generally need IDR and AFCA membership; an unlicensed COI lender has IDR duties without mandatory AFCA membership. Lender type is absent. Final: `unanswerable_contradictory`. |
| `case_0225` | `asic_rg271-p0008-c001-4a2206d2b3a8` / `asic_rg271-p0008-c002-8f54c97d110a` | An exempt SPFE has no own IDR duty; its servicing credit licensee must cover relevant complaints. Party role is absent. Final: `unanswerable_contradictory`. |
| `case_0042` | `asic_rg271-p0033-c001-79a60fdf3fe9` / `asic_rg271-p0033-c002-5f7f876bab63` | A complainant may pursue AFCA; a firm's direct referral requires the complainant's consent. Referrer is absent. Final: `unanswerable_contradictory`. |
| `case_0076` | `asic_rg271-p0019-c001-fe57db53dd3b` / `asic_rg271-p0020-c001-065c65220d78` | Acknowledgement may be verbal; the substantive IDR response is written. Communication stage is absent. Final: `unanswerable_contradictory`. |
| `case_0262` | `asic_rg271-p0024-c001-b4bba4141d6f` / `asic_rg271-p0025-c001-ccae911d4a7d` | An explanation or apology can support prompt closure; named complaint types and requests still require writing. Type and request status are absent. Final: `unanswerable_contradictory`. |
| `case_0119` | `asic_rg271-p0013-c001-a53d7d32bf80` / `asic_rg271-p0015-c001-29fdc2ba5f4c` | Complaints about products, services, or staff may enter customer IDR; employment-related staff complaints are excluded. Capacity and subject are absent. Final: `unanswerable_contradictory`. |
| `case_0018` | `asic_rg271-p0004-c001-fde204a5871a` / `fwo_dispute_resolution-p0002-c001-b5913d14d74a` | Highlighted RG 271 requirements are enforceable; the Fair Work document includes best-practice guidance alongside legal rules. Step and regime are absent. Final: `unanswerable_contradictory`. |
| `case_0068` | `fwo_dispute_resolution-p0004-c001-b24117433e9a` / `asic_rg271-p0033-c002-5f7f876bab63` | A workplace party may refer after internal steps; a firm's direct AFCA referral needs complainant consent. Regime and referrer are absent. Final: `unanswerable_contradictory`. |
| `case_0117` | `fwo_dispute_resolution-p0010-c002-4f814531e440` / `fwo_dispute_resolution-p0011-c001-229dc07ce14d` | A mediator does not give advice; a conciliator may provide expert advice or information. Neutral process is absent. Final: `unanswerable_contradictory`. |
| `case_0074` | `fwo_dispute_resolution-p0010-c002-4f814531e440` / `fwo_dispute_resolution-p0011-c001-229dc07ce14d` | Mediation seeks an agreed solution; arbitration produces a decision binding on everyone. External process is absent. Final: `unanswerable_contradictory`. |

## Abstention-category audit

The abstention cases were checked for answerability rather than difficulty:

- `unanswerable_missing` questions require a specific absent fact such as a
  current rate, fee, numerical threshold, mandated form, or universal period.
  They were not labelled missing because BM25 ranked the supporting material
  poorly.
- `unanswerable_contradictory` questions have competing support documented
  above. They do not claim that the legal regimes themselves contradict; the
  conflict arises because the question omits the discriminator.
- `out_of_scope` questions use plausible regulatory language but ask about
  subjects outside ASIC RG 271, the NES summary, and the Fair Work dispute
  guide. Nearby words do not provide a supported conclusion.
- `adversarial` questions contain a false premise, leading demand, citation
  fabrication request, or instruction override that is essential to the test.
  No otherwise fully answerable question was converted into an adversarial
  abstention case merely by wrapping it in an injection.

## Surface-cue and duplication audit

All values in this section come from `dataset/audit_summary.json` and the CSVs
written beside it.

### Question length

| Category | Cases | Mean words | Median words | Min-max words |
| --- | ---: | ---: | ---: | ---: |
| `answerable_clear` | 105 | 13.80 | 13 | 7-24 |
| `answerable_multihop` | 45 | 18.93 | 18 | 10-26 |
| `unanswerable_missing` | 45 | 15.13 | 15 | 11-20 |
| `unanswerable_contradictory` | 30 | 16.07 | 15 | 11-22 |
| `out_of_scope` | 45 | 12.71 | 13 | 8-15 |
| `adversarial` | 30 | 20.53 | 20 | 17-25 |

A stratified five-fold nearest-category-median classifier using only word
count achieved accuracy `0.3333333333333333`, below the `0.35` majority-class
baseline. Length therefore does not beat the baseline in this audit, although
the adversarial and multihop distributions are visibly longer and a model may
still exploit that difference.

### Lexical and template cues

The forbidden formulaic patterns produced zero hits: no question names its
category or contains “the corpus does not say”, “not in the corpus”, “cannot be
answered”, or “outside scope”. There are 51 distinct first tokens. The largest
count for one category sharing an identical first-three-token phrase is four.

The residual lexical leakage risk is material. A stratified five-fold
multinomial naive Bayes classifier over question-only word unigrams and
bigrams achieved accuracy `0.69` and macro recall `0.6624338624338625`, versus
the `0.35` majority-class accuracy. The audit CSV shows interpretable cues:
imperatives such as `cite` are associated with adversarial cases; commercial
and regulatory-topic words with out-of-scope cases; numerical words such as
`percentage` with missing-fact cases; and connective or comparative language
with multihop and contradictory cases.

This cue signal was not cosmetically erased. Some of it follows directly from
the registered taxonomy: adversarial cases must contain manipulation,
out-of-scope cases must discuss other domains, and multihop cases often ask for
comparisons. The consequence is a study limitation: measured abstention may
partly reflect recognition of authoring style or category-associated
vocabulary rather than corpus-grounded uncertainty alone.

### Exact and near duplicates

All 300 normalised questions are unique. The audit checked all 44,850
unordered pairs using lowercased Unicode word-token-set Jaccard similarity.
There are zero pairs at or above `0.8`; the maximum observed similarity is
`0.6666666666666666`. The 100 highest pairs are retained in
`dataset/audit_near_duplicates.csv` for inspection.

## Retrieval audit

The deterministic top-eight BM25 retrieval is not used to decide the gold
label. It retrieved every gold passage for 118 of 150 answerable cases
(`0.7866666666666666`) and at least one gold passage for 136 of 150
(`0.9066666666666666`). By category:

| Category | All gold retrieved | Any gold retrieved |
| --- | ---: | ---: |
| `answerable_clear` | 96 / 105 | 96 / 105 |
| `answerable_multihop` | 22 / 45 | 40 / 45 |
| **All answerable** | **118 / 150** | **136 / 150** |

The 32 cases missing at least one gold passage are listed in
`dataset/audit_summary.json` and row-by-row in
`dataset/audit_retrieval.csv`. They remain answerable against the complete
corpus. In particular, the 14 answerable cases for which BM25 retrieved no
gold passage remain in the set; this deliberately preserves difficult
end-to-end retrieval failures.

## Mechanical audit and limitations

`dataset/audit_cases.py` reports `PASS` for exact schema, unique contiguous
case IDs, target counts, behaviour/gold consistency, passage-ID existence,
manifest hashes, question uniqueness, and eight unique ordered retrieval
passages per case. The canonical hashes are recorded in
`dataset/audit_summary.json`, `dataset/cases_manifest.json`, and
`dataset/retrieval_manifest.json`.

The principal labelling limitations are author-written cases, a single author
and reviewer, no inter-rater agreement, one regulatory domain, three public
documents, and category-associated vocabulary documented above. These
limitations must remain visible in the final report.

## Owner-requested Phase 2 correction audit - 2026-08-31

This dated section supersedes the affected dispositions in the original
borderline ledger above without deleting that audit trail. It was completed
before Phase 3 and before any model call.

### Multihop spot checks

- `case_0014` remains `answerable_multihop`. Passage
  `fwo_dispute_resolution-p0003-c001-1a4a5fb3c291` describes negotiation,
  mediation and arbitration, while
  `fwo_dispute_resolution-p0011-c001-229dc07ce14d` supplies conciliation and
  its contrast with arbitration. The additional mediator detail is in
  `fwo_dispute_resolution-p0010-c002-4f814531e440`. No one passage contains
  the complete four-method comparison.
- `case_0016` remains `answerable_multihop`. Passage
  `asic_rg271-p0045-c001-5511043e4931` supplies the public-policy contents and
  availability rule; `asic_rg271-p0039-c001-6965df983e7f` separately states
  that the IDR process must be provided free of charge. No one passage
  supports the complete requested answer.

### Contradictory-case re-audit

Every one of the original 30 rows in the borderline ledger was re-read
against both passage IDs already named there. The following 19 cases retain
`unanswerable_contradictory`; each remains tied to the two exact passage IDs
in its ledger row, including explicit within-document scope conflicts:
`case_0007`, `case_0010`, `case_0018`, `case_0029`, `case_0068`, `case_0075`,
`case_0076`, `case_0083`, `case_0085`, `case_0113`, `case_0117`, `case_0119`,
`case_0132`, `case_0179`, `case_0189`, `case_0262`, `case_0270`, `case_0285`,
and `case_0291`.

The other 11 dispositions were corrected as follows:

- `case_0003` -> `answerable_clear`: one passage,
  `fwo_dispute_resolution-p0003-c001-1a4a5fb3c291`, directly contrasts a
  mediator helping parties agree with an arbitrator or court deciding.
- `case_0021` -> `answerable_clear`: one passage,
  `asic_rg271-p0028-c001-c4d0879b3776`, states both the urgent-credit direct
  AFCA pathway and the death-benefit prerequisite.
- `case_0042` -> `answerable_clear`: one overlapping passage,
  `asic_rg271-p0033-c002-5f7f876bab63`, distinguishes a complainant pursuing
  AFCA from a firm's consent-dependent direct referral.
- `case_0064` -> `answerable_clear`: one overlapping passage,
  `asic_rg271-p0014-c002-c83027a54f40`, contains both the controlled-channel
  social-media rule and the third-party-channel exception.
- `case_0074` -> `answerable_clear`: one passage,
  `fwo_dispute_resolution-p0003-c001-1a4a5fb3c291`, contrasts mediated
  agreement with binding arbitration or adjudication.
- `case_0108` -> `answerable_clear`: one passage,
  `asic_rg271-p0015-c001-29fdc2ba5f4c`, states both the bare-report exclusion
  and the conditions that turn an unauthorised-transaction report into a
  complaint.
- `case_0124` -> `answerable_clear`: one table passage,
  `asic_rg271-p0022-c001-c82f21d3ee0b`, relates the 28-day objection period to
  the subsequent 90-day maximum.
- `case_0183` -> `answerable_clear`: one table passage,
  `asic_rg271-p0021-c002-f2a3afc18de5`, contains the scoped 30-day and 45-day
  timeframes.
- `case_0225` -> `answerable_clear`: one table passage,
  `asic_rg271-p0008-c001-4a2206d2b3a8`, distinguishes an exempt SPFE's lack
  of its own IDR duty from its servicing licensee's coverage duty.
- `case_0246` -> `answerable_clear`: one overlapping passage,
  `asic_rg271-p0020-c002-86e3cf74ff52`, contains both the supporting-
  information requirement and the privacy or legislative limitation.
- `case_0211` -> `unanswerable_missing`: passage
  `asic_rg271-p0023-c001-94f83792660d` gives the complete conditions for a
  valid delay notice, but the question omits whether complexity or
  circumstances beyond the firm's control caused the delay. This is a
  missing material fact, not a source conflict.

The resulting distribution is 115 `answerable_clear`, 45
`answerable_multihop`, 46 `unanswerable_missing`, 19
`unanswerable_contradictory`, 45 `out_of_scope`, and 30 `adversarial`.

### Retrieval diagnostic

`dataset/retrieval_diagnostics.json` covers all 160 answerable cases. The
frozen BM25 top-eight retrieved all gold passages for 127 cases (`full`), at
least one but not all gold passages for 18 (`partial`), and no gold passage
for 15 (`none`). These values are computed from the committed retrieval rows,
not manually assigned.

### Question-only leakage classifier breakdown

The classifier remains a seeded, stratified five-fold multinomial naive Bayes
model over question-text word unigrams and bigrams that occur in at least two
training questions. The following matrices use rows as actual labels and
columns as predicted labels.

Same-topic three-way task (180 cases):

| Actual / predicted | `answerable_clear` | `unanswerable_missing` | `unanswerable_contradictory` |
| --- | ---: | ---: | ---: |
| `answerable_clear` | 107 | 3 | 5 |
| `unanswerable_missing` | 16 | 30 | 0 |
| `unanswerable_contradictory` | 7 | 1 | 11 |

Accuracy is `0.8222222222222222`, macro recall is
`0.7205186880244089`, and the majority-class baseline is
`0.6388888888888888`. The classifier therefore does distinguish these
same-topic labels from question text alone, especially `answerable_clear`.
This is material authoring-style or lexical leakage and remains a study
limitation.

Different-topic binary task (all 300 cases):

| Actual / predicted | `out_of_scope_or_adversarial` | `rest` |
| --- | ---: | ---: |
| `out_of_scope_or_adversarial` | 38 | 37 |
| `rest` | 13 | 212 |

Accuracy is `0.8333333333333334`, macro recall is `0.7244444444444444`,
and the majority-class baseline is `0.75`. Despite the higher raw accuracy,
the classifier identifies only 38 of 75 out-of-scope or adversarial cases;
the imbalance and strong `rest` recall account for much of the score.

The replacement full six-way question-only classifier result is accuracy
`0.64` and macro recall `0.5756589541486566`, against a majority-class
baseline of `0.38333333333333336`. Exact matrices and source hashes are in
`dataset/audit_summary.json`.

### Same-topic leakage interpretation - 2026-08-31

The `0.8222222222222222` same-topic result appears to be driven primarily by
a repeatable authorial phrasing tic, not an inherent semantic property of all
missing-detail questions. In the question-level cue audit, `many` occurs in
11 of 46 `unanswerable_missing` questions and `percentage` occurs in five,
matching repeated templates such as “how many”, “what percentage”, “which
form”, and requests for exact rates, amounts, or deadlines. Missing evidence
can be asked without those forms, and answerable regulatory questions can
also naturally request numbers, so the strength and repetition of these cues
reflect this single author's construction choices even though some semantic
signal is unavoidable. Phase 6 must carry this finding into the report's
limitations section explicitly; it must not be left only in the dataset notes.

### Recategorized-clear gold integrity check - 2026-08-31

The ten cases moved from `unanswerable_contradictory` to
`answerable_clear`—`case_0003`, `case_0021`, `case_0042`, `case_0064`,
`case_0074`, `case_0108`, `case_0124`, `case_0183`, `case_0225`, and
`case_0246`—were checked mechanically and manually before Phase 3. Every case
has a non-empty `gold_answer`, exactly one non-empty `gold_citations` entry,
and that passage ID exists in `corpus/passages.jsonl`. No gold repair was
required.
