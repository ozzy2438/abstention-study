#!/usr/bin/env python3
"""Run the frozen abstention-study matrix with crash-safe raw evidence."""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import json
import math
import os
import random
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from harness.models import (  # noqa: E402
    MODEL_BY_TIER,
    PRICE_TABLE_PATH,
    TIER_ORDER,
    ModelTier,
    cost_usd,
    load_model_tiers,
    load_price_table,
    sha256_path,
)
from harness.scoring import (  # noqa: E402
    ParsedOutput,
    parse_model_content,
    pre_adjudication_scores,
)
from harness.strategies import STRATEGY_ORDER  # noqa: E402
from harness.strategies import escalation, self_check, single_pass  # noqa: E402


HARNESS_DIR = REPO_ROOT / "harness"
CONFIG_PATH = HARNESS_DIR / "config.json"
PROMPTS_DIR = HARNESS_DIR / "prompts"
CASES_PATH = REPO_ROOT / "dataset" / "cases.jsonl"
CASES_MANIFEST_PATH = REPO_ROOT / "dataset" / "cases_manifest.json"
PILOT_CASES_PATH = REPO_ROOT / "dataset" / "pilot_cases.json"
RETRIEVAL_PATH = REPO_ROOT / "dataset" / "retrieval.jsonl"
RETRIEVAL_MANIFEST_PATH = REPO_ROOT / "dataset" / "retrieval_manifest.json"
PASSAGES_PATH = REPO_ROOT / "corpus" / "passages.jsonl"
CORPUS_MANIFEST_PATH = REPO_ROOT / "corpus" / "manifest.json"
RESULTS_RAW_DIR = REPO_ROOT / "results" / "raw"
RESULTS_RUNS_DIR = REPO_ROOT / "results" / "runs"

PROMPT_FILES = {
    "base": PROMPTS_DIR / "base_v1.0.0.txt",
    "critic": PROMPTS_DIR / "critic_v1.0.0.txt",
    "fallback": PROMPTS_DIR / "fallback_v1.0.0.txt",
}
PROMPT_VERSION_BY_STRATEGY = {
    "single_pass": "base-v1.0.0",
    "self_check": "base-v1.0.0+critic-v1.0.0",
    "escalation": "base-v1.0.0+fallback-v1.0.0",
}
STRATEGY_MODULES = {
    "single_pass": single_pass,
    "self_check": self_check,
    "escalation": escalation,
}

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "output_type": {
            "type": "string",
            "enum": ["ANSWER", "ABSTAIN", "ESCALATE"],
        },
        "answer_text": {"type": "string"},
        "citations": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["output_type", "answer_text", "citations", "confidence"],
    "additionalProperties": False,
}
RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "abstention_response",
        "strict": True,
        "schema": RESPONSE_SCHEMA,
    },
}

RESULT_FIELDS = [
    "case_id",
    "model_tier",
    "model_version",
    "strategy",
    "prompt_version",
    "seed",
    "output_type",
    "answer_text",
    "citations",
    "confidence",
    "correct",
    "citation_valid",
    "input_tokens",
    "fresh_input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "cost_usd",
    "latency_ms",
    "timestamp",
    "raw_response_path",
    "run_id",
    "prompt_sha256",
    "dataset_sha256",
    "corpus_manifest_sha256",
    "retrieved_passage_ids",
    "attempt_count",
    "raw_response_paths",
    "requested_models",
    "actual_models_used",
    "system_fingerprints",
    "finish_reasons",
    "error_state",
    "scoring_status",
    "scoring_note",
    "budget_guard_cost_usd",
    "price_table_version",
    "price_table_sha256",
]


class BudgetExceeded(RuntimeError):
    """Raised before a call that would exceed the hard guard budget."""


class ProviderCreditExhausted(RuntimeError):
    """Raised after raw evidence records a provider balance-exhaustion response."""


def provider_error_code(response_json: dict[str, Any] | None) -> str | None:
    if not isinstance(response_json, dict):
        return None
    error = response_json.get("error")
    if not isinstance(error, dict):
        return None
    code = error.get("code")
    return code if isinstance(code, str) else None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def redact_secret_material(value: str) -> str:
    """Redact API-key-shaped text from non-inference diagnostic responses."""
    return re.sub(
        r"sk-[A-Za-z0-9_*\-]{6,}",
        "[REDACTED_OPENAI_API_KEY]",
        value,
    )


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def relative_path(path: Path) -> str:
    return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    directory_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def append_csv_row(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists()
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=RESULT_FIELDS, lineterminator="\n")
        if write_header:
            writer.writeheader()
        writer.writerow(row)
        handle.flush()
        os.fsync(handle.fileno())


def atomic_write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    """Replace a run CSV only after a complete raw-evidence rescore succeeds."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=RESULT_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    directory_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def decimal_text(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.000000000001")), "f")


def csv_boolean(value: bool | None) -> str:
    if value is None:
        return ""
    return "true" if value else "false"


def load_and_validate_artifacts(scope: str) -> dict[str, Any]:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    cases_manifest = json.loads(CASES_MANIFEST_PATH.read_text(encoding="utf-8"))
    retrieval_manifest = json.loads(
        RETRIEVAL_MANIFEST_PATH.read_text(encoding="utf-8")
    )
    if cases_manifest["cases_sha256"] != sha256_path(CASES_PATH):
        raise ValueError("cases.jsonl does not match its manifest")
    if retrieval_manifest["cases_sha256"] != sha256_path(CASES_PATH):
        raise ValueError("retrieval manifest references a different case set")
    if retrieval_manifest["retrieval_sha256"] != sha256_path(RETRIEVAL_PATH):
        raise ValueError("retrieval.jsonl does not match its manifest")
    if retrieval_manifest["passages_sha256"] != sha256_path(PASSAGES_PATH):
        raise ValueError("canonical passages do not match the retrieval manifest")

    cases = read_jsonl(CASES_PATH)
    cases_by_id = {row["case_id"]: row for row in cases}
    retrieval_rows = read_jsonl(RETRIEVAL_PATH)
    retrieval_by_id = {row["case_id"]: row for row in retrieval_rows}
    passages = read_jsonl(PASSAGES_PATH)
    passages_by_id = {row["passage_id"]: row for row in passages}
    if set(cases_by_id) != set(retrieval_by_id):
        raise ValueError("Case and retrieval IDs differ")

    if scope == "pilot":
        pilot = json.loads(PILOT_CASES_PATH.read_text(encoding="utf-8"))
        if pilot["cases_sha256"] != sha256_path(CASES_PATH):
            raise ValueError("Pilot selection references a different case set")
        expected = sorted(
            random.Random(int(pilot["seed"])).sample(sorted(cases_by_id), 20)
        )
        if pilot["case_ids"] != expected:
            raise ValueError("Pilot IDs do not reproduce from the registered seed")
        selected_ids = expected
    else:
        selected_ids = sorted(cases_by_id)

    selected_cases = [cases_by_id[case_id] for case_id in selected_ids]
    for case in selected_cases:
        retrieved = retrieval_by_id[case["case_id"]]["passages"]
        if len(retrieved) != 8:
            raise ValueError(f"{case['case_id']} does not have exactly eight passages")
        for item in retrieved:
            if item["passage_id"] not in passages_by_id:
                raise ValueError(f"Unknown passage {item['passage_id']}")

    return {
        "config": config,
        "cases": selected_cases,
        "retrieval_by_id": retrieval_by_id,
        "passages_by_id": passages_by_id,
        "dataset_sha256": sha256_path(CASES_PATH),
        "corpus_manifest_sha256": sha256_path(CORPUS_MANIFEST_PATH),
        "retrieval_sha256": sha256_path(RETRIEVAL_PATH),
        "passages_sha256": sha256_path(PASSAGES_PATH),
        "scope_selection_sha256": (
            sha256_path(PILOT_CASES_PATH) if scope == "pilot" else sha256_path(CASES_PATH)
        ),
    }


class PromptFactory:
    def __init__(
        self,
        retrieval_by_id: dict[str, dict[str, Any]],
        passages_by_id: dict[str, dict[str, Any]],
    ) -> None:
        self.retrieval_by_id = retrieval_by_id
        self.passages_by_id = passages_by_id
        self.prompts = {
            name: path.read_text(encoding="utf-8") for name, path in PROMPT_FILES.items()
        }

    def context_object(self, case: dict[str, Any]) -> dict[str, Any]:
        passages = []
        for item in self.retrieval_by_id[case["case_id"]]["passages"]:
            passage = self.passages_by_id[item["passage_id"]]
            passages.append(
                {
                    "passage_id": passage["passage_id"],
                    "doc_id": passage["doc_id"],
                    "source_title": passage["source_title"],
                    "source_page": passage["source_page"],
                    "text": passage["text"],
                }
            )
        return {"question": case["question"], "passages": passages}

    def base_messages(self, case: dict[str, Any]) -> list[dict[str, str]]:
        return [
            {"role": "developer", "content": self.prompts["base"]},
            {"role": "user", "content": canonical_json(self.context_object(case))},
        ]

    def critic_messages(
        self, case: dict[str, Any], candidate_response: str
    ) -> list[dict[str, str]]:
        payload = self.context_object(case)
        payload["candidate_response_raw"] = candidate_response
        return [
            {"role": "developer", "content": self.prompts["critic"]},
            {"role": "user", "content": canonical_json(payload)},
        ]

    def fallback_messages(self, case: dict[str, Any]) -> list[dict[str, str]]:
        return [
            {"role": "developer", "content": self.prompts["fallback"]},
            {"role": "user", "content": canonical_json(self.context_object(case))},
        ]

    def prompt_hash(self, strategy: str) -> str:
        names = {
            "single_pass": ["base"],
            "self_check": ["base", "critic"],
            "escalation": ["base", "fallback"],
        }[strategy]
        digest = hashlib.sha256()
        for name in names:
            digest.update(name.encode("utf-8"))
            digest.update(b"\0")
            digest.update(self.prompts[name].encode("utf-8"))
            digest.update(b"\0")
        digest.update(canonical_json(RESPONSE_FORMAT).encode("utf-8"))
        return digest.hexdigest()


class TokenEstimator:
    def __init__(self, config: dict[str, Any]) -> None:
        try:
            import tiktoken
        except ImportError as exc:
            raise RuntimeError(
                "tiktoken is required; install requirements-phase3.txt"
            ) from exc
        expected_version = config["token_estimator"]["tiktoken_version"]
        if getattr(tiktoken, "__version__", None) != expected_version:
            raise RuntimeError(
                f"tiktoken {expected_version} is required, found "
                f"{getattr(tiktoken, '__version__', 'unknown')}"
            )
        self.encoding = tiktoken.get_encoding(config["token_estimator"]["encoding"])
        self.tokens_per_message = int(
            config["token_estimator"]["tokens_per_message"]
        )
        self.assistant_priming_tokens = int(
            config["token_estimator"]["assistant_priming_tokens"]
        )
        self.schema_tokens = len(self.encoding.encode(canonical_json(RESPONSE_FORMAT)))
        self._message_count_cache: dict[str, int] = {}

    def count_messages(self, messages: list[dict[str, str]]) -> int:
        cache_key = canonical_json(messages)
        cached = self._message_count_cache.get(cache_key)
        if cached is not None:
            return cached
        total = self.assistant_priming_tokens + self.schema_tokens
        for message in messages:
            total += self.tokens_per_message
            total += len(self.encoding.encode(message["role"]))
            total += len(self.encoding.encode(message["content"]))
        self._message_count_cache[cache_key] = total
        return total


def build_request_body(
    config: dict[str, Any], model_version: str, messages: list[dict[str, str]]
) -> dict[str, Any]:
    return {
        "model": model_version,
        "messages": messages,
        "response_format": RESPONSE_FORMAT,
        "temperature": config["temperature"],
        "top_p": config["top_p"],
        "seed": config["seed"],
        "reasoning_effort": config["reasoning_effort"],
        "max_completion_tokens": config["max_completion_tokens"],
        "service_tier": config["service_tier"],
        "stream": False,
        "store": False,
    }


def project_matrix(
    cases: list[dict[str, Any]],
    factory: PromptFactory,
    estimator: TokenEstimator,
    config: dict[str, Any],
    models: dict[str, ModelTier],
) -> dict[str, Any]:
    output_cap = int(config["max_completion_tokens"])
    projections: dict[str, Any] = {}
    total_cost = Decimal(0)
    total_calls = 0
    for tier in TIER_ORDER:
        for strategy in STRATEGY_ORDER:
            cost = Decimal(0)
            input_tokens = 0
            calls = 0
            for case in cases:
                if strategy == "single_pass":
                    count = estimator.count_messages(factory.base_messages(case))
                    input_tokens += count
                    cost += cost_usd(models[tier], count, output_cap)
                    calls += 1
                elif strategy == "self_check":
                    first_count = estimator.count_messages(factory.base_messages(case))
                    critic_count = (
                        estimator.count_messages(factory.critic_messages(case, ""))
                        + output_cap
                    )
                    input_tokens += first_count + critic_count
                    cost += cost_usd(models[tier], first_count, output_cap)
                    cost += cost_usd(models[tier], critic_count, output_cap)
                    calls += 2
                else:
                    primary_count = estimator.count_messages(factory.base_messages(case))
                    fallback_count = estimator.count_messages(
                        factory.fallback_messages(case)
                    )
                    input_tokens += primary_count + fallback_count
                    cost += cost_usd(models["cheap"], primary_count, output_cap)
                    cost += cost_usd(models[tier], fallback_count, output_cap)
                    calls += 2
            key = f"{tier}__{strategy}"
            projections[key] = {
                "case_count": len(cases),
                "maximum_calls": calls,
                "estimated_input_tokens": input_tokens,
                "maximum_output_tokens": calls * output_cap,
                "projected_max_cost_usd": decimal_text(cost),
            }
            total_cost += cost
            total_calls += calls
    return {
        "configurations": projections,
        "maximum_calls": total_calls,
        "projected_max_cost_usd": decimal_text(total_cost),
    }


class Budget:
    def __init__(
        self,
        cap: Decimal,
        initial_guard_spend: Decimal = Decimal(0),
        initial_known_actual: Decimal = Decimal(0),
        unknown_actual: bool = False,
    ) -> None:
        self.cap = cap
        self.guard_spend = initial_guard_spend
        self.known_actual = initial_known_actual
        self.unknown_actual = unknown_actual

    def check(self, maximum_charge: Decimal) -> None:
        if self.guard_spend + maximum_charge > self.cap:
            raise BudgetExceeded(
                "hard budget would be exceeded before the next API attempt: "
                f"guard_spend={decimal_text(self.guard_spend)} "
                f"next_guard={decimal_text(maximum_charge)} "
                f"cap={decimal_text(self.cap)}"
            )

    def charge(self, actual: Decimal | None, guard_charge: Decimal) -> None:
        self.guard_spend += guard_charge
        if actual is None:
            self.unknown_actual = True
        else:
            self.known_actual += actual


@dataclass
class CallResult:
    call_role: str
    requested_tier: str
    requested_model: str
    response_content: str | None
    parsed: ParsedOutput | None
    parse_error: str | None
    raw_paths: list[str]
    input_tokens: int | None
    fresh_input_tokens: int | None
    cached_input_tokens: int | None
    output_tokens: int | None
    cost: Decimal | None
    budget_guard_cost: Decimal
    actual_models: list[str]
    fingerprints: list[str]
    finish_reasons: list[str]
    error_state: str | None


def call_result_from_envelopes(
    call_role: str,
    model_tier: str,
    model: ModelTier,
    envelopes: list[tuple[Path, dict[str, Any]]],
) -> CallResult:
    """Reconstruct a call result solely from durable raw API envelopes."""
    if not envelopes:
        raise ValueError("Cannot construct a call result without raw envelopes")
    raw_paths = [relative_path(path) for path, _ in envelopes]
    all_usage_known = all(isinstance(item.get("usage"), dict) for _, item in envelopes)
    input_tokens = None
    fresh_input_tokens = None
    cached_input_tokens = None
    output_tokens = None
    if all_usage_known:
        try:
            prompt_values = [int(item["usage"]["prompt_tokens"]) for _, item in envelopes]
            completion_values = [
                int(item["usage"]["completion_tokens"]) for _, item in envelopes
            ]
            cached_values: list[int] = []
            for _, item in envelopes:
                details = item["usage"].get("prompt_tokens_details")
                cached_value = (
                    details.get("cached_tokens") if isinstance(details, dict) else None
                )
                if not isinstance(cached_value, int):
                    raise ValueError("cached input token count is unavailable")
                cached_values.append(cached_value)
            input_tokens = sum(prompt_values)
            output_tokens = sum(completion_values)
            cached_input_tokens = sum(cached_values)
            if cached_input_tokens < 0 or cached_input_tokens > input_tokens:
                raise ValueError("cached input token count is outside prompt-token bounds")
            fresh_input_tokens = input_tokens - cached_input_tokens
        except (KeyError, TypeError, ValueError):
            # Preserve total API usage when it is available, but do not invent a
            # fresh/cache split when the provider did not return one.
            try:
                input_tokens = sum(
                    int(item["usage"]["prompt_tokens"]) for _, item in envelopes
                )
                output_tokens = sum(
                    int(item["usage"]["completion_tokens"]) for _, item in envelopes
                )
            except (KeyError, TypeError, ValueError):
                input_tokens = None
                output_tokens = None
            fresh_input_tokens = None
            cached_input_tokens = None
    all_costs_known = all(item.get("cost_usd") is not None for _, item in envelopes)
    total_cost = None
    if all_costs_known:
        total_cost = sum(
            (Decimal(item["cost_usd"]) for _, item in envelopes), Decimal(0)
        )
    guard_cost = sum(
        (Decimal(item["budget_guard_cost_usd"]) for _, item in envelopes),
        Decimal(0),
    )
    actual_models = [
        str(item["returned_model"])
        for _, item in envelopes
        if item.get("returned_model")
    ]
    fingerprints = [
        str(item["system_fingerprint"])
        for _, item in envelopes
        if item.get("system_fingerprint")
    ]
    finish_reasons = [
        str(item["finish_reason"])
        for _, item in envelopes
        if item.get("finish_reason")
    ]
    final = envelopes[-1][1]
    response_content: str | None = None
    parsed: ParsedOutput | None = None
    parse_error: str | None = None
    error_state: str | None = None
    if final.get("http_status") == 200:
        try:
            response = json.loads(final["response_body_raw"])
            response_content = response["choices"][0]["message"]["content"]
            if not isinstance(response_content, str):
                response_content = None
                parse_error = "invalid_response:content_not_string"
            else:
                parsed, parse_error = parse_model_content(response_content)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            parse_error = f"invalid_response:{type(exc).__name__}"
        if final.get("returned_model") != model.model_version:
            parsed = None
            parse_error = "model_version_mismatch"
        error_state = parse_error
    else:
        error_state = final.get("transport_error") or f"http_{final.get('http_status')}"
    return CallResult(
        call_role=call_role,
        requested_tier=model_tier,
        requested_model=model.model_version,
        response_content=response_content,
        parsed=parsed,
        parse_error=parse_error,
        raw_paths=raw_paths,
        input_tokens=input_tokens,
        fresh_input_tokens=fresh_input_tokens,
        cached_input_tokens=cached_input_tokens,
        output_tokens=output_tokens,
        cost=total_cost,
        budget_guard_cost=guard_cost,
        actual_models=actual_models,
        fingerprints=fingerprints,
        finish_reasons=finish_reasons,
        error_state=error_state,
    )


class Runtime:
    def __init__(
        self,
        *,
        api_key: str,
        config: dict[str, Any],
        models: dict[str, ModelTier],
        factory: PromptFactory,
        estimator: TokenEstimator,
        budget: Budget,
        run_id: str,
        strategy: str,
        configured_tier: str,
        rng: random.Random,
    ) -> None:
        self.api_key = api_key
        self.config = config
        self.models = models
        self.factory = factory
        self.estimator = estimator
        self.budget = budget
        self.run_id = run_id
        self.strategy = strategy
        self.configured_tier = configured_tier
        self.rng = rng
        self.escalation_threshold = float(config["escalation_threshold"])

    def base_messages(self, case: dict[str, Any]) -> list[dict[str, str]]:
        return self.factory.base_messages(case)

    def critic_messages(
        self, case: dict[str, Any], candidate_response: str
    ) -> list[dict[str, str]]:
        return self.factory.critic_messages(case, candidate_response)

    def fallback_messages(self, case: dict[str, Any]) -> list[dict[str, str]]:
        return self.factory.fallback_messages(case)

    def _raw_directory(self, case_id: str) -> Path:
        return RESULTS_RAW_DIR / self.run_id / case_id

    def _existing_envelopes(
        self, case_id: str, call_index: int
    ) -> list[tuple[Path, dict[str, Any]]]:
        directory = self._raw_directory(case_id)
        paths = sorted(directory.glob(f"call-{call_index:02d}-attempt-*.json"))
        return [
            (path, json.loads(path.read_text(encoding="utf-8"))) for path in paths
        ]

    def _request_guard_cost(
        self,
        model: ModelTier,
        estimated_input_tokens: int,
    ) -> Decimal:
        return cost_usd(
            model,
            estimated_input_tokens,
            int(self.config["max_completion_tokens"]),
        )

    def invoke(
        self,
        *,
        case: dict[str, Any],
        model_tier: str,
        call_role: str,
        call_index: int,
        messages: list[dict[str, str]],
    ) -> CallResult:
        model = self.models[model_tier]
        request_body = build_request_body(
            self.config, model.model_version, messages
        )
        estimated_input = self.estimator.count_messages(messages)
        maximum_guard = self._request_guard_cost(model, estimated_input)
        existing = self._existing_envelopes(case["case_id"], call_index)
        if existing:
            last = existing[-1][1]
            if last.get("provider_error_code") == "credit_balance_exhausted":
                raise ProviderCreditExhausted(
                    "provider reported credit_balance_exhausted; no further "
                    "inference calls will be issued"
                )
            if last.get("http_status") == 200 or not last.get("retryable", False):
                return self._call_result(call_role, model_tier, model, existing)

        max_attempts = int(self.config["retry"]["max_attempts"])
        start_attempt = len(existing) + 1
        for attempt in range(start_attempt, max_attempts + 1):
            self.budget.check(maximum_guard)
            path = (
                self._raw_directory(case["case_id"])
                / f"call-{call_index:02d}-attempt-{attempt:02d}.json"
            )
            if path.exists():
                raise RuntimeError(f"Refusing to overwrite raw evidence: {path}")
            envelope = self._perform_attempt(
                case=case,
                model=model,
                call_role=call_role,
                call_index=call_index,
                attempt=attempt,
                request_body=request_body,
                path=path,
                maximum_guard=maximum_guard,
            )
            actual = (
                Decimal(envelope["cost_usd"])
                if envelope["cost_usd"] is not None
                else None
            )
            guard_charge = Decimal(envelope["budget_guard_cost_usd"])
            self.budget.charge(actual, guard_charge)
            existing.append((path, envelope))
            if envelope.get("provider_error_code") == "credit_balance_exhausted":
                raise ProviderCreditExhausted(
                    "provider reported credit_balance_exhausted; no further "
                    "inference calls will be issued"
                )
            if envelope.get("http_status") == 200:
                break
            if not envelope.get("retryable", False) or attempt == max_attempts:
                break
            base_delay = float(self.config["retry"]["base_delay_seconds"])
            max_delay = float(self.config["retry"]["max_delay_seconds"])
            jitter = float(self.config["retry"]["jitter_seconds"])
            delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
            delay += self.rng.uniform(0, jitter)
            time.sleep(delay)
        return self._call_result(call_role, model_tier, model, existing)

    def _perform_attempt(
        self,
        *,
        case: dict[str, Any],
        model: ModelTier,
        call_role: str,
        call_index: int,
        attempt: int,
        request_body: dict[str, Any],
        path: Path,
        maximum_guard: Decimal,
    ) -> dict[str, Any]:
        url = self.config["api_base_url"].rstrip("/") + "/chat/completions"
        request_bytes = canonical_json(request_body).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=request_bytes,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "User-Agent": "abstention-study-harness/1.0.0",
            },
        )
        started_at = utc_now()
        started = time.perf_counter()
        status: int | None = None
        response_bytes = b""
        response_headers: dict[str, str] = {}
        transport_error: str | None = None
        try:
            with urllib.request.urlopen(
                request, timeout=float(self.config["api_timeout_seconds"])
            ) as response:
                status = int(response.status)
                response_bytes = response.read()
                response_headers = self._safe_headers(response.headers)
        except urllib.error.HTTPError as exc:
            status = int(exc.code)
            response_bytes = exc.read()
            response_headers = self._safe_headers(exc.headers)
        except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as exc:
            transport_error = f"{type(exc).__name__}:{exc}"
        latency_ms = int(round((time.perf_counter() - started) * 1000))
        received_at = utc_now()

        response_text = response_bytes.decode("utf-8", errors="replace")
        response_json: dict[str, Any] | None = None
        try:
            parsed_json = json.loads(response_text) if response_bytes else None
            if isinstance(parsed_json, dict):
                response_json = parsed_json
        except json.JSONDecodeError:
            response_json = None

        error_code = provider_error_code(response_json)
        returned_model = response_json.get("model") if response_json else None
        fingerprint = response_json.get("system_fingerprint") if response_json else None
        usage = response_json.get("usage") if response_json else None
        finish_reason = None
        if response_json and isinstance(response_json.get("choices"), list):
            choices = response_json["choices"]
            if choices and isinstance(choices[0], dict):
                finish_reason = choices[0].get("finish_reason")

        computed_cost: Decimal | None = None
        if status == 200 and returned_model == model.model_version and isinstance(usage, dict):
            prompt_tokens = usage.get("prompt_tokens")
            completion_tokens = usage.get("completion_tokens")
            details = usage.get("prompt_tokens_details")
            cached_tokens = (
                details.get("cached_tokens") if isinstance(details, dict) else None
            )
            if all(
                isinstance(value, int)
                for value in (prompt_tokens, completion_tokens, cached_tokens)
            ):
                computed_cost = cost_usd(
                    model,
                    prompt_tokens,
                    completion_tokens,
                    cached_tokens,
                )
        guard_charge = (
            max(computed_cost, maximum_guard)
            if computed_cost is not None
            else maximum_guard
        )
        retryable_statuses = set(self.config["retry"]["retryable_http_statuses"])
        non_retryable_error_codes = set(
            self.config["retry"].get("non_retryable_error_codes", [])
        )
        retryable = (
            (transport_error is not None or status in retryable_statuses)
            and error_code not in non_retryable_error_codes
        )
        envelope = {
            "schema_version": "1.0.0",
            "run_id": self.run_id,
            "case_id": case["case_id"],
            "configured_tier": self.configured_tier,
            "strategy": self.strategy,
            "call_role": call_role,
            "call_index": call_index,
            "attempt": attempt,
            "request": {
                "method": "POST",
                "url": url,
                "body": request_body,
                "body_canonical_json": request_bytes.decode("utf-8"),
                "body_sha256": sha256_bytes(request_bytes),
            },
            "request_started_at": started_at,
            "response_received_at": received_at,
            "latency_ms": latency_ms,
            "http_status": status,
            "response_headers": response_headers,
            "response_body_raw": response_text,
            "response_body_base64": base64.b64encode(response_bytes).decode("ascii"),
            "response_body_sha256": sha256_bytes(response_bytes),
            "transport_error": transport_error,
            "provider_error_code": error_code,
            "retryable": retryable,
            "requested_model": model.model_version,
            "returned_model": returned_model,
            "system_fingerprint": fingerprint,
            "usage": usage,
            "finish_reason": finish_reason,
            "price_table_version": load_price_table()["price_table_version"],
            "price_table_sha256": sha256_path(PRICE_TABLE_PATH),
            "cost_usd": decimal_text(computed_cost) if computed_cost is not None else None,
            "budget_guard_cost_usd": decimal_text(guard_charge),
        }
        atomic_write_json(path, envelope)
        return envelope

    @staticmethod
    def _safe_headers(headers: Any) -> dict[str, str]:
        if headers is None:
            return {}
        allowed = {
            "date",
            "openai-processing-ms",
            "openai-version",
            "x-request-id",
            "x-ratelimit-limit-requests",
            "x-ratelimit-limit-tokens",
            "x-ratelimit-remaining-requests",
            "x-ratelimit-remaining-tokens",
            "x-ratelimit-reset-requests",
            "x-ratelimit-reset-tokens",
        }
        return {
            key.lower(): value
            for key, value in headers.items()
            if key.lower() in allowed
        }

    def _call_result(
        self,
        call_role: str,
        model_tier: str,
        model: ModelTier,
        envelopes: list[tuple[Path, dict[str, Any]]],
    ) -> CallResult:
        return call_result_from_envelopes(
            call_role,
            model_tier,
            model,
            envelopes,
        )


def prompt_metadata(factory: PromptFactory) -> dict[str, Any]:
    return {
        strategy: {
            "prompt_version": PROMPT_VERSION_BY_STRATEGY[strategy],
            "prompt_sha256": factory.prompt_hash(strategy),
        }
        for strategy in STRATEGY_ORDER
    }


def run_id_for(
    scope: str,
    tier: str,
    strategy: str,
    dataset_sha256: str,
    prompt_sha256: str,
) -> str:
    return (
        f"{scope}_v1__{tier}__{strategy}__"
        f"{dataset_sha256[:12]}__{prompt_sha256[:12]}"
    )


def load_existing_rows(path: Path, run_id: str) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    by_case: dict[str, dict[str, str]] = {}
    for row in rows:
        if row.get("run_id") != run_id:
            raise ValueError(f"Run identity mismatch in {path}")
        if row["case_id"] in by_case:
            raise ValueError(f"Duplicate completed case in {path}: {row['case_id']}")
        raw_paths = json.loads(row["raw_response_paths"])
        if not raw_paths or any(not (REPO_ROOT / item).is_file() for item in raw_paths):
            raise ValueError(f"Completed row lacks raw evidence: {row['case_id']}")
        by_case[row["case_id"]] = row
    return by_case


def existing_budget_state(run_ids: list[str]) -> tuple[Decimal, Decimal, bool]:
    guard = Decimal(0)
    known = Decimal(0)
    unknown = False
    for run_id in run_ids:
        directory = RESULTS_RAW_DIR / run_id
        for path in sorted(directory.glob("**/*.json")):
            envelope = json.loads(path.read_text(encoding="utf-8"))
            guard += Decimal(envelope["budget_guard_cost_usd"])
            if envelope.get("cost_usd") is None:
                unknown = True
            else:
                known += Decimal(envelope["cost_usd"])
    return guard, known, unknown


def row_has_fallback_trigger(row: dict[str, str]) -> bool:
    """Identify a strategy fallback from durable raw evidence, not row shape."""
    for raw_path_text in json.loads(row["raw_response_paths"]):
        raw_path = REPO_ROOT / raw_path_text
        envelope = json.loads(raw_path.read_text(encoding="utf-8"))
        if envelope.get("call_role") == "fallback":
            return True
    return False


class ProgressReporter:
    """Persist and print the full-run 25/50/75 percent checkpoints."""

    def __init__(
        self,
        *,
        scope: str,
        plan_identity_sha256: str,
        expected_rows: int,
        completed_rows: int,
        escalation_rows: int,
        fallback_triggers: int,
        budget: Budget,
        progress_path: Path | None = None,
    ) -> None:
        self.scope = scope
        self.plan_identity_sha256 = plan_identity_sha256
        self.expected_rows = expected_rows
        self.completed_rows = completed_rows
        self.escalation_rows = escalation_rows
        self.fallback_triggers = fallback_triggers
        self.budget = budget
        self.progress_path = progress_path or RESULTS_RUNS_DIR / f"{scope}_progress.json"
        self.targets = [
            (25, math.ceil(expected_rows * 0.25)),
            (50, math.ceil(expected_rows * 0.50)),
            (75, math.ceil(expected_rows * 0.75)),
        ]
        self.emitted_targets: set[int] = set()
        if self.progress_path.exists():
            previous = json.loads(self.progress_path.read_text(encoding="utf-8"))
            if previous.get("plan_identity_sha256") != self.plan_identity_sha256:
                raise ValueError(f"Progress identity differs: {self.progress_path}")
            self.emitted_targets = {
                int(item["completed_row_target"])
                for item in previous.get("emitted_checkpoints", [])
            }

    def _state(self, percent: int, target: int) -> dict[str, Any]:
        trigger_rate = (
            self.fallback_triggers / self.escalation_rows
            if self.escalation_rows
            else None
        )
        return {
            "checkpoint_percent": percent,
            "completed_row_target": target,
            "completed_rows": self.completed_rows,
            "expected_rows": self.expected_rows,
            "completed_fraction": self.completed_rows / self.expected_rows,
            "known_cumulative_spend_usd": decimal_text(self.budget.known_actual),
            "unknown_actual_cost_seen": self.budget.unknown_actual,
            "escalation_rows_completed": self.escalation_rows,
            "fallback_triggers": self.fallback_triggers,
            "escalation_trigger_rate": trigger_rate,
        }

    def _write(self) -> None:
        states = [
            self._state(percent, target)
            for percent, target in self.targets
            if target in self.emitted_targets
        ]
        atomic_write_json(
            self.progress_path,
            {
                "schema_version": "1.0.0",
                "scope": self.scope,
                "plan_identity_sha256": self.plan_identity_sha256,
                "definition": (
                    "A fallback trigger is a raw API envelope whose call_role is "
                    "fallback. The denominator is completed escalation-strategy rows."
                ),
                "emitted_checkpoints": states,
            },
        )

    def emit_due(self) -> None:
        for percent, target in self.targets:
            if self.completed_rows >= target and target not in self.emitted_targets:
                state = self._state(percent, target)
                self.emitted_targets.add(target)
                self._write()
                print(
                    json.dumps(
                        {
                            "event": "progress_checkpoint",
                            **state,
                            "progress_path": relative_path(self.progress_path),
                        },
                        sort_keys=True,
                    ),
                    flush=True,
                )

    def record_row(self, strategy: str, row: dict[str, str]) -> None:
        self.completed_rows += 1
        if strategy == "escalation":
            self.escalation_rows += 1
            if row_has_fallback_trigger(row):
                self.fallback_triggers += 1
        self.emit_due()


def validate_model_access(
    api_key: str, config: dict[str, Any], output_path: Path
) -> None:
    records: list[dict[str, Any]] = []
    for tier in TIER_ORDER:
        model_id = MODEL_BY_TIER[tier]
        url = (
            config["api_base_url"].rstrip("/")
            + "/models/"
            + urllib.parse.quote(model_id, safe="")
        )
        request = urllib.request.Request(
            url,
            method="GET",
            headers={
                "Authorization": f"Bearer {api_key}",
                "User-Agent": "abstention-study-harness/1.0.0",
            },
        )
        started_at = utc_now()
        status = None
        body = b""
        try:
            with urllib.request.urlopen(
                request, timeout=float(config["api_timeout_seconds"])
            ) as response:
                status = int(response.status)
                body = response.read()
        except urllib.error.HTTPError as exc:
            status = int(exc.code)
            body = exc.read()
        text = body.decode("utf-8", errors="replace")
        safe_text = text if status == 200 else redact_secret_material(text)
        safe_body = safe_text.encode("utf-8")
        response_json = None
        try:
            response_json = json.loads(safe_text)
        except json.JSONDecodeError:
            pass
        returned_id = response_json.get("id") if isinstance(response_json, dict) else None
        record = {
            "tier": tier,
            "requested_model": model_id,
            "checked_at_utc": started_at,
            "http_status": status,
            "returned_id": returned_id,
            "response_body_raw": safe_text,
            "response_body_base64": base64.b64encode(safe_body).decode("ascii"),
            "response_body_sha256": sha256_bytes(body),
            "response_redacted": safe_text != text,
        }
        records.append(record)
        if status != 200 or returned_id != model_id:
            atomic_write_json(
                output_path,
                {"schema_version": "1.0.0", "checks": records},
            )
            raise RuntimeError(f"Registered model is unavailable: {model_id}")
    atomic_write_json(
        output_path,
        {"schema_version": "1.0.0", "checks": records},
    )


def plan_identity(
    *,
    scope: str,
    execution_label: str,
    budget_cap: Decimal,
    prior_known_spend: Decimal,
    artifacts: dict[str, Any],
    factory: PromptFactory,
    projection: dict[str, Any],
) -> dict[str, Any]:
    price_table = load_price_table()
    return {
        "schema_version": "1.0.0",
        "scope": scope,
        "execution_label": execution_label,
        "case_count": len(artifacts["cases"]),
        "scope_selection_sha256": artifacts["scope_selection_sha256"],
        "dataset_sha256": artifacts["dataset_sha256"],
        "retrieval_sha256": artifacts["retrieval_sha256"],
        "passages_sha256": artifacts["passages_sha256"],
        "corpus_manifest_sha256": artifacts["corpus_manifest_sha256"],
        "config_sha256": sha256_path(CONFIG_PATH),
        "price_table_sha256": sha256_path(PRICE_TABLE_PATH),
        "price_table": price_table,
        "prompts": prompt_metadata(factory),
        "models": MODEL_BY_TIER,
        "strategies": list(STRATEGY_ORDER),
        "hard_budget_cap_usd": decimal_text(budget_cap),
        "prior_known_spend_usd": decimal_text(prior_known_spend),
        "cost_projection": projection,
    }


def ensure_plan(path: Path, identity: dict[str, Any]) -> dict[str, Any]:
    identity_hash = sha256_bytes(canonical_json(identity).encode("utf-8"))
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing.get("plan_identity_sha256") != identity_hash:
            raise ValueError(f"Existing plan identity differs: {path}")
        return existing
    plan = {
        **identity,
        "created_at_utc": utc_now(),
        "plan_identity_sha256": identity_hash,
    }
    atomic_write_json(path, plan)
    return plan


def ensure_run_manifest(
    scope: str,
    tier: str,
    strategy: str,
    run_id: str,
    plan: dict[str, Any],
) -> Path:
    path = RESULTS_RUNS_DIR / f"{scope}__{tier}__{strategy}.manifest.json"
    identity = {
        "schema_version": "1.0.0",
        "run_id": run_id,
        "scope": scope,
        "model_tier": tier,
        "model_version": MODEL_BY_TIER[tier],
        "strategy": strategy,
        "prompt_version": plan["prompts"][strategy]["prompt_version"],
        "prompt_sha256": plan["prompts"][strategy]["prompt_sha256"],
        "plan_identity_sha256": plan["plan_identity_sha256"],
        "case_count": plan["case_count"],
        "price_table": plan["price_table"],
    }
    if path.exists():
        if json.loads(path.read_text(encoding="utf-8")) != identity:
            raise ValueError(f"Run manifest identity differs: {path}")
    else:
        atomic_write_json(path, identity)
    return path


def combine_calls(
    calls: list[CallResult],
) -> tuple[
    int | None,
    int | None,
    int | None,
    int | None,
    Decimal | None,
    Decimal,
]:
    input_tokens = None
    fresh_input_tokens = None
    cached_input_tokens = None
    output_tokens = None
    if all(call.input_tokens is not None for call in calls):
        input_tokens = sum(int(call.input_tokens) for call in calls)
        output_tokens = sum(int(call.output_tokens) for call in calls)
    if all(call.fresh_input_tokens is not None for call in calls):
        fresh_input_tokens = sum(int(call.fresh_input_tokens) for call in calls)
    if all(call.cached_input_tokens is not None for call in calls):
        cached_input_tokens = sum(int(call.cached_input_tokens) for call in calls)
    total_cost = None
    if all(call.cost is not None for call in calls):
        total_cost = sum((call.cost for call in calls if call.cost is not None), Decimal(0))
    guard = sum((call.budget_guard_cost for call in calls), Decimal(0))
    return (
        input_tokens,
        fresh_input_tokens,
        cached_input_tokens,
        output_tokens,
        total_cost,
        guard,
    )


def build_result_row(
    *,
    case: dict[str, Any],
    tier: str,
    strategy: str,
    run_id: str,
    calls: list[CallResult],
    final_call: CallResult,
    latency_ms: int,
    artifacts: dict[str, Any],
    factory: PromptFactory,
    config: dict[str, Any],
    timestamp: str | None = None,
) -> dict[str, Any]:
    parsed = final_call.parsed
    retrieved_ids = [
        item["passage_id"]
        for item in artifacts["retrieval_by_id"][case["case_id"]]["passages"]
    ]
    correct, citation_valid, scoring_note = pre_adjudication_scores(
        case, parsed, set(retrieved_ids)
    )
    scoring_status = (
        "pending_manual_adjudication"
        if parsed is not None and parsed.output_type == "ANSWER" and correct is None
        else "deterministic"
    )
    (
        input_tokens,
        fresh_input_tokens,
        cached_input_tokens,
        output_tokens,
        total_cost,
        guard,
    ) = combine_calls(calls)
    raw_paths = [path for call in calls for path in call.raw_paths]
    requested_models = [call.requested_model for call in calls]
    actual_models = [model for call in calls for model in call.actual_models]
    fingerprints = [item for call in calls for item in call.fingerprints]
    finish_reasons = [item for call in calls for item in call.finish_reasons]
    error_states = [call.error_state for call in calls if call.error_state]
    price_table = load_price_table()
    return {
        "case_id": case["case_id"],
        "model_tier": tier,
        "model_version": MODEL_BY_TIER[tier],
        "strategy": strategy,
        "prompt_version": PROMPT_VERSION_BY_STRATEGY[strategy],
        "seed": config["seed"],
        "output_type": parsed.output_type if parsed is not None else "INVALID",
        "answer_text": parsed.answer_text if parsed is not None else "",
        "citations": json.dumps(parsed.citations if parsed is not None else []),
        "confidence": parsed.confidence if parsed is not None else "",
        "correct": csv_boolean(correct),
        "citation_valid": csv_boolean(citation_valid),
        "input_tokens": input_tokens if input_tokens is not None else "",
        "fresh_input_tokens": (
            fresh_input_tokens if fresh_input_tokens is not None else ""
        ),
        "cached_input_tokens": (
            cached_input_tokens if cached_input_tokens is not None else ""
        ),
        "output_tokens": output_tokens if output_tokens is not None else "",
        "cost_usd": decimal_text(total_cost) if total_cost is not None else "",
        "latency_ms": latency_ms,
        "timestamp": timestamp or utc_now(),
        "raw_response_path": raw_paths[-1] if raw_paths else "",
        "run_id": run_id,
        "prompt_sha256": factory.prompt_hash(strategy),
        "dataset_sha256": artifacts["dataset_sha256"],
        "corpus_manifest_sha256": artifacts["corpus_manifest_sha256"],
        "retrieved_passage_ids": json.dumps(retrieved_ids),
        "attempt_count": len(raw_paths),
        "raw_response_paths": json.dumps(raw_paths),
        "requested_models": json.dumps(requested_models),
        "actual_models_used": json.dumps(actual_models),
        "system_fingerprints": json.dumps(fingerprints),
        "finish_reasons": json.dumps(finish_reasons),
        "error_state": "|".join(error_states),
        "scoring_status": scoring_status,
        "scoring_note": scoring_note,
        "budget_guard_cost_usd": decimal_text(guard),
        "price_table_version": price_table["price_table_version"],
        "price_table_sha256": sha256_path(PRICE_TABLE_PATH),
    }


def raw_envelopes_for_call(
    run_id: str, case_id: str, call_index: int
) -> list[tuple[Path, dict[str, Any]]]:
    """Load one durable call sequence in attempt order without contacting the API."""
    directory = RESULTS_RAW_DIR / run_id / case_id
    paths = sorted(directory.glob(f"call-{call_index:02d}-attempt-*.json"))
    envelopes = [
        (path, json.loads(path.read_text(encoding="utf-8"))) for path in paths
    ]
    if not envelopes:
        raise ValueError(
            f"Missing raw evidence for run={run_id} case={case_id} call={call_index}"
        )
    for path, envelope in envelopes:
        if envelope.get("run_id") != run_id or envelope.get("case_id") != case_id:
            raise ValueError(f"Raw envelope identity mismatch: {path}")
        if envelope.get("call_index") != call_index:
            raise ValueError(f"Raw envelope call index mismatch: {path}")
    return envelopes


def reconstructed_calls_from_raw(
    *,
    case_id: str,
    tier: str,
    strategy: str,
    run_id: str,
    models: dict[str, ModelTier],
) -> tuple[list[CallResult], CallResult]:
    """Recover a strategy's final call and all billable calls from raw evidence."""
    primary_tier = "cheap" if strategy == "escalation" else tier
    primary_envelopes = raw_envelopes_for_call(run_id, case_id, 1)
    primary = call_result_from_envelopes(
        "primary", primary_tier, models[primary_tier], primary_envelopes
    )
    calls = [primary]

    if strategy == "single_pass":
        return calls, primary

    if strategy == "self_check":
        critic_envelopes = raw_envelopes_for_call(run_id, case_id, 2)
        critic = call_result_from_envelopes("critic", tier, models[tier], critic_envelopes)
        calls.append(critic)
        return calls, critic

    if strategy != "escalation":
        raise ValueError(f"Unknown strategy for raw reconstruction: {strategy}")

    fallback_directory = RESULTS_RAW_DIR / run_id / case_id
    if not list(fallback_directory.glob("call-02-attempt-*.json")):
        return calls, primary
    fallback_envelopes = raw_envelopes_for_call(run_id, case_id, 2)
    fallback = call_result_from_envelopes("fallback", tier, models[tier], fallback_envelopes)
    calls.append(fallback)
    return calls, fallback


def rescore_rows_from_raw(
    *,
    scope: str,
    selected_tiers: tuple[str, ...],
    selected_strategies: tuple[str, ...],
    artifacts: dict[str, Any],
    factory: PromptFactory,
    config: dict[str, Any],
    models: dict[str, ModelTier],
    plan: dict[str, Any],
) -> dict[str, Any]:
    """Backfill additive result fields by reconstructing complete rows from raw files.

    The existing timestamp and end-to-end latency are retained because they are
    measurements of the historical invocation, not values recoverable exactly
    from individual HTTP envelopes. All semantic, token, cost, and raw-path
    fields are reconstructed and must match the pre-rescore CSV.
    """
    audit_configurations: dict[str, Any] = {}
    total_rows = 0
    total_raw_files = 0
    immutable_fields = [
        field
        for field in RESULT_FIELDS
        if field not in {"fresh_input_tokens", "cached_input_tokens"}
    ]
    for tier in selected_tiers:
        for strategy in selected_strategies:
            prompt_hash = factory.prompt_hash(strategy)
            run_id = run_id_for(
                scope,
                tier,
                strategy,
                artifacts["dataset_sha256"],
                prompt_hash,
            )
            ensure_run_manifest(scope, tier, strategy, run_id, plan)
            path = RESULTS_RUNS_DIR / f"{scope}__{tier}__{strategy}.csv"
            if not path.exists():
                raise ValueError(f"Cannot rescore a missing run CSV: {path}")
            with path.open(encoding="utf-8", newline="") as handle:
                previous_rows = list(csv.DictReader(handle))
            previous_by_case = {row["case_id"]: row for row in previous_rows}
            if len(previous_by_case) != len(previous_rows):
                raise ValueError(f"Duplicate case IDs in run CSV: {path}")
            if set(previous_by_case) != {case["case_id"] for case in artifacts["cases"]}:
                raise ValueError(
                    f"Rescore requires a completed scope; run CSV is incomplete: {path}"
                )

            before_sha256 = sha256_path(path)
            rebuilt_rows: list[dict[str, Any]] = []
            for case in artifacts["cases"]:
                previous = previous_by_case[case["case_id"]]
                try:
                    latency_ms = int(previous["latency_ms"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise ValueError(
                        f"Historical latency is unavailable for {path}:{case['case_id']}"
                    ) from exc
                calls, final_call = reconstructed_calls_from_raw(
                    case_id=case["case_id"],
                    tier=tier,
                    strategy=strategy,
                    run_id=run_id,
                    models=models,
                )
                rebuilt = build_result_row(
                    case=case,
                    tier=tier,
                    strategy=strategy,
                    run_id=run_id,
                    calls=calls,
                    final_call=final_call,
                    latency_ms=latency_ms,
                    timestamp=previous.get("timestamp") or None,
                    artifacts=artifacts,
                    factory=factory,
                    config=config,
                )
                mismatch = [
                    field
                    for field in immutable_fields
                    if previous.get(field, "") != str(rebuilt[field])
                ]
                if mismatch:
                    raise ValueError(
                        "Raw-evidence rescore changed existing result values for "
                        f"{path}:{case['case_id']}: {', '.join(mismatch)}"
                    )
                rebuilt_rows.append(rebuilt)
                total_raw_files += len(calls[0].raw_paths) + sum(
                    len(call.raw_paths) for call in calls[1:]
                )
            atomic_write_csv(path, rebuilt_rows)
            audit_configurations[f"{tier}__{strategy}"] = {
                "run_path": relative_path(path),
                "previous_csv_sha256": before_sha256,
                "rescored_csv_sha256": sha256_path(path),
                "row_count": len(rebuilt_rows),
                "semantic_and_existing_fields_unchanged": True,
            }
            total_rows += len(rebuilt_rows)

    audit = {
        "schema_version": "1.0.0",
        "scope": scope,
        "created_at_utc": utc_now(),
        "method": "reconstructed completed result rows from committed raw API envelopes; no API calls",
        "additive_fields": ["fresh_input_tokens", "cached_input_tokens"],
        "historical_fields_retained": ["timestamp", "latency_ms"],
        "row_count": total_rows,
        "raw_envelope_references": total_raw_files,
        "configurations": audit_configurations,
    }
    audit_path = RESULTS_RUNS_DIR / f"{scope}_rescore.json"
    atomic_write_json(audit_path, audit)
    return {"audit": audit, "audit_path": audit_path}


def write_summary(
    *,
    scope: str,
    plan: dict[str, Any],
    started_at: str,
    wall_clock_ms: int,
    prior_known_spend: Decimal = Decimal(0),
) -> dict[str, Any]:
    by_config: dict[str, Any] = {}
    known_total = Decimal(0)
    unknown_cost_rows = 0
    completed = 0
    for tier in TIER_ORDER:
        for strategy in STRATEGY_ORDER:
            path = RESULTS_RUNS_DIR / f"{scope}__{tier}__{strategy}.csv"
            rows: list[dict[str, str]] = []
            if path.exists():
                with path.open(encoding="utf-8", newline="") as handle:
                    rows = list(csv.DictReader(handle))
            config_known = Decimal(0)
            config_unknown = 0
            for row in rows:
                if row["cost_usd"]:
                    config_known += Decimal(row["cost_usd"])
                else:
                    config_unknown += 1
            by_config[f"{tier}__{strategy}"] = {
                "completed_cases": len(rows),
                "known_cost_usd": decimal_text(config_known),
                "unknown_cost_rows": config_unknown,
                "run_path": relative_path(path),
            }
            completed += len(rows)
            known_total += config_known
            unknown_cost_rows += config_unknown
    summary = {
        "schema_version": "1.0.0",
        "scope": scope,
        "started_at_utc": started_at,
        "completed_at_utc": utc_now(),
        "wall_clock_ms_this_invocation": wall_clock_ms,
        "plan_identity_sha256": plan["plan_identity_sha256"],
        "expected_rows": plan["case_count"] * len(TIER_ORDER) * len(STRATEGY_ORDER),
        "completed_rows": completed,
        "known_cost_usd": decimal_text(known_total),
        "actual_total_cost_usd": (
            decimal_text(known_total) if unknown_cost_rows == 0 else None
        ),
        "prior_known_spend_usd": decimal_text(prior_known_spend),
        "phase_known_cost_usd": decimal_text(known_total + prior_known_spend),
        "phase_actual_total_cost_usd": (
            decimal_text(known_total + prior_known_spend)
            if unknown_cost_rows == 0
            else None
        ),
        "unknown_cost_rows": unknown_cost_rows,
        "configurations": by_config,
    }
    atomic_write_json(RESULTS_RUNS_DIR / f"{scope}_summary.json", summary)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the frozen 3x3 abstention-study matrix"
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--rescore",
        action="store_true",
        help=(
            "rebuild completed result rows from stored raw API envelopes without "
            "making API calls"
        ),
    )
    parser.add_argument("--scope", choices=("pilot", "full"), default="pilot")
    parser.add_argument(
        "--allow-full-run",
        action="store_true",
        help="required with --scope full after the Phase 3 gate is approved",
    )
    parser.add_argument(
        "--budget-usd",
        required=True,
        help="hard USD guard cap across all selected configurations",
    )
    parser.add_argument(
        "--run-revision",
        type=int,
        default=1,
        help=(
            "execution-artifact revision; use a new positive revision only when "
            "a full matrix must restart after a documented harness correction"
        ),
    )
    parser.add_argument(
        "--prior-known-spend-usd",
        default="0",
        help=(
            "known actual USD spend from a documented earlier, superseded "
            "execution that must count against this hard cap"
        ),
    )
    parser.add_argument("--tier", choices=TIER_ORDER, action="append")
    parser.add_argument("--strategy", choices=STRATEGY_ORDER, action="append")
    parser.add_argument(
        "--offline-dry-run",
        action="store_true",
        help="skip the non-inference model access check; valid only with --dry-run",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.scope == "full" and not args.allow_full_run:
        raise SystemExit("Full runs remain gated; pass --allow-full-run only after approval")
    if args.rescore and args.dry_run:
        raise SystemExit("--rescore and --dry-run cannot be combined")
    if args.offline_dry_run and not args.dry_run:
        raise SystemExit("--offline-dry-run requires --dry-run")
    try:
        budget_cap = Decimal(args.budget_usd)
    except Exception as exc:
        raise SystemExit("--budget-usd must be a decimal number") from exc
    if budget_cap <= 0:
        raise SystemExit("--budget-usd must be positive")
    if args.run_revision <= 0:
        raise SystemExit("--run-revision must be a positive integer")
    try:
        prior_known_spend = Decimal(args.prior_known_spend_usd)
    except Exception as exc:
        raise SystemExit("--prior-known-spend-usd must be a decimal number") from exc
    if prior_known_spend < 0:
        raise SystemExit("--prior-known-spend-usd must not be negative")
    artifact_scope = (
        args.scope if args.run_revision == 1 else f"{args.scope}_r{args.run_revision}"
    )

    selected_tiers = tuple(args.tier or TIER_ORDER)
    selected_strategies = tuple(args.strategy or STRATEGY_ORDER)
    if len(set(selected_tiers)) != len(selected_tiers) or len(
        set(selected_strategies)
    ) != len(selected_strategies):
        raise SystemExit("Duplicate --tier or --strategy values are not allowed")

    artifacts = load_and_validate_artifacts(args.scope)
    config = artifacts["config"]
    models = load_model_tiers()
    factory = PromptFactory(
        artifacts["retrieval_by_id"], artifacts["passages_by_id"]
    )
    estimator = TokenEstimator(config)
    full_projection = project_matrix(
        artifacts["cases"], factory, estimator, config, models
    )
    selected_keys = {
        f"{tier}__{strategy}"
        for tier in selected_tiers
        for strategy in selected_strategies
    }
    selected_projection_cost = sum(
        (
            Decimal(item["projected_max_cost_usd"])
            for key, item in full_projection["configurations"].items()
            if key in selected_keys
        ),
        Decimal(0),
    )
    if selected_projection_cost + prior_known_spend > budget_cap:
        raise SystemExit(
            "Projected maximum cost plus prior known spend exceeds the hard budget cap: "
            f"projection={decimal_text(selected_projection_cost)} "
            f"prior_known_spend={decimal_text(prior_known_spend)} "
            f"cap={decimal_text(budget_cap)}"
        )
    plan_path = RESULTS_RUNS_DIR / f"{artifact_scope}_plan.json"
    identity = plan_identity(
        scope=args.scope,
        execution_label=artifact_scope,
        budget_cap=budget_cap,
        prior_known_spend=prior_known_spend,
        artifacts=artifacts,
        factory=factory,
        projection=full_projection,
    )
    plan = ensure_plan(plan_path, identity)
    print(
        json.dumps(
            {
                "event": "cost_projection",
                "scope": args.scope,
                "execution_label": artifact_scope,
                "selected_configurations": sorted(selected_keys),
                "selected_projected_max_cost_usd": decimal_text(
                    selected_projection_cost
                ),
                "all_matrix_projected_max_cost_usd": full_projection[
                    "projected_max_cost_usd"
                ],
                "hard_budget_cap_usd": decimal_text(budget_cap),
                "prior_known_spend_usd": decimal_text(prior_known_spend),
                "projected_phase_max_cost_usd": decimal_text(
                    selected_projection_cost + prior_known_spend
                ),
                "maximum_calls_all_matrix": full_projection["maximum_calls"],
                "plan_path": relative_path(plan_path),
            },
            sort_keys=True,
        ),
        flush=True,
    )

    if args.rescore:
        outcome = rescore_rows_from_raw(
            scope=artifact_scope,
            selected_tiers=selected_tiers,
            selected_strategies=selected_strategies,
            artifacts=artifacts,
            factory=factory,
            config=config,
            models=models,
            plan=plan,
        )
        print(
            json.dumps(
                {
                    "event": "raw_rescore_complete",
                    "api_calls": 0,
                    "row_count": outcome["audit"]["row_count"],
                    "raw_envelope_references": outcome["audit"][
                        "raw_envelope_references"
                    ],
                    "audit_path": relative_path(outcome["audit_path"]),
                },
                sort_keys=True,
            ),
            flush=True,
        )
        return

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit("OPENAI_API_KEY is required for model access validation")
    availability_path = RESULTS_RUNS_DIR / f"{artifact_scope}_model_availability.json"
    if not args.offline_dry_run:
        validate_model_access(api_key, config, availability_path)
        print(
            json.dumps(
                {
                    "event": "model_access_validated",
                    "path": relative_path(availability_path),
                    "models": MODEL_BY_TIER,
                },
                sort_keys=True,
            ),
            flush=True,
        )
    if args.dry_run:
        print(
            json.dumps(
                {
                    "event": "dry_run_complete",
                    "inference_calls": 0,
                    "case_count": len(artifacts["cases"]),
                    "validation": "PASS",
                },
                sort_keys=True,
            ),
            flush=True,
        )
        return

    run_ids = [
        run_id_for(
            artifact_scope,
            tier,
            strategy,
            artifacts["dataset_sha256"],
            factory.prompt_hash(strategy),
        )
        for tier in selected_tiers
        for strategy in selected_strategies
    ]
    initial_guard, initial_known, initial_unknown = existing_budget_state(run_ids)
    budget = Budget(
        budget_cap,
        initial_guard_spend=initial_guard + prior_known_spend,
        initial_known_actual=initial_known + prior_known_spend,
        unknown_actual=initial_unknown,
    )
    if budget.guard_spend > budget.cap:
        raise SystemExit("Existing raw evidence already exceeds this budget cap")

    completed_by_configuration: dict[str, dict[str, dict[str, str]]] = {}
    initial_completed_rows = 0
    initial_escalation_rows = 0
    initial_fallback_triggers = 0
    for tier in selected_tiers:
        for strategy in selected_strategies:
            run_id = run_id_for(
                artifact_scope,
                tier,
                strategy,
                artifacts["dataset_sha256"],
                factory.prompt_hash(strategy),
            )
            run_path = RESULTS_RUNS_DIR / f"{artifact_scope}__{tier}__{strategy}.csv"
            completed = load_existing_rows(run_path, run_id)
            key = f"{tier}__{strategy}"
            completed_by_configuration[key] = completed
            initial_completed_rows += len(completed)
            if strategy == "escalation":
                initial_escalation_rows += len(completed)
                initial_fallback_triggers += sum(
                    row_has_fallback_trigger(row) for row in completed.values()
                )

    progress_reporter: ProgressReporter | None = None
    if args.scope == "full":
        progress_reporter = ProgressReporter(
            scope=artifact_scope,
            plan_identity_sha256=plan["plan_identity_sha256"],
            expected_rows=(
                len(artifacts["cases"])
                * len(selected_tiers)
                * len(selected_strategies)
            ),
            completed_rows=initial_completed_rows,
            escalation_rows=initial_escalation_rows,
            fallback_triggers=initial_fallback_triggers,
            budget=budget,
        )
        progress_reporter.emit_due()

    invocation_started_at = utc_now()
    invocation_started = time.perf_counter()
    try:
        for tier in selected_tiers:
            for strategy in selected_strategies:
                prompt_hash = factory.prompt_hash(strategy)
                run_id = run_id_for(
                    artifact_scope,
                    tier,
                    strategy,
                    artifacts["dataset_sha256"],
                    prompt_hash,
                )
                ensure_run_manifest(artifact_scope, tier, strategy, run_id, plan)
                run_path = RESULTS_RUNS_DIR / f"{artifact_scope}__{tier}__{strategy}.csv"
                completed = completed_by_configuration[f"{tier}__{strategy}"]
                print(
                    json.dumps(
                        {
                            "event": "configuration_start",
                            "tier": tier,
                            "strategy": strategy,
                            "completed": len(completed),
                            "remaining": len(artifacts["cases"]) - len(completed),
                            "run_path": relative_path(run_path),
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
                    configured_tier=tier,
                    rng=random.Random(
                        int(config["seed"])
                        + TIER_ORDER.index(tier) * 100
                        + STRATEGY_ORDER.index(strategy)
                    ),
                )
                for case in artifacts["cases"]:
                    if case["case_id"] in completed:
                        continue
                    case_started = time.perf_counter()
                    calls, final_call = STRATEGY_MODULES[strategy].execute(
                        runtime, case, tier
                    )
                    latency_ms = int(round((time.perf_counter() - case_started) * 1000))
                    row = build_result_row(
                        case=case,
                        tier=tier,
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
                    if progress_reporter is not None:
                        progress_reporter.record_row(strategy, row)
                    print(
                        json.dumps(
                            {
                                "event": "case_complete",
                                "tier": tier,
                                "strategy": strategy,
                                "case_id": case["case_id"],
                                "output_type": row["output_type"],
                                "attempt_count": row["attempt_count"],
                                "cost_usd": row["cost_usd"] or None,
                            },
                            sort_keys=True,
                        ),
                        flush=True,
                    )
    except ProviderCreditExhausted as exc:
        wall_clock_ms = int(round((time.perf_counter() - invocation_started) * 1000))
        summary = write_summary(
            scope=artifact_scope,
            plan=plan,
            started_at=invocation_started_at,
            wall_clock_ms=wall_clock_ms,
            prior_known_spend=prior_known_spend,
        )
        print(
            json.dumps(
                {
                    "event": "provider_credit_halt",
                    "message": str(exc),
                    "completed_rows": summary["completed_rows"],
                    "expected_rows": summary["expected_rows"],
                    "known_cost_usd": summary["known_cost_usd"],
                    "unknown_cost_rows": summary["unknown_cost_rows"],
                    "summary_path": relative_path(
                        RESULTS_RUNS_DIR / f"{artifact_scope}_summary.json"
                    ),
                },
                sort_keys=True,
            ),
            flush=True,
        )
        raise SystemExit(3) from exc
    except BudgetExceeded as exc:
        wall_clock_ms = int(round((time.perf_counter() - invocation_started) * 1000))
        summary = write_summary(
            scope=artifact_scope,
            plan=plan,
            started_at=invocation_started_at,
            wall_clock_ms=wall_clock_ms,
            prior_known_spend=prior_known_spend,
        )
        print(
            json.dumps(
                {
                    "event": "budget_halt",
                    "message": str(exc),
                    "completed_rows": summary["completed_rows"],
                    "expected_rows": summary["expected_rows"],
                    "known_cost_usd": summary["known_cost_usd"],
                    "unknown_cost_rows": summary["unknown_cost_rows"],
                    "summary_path": relative_path(
                        RESULTS_RUNS_DIR / f"{artifact_scope}_summary.json"
                    ),
                },
                sort_keys=True,
            ),
            flush=True,
        )
        raise SystemExit(2) from exc

    wall_clock_ms = int(round((time.perf_counter() - invocation_started) * 1000))
    summary = write_summary(
        scope=artifact_scope,
        plan=plan,
        started_at=invocation_started_at,
        wall_clock_ms=wall_clock_ms,
        prior_known_spend=prior_known_spend,
    )
    print(
        json.dumps(
            {
                "event": "run_complete",
                "completed_rows": summary["completed_rows"],
                "expected_rows": summary["expected_rows"],
                "actual_total_cost_usd": summary["actual_total_cost_usd"],
                "known_cost_usd": summary["known_cost_usd"],
                "unknown_cost_rows": summary["unknown_cost_rows"],
                "wall_clock_ms_this_invocation": wall_clock_ms,
                "summary_path": relative_path(
                    RESULTS_RUNS_DIR / f"{artifact_scope}_summary.json"
                ),
            },
            sort_keys=True,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
