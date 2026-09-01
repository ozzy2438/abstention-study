#!/usr/bin/env python3
"""Prepare blinded answer review packets and apply completed adjudications.

The reviewer queue intentionally omits model tier, strategy, confidence, cost,
latency, and run identity.  Exact duplicate case/answer/citation triples share a
single evidence-equivalent review decision; every issued-answer row is mapped
back to that reviewed fingerprint when adjudicated run files are written.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
RUNS_DIR = ROOT / "results" / "runs"
ADJUDICATION_DIR = ROOT / "analysis" / "adjudication"
ADJUDICATED_RUNS_DIR = RUNS_DIR / "adjudicated"
CASES_PATH = ROOT / "dataset" / "cases.jsonl"
PASSAGES_PATH = ROOT / "corpus" / "passages.jsonl"

CONFIGURATIONS = [
    f"{tier}__{strategy}"
    for tier in ("cheap", "standard", "capable")
    for strategy in ("single_pass", "self_check", "escalation")
]


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def source_paths(configuration: str) -> list[Path]:
    if configuration == "capable__self_check":
        return [
            RUNS_DIR / "full_r3__capable__self_check.csv",
            RUNS_DIR / "remaining_v1__capable__self_check.csv",
        ]
    if configuration == "capable__escalation":
        return [RUNS_DIR / "remaining_v1__capable__escalation.csv"]
    return [RUNS_DIR / f"full_r3__{configuration}.csv"]


def load_configuration(configuration: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for path in source_paths(configuration):
        for source_row_number, row in enumerate(read_csv(path), start=2):
            enriched = dict(row)
            enriched["source_run_path"] = str(path.relative_to(ROOT))
            enriched["source_row_number"] = str(source_row_number)
            rows.append(enriched)
    return rows


def parse_list(value: str) -> list[str]:
    parsed = json.loads(value)
    if not isinstance(parsed, list) or any(not isinstance(item, str) for item in parsed):
        raise ValueError(f"Expected JSON string list, received {value!r}")
    return parsed


def answer_fingerprint(row: dict[str, str]) -> str:
    payload = {
        "case_id": row["case_id"],
        "answer_text": row["answer_text"],
        "citations": parse_list(row["citations"]),
    }
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:20]


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def prepare() -> dict[str, Any]:
    cases = {row["case_id"]: row for row in read_jsonl(CASES_PATH)}
    passages = {row["passage_id"]: row for row in read_jsonl(PASSAGES_PATH)}
    grouped: dict[str, dict[str, Any]] = {}
    row_counts: Counter[str] = Counter()

    for configuration in CONFIGURATIONS:
        rows = load_configuration(configuration)
        if len(rows) != 300 or len({row["case_id"] for row in rows}) != 300:
            raise ValueError(f"{configuration} is not a complete 300-case cell")
        for row in rows:
            if row["output_type"] != "ANSWER":
                continue
            fingerprint = answer_fingerprint(row)
            row_counts[fingerprint] += 1
            if fingerprint in grouped:
                continue
            case = cases[row["case_id"]]
            citations = parse_list(row["citations"])
            cited_passages = [passages[citation] for citation in citations if citation in passages]
            gold_passages = [passages[citation] for citation in case["gold_citations"]]
            grouped[fingerprint] = {
                "adjudication_id": fingerprint,
                "case_id": row["case_id"],
                "question": case["question"],
                "category": case["category"],
                "expected_behaviour": case["expected_behaviour"],
                "gold_answer": case["gold_answer"],
                "gold_citations": case["gold_citations"],
                "case_notes": case["notes"],
                "answer_text": row["answer_text"],
                "citations": citations,
                "cited_passages": cited_passages,
                "gold_passages": gold_passages,
            }

    queue = []
    for fingerprint, record in sorted(
        grouped.items(), key=lambda item: (item[1]["case_id"], item[0])
    ):
        queue.append({**record, "issued_answer_rows": row_counts[fingerprint]})

    queue_path = ADJUDICATION_DIR / "review_queue.jsonl"
    write_jsonl(queue_path, queue)
    manifest = {
        "schema_version": "1.0.0",
        "review_blinding": {
            "omitted_fields": [
                "model_tier",
                "model_version",
                "strategy",
                "confidence",
                "latency_ms",
                "cost_usd",
                "run_id",
            ],
            "duplicate_policy": (
                "Exact duplicate case_id, answer_text, and ordered citations share one "
                "manual evidence-equivalent review decision."
            ),
        },
        "configuration_count": len(CONFIGURATIONS),
        "logical_run_rows": 2700,
        "issued_answer_rows": sum(row_counts.values()),
        "unique_review_items": len(queue),
        "review_queue_path": str(queue_path.relative_to(ROOT)),
        "review_queue_sha256": hashlib.sha256(queue_path.read_bytes()).hexdigest(),
    }
    manifest_path = ADJUDICATION_DIR / "review_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def bool_text(value: bool | None) -> str:
    if value is None:
        return ""
    return "true" if value else "false"


def expand_manual_rules() -> dict[str, Any]:
    queue_rows = read_jsonl(ADJUDICATION_DIR / "review_queue.jsonl")
    rules = json.loads((ADJUDICATION_DIR / "manual_rules.json").read_text())
    reviewed_case_ids = set(rules.get("reviewed_case_ids", []))
    defaults = rules.get("defaults_by_expected_behaviour", {})
    case_rules = rules.get("case_rules", {})
    queue_case_ids = {row["case_id"] for row in queue_rows}
    missing_cases = sorted(queue_case_ids - reviewed_case_ids)
    extra_cases = sorted(reviewed_case_ids - queue_case_ids)
    if missing_cases or extra_cases:
        raise ValueError(
            f"Manual rule coverage mismatch: missing_cases={missing_cases}, extra_cases={extra_cases}"
        )
    if set(defaults) != {"ANSWER", "ABSTAIN"}:
        raise ValueError("Manual rules require ANSWER and ABSTAIN defaults")
    unknown_case_rules = sorted(set(case_rules) - queue_case_ids)
    if unknown_case_rules:
        raise ValueError(f"Unknown case_rules: {unknown_case_rules}")

    decisions: list[dict[str, Any]] = []
    for item in queue_rows:
        decision = dict(defaults[item["expected_behaviour"]])
        case_rule = case_rules.get(item["case_id"], {})
        decision.update(case_rule.get("default", {}))
        decision.update(case_rule.get("overrides", {}).get(item["adjudication_id"], {}))
        decisions.append(
            {
                "adjudication_id": item["adjudication_id"],
                "correct": decision["correct"],
                "citation_valid": decision["citation_valid"],
                "reason": decision.get("reason", ""),
            }
        )
    decisions_path = ADJUDICATION_DIR / "decisions.jsonl"
    write_jsonl(decisions_path, decisions)
    return {
        "reviewed_case_count": len(reviewed_case_ids),
        "exception_case_rule_count": len(case_rules),
        "decision_count": len(decisions),
        "decisions_path": str(decisions_path.relative_to(ROOT)),
        "decisions_sha256": hashlib.sha256(decisions_path.read_bytes()).hexdigest(),
    }


def apply_decisions() -> dict[str, Any]:
    queue = {row["adjudication_id"]: row for row in read_jsonl(ADJUDICATION_DIR / "review_queue.jsonl")}
    decisions_rows = read_jsonl(ADJUDICATION_DIR / "decisions.jsonl")
    decisions = {row["adjudication_id"]: row for row in decisions_rows}
    if len(decisions) != len(decisions_rows):
        raise ValueError("Duplicate adjudication_id in decisions.jsonl")
    missing = sorted(set(queue) - set(decisions))
    extra = sorted(set(decisions) - set(queue))
    if missing or extra:
        raise ValueError(f"Adjudication coverage mismatch: missing={len(missing)}, extra={len(extra)}")
    for adjudication_id, decision in decisions.items():
        if not isinstance(decision.get("correct"), bool):
            raise ValueError(f"{adjudication_id}: correct must be boolean")
        if not isinstance(decision.get("citation_valid"), bool):
            raise ValueError(f"{adjudication_id}: citation_valid must be boolean")
        if decision["correct"] and not decision["citation_valid"]:
            raise ValueError(f"{adjudication_id}: a correct answer must have valid citations")
        if (not decision["correct"] or not decision["citation_valid"]) and not str(
            decision.get("reason", "")
        ).strip():
            raise ValueError(f"{adjudication_id}: false decisions require a reason")

    ADJUDICATED_RUNS_DIR.mkdir(parents=True, exist_ok=True)
    summary: dict[str, Any] = {"schema_version": "1.0.0", "configurations": {}}
    total_rows = 0
    total_answers = 0
    for configuration in CONFIGURATIONS:
        rows = load_configuration(configuration)
        output_rows: list[dict[str, str]] = []
        for row in rows:
            output = dict(row)
            output["adjudication_id"] = ""
            output["adjudication_reason"] = ""
            output_type = row["output_type"]
            if output_type == "ANSWER":
                adjudication_id = answer_fingerprint(row)
                decision = decisions[adjudication_id]
                output["correct"] = bool_text(decision["correct"])
                output["citation_valid"] = bool_text(decision["citation_valid"])
                output["adjudication_id"] = adjudication_id
                output["adjudication_reason"] = str(decision.get("reason", ""))
                output["scoring_status"] = "manually_adjudicated"
                output["scoring_note"] = "blind answer-fingerprint review"
                total_answers += 1
            elif output_type == "ABSTAIN":
                expected = cases_by_id()[row["case_id"]]["expected_behaviour"]
                output["correct"] = bool_text(expected == "ABSTAIN")
                output["citation_valid"] = ""
                output["scoring_status"] = "deterministic"
                output["scoring_note"] = "literal abstention vs frozen expected behaviour"
            elif output_type == "ESCALATE":
                output["correct"] = ""
                output["citation_valid"] = ""
                output["scoring_status"] = "deterministic"
                output["scoring_note"] = "operational deferral"
            elif output_type == "INVALID":
                output["correct"] = "false"
                output["citation_valid"] = "false"
                output["scoring_status"] = "deterministic"
                output["scoring_note"] = "invalid model output"
            else:
                raise ValueError(f"Unexpected output_type {output_type!r}")
            output_rows.append(output)

        output_path = ADJUDICATED_RUNS_DIR / f"{configuration}.csv"
        with output_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(output_rows[0]), lineterminator="\n")
            writer.writeheader()
            writer.writerows(output_rows)
        total_rows += len(output_rows)
        summary["configurations"][configuration] = {
            "rows": len(output_rows),
            "issued_answers": sum(row["output_type"] == "ANSWER" for row in output_rows),
            "path": str(output_path.relative_to(ROOT)),
            "sha256": hashlib.sha256(output_path.read_bytes()).hexdigest(),
        }

    decisions_path = ADJUDICATION_DIR / "decisions.jsonl"
    summary.update(
        {
            "logical_run_rows": total_rows,
            "issued_answer_rows": total_answers,
            "decision_count": len(decisions),
            "decisions_path": str(decisions_path.relative_to(ROOT)),
            "decisions_sha256": hashlib.sha256(decisions_path.read_bytes()).hexdigest(),
        }
    )
    summary_path = ADJUDICATION_DIR / "adjudication_manifest.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    return summary


_CASES_CACHE: dict[str, dict[str, Any]] | None = None


def cases_by_id() -> dict[str, dict[str, Any]]:
    global _CASES_CACHE
    if _CASES_CACHE is None:
        _CASES_CACHE = {row["case_id"]: row for row in read_jsonl(CASES_PATH)}
    return _CASES_CACHE


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("prepare", "expand", "apply"))
    args = parser.parse_args()
    if args.command == "prepare":
        result = prepare()
    elif args.command == "expand":
        result = expand_manual_rules()
    else:
        result = apply_decisions()
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
