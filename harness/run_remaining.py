#!/usr/bin/env python3
"""Complete the two owner-approved Phase 4 gaps under a separate USD sub-cap."""

from __future__ import annotations

import argparse
import copy
import csv
import json
import os
import random
import sys
import time
from decimal import Decimal
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from harness.models import MODEL_BY_TIER, load_model_tiers, sha256_path
from harness.run import (
    BudgetExceeded,
    CONFIG_PATH,
    PromptFactory,
    ProviderCreditExhausted,
    RESULTS_RAW_DIR,
    RESULTS_RUNS_DIR,
    RemainingBatchBudget,
    Runtime,
    STRATEGY_MODULES,
    TokenEstimator,
    append_csv_row,
    atomic_write_json,
    build_result_row,
    canonical_json,
    decimal_text,
    existing_budget_state,
    load_and_validate_artifacts,
    load_existing_rows,
    relative_path,
    run_id_for,
    sha256_bytes,
    utc_now,
    validate_model_access,
)


EXECUTION_LABEL = "remaining_v1"
TIER = "capable"
STRATEGIES = ("self_check", "escalation")
PHASE_CAP = Decimal("70")
BATCH_CAP = Decimal("4")
PROJECTION_PATH = RESULTS_RUNS_DIR / "remaining_work_cost_projection.json"
SOURCE_SELF_CHECK_PATH = RESULTS_RUNS_DIR / "full_r3__capable__self_check.csv"
SOURCE_SUMMARY_PATH = RESULTS_RUNS_DIR / "full_r3_summary.json"
PLAN_PATH = RESULTS_RUNS_DIR / f"{EXECUTION_LABEL}_plan.json"
SUMMARY_PATH = RESULTS_RUNS_DIR / f"{EXECUTION_LABEL}_summary.json"
AVAILABILITY_PATH = RESULTS_RUNS_DIR / f"{EXECUTION_LABEL}_model_availability.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def target_cases(
    cases: list[dict[str, Any]], strategy: str
) -> list[dict[str, Any]]:
    if strategy == "escalation":
        return cases
    source_rows = read_csv_rows(SOURCE_SELF_CHECK_PATH)
    if len(source_rows) != 227:
        raise ValueError(
            "remaining-work selection requires exactly 227 completed source "
            f"self-check rows, found {len(source_rows)}"
        )
    completed = {row["case_id"] for row in source_rows}
    selected = [case for case in cases if case["case_id"] not in completed]
    if len(selected) != 73:
        raise ValueError(f"Expected 73 remaining self-check cases, found {len(selected)}")
    if selected[0]["case_id"] != "case_0228" or selected[-1]["case_id"] != "case_0300":
        raise ValueError("Remaining self-check case boundary differs from owner approval")
    return selected


def projection_record() -> tuple[dict[str, Any], Decimal]:
    projection = json.loads(PROJECTION_PATH.read_text(encoding="utf-8"))
    estimate = Decimal(
        projection["capable_escalation_plus_remaining_self_check"][
            "cost_projection"
        ]["planning_point_estimate_usd_all_fresh"]
    )
    if estimate >= BATCH_CAP:
        raise SystemExit(
            "Remaining-work dry-run estimate is not below the batch sub-cap: "
            f"estimate={decimal_text(estimate)} cap={decimal_text(BATCH_CAP)}"
        )
    return projection, estimate


def prior_phase_spend() -> Decimal:
    summary = json.loads(SOURCE_SUMMARY_PATH.read_text(encoding="utf-8"))
    value = summary.get("phase_known_cost_usd")
    if value is None or summary.get("unknown_cost_rows") != 0:
        raise ValueError("Prior Phase 4 spend is not fully known")
    return Decimal(value)


def all_openai_config(config: dict[str, Any]) -> dict[str, Any]:
    routed = copy.deepcopy(config)
    routed["provider_by_call_role"] = {
        "primary": "openai",
        "critic": "openai",
        "fallback": "openai",
    }
    return routed


def plan_identity(
    *,
    artifacts: dict[str, Any],
    factory: PromptFactory,
    estimate: Decimal,
    prior_spend: Decimal,
    targets: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "execution_label": EXECUTION_LABEL,
        "purpose": "complete exactly the two remaining Phase 4 gaps",
        "tier": TIER,
        "strategies": list(STRATEGIES),
        "model_versions": MODEL_BY_TIER,
        "provider_by_call_role": {
            "primary": "openai",
            "critic": "openai",
            "fallback": "openai",
        },
        "expected_rows": sum(len(items) for items in targets.values()),
        "expected_rows_by_configuration": {
            strategy: len(items) for strategy, items in targets.items()
        },
        "target_case_ids_sha256": {
            strategy: sha256_bytes(
                canonical_json([case["case_id"] for case in items]).encode("utf-8")
            )
            for strategy, items in targets.items()
        },
        "dataset_sha256": artifacts["dataset_sha256"],
        "retrieval_sha256": artifacts["retrieval_sha256"],
        "passages_sha256": artifacts["passages_sha256"],
        "corpus_manifest_sha256": artifacts["corpus_manifest_sha256"],
        "source_self_check_csv": relative_path(SOURCE_SELF_CHECK_PATH),
        "source_self_check_csv_sha256": sha256_path(SOURCE_SELF_CHECK_PATH),
        "projection_path": relative_path(PROJECTION_PATH),
        "projection_sha256": sha256_path(PROJECTION_PATH),
        "dry_run_point_estimate_usd": decimal_text(estimate),
        "remaining_batch_cap_usd": decimal_text(BATCH_CAP),
        "phase_wide_cap_usd": decimal_text(PHASE_CAP),
        "prior_phase_known_spend_usd": decimal_text(prior_spend),
        "retry_max_attempts_per_logical_call": int(
            artifacts["config"]["retry"]["max_attempts"]
        ),
        "prompts": {
            strategy: {
                "prompt_sha256": factory.prompt_hash(strategy),
            }
            for strategy in STRATEGIES
        },
    }


def ensure_plan(identity: dict[str, Any]) -> dict[str, Any]:
    digest = sha256_bytes(canonical_json(identity).encode("utf-8"))
    if PLAN_PATH.exists():
        plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
        if plan.get("plan_identity_sha256") != digest:
            raise ValueError(f"Existing remaining-work plan differs: {PLAN_PATH}")
        return plan
    plan = {
        **identity,
        "created_at_utc": utc_now(),
        "plan_identity_sha256": digest,
    }
    atomic_write_json(PLAN_PATH, plan)
    return plan


def ensure_manifest(
    *,
    strategy: str,
    run_id: str,
    plan: dict[str, Any],
    cases: list[dict[str, Any]],
) -> None:
    path = RESULTS_RUNS_DIR / f"{EXECUTION_LABEL}__{TIER}__{strategy}.manifest.json"
    identity = {
        "schema_version": "1.0.0",
        "run_id": run_id,
        "execution_label": EXECUTION_LABEL,
        "model_tier": TIER,
        "model_version": MODEL_BY_TIER[TIER],
        "strategy": strategy,
        "prompt_sha256": plan["prompts"][strategy]["prompt_sha256"],
        "plan_identity_sha256": plan["plan_identity_sha256"],
        "case_count": len(cases),
        "case_ids_sha256": plan["target_case_ids_sha256"][strategy],
    }
    if path.exists():
        if json.loads(path.read_text(encoding="utf-8")) != identity:
            raise ValueError(f"Existing remaining-work manifest differs: {path}")
    else:
        atomic_write_json(path, identity)


def write_summary(
    *,
    plan: dict[str, Any],
    prior_spend: Decimal,
    batch_spend: Decimal,
    started_at: str,
    wall_clock_ms: int,
    state: str,
    halt_reason: str | None = None,
) -> dict[str, Any]:
    by_configuration = {}
    total_rows = 0
    unknown_rows = 0
    for strategy in STRATEGIES:
        path = RESULTS_RUNS_DIR / f"{EXECUTION_LABEL}__{TIER}__{strategy}.csv"
        rows = read_csv_rows(path)
        total_rows += len(rows)
        unknown = sum(not row.get("cost_usd") for row in rows)
        unknown_rows += unknown
        by_configuration[f"{TIER}__{strategy}"] = {
            "completed_rows": len(rows),
            "expected_rows": plan["expected_rows_by_configuration"][strategy],
            "unknown_cost_rows": unknown,
            "run_path": relative_path(path),
        }
    summary = {
        "schema_version": "1.0.0",
        "execution_label": EXECUTION_LABEL,
        "state": state,
        "halt_reason": halt_reason,
        "started_at_utc": started_at,
        "updated_at_utc": utc_now(),
        "wall_clock_ms_this_invocation": wall_clock_ms,
        "plan_identity_sha256": plan["plan_identity_sha256"],
        "completed_rows": total_rows,
        "expected_rows": plan["expected_rows"],
        "remaining_batch_known_spend_usd": decimal_text(batch_spend),
        "remaining_batch_cap_usd": decimal_text(BATCH_CAP),
        "prior_phase_known_spend_usd": decimal_text(prior_spend),
        "phase_known_spend_usd": decimal_text(prior_spend + batch_spend),
        "unknown_cost_rows": unknown_rows,
        "configurations": by_configuration,
    }
    atomic_write_json(SUMMARY_PATH, summary)
    return summary


def main() -> None:
    args = parse_args()
    projection, estimate = projection_record()
    del projection
    artifacts = load_and_validate_artifacts("full")
    config = all_openai_config(artifacts["config"])
    models = load_model_tiers()
    factory = PromptFactory(
        artifacts["retrieval_by_id"], artifacts["passages_by_id"]
    )
    estimator = TokenEstimator(config)
    targets = {
        strategy: target_cases(artifacts["cases"], strategy)
        for strategy in STRATEGIES
    }
    prior_spend = prior_phase_spend()
    identity = plan_identity(
        artifacts=artifacts,
        factory=factory,
        estimate=estimate,
        prior_spend=prior_spend,
        targets=targets,
    )
    plan = ensure_plan(identity)
    print(
        json.dumps(
            {
                "event": "remaining_work_dry_run_check",
                "estimate_usd": decimal_text(estimate),
                "batch_cap_usd": decimal_text(BATCH_CAP),
                "under_cap": estimate < BATCH_CAP,
                "expected_rows": plan["expected_rows"],
                "provider_by_call_role": plan["provider_by_call_role"],
                "api_inference_calls": 0,
            },
            sort_keys=True,
        ),
        flush=True,
    )

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit("OPENAI_API_KEY is required")
    validate_model_access(api_key, config, AVAILABILITY_PATH)
    print(
        json.dumps(
            {
                "event": "remaining_work_model_access_validated",
                "path": relative_path(AVAILABILITY_PATH),
                "api_inference_calls": 0,
            },
            sort_keys=True,
        ),
        flush=True,
    )
    if args.dry_run:
        print(
            json.dumps(
                {
                    "event": "remaining_work_dry_run_complete",
                    "api_inference_calls": 0,
                    "validation": "PASS",
                },
                sort_keys=True,
            ),
            flush=True,
        )
        return

    run_ids = {
        strategy: run_id_for(
            EXECUTION_LABEL,
            TIER,
            strategy,
            artifacts["dataset_sha256"],
            factory.prompt_hash(strategy),
        )
        for strategy in STRATEGIES
    }
    _, initial_batch_actual, initial_unknown = existing_budget_state(
        list(run_ids.values())
    )
    budget = RemainingBatchBudget(
        batch_cap=BATCH_CAP,
        phase_cap=PHASE_CAP,
        prior_phase_spend=prior_spend,
        initial_batch_actual=initial_batch_actual,
        unknown_actual=initial_unknown,
    )
    started_at = utc_now()
    started = time.perf_counter()
    try:
        for strategy in STRATEGIES:
            run_id = run_ids[strategy]
            selected_cases = targets[strategy]
            ensure_manifest(
                strategy=strategy,
                run_id=run_id,
                plan=plan,
                cases=selected_cases,
            )
            run_path = RESULTS_RUNS_DIR / f"{EXECUTION_LABEL}__{TIER}__{strategy}.csv"
            completed = load_existing_rows(run_path, run_id)
            print(
                json.dumps(
                    {
                        "event": "remaining_configuration_start",
                        "tier": TIER,
                        "strategy": strategy,
                        "completed": len(completed),
                        "remaining": len(selected_cases) - len(completed),
                        "batch_spend_usd": decimal_text(budget.batch_known_actual),
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
            runtime = Runtime(
                api_key=api_key,
                config=config,
                models=models,
                factory=factory,
                estimator=estimator,
                budget=budget,
                run_id=run_id,
                strategy=strategy,
                configured_tier=TIER,
                rng=random.Random(
                    int(config["seed"])
                    + 10_000
                    + STRATEGIES.index(strategy)
                ),
            )
            for case in selected_cases:
                if case["case_id"] in completed:
                    continue
                case_started = time.perf_counter()
                calls, final_call = STRATEGY_MODULES[strategy].execute(
                    runtime, case, TIER
                )
                latency_ms = int(round((time.perf_counter() - case_started) * 1000))
                row = build_result_row(
                    case=case,
                    tier=TIER,
                    strategy=strategy,
                    run_id=run_id,
                    calls=calls,
                    final_call=final_call,
                    latency_ms=latency_ms,
                    artifacts=artifacts,
                    factory=factory,
                    config=config,
                )
                append_csv_row(run_path, row)
                completed[case["case_id"]] = row
                elapsed_ms = int(round((time.perf_counter() - started) * 1000))
                summary = write_summary(
                    plan=plan,
                    prior_spend=prior_spend,
                    batch_spend=budget.batch_known_actual,
                    started_at=started_at,
                    wall_clock_ms=elapsed_ms,
                    state="running",
                )
                print(
                    json.dumps(
                        {
                            "event": "remaining_case_complete",
                            "strategy": strategy,
                            "case_id": case["case_id"],
                            "configuration_rows": len(completed),
                            "total_completed_rows": summary["completed_rows"],
                            "batch_spend_usd": summary[
                                "remaining_batch_known_spend_usd"
                            ],
                            "batch_cap_usd": summary["remaining_batch_cap_usd"],
                        },
                        sort_keys=True,
                    ),
                    flush=True,
                )
    except (BudgetExceeded, ProviderCreditExhausted) as exc:
        elapsed_ms = int(round((time.perf_counter() - started) * 1000))
        summary = write_summary(
            plan=plan,
            prior_spend=prior_spend,
            batch_spend=budget.batch_known_actual,
            started_at=started_at,
            wall_clock_ms=elapsed_ms,
            state="halted",
            halt_reason=str(exc),
        )
        print(
            json.dumps(
                {
                    "event": "remaining_work_halt",
                    "reason": str(exc),
                    "completed_rows": summary["completed_rows"],
                    "expected_rows": summary["expected_rows"],
                    "batch_spend_usd": summary[
                        "remaining_batch_known_spend_usd"
                    ],
                    "configurations": summary["configurations"],
                },
                sort_keys=True,
            ),
            flush=True,
        )
        raise SystemExit(2) from exc

    elapsed_ms = int(round((time.perf_counter() - started) * 1000))
    summary = write_summary(
        plan=plan,
        prior_spend=prior_spend,
        batch_spend=budget.batch_known_actual,
        started_at=started_at,
        wall_clock_ms=elapsed_ms,
        state="complete",
    )
    if summary["completed_rows"] != summary["expected_rows"]:
        raise RuntimeError("Remaining-work runner ended without all expected rows")
    print(
        json.dumps(
            {
                "event": "remaining_work_complete",
                "completed_rows": summary["completed_rows"],
                "expected_rows": summary["expected_rows"],
                "batch_spend_usd": summary["remaining_batch_known_spend_usd"],
                "phase_known_spend_usd": summary["phase_known_spend_usd"],
                "configurations": summary["configurations"],
                "summary_path": relative_path(SUMMARY_PATH),
            },
            sort_keys=True,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
