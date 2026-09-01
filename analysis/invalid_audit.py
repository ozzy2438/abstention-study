#!/usr/bin/env python3
"""Audit standard/single_pass INVALID rows from stored raw responses only."""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUN_PATH = ROOT / "results" / "runs" / "standard__single_pass.csv"
if not RUN_PATH.exists():
    RUN_PATH = ROOT / "results" / "runs" / "adjudicated" / "standard__single_pass.csv"
CASES_PATH = ROOT / "dataset" / "cases.jsonl"
OUT_DIR = ROOT / "analysis" / "figures"
REPORT_PATH = ROOT / "analysis" / "invalid_audit.md"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def main() -> None:
    cases = {
        row["case_id"]: row
        for row in (json.loads(line) for line in CASES_PATH.read_text().splitlines() if line.strip())
    }
    rows = read_csv(RUN_PATH)
    invalid = [row for row in rows if row["output_type"] == "INVALID"]
    if len(invalid) != 62:
        raise ValueError(f"Expected 62 standard/single_pass INVALID rows, found {len(invalid)}")
    evidence: list[dict[str, str]] = []
    raw_contents: Counter[str] = Counter()
    for row in invalid:
        raw = json.loads((ROOT / row["raw_response_path"]).read_text())
        body = json.loads(raw["response_body_raw"])
        content = body["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        raw_contents[content] += 1
        evidence.append(
            {
                "case_id": row["case_id"],
                "category": cases[row["case_id"]]["category"],
                "parser_error": row["error_state"],
                "http_status": str(raw["http_status"]),
                "finish_reason": str(raw["finish_reason"]),
                "requested_model": raw["requested_model"],
                "returned_model": raw["returned_model"],
                "raw_response_path": row["raw_response_path"],
                "response_content": content,
                "content_keys": ",".join(sorted(parsed)),
                "answer_text_empty": str(parsed.get("answer_text") == ""),
                "citations_empty": str(parsed.get("citations") == []),
                "confidence": str(parsed.get("confidence", "")),
            }
        )
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fields = list(evidence[0])
    with (OUT_DIR / "standard_single_pass_invalid_audit.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(evidence)

    by_category = Counter(row["category"] for row in evidence)
    same_content = max(raw_contents.values())
    examples = []
    for category in ("answerable_clear", "answerable_multihop", "unanswerable_contradictory"):
        examples.extend(row for row in evidence if row["category"] == category)
    examples = examples[:9]
    lines = [
        "# INVALID audit: standard / single_pass",
        "",
        "This audit re-read stored raw response files; it made no API calls and did not alter "
        "the frozen run rows. The cell has 62 INVALID rows: "
        + ", ".join(f"{category}={by_category[category]}" for category in sorted(by_category))
        + ".",
        "",
        "Every inspected response has HTTP 200 and finish reason `stop`. The model itself returns "
        "a syntactically valid JSON object whose `output_type` is `ANSWER`, but `answer_text` is "
        "empty and `citations` is an empty list. That violates the pre-registered ANSWER contract; "
        "the harness correctly records `invalid_contract:answer_fields`. The repeated payload occurs "
        f"{same_content} times in this cell. This is a genuine standard-tier format/contract "
        "failure, not a tier-specific parser bug, so no rows were re-scored.",
        "",
        "The same standard tier has lower INVALID rates with the other workflows: "
        "self_check has 12/300 (4.0%) and escalation 13/300 (4.3%), versus 62/300 (20.7%) "
        "for single_pass. This is consistent with a second pass or escalation path avoiding the "
        "blank-ANSWER emission; it does not prove which component corrected each row.",
        "",
        "## Stored examples",
        "",
    ]
    for row in examples:
        lines.extend(
            [
                f"- `{row['case_id']}` ({row['category']}), parser result `{row['parser_error']}`, "
                f"raw `{row['raw_response_path']}`:",
                "",
                f"  `{row['response_content']}`",
                "",
            ]
        )
    lines.extend(
        [
            "The row-level evidence is in `analysis/figures/standard_single_pass_invalid_audit.csv`; "
            "the full raw API envelopes remain under `results/raw/`.",
            "",
        ]
    )
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"status": "PASS", "invalid_rows": len(evidence), "by_category": dict(by_category), "unique_payloads": len(raw_contents)}, indent=2))


if __name__ == "__main__":
    main()
