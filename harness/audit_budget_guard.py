#!/usr/bin/env python3
"""Audit a saved run's runtime budget guard against durable API usage."""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.run import REPO_ROOT, TokenEstimator, atomic_write_json, relative_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-prefix", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = json.loads((REPO_ROOT / "harness" / "config.json").read_text())
    estimator = TokenEstimator(config)
    paths = sorted((REPO_ROOT / "results" / "raw").glob(f"{args.run_prefix}__*/**/*.json"))
    rows: list[dict[str, object]] = []
    for path in paths:
        envelope = json.loads(path.read_text())
        usage = envelope.get("usage") or {}
        if envelope.get("http_status") != 200 or not isinstance(usage.get("prompt_tokens"), int):
            continue
        estimated = estimator.count_messages(envelope["request"]["body"]["messages"])
        actual = int(usage["prompt_tokens"])
        request_bytes = len(envelope["request"]["body_canonical_json"].encode("utf-8"))
        cost = Decimal(envelope["cost_usd"])
        guard = Decimal(envelope["budget_guard_cost_usd"])
        rows.append(
            {
                "path": relative_path(path),
                "actual_prompt_tokens": actual,
                "estimated_prompt_tokens": estimated,
                "request_utf8_bytes": request_bytes,
                "actual_minus_estimated_tokens": actual - estimated,
                "budget_guard_cost_usd": guard,
                "cost_usd": cost,
            }
        )
    if not rows:
        raise SystemExit("No successful raw envelopes with usage were found")

    differences = [int(row["actual_minus_estimated_tokens"]) for row in rows]
    ratios = [
        Decimal(row["budget_guard_cost_usd"]) / Decimal(row["cost_usd"])
        for row in rows
        if Decimal(row["cost_usd"]) > 0
    ]
    output = {
        "schema_version": "1.0.0",
        "run_prefix": args.run_prefix,
        "successful_envelope_count": len(rows),
        "actual_minus_estimated_prompt_tokens": {
            "minimum": min(differences),
            "maximum": max(differences),
            "mean": str(sum(differences) / len(differences)),
            "positive_count": sum(value > 0 for value in differences),
        },
        "budget_guard_to_actual_cost_ratio": {
            "minimum": str(min(ratios)),
            "maximum": str(max(ratios)),
        },
        "source_raw_envelopes": [str(row["path"]) for row in rows],
    }
    output_path = REPO_ROOT / args.output
    atomic_write_json(output_path, output)
    print(
        json.dumps(
            {
                "event": "budget_guard_audit_complete",
                "output_path": relative_path(output_path),
                "successful_envelope_count": len(rows),
                "actual_minus_estimated_prompt_tokens": output[
                    "actual_minus_estimated_prompt_tokens"
                ],
                "budget_guard_to_actual_cost_ratio": output[
                    "budget_guard_to_actual_cost_ratio"
                ],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
