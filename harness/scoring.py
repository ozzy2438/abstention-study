#!/usr/bin/env python3
"""Semantic validation and pre-adjudication scoring helpers."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any


OUTPUT_TYPES = {"ANSWER", "ABSTAIN", "ESCALATE"}
REQUIRED_KEYS = {"output_type", "answer_text", "citations", "confidence"}


@dataclass(frozen=True)
class ParsedOutput:
    output_type: str
    answer_text: str
    citations: list[str]
    confidence: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "output_type": self.output_type,
            "answer_text": self.answer_text,
            "citations": self.citations,
            "confidence": self.confidence,
        }


def parse_model_content(content: str) -> tuple[ParsedOutput | None, str | None]:
    try:
        value = json.loads(content)
    except (TypeError, json.JSONDecodeError) as exc:
        return None, f"invalid_json:{type(exc).__name__}"
    if not isinstance(value, dict) or set(value) != REQUIRED_KEYS:
        return None, "invalid_schema:keys"
    output_type = value["output_type"]
    answer_text = value["answer_text"]
    citations = value["citations"]
    confidence = value["confidence"]
    if output_type not in OUTPUT_TYPES:
        return None, "invalid_schema:output_type"
    if not isinstance(answer_text, str):
        return None, "invalid_schema:answer_text"
    if not isinstance(citations, list) or any(
        not isinstance(item, str) or not item for item in citations
    ):
        return None, "invalid_schema:citations"
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        return None, "invalid_schema:confidence_type"
    if not 0 <= float(confidence) <= 1:
        return None, "invalid_schema:confidence_range"
    if output_type == "ANSWER" and (not answer_text.strip() or not citations):
        return None, "invalid_contract:answer_fields"
    if output_type != "ANSWER" and (answer_text != "" or citations):
        return None, "invalid_contract:nonanswer_fields"
    return (
        ParsedOutput(
            output_type=output_type,
            answer_text=answer_text,
            citations=list(citations),
            confidence=float(confidence),
        ),
        None,
    )


def pre_adjudication_scores(
    case: dict[str, Any],
    parsed: ParsedOutput | None,
    retrieved_passage_ids: set[str],
) -> tuple[bool | None, bool | None, str]:
    if parsed is None:
        return False, False, "invalid model output"
    if parsed.output_type == "ABSTAIN":
        return case["expected_behaviour"] == "ABSTAIN", None, "deterministic label"
    if parsed.output_type == "ESCALATE":
        return None, None, "operational deferral"
    if not set(parsed.citations).issubset(retrieved_passage_ids):
        return False, False, "one or more citations are outside the supplied passages"
    return None, None, "manual answer and citation adjudication required"


def _row_bool(value: Any) -> bool | None:
    if value in (True, "true", "True", 1, "1"):
        return True
    if value in (False, "false", "False", 0, "0"):
        return False
    if value in (None, "", "null"):
        return None
    raise ValueError(f"Invalid boolean field: {value!r}")


def _nearest_rank(values: list[int], quantile: float) -> int:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(quantile * len(ordered)) - 1)]


def compute_registered_metrics(
    rows: list[dict[str, Any]], cases_by_id: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Compute registered scalar metrics after manual answer adjudication."""

    if not rows:
        raise ValueError("Cannot score an empty run")
    for row in rows:
        if row["case_id"] not in cases_by_id:
            raise ValueError(f"Unknown case ID: {row['case_id']}")
        if row["output_type"] == "ANSWER" and _row_bool(row.get("correct")) is None:
            raise ValueError(
                f"Manual adjudication is incomplete for {row['case_id']}"
            )

    n = len(rows)
    answered = [row for row in rows if row["output_type"] == "ANSWER"]
    abstained = [row for row in rows if row["output_type"] == "ABSTAIN"]
    escalated = [row for row in rows if row["output_type"] == "ESCALATE"]
    invalid = [row for row in rows if row["output_type"] == "INVALID"]
    correct_answers = [row for row in answered if _row_bool(row["correct"]) is True]
    wrong_answers = [row for row in answered if _row_bool(row["correct"]) is False]

    brier = None
    ece = None
    bins: list[dict[str, Any]] = []
    if answered:
        brier = sum(
            (float(row["confidence"]) - (1.0 if _row_bool(row["correct"]) else 0.0))
            ** 2
            for row in answered
        ) / len(answered)
        ece_total = 0.0
        for bin_index in range(10):
            lower = bin_index / 10
            upper = (bin_index + 1) / 10
            members = [
                row
                for row in answered
                if lower <= float(row["confidence"]) < upper
                or (bin_index == 9 and float(row["confidence"]) == 1.0)
            ]
            if members:
                accuracy = sum(
                    _row_bool(row["correct"]) is True for row in members
                ) / len(members)
                confidence = sum(float(row["confidence"]) for row in members) / len(
                    members
                )
                ece_total += len(members) / len(answered) * abs(
                    accuracy - confidence
                )
            else:
                accuracy = None
                confidence = None
            bins.append(
                {
                    "bin": bin_index + 1,
                    "lower": lower,
                    "upper": upper,
                    "count": len(members),
                    "accuracy": accuracy,
                    "mean_confidence": confidence,
                }
            )
        ece = ece_total

    should_abstain_ids = {
        case_id
        for case_id, case in cases_by_id.items()
        if case["expected_behaviour"] == "ABSTAIN"
    }
    true_abstentions = sum(
        row["case_id"] in should_abstain_ids for row in abstained
    )
    should_abstain_count = sum(
        row["case_id"] in should_abstain_ids for row in rows
    )
    costs_known = all(row.get("cost_usd") not in (None, "") for row in rows)
    total_cost = (
        sum(float(row["cost_usd"]) for row in rows) if costs_known else None
    )
    latencies = [int(row["latency_ms"]) for row in rows]

    return {
        "n": n,
        "coverage": len(answered) / n,
        "selective_accuracy": (
            len(correct_answers) / len(answered) if answered else None
        ),
        "brier_score": brier,
        "ece_10_equal_width": ece,
        "reliability_bins": bins,
        "false_confidence_rate_at_0_8": (
            sum(float(row["confidence"]) >= 0.8 for row in wrong_answers)
            / len(wrong_answers)
            if wrong_answers
            else None
        ),
        "abstention_precision": (
            true_abstentions / len(abstained) if abstained else None
        ),
        "abstention_recall": (
            true_abstentions / should_abstain_count
            if should_abstain_count
            else None
        ),
        "escalation_rate": len(escalated) / n,
        "invalid_rate": len(invalid) / n,
        "cost_per_correct_answer_usd": (
            total_cost / len(correct_answers)
            if total_cost is not None and correct_answers
            else None
        ),
        "total_cost_usd": total_cost,
        "p50_latency_ms": _nearest_rank(latencies, 0.50),
        "p95_latency_ms": _nearest_rank(latencies, 0.95),
    }
