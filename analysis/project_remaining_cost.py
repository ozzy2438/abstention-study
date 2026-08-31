#!/usr/bin/env python3
"""Project the two unfinished Phase 4 work scopes without provider calls."""

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

from harness.models import cost_usd, load_model_tiers, sha256_path
from harness.run import atomic_write_json


OUTPUT_PATH = REPO_ROOT / "results" / "runs" / "remaining_work_cost_projection.json"
CASES_PATH = REPO_ROOT / "dataset" / "cases.jsonl"
PRICE_PATH = REPO_ROOT / "harness" / "pricing.json"
CATEGORIES = (
    "answerable_clear",
    "answerable_multihop",
    "unanswerable_missing",
    "unanswerable_contradictory",
    "out_of_scope",
    "adversarial",
)
ITERATIONS = 5_000
SEED = 20260831
SCALE = 10**12


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def read_rows(name: str) -> list[dict[str, str]]:
    path = REPO_ROOT / "results" / "runs" / name
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def envelopes(row: dict[str, str]) -> list[dict[str, Any]]:
    return [
        json.loads((REPO_ROOT / path).read_text())
        for path in json.loads(row["raw_response_paths"])
    ]


def pico(value: Decimal) -> int:
    scaled = value * SCALE
    if scaled != scaled.to_integral_value():
        raise ValueError(f"Cost exceeds 12-decimal precision: {value}")
    return int(scaled)


def pico_text(value: int) -> str:
    return f"{Decimal(value) / SCALE:.12f}"


def quantile(values: list[int], probability: float) -> int:
    ordered = sorted(values)
    index = (len(ordered) - 1) * probability
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = Decimal(str(index - lower))
    return int(
        Decimal(ordered[lower])
        + (Decimal(ordered[upper]) - Decimal(ordered[lower])) * fraction
    )


def reprice(envelope: dict[str, Any], model: Any, use_cache: bool) -> int:
    usage = envelope["usage"]
    cached = usage["prompt_tokens_details"]["cached_tokens"] if use_cache else 0
    return pico(
        cost_usd(
            model,
            int(usage["prompt_tokens"]),
            int(usage["completion_tokens"]),
            int(cached),
        )
    )


def projection_summary(
    cached_samples: list[int],
    fresh_samples: list[int],
    point_cached: int,
    point_fresh: int,
) -> dict[str, Any]:
    return {
        "planning_point_estimate_usd_all_fresh": pico_text(point_fresh),
        "observed_cache_point_estimate_usd": pico_text(point_cached),
        "range_usd_p05_cache_to_p95_all_fresh": [
            pico_text(quantile(cached_samples, 0.05)),
            pico_text(quantile(fresh_samples, 0.95)),
        ],
        "bootstrap_p05_cache_inclusive_usd": pico_text(
            quantile(cached_samples, 0.05)
        ),
        "bootstrap_p95_cache_inclusive_usd": pico_text(
            quantile(cached_samples, 0.95)
        ),
        "bootstrap_p05_all_fresh_usd": pico_text(quantile(fresh_samples, 0.05)),
        "bootstrap_p95_all_fresh_usd": pico_text(quantile(fresh_samples, 0.95)),
    }


def main() -> None:
    cases = read_jsonl(CASES_PATH)
    cases_by_id = {case["case_id"]: case for case in cases}
    full_counts = Counter(case["category"] for case in cases)
    models = load_model_tiers()
    cheap = models["cheap"]
    capable = models["capable"]

    primary_observations: dict[str, list[dict[str, int]]] = defaultdict(list)
    standard_fallback_usage: dict[str, list[dict[str, int]]] = defaultdict(list)
    observed_cell_rates: dict[str, Any] = {}
    escalation_inputs = []
    for ceiling in ("cheap", "standard"):
        filename = f"full_r3__{ceiling}__escalation.csv"
        escalation_inputs.append(filename)
        rows = read_rows(filename)
        if len(rows) != 300:
            raise ValueError(f"Expected 300 rows in {filename}, found {len(rows)}")
        counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        for row in rows:
            category = cases_by_id[row["case_id"]]["category"]
            raw = envelopes(row)
            primary = next(item for item in raw if item["call_role"] == "primary")
            fallback = [item for item in raw if item["call_role"] == "fallback"]
            triggered = int(bool(fallback))
            primary_observations[category].append(
                {
                    "cached": reprice(primary, cheap, True),
                    "fresh": reprice(primary, cheap, False),
                    "triggered": triggered,
                }
            )
            counts[category][0] += triggered
            counts[category][1] += 1
            if ceiling == "standard" and fallback:
                standard_fallback_usage[category].append(
                    {
                        "cached": reprice(fallback[0], capable, True),
                        "fresh": reprice(fallback[0], capable, False),
                    }
                )
        observed_cell_rates[ceiling] = {
            category: {
                "triggered": numerator,
                "rows": denominator,
                "rate": f"{Decimal(numerator) / Decimal(denominator):.12f}",
            }
            for category, (numerator, denominator) in counts.items()
        }

    capable_pilot_fallback_usage: dict[str, list[dict[str, int]]] = defaultdict(list)
    pilot_filename = "pilot__capable__escalation.csv"
    for row in read_rows(pilot_filename):
        category = cases_by_id[row["case_id"]]["category"]
        for raw in envelopes(row):
            if raw["call_role"] == "fallback":
                capable_pilot_fallback_usage[category].append(
                    {
                        "cached": reprice(raw, capable, True),
                        "fresh": reprice(raw, capable, False),
                    }
                )

    fallback_usage = {}
    fallback_source = {}
    for category in CATEGORIES:
        if capable_pilot_fallback_usage[category]:
            fallback_usage[category] = capable_pilot_fallback_usage[category]
            fallback_source[category] = {
                "source": "observed capable-tier pilot fallbacks",
                "observations": len(fallback_usage[category]),
            }
        else:
            fallback_usage[category] = standard_fallback_usage[category]
            fallback_source[category] = {
                "source": "observed standard-tier full fallbacks repriced at capable rates",
                "observations": len(fallback_usage[category]),
                "reason": "no capable-tier pilot fallback was observed for this category",
            }
        if not fallback_usage[category]:
            raise ValueError(f"No fallback usage proxy for {category}")

    escalation_point_cached = 0
    escalation_point_fresh = 0
    escalation_point_triggers = Decimal(0)
    category_projection = {}
    for category in CATEGORIES:
        target = full_counts[category]
        primary = primary_observations[category]
        fallback = fallback_usage[category]
        trigger_rate = Decimal(sum(item["triggered"] for item in primary)) / Decimal(
            len(primary)
        )
        mean_primary_cached = Decimal(sum(item["cached"] for item in primary)) / len(
            primary
        )
        mean_primary_fresh = Decimal(sum(item["fresh"] for item in primary)) / len(
            primary
        )
        mean_fallback_cached = Decimal(sum(item["cached"] for item in fallback)) / len(
            fallback
        )
        mean_fallback_fresh = Decimal(sum(item["fresh"] for item in fallback)) / len(
            fallback
        )
        escalation_point_cached += int(
            target * (mean_primary_cached + trigger_rate * mean_fallback_cached)
        )
        escalation_point_fresh += int(
            target * (mean_primary_fresh + trigger_rate * mean_fallback_fresh)
        )
        projected_triggers = Decimal(target) * trigger_rate
        escalation_point_triggers += projected_triggers
        category_projection[category] = {
            "full_rows": target,
            "observed_primary_rows": len(primary),
            "observed_trigger_rate": f"{trigger_rate:.12f}",
            "projected_fallback_calls": f"{projected_triggers:.12f}",
            "fallback_usage_proxy": fallback_source[category],
        }

    rng = random.Random(SEED + 9_100)
    escalation_cached_samples = []
    escalation_fresh_samples = []
    trigger_samples = []
    for _ in range(ITERATIONS):
        cached_total = 0
        fresh_total = 0
        triggered_total = 0
        for category in CATEGORIES:
            for _ in range(full_counts[category]):
                primary = rng.choice(primary_observations[category])
                cached_total += primary["cached"]
                fresh_total += primary["fresh"]
                triggered_total += primary["triggered"]
                if primary["triggered"]:
                    fallback = rng.choice(fallback_usage[category])
                    cached_total += fallback["cached"]
                    fresh_total += fallback["fresh"]
        escalation_cached_samples.append(cached_total)
        escalation_fresh_samples.append(fresh_total)
        trigger_samples.append(triggered_total)

    self_rows = read_rows("full_r3__capable__self_check.csv")
    if len(self_rows) != 227:
        raise ValueError(f"Expected 227 completed capable self-check rows, found {len(self_rows)}")
    completed_ids = {row["case_id"] for row in self_rows}
    missing_ids = [case["case_id"] for case in cases if case["case_id"] not in completed_ids]
    if len(missing_ids) != 73:
        raise ValueError(f"Expected 73 missing capable self-check rows, found {len(missing_ids)}")
    self_observations: dict[str, list[dict[str, int]]] = defaultdict(list)
    for row in self_rows:
        category = cases_by_id[row["case_id"]]["category"]
        raw = envelopes(row)
        self_observations[category].append(
            {
                "cached": sum(reprice(item, capable, True) for item in raw),
                "fresh": sum(reprice(item, capable, False) for item in raw),
            }
        )
    missing_counts = Counter(cases_by_id[case_id]["category"] for case_id in missing_ids)
    self_point_cached = 0
    self_point_fresh = 0
    for category, target in missing_counts.items():
        observations = self_observations[category]
        self_point_cached += int(
            Decimal(target)
            * Decimal(sum(item["cached"] for item in observations))
            / len(observations)
        )
        self_point_fresh += int(
            Decimal(target)
            * Decimal(sum(item["fresh"] for item in observations))
            / len(observations)
        )

    rng = random.Random(SEED + 9_200)
    self_cached_samples = []
    self_fresh_samples = []
    for _ in range(ITERATIONS):
        cached_total = 0
        fresh_total = 0
        for category, target in missing_counts.items():
            for _ in range(target):
                observation = rng.choice(self_observations[category])
                cached_total += observation["cached"]
                fresh_total += observation["fresh"]
        self_cached_samples.append(cached_total)
        self_fresh_samples.append(fresh_total)

    combined_cached_samples = [
        escalation + self_check
        for escalation, self_check in zip(
            escalation_cached_samples, self_cached_samples, strict=True
        )
    ]
    combined_fresh_samples = [
        escalation + self_check
        for escalation, self_check in zip(
            escalation_fresh_samples, self_fresh_samples, strict=True
        )
    ]

    run_paths = [
        REPO_ROOT / "results" / "runs" / name
        for name in escalation_inputs
        + [pilot_filename, "full_r3__capable__self_check.csv"]
    ]
    output = {
        "schema_version": "1.0.0",
        "created_at_utc": datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z"),
        "method": {
            "type": "category-stratified empirical bootstrap",
            "seed": SEED,
            "iterations": ITERATIONS,
            "api_calls": 0,
            "full_category_counts_fixed": dict(full_counts),
            "range_definition": (
                "bootstrap p05 with observed cache splits through bootstrap p95 "
                "with all input repriced as fresh"
            ),
            "planning_point_definition": (
                "category-stratified all-fresh point estimate because future cache "
                "discounts are not guaranteed"
            ),
            "retry_treatment": "successful first attempt only; retry spend excluded",
            "pricing_formula": (
                "((fresh_input * input_rate) + (cached_input * cached_rate) + "
                "(output * output_rate)) / 1,000,000"
            ),
        },
        "pricing": {
            "price_table_sha256": sha256_path(PRICE_PATH),
            "cheap": {
                "model": cheap.model_version,
                "input_per_1m": str(cheap.input_per_1m_tokens),
                "cached_input_per_1m": str(cheap.cached_input_per_1m_tokens),
                "output_per_1m": str(cheap.output_per_1m_tokens),
            },
            "capable": {
                "model": capable.model_version,
                "input_per_1m": str(capable.input_per_1m_tokens),
                "cached_input_per_1m": str(capable.cached_input_per_1m_tokens),
                "output_per_1m": str(capable.output_per_1m_tokens),
            },
        },
        "inputs": {
            path.relative_to(REPO_ROOT).as_posix(): sha256_path(path)
            for path in [CASES_PATH, *run_paths]
        },
        "observed_escalation_trigger_rates": observed_cell_rates,
        "capable_escalation_only": {
            "rows": 300,
            "category_projection": category_projection,
            "fallback_projection": {
                "point_estimate_calls": f"{escalation_point_triggers:.12f}",
                "point_estimate_rate": f"{escalation_point_triggers / 300:.12f}",
                "bootstrap_p05_calls": quantile(trigger_samples, 0.05),
                "bootstrap_p95_calls": quantile(trigger_samples, 0.95),
            },
            "cost_projection": projection_summary(
                escalation_cached_samples,
                escalation_fresh_samples,
                escalation_point_cached,
                escalation_point_fresh,
            ),
        },
        "remaining_capable_self_check": {
            "rows": 73,
            "first_case": missing_ids[0],
            "last_case": missing_ids[-1],
            "category_counts_fixed": dict(missing_counts),
            "cost_projection": projection_summary(
                self_cached_samples,
                self_fresh_samples,
                self_point_cached,
                self_point_fresh,
            ),
        },
        "capable_escalation_plus_remaining_self_check": {
            "rows": 373,
            "cost_projection": projection_summary(
                combined_cached_samples,
                combined_fresh_samples,
                escalation_point_cached + self_point_cached,
                escalation_point_fresh + self_point_fresh,
            ),
        },
        "limitations": [
            (
                "The capable pilot observed no contradictory-category fallback; "
                "that category uses full-run standard fallback token usage repriced "
                "at capable rates."
            ),
            (
                "The range combines empirical sampling uncertainty with a cache "
                "sensitivity envelope; it is not a provider billing guarantee."
            ),
            "Retries, pricing changes, and provider-side behaviour changes are excluded.",
        ],
    }
    atomic_write_json(OUTPUT_PATH, output)
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
