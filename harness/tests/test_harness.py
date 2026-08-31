from __future__ import annotations

import unittest
from decimal import Decimal
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from harness.models import cost_usd, load_model_tiers
from harness.run import (
    REPO_ROOT,
    Budget,
    ProviderCreditExhausted,
    ProgressReporter,
    Runtime,
    call_result_from_envelopes,
    provider_error_code,
    redact_secret_material,
)
from harness.strategies import self_check
from harness.scoring import (
    compute_registered_metrics,
    parse_model_content,
    pre_adjudication_scores,
)


class SemanticOutputTests(unittest.TestCase):
    def test_valid_answer(self) -> None:
        parsed, error = parse_model_content(
            '{"output_type":"ANSWER","answer_text":"Grounded.",'
            '"citations":["p1"],"confidence":0.8}'
        )
        self.assertIsNone(error)
        self.assertEqual(parsed.output_type, "ANSWER")

    def test_nonanswer_fields_must_be_empty(self) -> None:
        parsed, error = parse_model_content(
            '{"output_type":"ABSTAIN","answer_text":"because",'
            '"citations":[],"confidence":0.2}'
        )
        self.assertIsNone(parsed)
        self.assertEqual(error, "invalid_contract:nonanswer_fields")

    def test_unknown_citation_fails_pre_adjudication(self) -> None:
        parsed, _ = parse_model_content(
            '{"output_type":"ANSWER","answer_text":"Grounded.",'
            '"citations":["invented"],"confidence":0.8}'
        )
        correct, citation_valid, _ = pre_adjudication_scores(
            {"expected_behaviour": "ANSWER"}, parsed, {"p1"}
        )
        self.assertFalse(correct)
        self.assertFalse(citation_valid)


class CostTests(unittest.TestCase):
    def test_frozen_nano_cost(self) -> None:
        model = load_model_tiers()["cheap"]
        self.assertEqual(
            cost_usd(model, 1_000_000, 1_000_000), Decimal("1.45")
        )

    def test_diagnostic_key_redaction(self) -> None:
        value = "Incorrect API key provided: sk-proj-example_secret_value"
        redacted = redact_secret_material(value)
        self.assertNotIn("sk-proj", redacted)
        self.assertIn("[REDACTED_OPENAI_API_KEY]", redacted)

    def test_raw_result_exposes_fresh_and_cached_input_tokens(self) -> None:
        model = load_model_tiers()["cheap"]
        response_body = {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"output_type":"ABSTAIN","answer_text":"",'
                            '"citations":[],"confidence":0.2}'
                        )
                    }
                }
            ]
        }
        envelope = {
            "http_status": 200,
            "response_body_raw": json.dumps(response_body),
            "returned_model": model.model_version,
            "usage": {
                "prompt_tokens": 3352,
                "completion_tokens": 76,
                "prompt_tokens_details": {"cached_tokens": 2816},
            },
            "cost_usd": "0.000258520000",
            "budget_guard_cost_usd": "0.005000000000",
        }
        path = REPO_ROOT / "tmp" / "unit-cache-envelope.json"
        result = call_result_from_envelopes(
            "primary", "cheap", model, [(path, envelope)]
        )

        self.assertEqual(result.input_tokens, 3352)
        self.assertEqual(result.cached_input_tokens, 2816)
        self.assertEqual(result.fresh_input_tokens, 536)
        self.assertEqual(result.output_tokens, 76)

    def test_budget_guard_uses_frozen_token_estimate(self) -> None:
        config = json.loads((REPO_ROOT / "harness" / "config.json").read_text())
        model = load_model_tiers()["cheap"]
        runtime = object.__new__(Runtime)
        runtime.config = config

        guard = runtime._request_guard_cost(model, 3_352)

        self.assertEqual(
            guard,
            cost_usd(model, 3_352, int(config["max_completion_tokens"])),
        )

    def test_provider_credit_error_is_identified(self) -> None:
        self.assertEqual(
            provider_error_code({"error": {"code": "credit_balance_exhausted"}}),
            "credit_balance_exhausted",
        )

    def test_existing_credit_error_halts_without_another_attempt(self) -> None:
        config = json.loads((REPO_ROOT / "harness" / "config.json").read_text())
        model = load_model_tiers()["cheap"]
        runtime = object.__new__(Runtime)
        runtime.models = {"cheap": model}
        runtime.config = config
        runtime.estimator = Mock()
        runtime.estimator.count_messages.return_value = 1
        runtime._existing_envelopes = Mock(
            return_value=[
                (
                    REPO_ROOT / "tmp" / "credit-exhausted.json",
                    {
                        "http_status": 429,
                        "retryable": False,
                        "provider_error_code": "credit_balance_exhausted",
                    },
                )
            ]
        )
        runtime._perform_attempt = Mock()

        with self.assertRaises(ProviderCreditExhausted):
            runtime.invoke(
                case={"case_id": "case_0001"},
                model_tier="cheap",
                call_role="primary",
                call_index=1,
                messages=[],
            )
        runtime._perform_attempt.assert_not_called()


class MetricTests(unittest.TestCase):
    def test_metrics_require_manual_answer_adjudication(self) -> None:
        rows = [
            {
                "case_id": "case_0001",
                "output_type": "ANSWER",
                "correct": "",
                "confidence": "0.8",
                "cost_usd": "0.01",
                "latency_ms": "100",
            }
        ]
        with self.assertRaises(ValueError):
            compute_registered_metrics(
                rows,
                {"case_0001": {"expected_behaviour": "ANSWER"}},
            )

    def test_invalid_rows_are_not_covered_or_selectively_accurate(self) -> None:
        rows = [
            {
                "case_id": "case_0001",
                "output_type": "INVALID",
                "correct": "false",
                "confidence": "",
                "cost_usd": "0.01",
                "latency_ms": "100",
            },
            {
                "case_id": "case_0002",
                "output_type": "ABSTAIN",
                "correct": "true",
                "confidence": "0.1",
                "cost_usd": "0.01",
                "latency_ms": "100",
            },
        ]
        metrics = compute_registered_metrics(
            rows,
            {
                "case_0001": {"expected_behaviour": "ANSWER"},
                "case_0002": {"expected_behaviour": "ABSTAIN"},
            },
        )
        self.assertEqual(metrics["coverage"], 0.0)
        self.assertIsNone(metrics["selective_accuracy"])
        self.assertEqual(metrics["invalid_rate"], 0.5)


class StrategyTests(unittest.TestCase):
    def test_self_check_always_makes_critic_call(self) -> None:
        primary = SimpleNamespace(response_content=None)
        critic = SimpleNamespace(response_content="final")
        runtime = Mock()
        runtime.base_messages.return_value = []
        runtime.critic_messages.return_value = []
        runtime.invoke.side_effect = [primary, critic]

        calls, final = self_check.execute(
            runtime, {"case_id": "case_0001"}, "cheap"
        )

        self.assertEqual(runtime.invoke.call_count, 2)
        self.assertEqual(calls, [primary, critic])
        self.assertIs(final, critic)


class ProgressCheckpointTests(unittest.TestCase):
    def test_reports_25_50_75_percent_with_spend_and_trigger_rate(self) -> None:
        progress_path = REPO_ROOT / "tmp" / "unit-full-progress.json"
        progress_path.unlink(missing_ok=True)
        try:
            reporter = ProgressReporter(
                scope="full",
                plan_identity_sha256="plan",
                expected_rows=8,
                completed_rows=0,
                escalation_rows=2,
                fallback_triggers=1,
                budget=Budget(
                    Decimal("70"), initial_known_actual=Decimal("1.25")
                ),
                progress_path=progress_path,
            )
            with patch("builtins.print") as mocked_print:
                for _ in range(6):
                    reporter.record_row("single_pass", {})

            emitted = [
                json.loads(call.args[0])
                for call in mocked_print.call_args_list
                if call.args and isinstance(call.args[0], str)
            ]
            self.assertEqual(
                [item["checkpoint_percent"] for item in emitted], [25, 50, 75]
            )
            self.assertTrue(
                all(item["known_cumulative_spend_usd"] == "1.250000000000" for item in emitted)
            )
            self.assertTrue(
                all(item["escalation_trigger_rate"] == 0.5 for item in emitted)
            )
            saved = json.loads(progress_path.read_text(encoding="utf-8"))
            self.assertEqual(len(saved["emitted_checkpoints"]), 3)
        finally:
            progress_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
