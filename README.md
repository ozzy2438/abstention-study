# Agent Abstention Study

An evidence-first evaluation of when a regulatory QA agent should answer,
abstain, or escalate. This is a public-document study, not a product or a
claim of legal advice.

## Headline result

At the registered 50% coverage point, capable/self_check retained 82.67%
selective accuracy (124/150), while capable/single_pass retained 80.00%
(120/150). A 0.98 confidence gate on capable/self_check reached 94.31%
accuracy at 41.00% coverage, but 179 of 220 wrong issued answers across the
study still had confidence at least 0.80. Contradictory-case strict abstention
recall was 42.69% (n=19 per configuration).

The full Phase 6 report is [`report/REPORT.md`](report/REPORT.md). Figures and
their source CSVs are in [`analysis/figures/`](analysis/figures/); the manually
inspected failure atlas is [`report/failure_atlas.md`](report/failure_atlas.md).

## Reproduce the measured analysis

The three source PDF binaries are intentionally excluded from Git. ASIC
permits regulatory-guide content under CC BY 4.0 but separately prohibits use
of its design, formatting, logo, and graphics. Fair Work licenses its material
under CC BY-NC 4.0 but excludes its logo, Commonwealth marks, website design,
and third-party material. Because the complete PDFs include presentation and
branding whose redistribution is not unambiguously covered, reproducers must
download the original files themselves.

Canonical URLs, expected local paths, retrieval timestamps, byte counts, page
counts, and SHA-256 hashes are in [`corpus/manifest.json`](corpus/manifest.json).
After download, verify every file against that manifest before use. The
committed passage file contains extracted text with stable IDs; it does not
reproduce the source PDF layout or graphics.

Sources and attribution:

- Australian Securities and Investments Commission, *Regulatory Guide RG 271
  Internal dispute resolution*, © Australian Securities & Investments
  Commission. See the [ASIC copyright
  terms](https://www.asic.gov.au/about-asic/dealing-with-asic/copyright-and-linking-to-our-websites).
- Fair Work Ombudsman, *Introduction to the National Employment Standards*
  and *Effective dispute resolution best practice guide*, © Fair Work
  Ombudsman, used for this non-commercial study under CC BY-NC 4.0. See the
  [Fair Work copyright
  statement](https://www.fairwork.gov.au/website-information/copyright).

No affiliation, sponsorship, or endorsement by ASIC, the Commonwealth of
Australia, or the Fair Work Ombudsman is claimed or implied.

Place the three downloaded PDFs at the exact `local_path` values in
`corpus/manifest.json`, then run:

```sh
python3 -m venv tmp/phase3-venv
./tmp/phase3-venv/bin/pip install -r requirements-phase2.txt -r requirements-phase3.txt -r requirements-phase5.txt
./tmp/phase3-venv/bin/python corpus/build_passages.py
./tmp/phase3-venv/bin/python dataset/build_cases.py
./tmp/phase3-venv/bin/python dataset/build_retrieval.py
./tmp/phase3-venv/bin/python dataset/audit_cases.py
./tmp/phase3-venv/bin/python analysis/curves.py
./tmp/phase3-venv/bin/python analysis/failure_atlas.py
./tmp/phase3-venv/bin/python analysis/invalid_audit.py
./tmp/phase3-venv/bin/python analysis/validate_phase5.py
```

The final analysis uses the committed 2,700 adjudicated rows and stored raw
responses, so these commands do not require an API call. Validation should
report 220 wrong issued answers, 179 confidently wrong answers, final
logical-cell cost sum `$12.572095190000`, and `status: PASS`. The historical
Phase 4 ledger, including pilot and superseded operational spend, is
`$23.050594400000`; see the report for the distinction. Re-running the API
harness is a separate, billable operation.

The protocol was frozen before data construction. The standalone repository
preserves the owner-provided provenance hash for the earlier nested-repository
freeze (`2acebcef4...`) in Git history and [`PROTOCOL.md`](PROTOCOL.md).

## Honesty statement

This evaluates an agent on one fixed public regulatory corpus. The agent under
test controls neither the corpus nor the labels, and no affiliation or
endorsement by ASIC, the Commonwealth of Australia, or the Fair Work Ombudsman
is claimed. Every number comes from the committed harness, stored raw
responses, adjudicated rows, and source CSVs; limitations—including
author-written cases, no inter-rater agreement, retrieval failures, same-topic
leakage, point-in-time model versions, and the small contradictory category—are
reported plainly.
