from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from typing import Mapping

from boloride.llm.models import ProviderName, TokenUsage


TOKENS_PER_PRICING_UNIT = Decimal("1000000")


@dataclass(frozen=True, slots=True)
class ModelPricing:
    input_per_1m_tokens: Decimal
    output_per_1m_tokens: Decimal
    currency: str
    source: str
    last_verified: date

    def __post_init__(self) -> None:
        if self.input_per_1m_tokens < 0 or self.output_per_1m_tokens < 0:
            raise ValueError("model token prices cannot be negative")
        if not self.currency.strip() or not self.source.strip():
            raise ValueError("model pricing currency and source are required")


# BoloRide-owned registry. Add only exact, explicitly verified provider/model prices.
MODEL_PRICING: Mapping[tuple[ProviderName, str], ModelPricing] = {}


def apply_llm_cost(
    provider: ProviderName,
    model: str,
    usage: TokenUsage,
    *,
    registry: Mapping[tuple[ProviderName, str], ModelPricing] = MODEL_PRICING,
) -> TokenUsage:
    """Attach execution-time cost without substituting model aliases."""
    if usage.cost_source == "provider_reported":
        return usage
    pricing = registry.get((provider, model))
    if pricing is None or usage.input_tokens is None or usage.output_tokens is None:
        return replace(
            usage,
            input_cost=None,
            output_cost=None,
            total_cost=None,
            currency=None,
            cost_source="unknown",
        )
    input_cost = (
        Decimal(usage.input_tokens) / TOKENS_PER_PRICING_UNIT
    ) * pricing.input_per_1m_tokens
    output_cost = (
        Decimal(usage.output_tokens) / TOKENS_PER_PRICING_UNIT
    ) * pricing.output_per_1m_tokens
    return replace(
        usage,
        input_cost=input_cost,
        output_cost=output_cost,
        total_cost=input_cost + output_cost,
        currency=pricing.currency,
        cost_source="pricing_registry",
    )
