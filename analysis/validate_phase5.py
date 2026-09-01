#!/usr/bin/env python3
"""Independent consistency checks for all Phase 5 outputs."""

from __future__ import annotations

import csv
import json
import math
from collections import Counter
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "results" / "runs" / "adjudicated"
FIGURES = ROOT / "analysis" / "figures"
CONFIGURATIONS = [
    f"{tier}__{strategy}"
    for tier in ("cheap", "standard", "capable")
    for strategy in ("single_pass", "self_check", "escalation")
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def close(actual: float, expected: str, label: str) -> None:
    if expected == "NA" or not math.isclose(actual, float(expected), rel_tol=0, abs_tol=5e-12):
        raise AssertionError(f"{label}: {actual} != {expected}")


def nearest_rank(values: list[int], q: float) -> int:
    values = sorted(values)
    return values[max(0, math.ceil(q * len(values)) - 1)]


def main() -> None:
    cases = {
        row["case_id"]: row
        for row in (json.loads(line) for line in (ROOT / "dataset" / "cases.jsonl").read_text().splitlines())
    }
    summary = {row["configuration"]: row for row in read_csv(FIGURES / "metrics_summary.csv")}
    reliability = read_csv(FIGURES / "reliability.csv")
    crossings = {row["configuration"]: row for row in read_csv(FIGURES / "coverage_accuracy_90_crossings.csv")}
    pareto = {row["configuration"]: row for row in read_csv(FIGURES / "cost_quality_pareto.csv")}
    pareto_20 = {row["configuration"]: row for row in read_csv(FIGURES / "cost_quality_pareto_20pct.csv")}
    confusion = read_csv(FIGURES / "abstention_confusion.csv")
    latency = {(row["scope"], row["name"]): row for row in read_csv(FIGURES / "latency_percentiles.csv")}

    total_rows = 0
    total_wrong = 0
    total_confident_wrong = 0
    exact_full_cell_cost = Decimal("0")
    all_rows: dict[str, list[dict[str, str]]] = {}
    for configuration in CONFIGURATIONS:
        rows = read_csv(RUNS / f"{configuration}.csv")
        all_rows[configuration] = rows
        assert len(rows) == 300
        assert len({row["case_id"] for row in rows}) == 300
        assert set(row["case_id"] for row in rows) == set(cases)
        assert all((ROOT / row["raw_response_path"]).is_file() for row in rows)
        assert all(row["output_type"] != "ANSWER" or row["correct"] in {"true", "false"} for row in rows)
        total_rows += len(rows)

        answers = [row for row in rows if row["output_type"] == "ANSWER"]
        wrong = [row for row in answers if row["correct"] == "false"]
        correct = len(answers) - len(wrong)
        total_wrong += len(wrong)
        total_confident_wrong += sum(float(row["confidence"]) >= 0.8 for row in wrong)
        exact_cost = sum(Decimal(row["cost_usd"]) for row in rows)
        exact_full_cell_cost += exact_cost
        observed = summary[configuration]
        assert int(observed["n"]) == 300
        assert int(observed["answers"]) == len(answers)
        assert int(observed["correct_answers"]) == correct
        assert int(observed["wrong_answers"]) == len(wrong)
        close(len(answers) / 300, observed["coverage"], f"{configuration} coverage")
        close(correct / len(answers), observed["selective_accuracy"], f"{configuration} selective accuracy")
        brier = sum((float(row["confidence"]) - (1 if row["correct"] == "true" else 0)) ** 2 for row in answers) / len(answers)
        close(brier, observed["brier_score"], f"{configuration} Brier")
        fcr = sum(float(row["confidence"]) >= 0.8 for row in wrong) / len(wrong)
        close(fcr, observed["false_confidence_rate_at_0_8"], f"{configuration} FCR")
        assert Decimal(observed["total_cost_usd"]) == exact_cost
        assert int(observed["p50_latency_ms"]) == nearest_rank([int(row["latency_ms"]) for row in rows], 0.50)
        assert int(observed["p95_latency_ms"]) == nearest_rank([int(row["latency_ms"]) for row in rows], 0.95)

        bins = [row for row in reliability if row["configuration"] == configuration]
        assert len(bins) == 10 and sum(int(row["count"]) for row in bins) == len(answers)
        ece = sum(
            int(row["count"]) / len(answers) * abs(float(row["accuracy"]) - float(row["mean_confidence"]))
            for row in bins if int(row["count"])
        )
        close(ece, observed["ece_10_equal_width"], f"{configuration} ECE")

        thresholds = sorted({0.0, 1.0, *(float(row["confidence"]) for row in answers)})
        candidates = []
        for threshold in thresholds:
            retained = [row for row in answers if float(row["confidence"]) >= threshold]
            if retained:
                accuracy = sum(row["correct"] == "true" for row in retained) / len(retained)
                if accuracy >= 0.90:
                    candidates.append((len(retained) / 300, threshold, accuracy))
        crossing = crossings[configuration]
        if candidates:
            chosen = sorted(candidates, key=lambda item: (-item[0], item[1]))[0]
            assert crossing["attained"] == "true"
            close(chosen[0], crossing["coverage_at_90"], f"{configuration} 90 crossing")
            close(chosen[1], crossing["threshold"], f"{configuration} threshold")
        else:
            assert crossing["attained"] == "false"

        category_rows = [row for row in confusion if row["configuration"] == configuration]
        assert len(category_rows) == 6
        assert sum(int(row["n"]) for row in category_rows) == 300
        for row in category_rows:
            assert sum(int(row[key]) for key in ("answer", "abstain", "escalate", "invalid")) == int(row["n"])

        ranked = sorted(answers, key=lambda row: (-float(row["confidence"]), row["case_id"]))
        point = pareto[configuration]
        assert point["target_coverage"] == "0.500000000000"
        assert int(point["target_retained_answers"]) == 150
        assert (point["attained_fixed_coverage"] == "true") == (len(ranked) >= 150)
        if len(ranked) >= 150:
            retained_correct = sum(row["correct"] == "true" for row in ranked[:150])
            assert int(point["correct_retained"]) == retained_correct
            close(retained_correct / 150, point["selective_accuracy_at_fixed_coverage"], f"{configuration} Pareto accuracy")

        point20 = pareto_20[configuration]
        assert point20["target_coverage"] == "0.200000000000"
        assert int(point20["target_retained_answers"]) == 60
        assert (point20["attained_fixed_coverage"] == "true") == (len(ranked) >= 60)
        if len(ranked) >= 60:
            retained20_correct = sum(row["correct"] == "true" for row in ranked[:60])
            assert int(point20["correct_retained"]) == retained20_correct
            close(retained20_correct / 60, point20["selective_accuracy_at_fixed_coverage"], f"{configuration} 20% Pareto accuracy")

        row = latency[("configuration", configuration)]
        values = [int(item["latency_ms"]) for item in rows]
        assert int(row["p50_latency_ms"]) == nearest_rank(values, 0.50)
        assert int(row["p95_latency_ms"]) == nearest_rank(values, 0.95)

    assert total_rows == 2700
    assert total_wrong == 220
    assert total_confident_wrong == 179
    failure_summary = read_csv(FIGURES / "failure_modes_summary.csv")
    assert len(failure_summary) == 9
    assert sum(int(row["wrong_answer_rows"]) for row in failure_summary) == total_wrong
    assert sum(int(row["confidently_wrong_rows"]) for row in failure_summary) == total_confident_wrong
    failure_detail = read_csv(FIGURES / "failure_modes.csv")
    assert len(failure_detail) == total_wrong

    for strategy in ("single_pass", "self_check", "escalation"):
        values = [
            int(row["latency_ms"])
            for configuration, rows in all_rows.items()
            if configuration.endswith(f"__{strategy}")
            for row in rows
        ]
        point = latency[("strategy", strategy)]
        assert len(values) == 900
        assert int(point["p50_latency_ms"]) == nearest_rank(values, 0.50)
        assert int(point["p95_latency_ms"]) == nearest_rank(values, 0.95)

    print(
        json.dumps(
            {
                "validated_configuration_rows": total_rows,
                "validated_raw_response_paths": total_rows,
                "wrong_issued_answers": total_wrong,
                "confidently_wrong_answers": total_confident_wrong,
                "full_cell_cost_sum_usd": format(exact_full_cell_cost, "f"),
                "status": "PASS",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
