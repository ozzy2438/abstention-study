#!/usr/bin/env python3
"""Build the manually curated failure atlas from adjudicated run rows."""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RUNS_DIR = ROOT / "results" / "runs" / "adjudicated"
FIGURES_DIR = ROOT / "analysis" / "figures"
REPORT_PATH = ROOT / "report" / "failure_atlas.md"
CASES_PATH = ROOT / "dataset" / "cases.jsonl"

CONFIGURATIONS = [
    f"{tier}__{strategy}"
    for tier in ("cheap", "standard", "capable")
    for strategy in ("single_pass", "self_check", "escalation")
]

CASE_MODES = {
    "Dropped a material exception or qualifier": {
        "case_0021", "case_0049", "case_0104", "case_0158", "case_0240",
        "case_0246", "case_0269", "case_0276", "case_0286",
    },
    "Truncated a multihop checklist": {
        "case_0038", "case_0054", "case_0080", "case_0128", "case_0145",
        "case_0151", "case_0180", "case_0192", "case_0194", "case_0195",
        "case_0198", "case_0227", "case_0241", "case_0259",
    },
    "Substituted an adjacent procedural route": {
        "case_0248", "case_0257", "case_0284",
    },
    "Collapsed distinct resolution mechanisms": {
        "case_0014", "case_0074", "case_0138", "case_0231",
    },
    "Returned the opposite polarity": {"case_0047", "case_0099"},
    "Confused institution or role labels": {"case_0209"},
    "Stopped before the external-escalation duty": {"case_0089"},
}

MODE_ORDER = [
    "Answered an under-specified question",
    "Truncated a multihop checklist",
    "Dropped a material exception or qualifier",
    "Unsupported citation or invented specificity",
    "Collapsed distinct resolution mechanisms",
    "Substituted an adjacent procedural route",
    "Stopped before the external-escalation duty",
    "Returned the opposite polarity",
    "Confused institution or role labels",
]

MODE_DESCRIPTIONS = {
    "Answered an under-specified question": (
        "The model selected one plausible regime, actor, complaint type, or procedural stage "
        "even though the question withheld the fact needed to choose. These were registered "
        "ABSTAIN cases; a conditional explanation did not satisfy the output contract."
    ),
    "Truncated a multihop checklist": (
        "The answer retrieved a real part of a multi-passage requirement but stopped before "
        "one or more material duties, capabilities, governance checks, or comparison points."
    ),
    "Dropped a material exception or qualifier": (
        "The headline rule was usually right, but an exception, timing condition, privacy "
        "constraint, or escalation protection that changes how the rule can be used was absent."
    ),
    "Unsupported citation or invented specificity": (
        "The answer cited a nonexistent, irrelevant, or passage-boundary-mismatched source, or "
        "gave a specific number/rule that the cited passage did not support. This mode takes "
        "priority when a row also had a content omission."
    ),
    "Collapsed distinct resolution mechanisms": (
        "The response described one branch—often arbitration—without preserving the registered "
        "contrast with mediation, conciliation, or another outcome-control mechanism."
    ),
    "Substituted an adjacent procedural route": (
        "The model gave a nearby best-practice or representation step but not the applicable "
        "award/agreement route, independent settlement requirement, or Commission referral."
    ),
    "Stopped before the external-escalation duty": (
        "The answer mentioned AFCA referral but omitted the mandatory right-to-escalate notice "
        "or AFCA contact details required in the registered answer."
    ),
    "Returned the opposite polarity": (
        "A leading yes/no contradicted the rule that followed. The supporting explanation did "
        "not cure the operationally dangerous first-token answer."
    ),
    "Confused institution or role labels": (
        "The response replaced a required institutional relationship—AFCA membership—with a "
        "nearby but different concept, ASIC oversight of AFCA."
    ),
}

EXAMPLES = {
    "Answered an under-specified question": ("standard__single_pass", "case_0189"),
    "Truncated a multihop checklist": ("capable__escalation", "case_0259"),
    "Dropped a material exception or qualifier": ("cheap__self_check", "case_0269"),
    "Unsupported citation or invented specificity": ("standard__self_check", "case_0071"),
    "Collapsed distinct resolution mechanisms": ("capable__single_pass", "case_0074"),
    "Substituted an adjacent procedural route": ("cheap__self_check", "case_0248"),
    "Stopped before the external-escalation duty": ("standard__escalation", "case_0089"),
    "Returned the opposite polarity": ("capable__escalation", "case_0099"),
    "Confused institution or role labels": ("capable__self_check", "case_0209"),
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def classify(row: dict[str, str], case: dict[str, Any]) -> str:
    if row["citation_valid"] == "false":
        return "Unsupported citation or invented specificity"
    if case["expected_behaviour"] == "ABSTAIN":
        return "Answered an under-specified question"
    matches = [mode for mode, case_ids in CASE_MODES.items() if row["case_id"] in case_ids]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one failure mode for {row['case_id']}: {matches}")
    return matches[0]


def markdown_quote(text: str) -> str:
    return "\n".join(f"> {line}" if line else ">" for line in text.splitlines())


def main() -> None:
    cases = {
        row["case_id"]: row
        for row in (json.loads(line) for line in CASES_PATH.read_text().splitlines() if line.strip())
    }
    failures: list[dict[str, Any]] = []
    source_rows: dict[tuple[str, str], dict[str, str]] = {}
    for configuration in CONFIGURATIONS:
        for row in read_csv(RUNS_DIR / f"{configuration}.csv"):
            source_rows[(configuration, row["case_id"])] = row
            if row["output_type"] != "ANSWER" or row["correct"] != "false":
                continue
            mode = classify(row, cases[row["case_id"]])
            failures.append(
                {
                    "configuration": configuration,
                    "case_id": row["case_id"],
                    "category": cases[row["case_id"]]["category"],
                    "confidence": float(row["confidence"]),
                    "confidently_wrong_at_0_8": float(row["confidence"]) >= 0.8,
                    "citation_valid": row["citation_valid"] == "true",
                    "failure_mode": mode,
                    "raw_response_path": row["raw_response_path"],
                    "adjudication_reason": row["adjudication_reason"],
                }
            )

    if len(failures) != 220:
        raise ValueError(f"Expected 220 wrong issued answers, found {len(failures)}")
    if sum(row["confidently_wrong_at_0_8"] for row in failures) != 179:
        raise ValueError("Confidently-wrong count drifted from the reviewed rows")

    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    detail_path = FIGURES_DIR / "failure_modes.csv"
    with detail_path.open("w", newline="", encoding="utf-8") as handle:
        fields = [
            "configuration", "case_id", "category", "confidence",
            "confidently_wrong_at_0_8", "citation_valid", "failure_mode",
            "raw_response_path", "adjudication_reason",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(failures)

    counts = Counter(row["failure_mode"] for row in failures)
    confident_counts = Counter(
        row["failure_mode"] for row in failures if row["confidently_wrong_at_0_8"]
    )
    summary_path = FIGURES_DIR / "failure_modes_summary.csv"
    with summary_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["failure_mode", "wrong_answer_rows", "share_of_wrong_answers", "confidently_wrong_rows"],
            lineterminator="\n",
        )
        writer.writeheader()
        for mode in MODE_ORDER:
            writer.writerow(
                {
                    "failure_mode": mode,
                    "wrong_answer_rows": counts[mode],
                    "share_of_wrong_answers": f"{counts[mode] / len(failures):.12f}",
                    "confidently_wrong_rows": confident_counts[mode],
                }
            )

    lines = [
        "# Failure atlas",
        "",
        "This atlas covers every one of the **220 wrong issued-answer rows** across the nine "
        "completed configurations. Of those, **179** carried confidence at or above `0.80`. "
        "The blinded answer review preceded this grouping; failure modes were assigned only "
        "after correctness and citation validity were fixed.",
        "",
        "The modes are mutually exclusive primary labels so their counts sum to 220. Some rows "
        "could reasonably fit more than one mode; citation failure takes priority, then a "
        "registered should-abstain error, then the content taxonomy below. Counts are row counts, "
        "not unique questions, because each configuration is a measured decision.",
        "",
        "| Failure mode | Wrong rows | Share | Confidence >= 0.80 |",
        "|---|---:|---:|---:|",
    ]
    for mode in MODE_ORDER:
        lines.append(
            f"| {mode} | {counts[mode]} | {counts[mode] / len(failures):.1%} | {confident_counts[mode]} |"
        )
    lines.extend(["", "## Modes and real examples", ""])

    for index, mode in enumerate(MODE_ORDER, start=1):
        configuration, case_id = EXAMPLES[mode]
        row = source_rows[(configuration, case_id)]
        case = cases[case_id]
        if not (row["output_type"] == "ANSWER" and row["correct"] == "false"):
            raise ValueError(f"Registered example is not a wrong answer: {configuration}/{case_id}")
        lines.extend(
            [
                f"### {index}. {mode}",
                "",
                f"**Frequency:** {counts[mode]} of 220 wrong answers ({counts[mode] / len(failures):.1%}); "
                f"{confident_counts[mode]} were confidently wrong.",
                "",
                MODE_DESCRIPTIONS[mode],
                "",
                f"**Example:** `{configuration}`, `{case_id}` (`{case['category']}`), confidence "
                f"`{float(row['confidence']):.2f}`. Raw evidence: `{row['raw_response_path']}`.",
                "",
                "Question:",
                "",
                markdown_quote(case["question"]),
                "",
                "Actual model answer:",
                "",
                markdown_quote(row["answer_text"]),
                "",
                f"Why it failed: {row['adjudication_reason']}",
                "",
            ]
        )

    lines.extend(
        [
            "## Reading the atlas",
            "",
            "The dominant pattern is not random factual ignorance. It is release-control failure: "
            "the model often had a relevant passage and produced a fluent partial rule, but did "
            "not stop when scope was unresolved or when the retrieved evidence did not cover every "
            "material limb. The high-confidence counts show why selective release must be measured "
            "rather than inferred from answer quality alone.",
            "",
            "The underlying row-level assignments are in `analysis/figures/failure_modes.csv`; "
            "aggregate counts are in `analysis/figures/failure_modes_summary.csv`.",
            "",
        ]
    )
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {REPORT_PATH} with {len(failures)} classified wrong answers")


if __name__ == "__main__":
    main()
