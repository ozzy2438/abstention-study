#!/usr/bin/env python3
"""Generate the preregistered Phase 5 tables and figures.

All statistics are calculated from the immutable run rows plus blinded manual
adjudications.  Every plotted value is also written to CSV beside the figures.
"""

from __future__ import annotations

import csv
import json
import math
import sys
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from harness.scoring import compute_registered_metrics


RUNS_DIR = ROOT / "results" / "runs" / "adjudicated"
FIGURES_DIR = ROOT / "analysis" / "figures"
CASES_PATH = ROOT / "dataset" / "cases.jsonl"
RETRIEVAL_PATH = ROOT / "dataset" / "retrieval_diagnostics.json"

TIERS = ("cheap", "standard", "capable")
STRATEGIES = ("single_pass", "self_check", "escalation")
CONFIGURATIONS = [f"{tier}__{strategy}" for tier in TIERS for strategy in STRATEGIES]
CATEGORIES = (
    "answerable_clear",
    "answerable_multihop",
    "unanswerable_missing",
    "unanswerable_contradictory",
    "out_of_scope",
    "adversarial",
)
PALETTE = {
    "cheap": "#3B82F6",
    "standard": "#F59E0B",
    "capable": "#10B981",
}
LINESTYLES = {"single_pass": "-", "self_check": "--", "escalation": ":"}
OUTCOME_COLORS = {
    "ANSWER": "#2563EB",
    "ABSTAIN": "#059669",
    "ESCALATE": "#D97706",
    "INVALID": "#DC2626",
}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n"
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({key: format_value(row.get(key)) for key in fieldnames})


def format_value(value: Any) -> Any:
    if value is None:
        return "NA"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        if math.isnan(value):
            return "NA"
        return f"{value:.12f}"
    if isinstance(value, Decimal):
        return format(value, "f")
    return value


def row_bool(value: str) -> bool | None:
    if value == "true":
        return True
    if value == "false":
        return False
    if value == "":
        return None
    raise ValueError(f"Unexpected boolean encoding: {value!r}")


def nearest_rank(values: list[int], quantile: float) -> int:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(quantile * len(ordered)) - 1)]


def configuration_label(configuration: str) -> str:
    tier, strategy = configuration.split("__", 1)
    return f"{tier} / {strategy.replace('_', ' ')}"


def load_inputs() -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, str]]]]:
    cases = {row["case_id"]: row for row in read_jsonl(CASES_PATH)}
    runs: dict[str, list[dict[str, str]]] = {}
    for configuration in CONFIGURATIONS:
        path = RUNS_DIR / f"{configuration}.csv"
        rows = read_csv(path)
        if len(rows) != 300 or len({row["case_id"] for row in rows}) != 300:
            raise ValueError(f"{configuration}: expected exactly 300 unique cases")
        if any(
            row["output_type"] == "ANSWER" and row_bool(row["correct"]) is None
            for row in rows
        ):
            raise ValueError(f"{configuration}: unadjudicated answer")
        runs[configuration] = rows
    return cases, runs


def make_metrics_tables(
    cases: dict[str, dict[str, Any]], runs: dict[str, list[dict[str, str]]]
) -> dict[str, dict[str, Any]]:
    summary_rows: list[dict[str, Any]] = []
    reliability_rows: list[dict[str, Any]] = []
    metrics_by_config: dict[str, dict[str, Any]] = {}
    for configuration, rows in runs.items():
        metrics = compute_registered_metrics(rows, cases)
        metrics_by_config[configuration] = metrics
        counts = Counter(row["output_type"] for row in rows)
        answers = [row for row in rows if row["output_type"] == "ANSWER"]
        correct_answers = sum(row_bool(row["correct"]) is True for row in answers)
        tier, strategy = configuration.split("__", 1)
        summary_rows.append(
            {
                "configuration": configuration,
                "model_tier": tier,
                "strategy": strategy,
                "n": len(rows),
                "answers": counts["ANSWER"],
                "correct_answers": correct_answers,
                "wrong_answers": counts["ANSWER"] - correct_answers,
                "abstains": counts["ABSTAIN"],
                "escalates": counts["ESCALATE"],
                "invalids": counts["INVALID"],
                **{key: value for key, value in metrics.items() if key != "reliability_bins"},
            }
        )
        for bin_row in metrics["reliability_bins"]:
            reliability_rows.append({"configuration": configuration, **bin_row})

    fields = [
        "configuration", "model_tier", "strategy", "n", "answers",
        "correct_answers", "wrong_answers", "abstains", "escalates", "invalids",
        "coverage", "selective_accuracy", "brier_score", "ece_10_equal_width",
        "false_confidence_rate_at_0_8", "abstention_precision", "abstention_recall",
        "escalation_rate", "invalid_rate", "cost_per_correct_answer_usd",
        "total_cost_usd", "p50_latency_ms", "p95_latency_ms",
    ]
    write_csv(FIGURES_DIR / "metrics_summary.csv", fields, summary_rows)
    write_csv(
        FIGURES_DIR / "reliability.csv",
        ["configuration", "bin", "lower", "upper", "count", "accuracy", "mean_confidence"],
        reliability_rows,
    )
    return metrics_by_config


def make_coverage_accuracy(runs: dict[str, list[dict[str, str]]]) -> None:
    curve_rows: list[dict[str, Any]] = []
    crossing_rows: list[dict[str, Any]] = []
    fig, ax = plt.subplots(figsize=(10.5, 6.8))
    for configuration, rows in runs.items():
        answers = [row for row in rows if row["output_type"] == "ANSWER"]
        thresholds = sorted({0.0, 1.0, *(float(row["confidence"]) for row in answers)})
        points = []
        for threshold in thresholds:
            retained = [row for row in answers if float(row["confidence"]) >= threshold]
            if not retained:
                continue
            correct = sum(row_bool(row["correct"]) is True for row in retained)
            point = {
                "configuration": configuration,
                "threshold": threshold,
                "retained_answers": len(retained),
                "coverage": len(retained) / len(rows),
                "selective_accuracy": correct / len(retained),
                "correct_retained": correct,
            }
            points.append(point)
            curve_rows.append(point)
        candidates = [point for point in points if point["selective_accuracy"] >= 0.90]
        crossing = None
        if candidates:
            crossing = sorted(candidates, key=lambda p: (-p["coverage"], p["threshold"]))[0]
        baseline = max((point["coverage"] for point in points), default=0.0)
        crossing_rows.append(
            {
                "configuration": configuration,
                "attained": crossing is not None,
                "threshold": crossing["threshold"] if crossing else None,
                "coverage_at_90": crossing["coverage"] if crossing else None,
                "accuracy_at_crossing": crossing["selective_accuracy"] if crossing else None,
                "baseline_coverage": baseline,
                "coverage_cost": baseline - crossing["coverage"] if crossing else None,
            }
        )
        tier, strategy = configuration.split("__", 1)
        plot_points = sorted(points, key=lambda p: (p["coverage"], p["threshold"]))
        ax.plot(
            [point["coverage"] for point in plot_points],
            [point["selective_accuracy"] for point in plot_points],
            color=PALETTE[tier], linestyle=LINESTYLES[strategy], linewidth=2,
            alpha=0.92, label=configuration_label(configuration),
        )
        if crossing:
            ax.scatter(crossing["coverage"], crossing["selective_accuracy"], s=30,
                       color=PALETTE[tier], edgecolor="white", linewidth=0.7, zorder=4)
    ax.axhline(0.90, color="#64748B", linewidth=1, linestyle="--")
    ax.text(0.006, 0.905, "90%", color="#475569", fontsize=9)
    ax.set(xlabel="Coverage", ylabel="Selective accuracy", xlim=(0, 0.60), ylim=(0, 1.02))
    ax.set_title("Coverage–accuracy trade-off")
    ax.grid(True, alpha=0.18)
    ax.legend(ncol=3, fontsize=8, frameon=False, loc="lower left")
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "coverage_accuracy.png", dpi=180)
    plt.close(fig)
    write_csv(
        FIGURES_DIR / "coverage_accuracy.csv",
        ["configuration", "threshold", "retained_answers", "coverage", "selective_accuracy", "correct_retained"],
        curve_rows,
    )
    write_csv(
        FIGURES_DIR / "coverage_accuracy_90_crossings.csv",
        ["configuration", "attained", "threshold", "coverage_at_90", "accuracy_at_crossing", "baseline_coverage", "coverage_cost"],
        crossing_rows,
    )


def make_reliability(metrics_by_config: dict[str, dict[str, Any]]) -> None:
    fig, axes = plt.subplots(3, 3, figsize=(12, 10.2), sharex=True, sharey=True)
    for ax, configuration in zip(axes.flat, CONFIGURATIONS):
        metrics = metrics_by_config[configuration]
        bins = metrics["reliability_bins"]
        populated = [row for row in bins if row["count"]]
        ax.plot([0, 1], [0, 1], color="#94A3B8", linestyle="--", linewidth=1)
        ax.plot(
            [row["mean_confidence"] for row in populated],
            [row["accuracy"] for row in populated],
            marker="o", color=PALETTE[configuration.split("__", 1)[0]], linewidth=1.8,
        )
        for row in populated:
            ax.annotate(str(row["count"]), (row["mean_confidence"], row["accuracy"]),
                        xytext=(3, 3), textcoords="offset points", fontsize=6, color="#475569")
        ax.set_title(f"{configuration_label(configuration)}\nECE={metrics['ece_10_equal_width']:.3f}", fontsize=9)
        ax.grid(True, alpha=0.15)
    for ax in axes[-1, :]:
        ax.set_xlabel("Mean confidence")
    for ax in axes[:, 0]:
        ax.set_ylabel("Observed accuracy")
    fig.suptitle("Reliability of issued answers (bin labels are counts)", fontsize=14, y=0.995)
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "reliability_diagrams.png", dpi=180)
    plt.close(fig)


def make_abstention_confusion(
    cases: dict[str, dict[str, Any]], runs: dict[str, list[dict[str, str]]]
) -> None:
    table_rows: list[dict[str, Any]] = []
    fig, axes = plt.subplots(3, 3, figsize=(14.5, 11), sharex=True)
    for ax, configuration in zip(axes.flat, CONFIGURATIONS):
        rows = runs[configuration]
        y = list(range(len(CATEGORIES)))
        cumulative = [0.0] * len(CATEGORIES)
        for outcome in ("ANSWER", "ABSTAIN", "ESCALATE", "INVALID"):
            shares = []
            for category in CATEGORIES:
                members = [row for row in rows if cases[row["case_id"]]["category"] == category]
                counts = Counter(row["output_type"] for row in members)
                share = counts[outcome] / len(members)
                shares.append(share)
                if outcome == "ANSWER":
                    table_rows.append(
                        {
                            "configuration": configuration,
                            "category": category,
                            "expected_behaviour": cases[members[0]["case_id"]]["expected_behaviour"],
                            "n": len(members),
                            "answer": counts["ANSWER"],
                            "abstain": counts["ABSTAIN"],
                            "escalate": counts["ESCALATE"],
                            "invalid": counts["INVALID"],
                            "strict_abstention_rate": counts["ABSTAIN"] / len(members),
                        }
                    )
            ax.barh(y, shares, left=cumulative, color=OUTCOME_COLORS[outcome], label=outcome)
            cumulative = [left + value for left, value in zip(cumulative, shares)]
        ax.set_yticks(y, [category.replace("unanswerable_", "unans. ").replace("answerable_", "ans. ").replace("_", " ") for category in CATEGORIES], fontsize=7)
        ax.invert_yaxis()
        ax.set_title(configuration_label(configuration), fontsize=9)
        ax.grid(axis="x", alpha=0.14)
    for ax in axes[-1, :]:
        ax.set_xlabel("Share of category")
    handles = [plt.Rectangle((0, 0), 1, 1, color=OUTCOME_COLORS[o]) for o in OUTCOME_COLORS]
    fig.legend(handles, list(OUTCOME_COLORS), loc="lower center", ncol=4, frameon=False)
    fig.suptitle("Output outcome by case category", fontsize=14, y=0.995)
    fig.tight_layout(rect=(0, 0.04, 1, 0.98))
    fig.savefig(FIGURES_DIR / "abstention_confusion.png", dpi=180)
    plt.close(fig)
    write_csv(
        FIGURES_DIR / "abstention_confusion.csv",
        ["configuration", "category", "expected_behaviour", "n", "answer", "abstain", "escalate", "invalid", "strict_abstention_rate"],
        table_rows,
    )


def make_cost_quality(runs: dict[str, list[dict[str, str]]]) -> None:
    points: list[dict[str, Any]] = []
    for configuration, rows in runs.items():
        answers = sorted(
            (row for row in rows if row["output_type"] == "ANSWER"),
            key=lambda row: (-float(row["confidence"]), row["case_id"]),
        )
        total_cost = sum(Decimal(row["cost_usd"]) for row in rows)
        attained = len(answers) >= 150
        retained = answers[:150] if attained else []
        correct = sum(row_bool(row["correct"]) is True for row in retained)
        points.append(
            {
                "configuration": configuration,
                "attained_0_50_coverage": attained,
                "issued_answers": len(answers),
                "retained_answers": len(retained),
                "correct_retained": correct if attained else None,
                "selective_accuracy_at_0_50": correct / 150 if attained else None,
                "total_configuration_cost_usd": total_cost,
                "cost_per_correct_retained_usd": total_cost / correct if attained and correct else None,
                "dominated": None,
            }
        )
    attained_points = [point for point in points if point["attained_0_50_coverage"]]
    for point in attained_points:
        point["dominated"] = any(
            other is not point
            and other["cost_per_correct_retained_usd"] <= point["cost_per_correct_retained_usd"]
            and other["selective_accuracy_at_0_50"] >= point["selective_accuracy_at_0_50"]
            and (
                other["cost_per_correct_retained_usd"] < point["cost_per_correct_retained_usd"]
                or other["selective_accuracy_at_0_50"] > point["selective_accuracy_at_0_50"]
            )
            for other in attained_points
        )
    fig, (ax, note_ax) = plt.subplots(
        1, 2, figsize=(11.8, 6.2), gridspec_kw={"width_ratios": [3.2, 2.0]}
    )
    for point in attained_points:
        tier, strategy = point["configuration"].split("__", 1)
        marker = "x" if point["dominated"] else "o"
        ax.scatter(float(point["cost_per_correct_retained_usd"]), point["selective_accuracy_at_0_50"],
                   color=PALETTE[tier], marker=marker, s=90, linewidth=2, zorder=3)
        ax.annotate(configuration_label(point["configuration"]),
                    (float(point["cost_per_correct_retained_usd"]), point["selective_accuracy_at_0_50"]),
                    xytext=(7, 5), textcoords="offset points", fontsize=9)
    unattained = [point for point in points if not point["attained_0_50_coverage"]]
    note_ax.axis("off")
    note_ax.text(0.02, 0.96, "Coverage not attained", fontsize=11, fontweight="semibold", va="top")
    note_ax.text(0.02, 0.90, "Fewer than 150 issued answers; no extrapolation.", fontsize=8.5,
                 color="#475569", va="top")
    for index, point in enumerate(unattained):
        note_ax.text(0.04, 0.82 - index * 0.095,
                     f"{configuration_label(point['configuration'])}  ({point['issued_answers']}/150)",
                     fontsize=9, va="top")
    ax.set_xlabel("Total configuration cost / correct retained answer (USD)")
    ax.set_ylabel("Selective accuracy at 50% coverage")
    ax.set_title("Cost–quality Pareto at registered 50% coverage")
    ax.grid(True, alpha=0.18)
    fig.suptitle("Cost–quality Pareto at registered 50% coverage", fontsize=14, fontweight="semibold")
    ax.set_title("")
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    fig.savefig(FIGURES_DIR / "cost_quality_pareto.png", dpi=180)
    plt.close(fig)
    write_csv(
        FIGURES_DIR / "cost_quality_pareto.csv",
        ["configuration", "attained_0_50_coverage", "issued_answers", "retained_answers", "correct_retained", "selective_accuracy_at_0_50", "total_configuration_cost_usd", "cost_per_correct_retained_usd", "dominated"],
        points,
    )


def make_latency(runs: dict[str, list[dict[str, str]]]) -> None:
    raw_rows: list[dict[str, Any]] = []
    percentile_rows: list[dict[str, Any]] = []
    by_strategy: dict[str, list[int]] = defaultdict(list)
    for configuration, rows in runs.items():
        tier, strategy = configuration.split("__", 1)
        values = [int(row["latency_ms"]) for row in rows]
        by_strategy[strategy].extend(values)
        percentile_rows.append(
            {"scope": "configuration", "name": configuration, "n": len(values),
             "p50_latency_ms": nearest_rank(values, 0.50), "p95_latency_ms": nearest_rank(values, 0.95)}
        )
        raw_rows.extend(
            {"configuration": configuration, "model_tier": tier, "strategy": strategy,
             "case_id": row["case_id"], "latency_ms": int(row["latency_ms"])}
            for row in rows
        )
    for strategy, values in by_strategy.items():
        percentile_rows.append(
            {"scope": "strategy", "name": strategy, "n": len(values),
             "p50_latency_ms": nearest_rank(values, 0.50), "p95_latency_ms": nearest_rank(values, 0.95)}
        )
    fig, ax = plt.subplots(figsize=(9.2, 6.4))
    data = [[value / 1000 for value in by_strategy[strategy]] for strategy in STRATEGIES]
    box = ax.boxplot(data, tick_labels=[s.replace("_", " ") for s in STRATEGIES], showfliers=False,
                     patch_artist=True, widths=0.55)
    for patch, color in zip(box["boxes"], ("#60A5FA", "#FBBF24", "#34D399")):
        patch.set_facecolor(color); patch.set_alpha(0.72)
    for index, strategy in enumerate(STRATEGIES, start=1):
        values = by_strategy[strategy]
        p50 = nearest_rank(values, 0.50) / 1000
        p95 = nearest_rank(values, 0.95) / 1000
        ax.scatter(index, p95, marker="D", s=38, color="#DC2626", zorder=4)
        ax.annotate(f"p50 {p50:.1f}s\np95 {p95:.1f}s", (index, p95), xytext=(8, 0),
                    textcoords="offset points", va="center", fontsize=8)
    ax.set_yscale("log")
    ax.set_ylabel("End-to-end case latency (seconds, log scale)")
    ax.set_title("Latency distribution by strategy")
    ax.grid(axis="y", which="both", alpha=0.18)
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "latency_distribution.png", dpi=180)
    plt.close(fig)
    write_csv(FIGURES_DIR / "latency_raw.csv", ["configuration", "model_tier", "strategy", "case_id", "latency_ms"], raw_rows)
    write_csv(FIGURES_DIR / "latency_percentiles.csv", ["scope", "name", "n", "p50_latency_ms", "p95_latency_ms"], percentile_rows)


def make_retrieval_stratification(
    cases: dict[str, dict[str, Any]], runs: dict[str, list[dict[str, str]]]
) -> None:
    raw = json.loads(RETRIEVAL_PATH.read_text())
    diagnostics = raw.get("cases", raw)
    output: list[dict[str, Any]] = []
    for configuration, rows in runs.items():
        for status in ("full", "partial", "none"):
            members = [
                row for row in rows
                if cases[row["case_id"]]["expected_behaviour"] == "ANSWER"
                and diagnostics[row["case_id"]]["bm25_top8_gold_hit"] == status
            ]
            answers = [row for row in members if row["output_type"] == "ANSWER"]
            correct = sum(row_bool(row["correct"]) is True for row in answers)
            brier = (
                sum((float(row["confidence"]) - (1.0 if row_bool(row["correct"]) else 0.0)) ** 2 for row in answers) / len(answers)
                if answers else None
            )
            output.append(
                {"configuration": configuration, "bm25_top8_gold_hit": status, "answerable_cases": len(members),
                 "issued_answers": len(answers), "coverage_within_stratum": len(answers) / len(members) if members else None,
                 "selective_accuracy": correct / len(answers) if answers else None, "brier_score": brier}
            )
    write_csv(
        FIGURES_DIR / "retrieval_stratified_metrics.csv",
        ["configuration", "bm25_top8_gold_hit", "answerable_cases", "issued_answers", "coverage_within_stratum", "selective_accuracy", "brier_score"],
        output,
    )


def main() -> None:
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({
        "font.family": "DejaVu Sans", "axes.spines.top": False, "axes.spines.right": False,
        "axes.titleweight": "semibold", "figure.facecolor": "white", "axes.facecolor": "white",
    })
    cases, runs = load_inputs()
    metrics = make_metrics_tables(cases, runs)
    make_coverage_accuracy(runs)
    make_reliability(metrics)
    make_abstention_confusion(cases, runs)
    make_cost_quality(runs)
    make_latency(runs)
    make_retrieval_stratification(cases, runs)
    print(f"Wrote Phase 5 analysis artifacts to {FIGURES_DIR}")


if __name__ == "__main__":
    main()
