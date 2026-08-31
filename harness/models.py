#!/usr/bin/env python3
"""Frozen model-tier and price-table configuration."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any


HARNESS_DIR = Path(__file__).resolve().parent
PRICE_TABLE_PATH = HARNESS_DIR / "pricing.json"
TIER_ORDER = ("cheap", "standard", "capable")
MODEL_BY_TIER = {
    "cheap": "gpt-5.4-nano-2026-03-17",
    "standard": "gpt-5.4-mini-2026-03-17",
    "capable": "gpt-5.4-2026-03-05",
}


def sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class ModelTier:
    tier: str
    model_version: str
    input_per_1m_tokens: Decimal
    cached_input_per_1m_tokens: Decimal
    output_per_1m_tokens: Decimal
    source_url: str


def load_price_table() -> dict[str, Any]:
    table = json.loads(PRICE_TABLE_PATH.read_text(encoding="utf-8"))
    if table.get("unit") != "per_1m_tokens" or table.get("currency") != "USD":
        raise ValueError("Unsupported price-table unit or currency")
    if set(table.get("models", {})) != set(MODEL_BY_TIER.values()):
        raise ValueError("Price table does not exactly cover the frozen model snapshots")
    return table


def load_model_tiers() -> dict[str, ModelTier]:
    table = load_price_table()
    tiers: dict[str, ModelTier] = {}
    for tier in TIER_ORDER:
        model_version = MODEL_BY_TIER[tier]
        prices = table["models"][model_version]
        tiers[tier] = ModelTier(
            tier=tier,
            model_version=model_version,
            input_per_1m_tokens=Decimal(str(prices["input_per_1m_tokens"])),
            cached_input_per_1m_tokens=Decimal(
                str(prices["cached_input_per_1m_tokens"])
            ),
            output_per_1m_tokens=Decimal(str(prices["output_per_1m_tokens"])),
            source_url=str(prices["source_url"]),
        )
    return tiers


def cost_usd(
    model: ModelTier,
    input_tokens: int,
    output_tokens: int,
    cached_input_tokens: int = 0,
) -> Decimal:
    if min(input_tokens, output_tokens, cached_input_tokens) < 0:
        raise ValueError("Token counts cannot be negative")
    if cached_input_tokens > input_tokens:
        raise ValueError("Cached input tokens cannot exceed input tokens")
    million = Decimal(1_000_000)
    uncached = input_tokens - cached_input_tokens
    return (
        Decimal(uncached) * model.input_per_1m_tokens
        + Decimal(cached_input_tokens) * model.cached_input_per_1m_tokens
        + Decimal(output_tokens) * model.output_per_1m_tokens
    ) / million
