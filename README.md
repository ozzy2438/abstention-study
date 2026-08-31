# Agent Abstention Study

This repository contains a public evaluation study of when a regulatory
question-answering agent should answer, abstain, or escalate. It is an
evidence project, not a deployed product. Phase 2 is complete; model-run
results are `TODO: not measured` because Phase 3 has not started.

The protocol was frozen before data construction. The standalone repository's
first commit is the protocol freeze; the owner-provided provenance for the
earlier nested-repository freeze is `2acebcef4...`.

## Source-document distribution

The three source PDF binaries are intentionally excluded from Git. ASIC
permits regulatory-guide content under CC BY 4.0 but separately prohibits use
of its design, formatting, logo, and graphics. Fair Work licenses its material
under CC BY-NC 4.0 but excludes its logo, Commonwealth marks, website design,
and third-party material. Because the complete PDFs include presentation and
branding whose redistribution is not unambiguously covered, reproducers must
download the original files themselves.

Canonical URLs, expected local paths, retrieval timestamps, byte counts,
page counts, and SHA-256 hashes are in `corpus/manifest.json`. After download,
verify every file against that manifest before use. The committed passage file
contains extracted text with stable IDs; it does not reproduce the source PDF
layout or graphics.

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

## Rebuild the Phase 2 artifacts

Place the three downloaded PDFs at the exact `local_path` values in
`corpus/manifest.json`. Use CPython 3.12.13 and install the pinned Phase 2
dependency, then run:

```sh
python3 -m pip install -r requirements-phase2.txt
python3 corpus/build_passages.py
python3 dataset/build_cases.py
python3 dataset/build_retrieval.py
python3 dataset/audit_cases.py
```

The generated hashes must match the committed manifests and audit summary.
The full study README, including model-run commands, runtime, cost, and
measured findings, will be written only after those quantities have actually
been measured.
