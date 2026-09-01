# Manual adjudication worklog

Reviewer fields were blinded as recorded in `review_manifest.json`. IDs below
refer to `adjudication_id` values in `review_queue.jsonl`. `T/T` means correct
and citation-valid; `F/T` means answer-incorrect but citations valid for the
claims actually made; `F/F` means answer-incorrect and citation-invalid.

## Reviewed through case_0043

- `case_0001`: all T/T.
- `case_0003`: all T/T; the cited later passages directly support the same
  mediation/arbitration distinction as the frozen gold passage.
- `case_0004`: all T/T.
- `case_0006`: all T/T.
- `case_0007`: all F/F; an `ANSWER` cannot resolve the service-scope ambiguity,
  and the cited accessibility passages do not establish the asserted corpus-wide
  absence rule.
- `case_0009`: all T/T.
- `case_0010`: all F/T; the conditional explanation is passage-supported, but
  the question omits whether a response was expected or whether this was survey
  feedback, so the frozen task requires abstention.
- `case_0011`: all T/T; the cited consecutive passages include both preparation
  and organisational-change communication guidance.
- `case_0012`: all T/T except `3601aad97985feefa034` F/F because its sole
  passage ends before the RSA-holder language it quotes.
- `case_0014`: `0456b74569800304f7e1` and `1420eeaa60a99ce97a10` F/T because
  they omit the material expert-advice distinction for conciliation; all other
  variants T/T.
- `case_0016`, `case_0017`: all T/T.
- `case_0021`: `63dacf1bb3225d67c8c3` T/T; `68b1bf08e4f46a2f83fd` and
  `d755cd66f0ef147cd0e5` F/T because they omit the death-benefit constraint
  requested by the broad question.
- `case_0022` through `case_0028`: all T/T.
- `case_0029`: all F/T; the conditions are supported, but the transaction type
  is absent and the frozen label requires abstention.
- `case_0031`: all T/T.
- `case_0032`: all F/F; neither variant gives the frozen supported rule that a
  hardship notice is not automatically a complaint, and the cited passages do
  not support that missing exception.
- `case_0034` through `case_0036`: all T/T.
- `case_0038`: all F/T; each omits the material manager-training and employee-
  communication steps in the frozen multihop answer.
- `case_0041` through `case_0043`: all T/T.

## Reviewed case_0044 through case_0076

- `case_0044` through `case_0046`: all T/T.
- `case_0047`: `68156ed3a7b6bde21f5a` and `934e7b286be3ab23dcd2`
  F/T because their leading "Yes" reverses the answer; all other variants T/T.
- `case_0049`: all F/T because they omit the registered requirement that the
  rejection explanation be detailed enough to understand the basis and assess
  escalation.
- `case_0050`: all F/F. Most apply the general 30-day rule despite the specific
  45-day superannuation rule; `37cdba529fe51341976b` gives 45 days but does not
  cite the table passage containing 45 days; `809dacb55646b120b533` does not
  answer the period; `e322ce1a241f4578b082` also invents a passage ID.
- `case_0051`: all T/T.
- `case_0054`: all incomplete because they omit provider selection, monitoring,
  and deficiency handling. `6a19eaf381920bf4d403` is F/T; the other two are
  F/F because their extra complaint-definition citation is irrelevant.
- `case_0061`, `case_0063`, `case_0064`, and `case_0066`: all T/T. The conditional
  owned-or-controlled-account wording in `case_0064` correctly limits the duty.
- `case_0068`: all F/T; the financial-context answer is supported but cannot
  resolve the deliberately unspecified cross-domain question.
- `case_0071`: F/F; the source only names redundancy pay and does not give the
  seven-year amount asserted.
- `case_0072`: all T/T; the cited adjacent RG passages expressly state urgency.
- `case_0074`: all F/T because they answer only the arbitration branch and omit
  the material contrast with a party-controlled mediated outcome.
- `case_0075`: all F/T; the conditions and exceptions are supported, but the
  complaint type/request facts needed to choose among them are absent.
- `case_0076`: all F/T; the financial examples are supported but do not resolve
  which organisation/process the question means.

## Reviewed case_0077 through case_0100

- `case_0077` and `case_0079`: all T/T.
- `case_0080`: all F/T because each gives the IDR requirement and COI-lender
  exception but omits the other generally required arrangement: AFCA
  membership.
- `case_0083`: all F/T; both possible periods are supported but complaint type
  is missing, so the frozen label requires abstention.
- `case_0084`: all T/T.
- `case_0085`: all F/T; the financial and workplace rules are supported but
  the question lacks the domain fact needed to choose one.
- `case_0087`: all T/T.
- `case_0088`: all T/T except `aa41b117a24aba192cf8` and
  `ab1024219a1b4b1141f4` F/F because they add an irrelevant page-2 document-
  history citation.
- `case_0089`: `7b986ce6c2c761a55c39` and `b55c9b7d1d93a0d4fb3e`
  T/T. The other variants are F/T because they omit either the required AFCA
  access/contact information or the core duty to inform the complainant.
- `case_0090` through `case_0093`: all T/T. For `case_0091`, the concise no-IDR
  answer directly and non-misleadingly answers the question even when it omits
  optional AFCA context. For `case_0092`, the question asks the ordinary period,
  so the supported 21-day answer is sufficient.
- `case_0095`, `case_0096`, and `case_0098`: all T/T; the additional policy and
  resourcing passages in `case_0096` each contain a free-of-charge clause.
- `case_0099`: `e1cfa89d794e9cdba173` F/T because its leading "Yes" reverses
  the supported prohibition; the other variants T/T.
- `case_0100`: all T/T.

## Reviewed case_0103 through case_0138

- `case_0103`: all T/T.
- `case_0104`: `3fbde0a90a28e68b1862`, `64f9f7bbde11cf46994c`, and
  `a4a5109bfbeebfa8d0ec` T/T. The other three are F/T because they omit
  the exceptions that still require writing.
- `case_0106` through `case_0116`: all T/T. For `case_0114`, the court-
  proceedings passage itself states the 45-day period and the pause/restart
  conditions.
- `case_0117`: all F/T; conciliation may involve advice while mediation may
  not, and the question does not identify the process.
- `case_0118`: all T/T.
- `case_0119`: all F/T; the answers assume an employment grievance although
  the question does not say whether the staff member complained as employee or
  customer.
- `case_0124`: all T/T except `84c5cf84311444b12807` F/F because it adds an
  irrelevant ordinary-IDR-response citation.
- `case_0127`: all T/T.
- `case_0128`: `9b1fcd64bcfd97c53539` T/T; every other variant is F/T for
  omitting unlicensed carried over instrument lenders from the requested list.
- `case_0129`: all T/T except `22d134b6e8c2bb4f4f48` F/F because its sole
  passage ends before the mandatory-step prohibition quoted from the next
  passage.
- `case_0132`: all F/T; the alternatives are supported but the question omits
  the procedural stage needed to choose one.
- `case_0138`: all F/T; each correctly describes the cited financial remedies
  and workplace process material, but none retrieves or states the registered
  negotiated/mediated/arbitrated workplace outcome taxonomy.

## Reviewed case_0139 through case_0167

- `case_0139`, `case_0140`, `case_0143`, and `case_0144`: all T/T.
- `case_0142`: `a053924d0f4cc4fa3c0d` F/F because it cites a nonexistent
  passage ID; all other variants T/T.
- `case_0145`: all incomplete for omitting the latter registered capability
  attributes (cultural awareness, communication, analysis, and judgement).
  `b87261b4cc615fe8409a` is F/F because it additionally cites an irrelevant
  acknowledgement passage; the other variants are F/T.
- `case_0147` and `case_0148`: all T/T.
- `case_0151`: `7bcfc9a7b798691dc6b2` and `e78a0aedacb8741e23fe`
  T/T; the other variants are F/T because they omit enabling staff escalation
  and regular complaint-data analysis from the registered answer.
- `case_0153`, `case_0154`, and `case_0157`: all T/T.
- `case_0158`: `d53f64f527567fc2cfb8` T/T;
  `98f91683e7d6f7821c55` F/T because it omits the legally-required limb of the
  complaint definition.
- `case_0159` through `case_0161`: all T/T.
- `case_0163`: F/F; the response omits the 30-day answer and its sole citation
  cannot substantiate the material assertion that the deadline is absent.
- `case_0167`: all T/T; the special 21-day/information-dependent pathways
  directly answer why the ordinary 30-day period cannot be applied.

## Reviewed case_0169 through case_0198

- `case_0169`, `case_0171`, `case_0173`, `case_0174`, and `case_0177`: all
  T/T. The extra page-1 citations in `case_0174` repeat the transition rule.
- `case_0179`: all F/T because the question does not identify which kind of
  response is at issue.
- `case_0180`: all F/T; the workplace half is supported, but the retrieved
  financial passage concerns accessibility/complaint sourcing rather than the
  registered use of complaint data to find systemic issues and improvements.
- `case_0182` through `case_0187`: all T/T.
- `case_0189`: all F/T; the 24-hour expectation is financial-firm specific and
  the question does not identify the organisation/domain.
- `case_0192`: all F/T; each covers assistance and representatives but omits
  the requested accessibility, communication-needs, and suitable-channel
  elements.
- `case_0194`: all F/T; the variants omit the registered record detail, trends,
  and management recommendations needed to connect individual records to
  meaningful board oversight.
- `case_0195`: `03f232eb10656a8ca37d` and `4f0e8368f3efeed9f348` T/T. All
  other variants are F/T for omitting either escalation or the required fair,
  prompt, no-retaliation complaint treatment.
- `case_0196`: all T/T; the added ordinary-response passage contains the
  specific death-benefit AFCA time-limit note.
- `case_0198`: all incomplete. `5511f9186a72f79cb128` is F/F because it also
  adds unsupported accessibility/consumer-centric claims with an irrelevant
  complaint-definition citation; all other variants are F/T.

## Reviewed case_0201 through case_0218

- `case_0201`: all T/T.
- `case_0209`: all F/T. The responses replace the required second component,
  AFCA membership, with ASIC's oversight of AFCA. The cited passages support
  the narrower statements actually made.
- `case_0211`: all F/T. The conditional explanations are supported, but the
  registered case is under-specified and requires ABSTAIN rather than an
  issued answer.
- `case_0216` through `case_0218`: all T/T.

## Reviewed case_0222 through case_0229

- `case_0222` through `case_0225`: all T/T.
- `case_0227`: all T/T except `c66860345d0fa39bdd38` F/T because it
  omits the outcome-approval and financial-delegation requirement.
- `case_0229`: all T/T.

## Reviewed case_0231 through case_0239

- `case_0231`: `4efdf53b901c482d0f07` T/T. The other two variants are F/T
  because they omit that private mediation may be free or low-cost (and the
  first also omits review of the assistance request).
- `case_0232` through `case_0237`: all T/T.
- `case_0239`: F/F. It identifies the broad workplace pathway, but omits the
  registered award/agreement procedure, internal discussion, and Fair Work
  Commission route; its citations also do not establish RG 271's explicit
  employment-grievance exclusion.

## Reviewed case_0240 through case_0246

- `case_0240`: all F/T because the variants omit the requirement to give
  enough detail for the complainant to understand the decision and consider
  escalation.
- `case_0241`: all F/T. Each gives supported organisational benefits, but
  omits several registered comparison points, including Fair Work's
  productivity, retention, stress, relationship, and external-cost effects.
- `case_0242`, `case_0244`, and `case_0245`: all T/T.
- `case_0246`: all F/T because the variants omit both the sufficient-detail
  requirement and the privacy/legislative-obligation exception.

## Reviewed case_0247 through case_0257

- `case_0247`: all T/T.
- `case_0248`: `d46474c9c5c9042f112e` and `f3ffd139d14e730a78ff`
  T/T; the first two variants are F/T because they mention representation but
  omit the required independent-settlement procedure.
- `case_0250`, `case_0252`, and `case_0256`: all T/T.
- `case_0257`: all F/T. The answers give a supported generic escalation route
  but omit the registered award/agreement route and explicit Fair Work
  Commission referral, as well as review of the no-cost-assistance request.

## Reviewed case_0259 through case_0272

- `case_0259`: all F/T. The variants omit resource-adequacy review and the
  larger-firm internal-audit/qualified-independent-consultant option; several
  also omit compliance audits or senior-management review.
- `case_0262`: all F/T. The conditions and exceptions are supported, but the
  case deliberately withholds facts needed to choose yes or no and therefore
  requires ABSTAIN.
- `case_0264`: all T/T.
- `case_0269`: all T/T except `d21acd91ceef60003fbc` F/T because it omits
  the exception that can still require a written response.
- `case_0270`: all F/T. The contextual discussion is supported, but the case
  has no single corpus-wide answer and requires ABSTAIN.
- `case_0272`: all T/T.

## Reviewed case_0274 through case_0279

- `case_0274` and `case_0275`: all T/T.
- `case_0276`: `cfe70108a5b77b9cf1e0` T/T. All other variants are F/T
  because they omit the limitation-period exception, the expected 14-day
  post-response AFCA window, or both.
- `case_0277` through `case_0279`: all T/T.

## Reviewed case_0281 through case_0291

- `case_0281` and `case_0282`: all T/T.
- `case_0284`: `22dd1ed535978c1d62f9` F/F because it cites a nonexistent
  passage ID. `5c73e0298ffe2262acd6` is F/T because it omits the independent-
  settlement requirement. All other variants are T/T.
- `case_0286`: all F/T because every variant omits that customer-advocate
  review cannot block AFCA access.
- `case_0290`: all T/T.
- `case_0291`: all F/T. The pathway distinctions are supported, but the
  question deliberately leaves the pathway unspecified and requires ABSTAIN.

## Reviewed case_0295 through case_0300

- `case_0295`, `case_0299`, and `case_0300`: all T/T.

Manual blinded review is complete for all 797 unique issued-answer variants
covering all 171 case IDs that received at least one ANSWER.
