#!/usr/bin/env python3
"""Project full-matrix spend from the completed pilot without API calls.

The projection fixes the full dataset's realised category counts, rather than
scaling the 20-case pilot by 15. It reports cache-inclusive pilot behaviour and
an all-fresh-token sensitivity bound separately, because server-side prompt
cache hits are provider-reported observations rather than a reproducible local
guarantee for a future invocation.
"""

from __future__ import annotations

import csv
import json
import random
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from harness.models import ModelTier, cost_usd, load_model_tiers, sha256_path
from harness.run import (
    PromptFactory,
    RESULTS_RUNS_DIR,
    TokenEstimator,
    atomic_write_json,
    load_and_validate_artifacts,
    project_matrix,
)
from harness.strategies import STRATEGY_ORDER


PILOT_CASES_PATH = REPO_ROOT / "dataset" / "pilot_cases.json"
OUTPUT_PATH = RESULTS_RUNS_DIR / "full_cost_projection_prephase4.json"
CATEGORIES = (
    "answerable_clear",
    "answerable_multihop",
    "unanswerable_missing",
    "unanswerable_contradictory",
    "out_of_scope",
    "adversarial",
)
TIERS = ("cheap", "standard", "capable")
SCALE = 10**12
ITERATIONS = 5_000
SEED = 20260831


def decimal_to_pico(value: Decimal) -> int:
    scaled = value * SCALE
    if scaled != scaled.to_integral_value():
        raise ValueError(f"Value does not fit the recorded 12-decimal scale: {value}")
    return int(scaled)


def pico_text(value: int) -> str:
    sign = "-" if value < 0 else ""
    value = abs(value)
    return f"{sign}{value // SCALE}.{value % SCALE:012d}"


def quantile(values: list[int], probability: float) -> int:
    """Deterministic linear percentile, matching the recorded method exactly."""
    if not values:
        raise ValueError("Cannot calculate a percentile of no values")
    ordered = sorted(values)
    index = (len(ordered) - 1) * probability
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = Decimal(str(index - lower))
    return int(
        Decimal(ordered[lower])
        + (Decimal(ordered[upper]) - Decimal(ordered[lower])) * fraction
    )


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def raw_row_observation(
    row: dict[str, str], models_by_version: dict[str, ModelTier]
) -> dict[str, int]:
    raw_paths = json.loads(row["raw_response_paths"])
    if not raw_paths:
        raise ValueError(f"No raw response paths for {row['case_id']}")
    billed = 0
    all_fresh = 0
    fallback_triggered = 0
    for raw_path_text in raw_paths:
        raw_path = REPO_ROOT / raw_path_text
        envelope = json.loads(raw_path.read_text(encoding="utf-8"))
        model_version = envelope.get("returned_model")
        model = models_by_version.get(model_version)
        if model is None:
            raise ValueError(f"Unrecognised returned model in {raw_path}: {model_version}")
        usage = envelope.get("usage")
        if not isinstance(usage, dict):
            raise ValueError(f"Missing usage in {raw_path}")
        details = usage.get("prompt_tokens_details")
        if not isinstance(details, dict) or not isinstance(details.get("cached_tokens"), int):
            raise ValueError(f"Missing cached-token split in {raw_path}")
        if envelope.get("cost_usd") is None:
            raise ValueError(f"Missing billed cost in {raw_path}")
        billed += decimal_to_pico(Decimal(str(envelope["cost_usd"])))
        all_fresh += decimal_to_pico(
            cost_usd(
                model,
                int(usage["prompt_tokens"]),
                int(usage["completion_tokens"]),
                cached_input_tokens=0,
            )
        )
        if envelope.get("call_role") == "fallback":
            fallback_triggered = 1
    row_billed = decimal_to_pico(Decimal(row["cost_usd"]))
    if billed != row_billed:
        raise ValueError(
            f"Raw billed costs do not equal the run row for {row['case_id']}: "
            f"{pico_text(billed)} != {pico_text(row_billed)}"
        )
    return {
        "billed_pico_usd": billed,
        "all_fresh_pico_usd": all_fresh,
        "fallback_triggered": fallback_triggered,
        "final_escalate": int(row["output_type"] == "ESCALATE"),
    }


def bootstrap_configuration(
    observations: dict[str, list[dict[str, int]]],
    full_counts: dict[str, int],
    rng: random.Random,
) -> tuple[dict[str, Any], list[int], list[int], list[int], list[int]]:
    category_summary: dict[str, Any] = {}
    point_billed = 0
    point_fresh = 0
    point_fallback = 0
    point_final_escalate = 0
    for category in CATEGORIES:
        category_observations = observations[category]
        target_count = full_counts[category]
        pilot_count = len(category_observations)
        billed_sum = sum(item["billed_pico_usd"] for item in category_observations)
        fresh_sum = sum(item["all_fresh_pico_usd"] for item in category_observations)
        fallback_sum = sum(item["fallback_triggered"] for item in category_observations)
        final_escalate_sum = sum(
            item["final_escalate"] for item in category_observations
        )
        point_billed += target_count * billed_sum // pilot_count
        point_fresh += target_count * fresh_sum // pilot_count
        point_fallback += target_count * fallback_sum / pilot_count
        point_final_escalate += target_count * final_escalate_sum / pilot_count
        category_summary[category] = {
            "pilot_cases": pilot_count,
            "pilot_fallback_trigger_count": fallback_sum,
            "full_cases": target_count,
            "pilot_mean_billed_cost_usd": pico_text(billed_sum // pilot_count),
            "pilot_mean_all_fresh_cost_usd": pico_text(fresh_sum // pilot_count),
            "pilot_fallback_trigger_rate": f"{fallback_sum / pilot_count:.12f}",
            "pilot_final_ESCALATE_rate": f"{final_escalate_sum / pilot_count:.12f}",
            "projected_fallback_calls": f"{target_count * fallback_sum / pilot_count:.12f}",
            "projected_final_ESCALATE_rows": (
                f"{target_count * final_escalate_sum / pilot_count:.12f}"
            ),
        }

    sampled_billed: list[int] = []
    sampled_fresh: list[int] = []
    sampled_fallback: list[int] = []
    sampled_final_escalate: list[int] = []
    for _ in range(ITERATIONS):
        billed_total = 0
        fresh_total = 0
        fallback_total = 0
        final_escalate_total = 0
        for category in CATEGORIES:
            values = observations[category]
            for _ in range(full_counts[category]):
                sample = rng.choice(values)
                billed_total += sample["billed_pico_usd"]
                fresh_total += sample["all_fresh_pico_usd"]
                fallback_total += sample["fallback_triggered"]
                final_escalate_total += sample["final_escalate"]
        sampled_billed.append(billed_total)
        sampled_fresh.append(fresh_total)
        sampled_fallback.append(fallback_total)
        sampled_final_escalate.append(final_escalate_total)

    summary = {
        "category_strata": category_summary,
        "cost_projection_usd": {
            "point_estimate_cache_inclusive": pico_text(point_billed),
            "bootstrap_p05_cache_inclusive": pico_text(quantile(sampled_billed, 0.05)),
            "bootstrap_p95_cache_inclusive": pico_text(quantile(sampled_billed, 0.95)),
            "point_estimate_all_fresh": pico_text(point_fresh),
            "bootstrap_p05_all_fresh": pico_text(quantile(sampled_fresh, 0.05)),
            "bootstrap_p95_all_fresh": pico_text(quantile(sampled_fresh, 0.95)),
            "cache_sensitivity_envelope_p05_billed_to_p95_fresh": [
                pico_text(quantile(sampled_billed, 0.05)),
                pico_text(quantile(sampled_fresh, 0.95)),
            ],
        },
        "fallback_trigger_projection": {
            "point_estimate_calls": f"{point_fallback:.12f}",
            "bootstrap_p05_calls": quantile(sampled_fallback, 0.05),
            "bootstrap_p95_calls": quantile(sampled_fallback, 0.95),
        },
        "final_ESCALATE_label_projection": {
            "point_estimate_rows": f"{point_final_escalate:.12f}",
            "bootstrap_p05_rows": quantile(sampled_final_escalate, 0.05),
            "bootstrap_p95_rows": quantile(sampled_final_escalate, 0.95),
        },
    }
    return (
        summary,
        sampled_billed,
        sampled_fresh,
        sampled_fallback,
        sampled_final_escalate,
    )


def main() -> None:
    artifacts = load_and_validate_artifacts("full")
    cases_by_id = {case["case_id"]: case for case in artifacts["cases"]}
    full_counts = dict(Counter(case["category"] for case in artifacts["cases"]))
    if tuple(sorted(full_counts)) != tuple(sorted(CATEGORIES)):
        raise ValueError("Full dataset does not contain exactly the registered categories")
    pilot = json.loads(PILOT_CASES_PATH.read_text(encoding="utf-8"))
    pilot_counts = dict(Counter(cases_by_id[case_id]["category"] for case_id in pilot["case_ids"]))
    models = load_model_tiers()
    models_by_version = {model.model_version: model for model in models.values()}

    factory = PromptFactory(artifacts["retrieval_by_id"], artifacts["passages_by_id"])
    estimator = TokenEstimator(artifacts["config"])
    conservative_projection = project_matrix(
        artifacts["cases"], factory, estimator, artifacts["config"], models
    )

    configurations: dict[str, Any] = {}
    total_billed_samples = [0] * ITERATIONS
    total_fresh_samples = [0] * ITERATIONS
    total_fallback_samples = [0] * ITERATIONS
    total_final_escalate_samples = [0] * ITERATIONS
    for config_index, tier in enumerate(TIERS):
        for strategy_index, strategy in enumerate(STRATEGY_ORDER):
            key = f"{tier}__{strategy}"
            path = RESULTS_RUNS_DIR / f"pilot__{tier}__{strategy}.csv"
            with path.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            if {row["case_id"] for row in rows} != set(pilot["case_ids"]):
                raise ValueError(f"Pilot run does not cover the fixed pilot cases: {path}")
            observations: dict[str, list[dict[str, int]]] = defaultdict(list)
            for row in rows:
                category = cases_by_id[row["case_id"]]["category"]
                observations[category].append(raw_row_observation(row, models_by_version))
            if set(observations) != set(CATEGORIES):
                raise ValueError(f"Pilot category coverage is incomplete in {path}")
            result, billed, fresh, fallback, final_escalate = bootstrap_configuration(
                observations,
                full_counts,
                random.Random(SEED + config_index * 100 + strategy_index),
            )
            result["pilot_run_csv"] = path.relative_to(REPO_ROOT).as_posix()
            result["pilot_run_csv_sha256"] = sha256_path(path)
            configurations[key] = result
            for index in range(ITERATIONS):
                total_billed_samples[index] += billed[index]
                total_fresh_samples[index] += fresh[index]
                total_fallback_samples[index] += fallback[index]
                total_final_escalate_samples[index] += final_escalate[index]

    point_billed = sum(
        decimal_to_pico(
            Decimal(item["cost_projection_usd"]["point_estimate_cache_inclusive"])
        )
        for item in configurations.values()
    )
    point_fresh = sum(
        decimal_to_pico(Decimal(item["cost_projection_usd"]["point_estimate_all_fresh"]))
        for item in configurations.values()
    )
    escalation_keys = tuple(f"{tier}__escalation" for tier in TIERS)
    escalation_row_count = len(artifacts["cases"]) * len(escalation_keys)
    aggregate_fallback_calls = sum(
        Decimal(configurations[key]["fallback_trigger_projection"]["point_estimate_calls"])
        for key in escalation_keys
    )
    contradictory_full_cases = full_counts["unanswerable_contradictory"]
    contradictory_flip_one_cell_calls = aggregate_fallback_calls + contradictory_full_cases
    contradictory_flip_all_cells_calls = (
        aggregate_fallback_calls
        + contradictory_full_cases * len(escalation_keys)
    )
    per_category_escalation = {}
    for category in CATEGORIES:
        per_category_escalation[category] = {
            "pilot_cases": pilot_counts[category],
            "by_escalation_configuration": {
                key: {
                    "pilot_fallback_trigger_count": configurations[key][
                        "category_strata"
                    ][category]["pilot_fallback_trigger_count"],
                    "pilot_fallback_trigger_rate": configurations[key][
                        "category_strata"
                    ][category]["pilot_fallback_trigger_rate"],
                    "projected_fallback_calls": configurations[key][
                        "category_strata"
                    ][category]["projected_fallback_calls"],
                }
                for key in escalation_keys
            },
        }
    output = {
        "schema_version": "1.0.0",
        "created_at_utc": datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z"),
        "method": {
            "type": "category-stratified empirical bootstrap",
            "seed": SEED,
            "iterations": ITERATIONS,
            "full_category_counts_fixed": full_counts,
            "pilot_category_counts": pilot_counts,
            "pilot_proportionally_stratified": False,
            "pilot_selection_note": (
                "The frozen pilot was a deterministic uniform 20-case sample, not a "
                "category-stratified quota sample; its category counts are therefore "
                "used only as within-category empirical observations."
            ),
            "cache_sensitivity_note": (
                "Cache-inclusive values preserve observed provider cache discounts. "
                "All-fresh values reprice the same raw calls with cached input tokens set "
                "to zero. The envelope is a cache-sensitivity range, not a confidence "
                "interval for future model behaviour."
            ),
            "fallback_definition": (
                "A fallback trigger is a second strategy call with call_role=fallback; "
                "it is distinct from a final output label of ESCALATE."
            ),
        },
        "conservative_preflight_maximum": conservative_projection,
        "conservative_preflight_assumptions": {
            "classification": (
                "conservative successful-first-attempt budget projection, not a "
                "realistic spend estimate or a retry-inclusive completion guarantee"
            ),
            "pricing_formula": (
                "cost_usd(model, input_tokens, output_tokens, cached_input_tokens=0) "
                "= (input_tokens * input_per_1m_tokens + output_tokens * "
                "output_per_1m_tokens) / 1_000_000"
            ),
            "cached_input_tokens": 0,
            "output_tokens_per_call": int(artifacts["config"]["max_completion_tokens"]),
            "optional_calls": "every critic and every escalation fallback is charged",
            "retry_attempts": (
                "not included in this logical-call projection; the runtime hard cap "
                "checks every retry attempt before it is sent"
            ),
            "self_check_critic_input": (
                "the registered critic prompt estimate plus a full 1,200-token primary "
                "response reserve"
            ),
            "escalation_model_assignment": {
                "cheap__escalation": ["cheap", "cheap"],
                "standard__escalation": ["cheap", "standard"],
                "capable__escalation": ["cheap", "capable"],
            },
            "price_table_per_1m_tokens": {
                tier: {
                    "model_version": model.model_version,
                    "input": str(model.input_per_1m_tokens),
                    "cached_input": str(model.cached_input_per_1m_tokens),
                    "output": str(model.output_per_1m_tokens),
                }
                for tier, model in models.items()
            },
            "maximum_calls_all_matrix": conservative_projection["maximum_calls"],
        },
        "escalation_trigger_projection": {
            "definition": (
                "A trigger is a raw API envelope with call_role=fallback; the denominator "
                "is all 900 rows in the three escalation configurations."
            ),
            "escalation_row_denominator": escalation_row_count,
            "point_estimate_fallback_calls": f"{aggregate_fallback_calls:.12f}",
            "point_estimate_trigger_rate": f"{aggregate_fallback_calls / escalation_row_count:.12f}",
            "per_category": per_category_escalation,
            "contradictory_single_case_sensitivity": {
                "warning": (
                    "unanswerable_contradictory has one pilot case; its observed fallback "
                    "count is 0/1 in each escalation configuration."
                ),
                "if_one_of_three_cell_outcomes_flips": {
                    "incremental_fallback_calls": contradictory_full_cases,
                    "trigger_rate_shift": f"{Decimal(contradictory_full_cases) / escalation_row_count:.12f}",
                    "resulting_trigger_rate": f"{contradictory_flip_one_cell_calls / escalation_row_count:.12f}",
                },
                "if_all_three_cell_outcomes_flip": {
                    "incremental_fallback_calls": contradictory_full_cases
                    * len(escalation_keys),
                    "trigger_rate_shift": f"{Decimal(contradictory_full_cases * len(escalation_keys)) / escalation_row_count:.12f}",
                    "resulting_trigger_rate": f"{contradictory_flip_all_cells_calls / escalation_row_count:.12f}",
                },
            },
        },
        "configurations": configurations,
        "all_matrix": {
            "cost_projection_usd": {
                "point_estimate_cache_inclusive": pico_text(point_billed),
                "bootstrap_p05_cache_inclusive": pico_text(
                    quantile(total_billed_samples, 0.05)
                ),
                "bootstrap_p95_cache_inclusive": pico_text(
                    quantile(total_billed_samples, 0.95)
                ),
                "point_estimate_all_fresh": pico_text(point_fresh),
                "bootstrap_p05_all_fresh": pico_text(
                    quantile(total_fresh_samples, 0.05)
                ),
                "bootstrap_p95_all_fresh": pico_text(
                    quantile(total_fresh_samples, 0.95)
                ),
                "cache_sensitivity_envelope_p05_billed_to_p95_fresh": [
                    pico_text(quantile(total_billed_samples, 0.05)),
                    pico_text(quantile(total_fresh_samples, 0.95)),
                ],
            },
            "fallback_trigger_projection": {
                "bootstrap_p05_calls": quantile(total_fallback_samples, 0.05),
                "bootstrap_p95_calls": quantile(total_fallback_samples, 0.95),
            },
            "final_ESCALATE_label_projection": {
                "bootstrap_p05_rows": quantile(total_final_escalate_samples, 0.05),
                "bootstrap_p95_rows": quantile(total_final_escalate_samples, 0.95),
            },
        },
    }
    atomic_write_json(OUTPUT_PATH, output)
    print(json.dumps({"output": str(OUTPUT_PATH), "all_matrix": output["all_matrix"]}))


if __name__ == "__main__":
    main()
