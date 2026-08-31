from __future__ import annotations

import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

from harness.models import cost_usd, load_model_tiers
from harness.run import redact_secret_material
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


if __name__ == "__main__":
    unittest.main()
