from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from threading import Lock
from typing import Any, Literal


class FunnelMilestone(StrEnum):
    SESSION_STARTED = "SESSION_STARTED"
    IDENTIFIED = "IDENTIFIED"
    GEOGRAPHY_ESTABLISHED = "GEOGRAPHY_ESTABLISHED"
    LOCATIONS_RESOLVED = "LOCATIONS_RESOLVED"
    ROUTE_READY = "ROUTE_READY"
    QUOTED = "QUOTED"
    CONFIRMED = "CONFIRMED"
    BOOKED = "BOOKED"
    STATUS_CHECKED = "STATUS_CHECKED"
    CANCELLED = "CANCELLED"


_FUNNEL_ORDER = (
    FunnelMilestone.SESSION_STARTED,
    FunnelMilestone.IDENTIFIED,
    FunnelMilestone.GEOGRAPHY_ESTABLISHED,
    FunnelMilestone.LOCATIONS_RESOLVED,
    FunnelMilestone.ROUTE_READY,
    FunnelMilestone.QUOTED,
    FunnelMilestone.CONFIRMED,
    FunnelMilestone.BOOKED,
)

ClarificationCategory = Literal["geography", "location", "timing", "vehicle", "passengers", "other"]
CorrectionCategory = Literal["timing", "pickup", "destination", "vehicle", "passengers", "other"]
ToolCategory = Literal["location", "route", "quote", "booking", "status", "cancellation"]
ReconciliationResult = Literal["pending", "attempted", "success", "unresolved"]


@dataclass(slots=True)
class _ProviderModelMetrics:
    calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cached_tokens: int = 0
    known_cost: Decimal = Decimal("0")
    fallback_calls: int = 0


class SessionMetrics:
    """Small, session-owned accumulator for bounded operational facts."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._milestones = {FunnelMilestone.SESSION_STARTED}
        self.customer_turn_count = 0
        self.clarification_count = 0
        self.correction_count = 0
        self.location_clarification_count = 0
        self.llm_call_count = 0
        self.successful_llm_calls = 0
        self.failed_llm_calls = 0
        self.llm_fallback_count = 0
        self.maps_fallback_count = 0
        self.tool_failure_count = 0
        self.slow_ack_count = 0
        self.guardrail_event_count = 0
        self.blocked_guardrail_count = 0
        self.guardrail_session_terminated = False
        self.silence_recovery_count = 0
        self.silence_termination = False
        self.input_tokens = 0
        self.output_tokens = 0
        self.total_tokens = 0
        self.cached_tokens = 0
        self.known_ai_cost = Decimal("0")
        self.unknown_cost_call_count = 0
        self.fallback_known_cost = Decimal("0")
        self.reconciliation_pending_count = 0
        self.reconciliation_attempt_count = 0
        self.reconciliation_success_count = 0
        self.reconciliation_unresolved_count = 0
        self._clarifications: dict[str, int] = {}
        self._corrections: dict[str, int] = {}
        self._tool_failures: dict[str, int] = {}
        self._provider_models: dict[tuple[str, str], _ProviderModelMetrics] = {}
        self._currencies: set[str] = set()

    def mark_milestone(self, milestone: FunnelMilestone) -> None:
        with self._lock:
            self._milestones.add(milestone)

    def record_customer_turn(self) -> None:
        with self._lock:
            self.customer_turn_count += 1

    def record_clarification(
        self, category: ClarificationCategory, *, location: bool = False
    ) -> None:
        with self._lock:
            self.clarification_count += 1
            self._clarifications[category] = self._clarifications.get(category, 0) + 1
            if location:
                self.location_clarification_count += 1

    def record_correction(self, category: CorrectionCategory) -> None:
        with self._lock:
            self.correction_count += 1
            self._corrections[category] = self._corrections.get(category, 0) + 1

    def record_llm_call(
        self,
        *,
        provider: str,
        model: str,
        success: bool,
        fallback: bool,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        total_tokens: int | None = None,
        cached_tokens: int | None = None,
        total_cost: Decimal | None = None,
        currency: str | None = None,
    ) -> None:
        with self._lock:
            self.llm_call_count += 1
            self.successful_llm_calls += int(success)
            self.failed_llm_calls += int(not success)
            self.llm_fallback_count += int(fallback)
            self.input_tokens += input_tokens or 0
            self.output_tokens += output_tokens or 0
            self.total_tokens += total_tokens or 0
            self.cached_tokens += cached_tokens or 0
            item = self._provider_models.setdefault(
                (provider, model), _ProviderModelMetrics()
            )
            item.calls += 1
            item.successful_calls += int(success)
            item.failed_calls += int(not success)
            item.fallback_calls += int(fallback)
            item.input_tokens += input_tokens or 0
            item.output_tokens += output_tokens or 0
            item.total_tokens += total_tokens or 0
            item.cached_tokens += cached_tokens or 0
            if total_cost is None or currency is None:
                self.unknown_cost_call_count += 1
            else:
                self.known_ai_cost += total_cost
                item.known_cost += total_cost
                self._currencies.add(currency)
                if fallback:
                    self.fallback_known_cost += total_cost

    def record_maps_fallback(self) -> None:
        with self._lock:
            self.maps_fallback_count += 1

    def record_tool_failure(self, category: ToolCategory) -> None:
        with self._lock:
            self.tool_failure_count += 1
            self._tool_failures[category] = self._tool_failures.get(category, 0) + 1

    def record_reconciliation(self, result: ReconciliationResult) -> None:
        field = {
            "pending": "reconciliation_pending_count",
            "attempted": "reconciliation_attempt_count",
            "success": "reconciliation_success_count",
            "unresolved": "reconciliation_unresolved_count",
        }[result]
        with self._lock:
            setattr(self, field, getattr(self, field) + 1)

    def record_slow_ack(self) -> None:
        with self._lock:
            self.slow_ack_count += 1

    def record_silence_recovery(self, *, terminated: bool = False) -> None:
        with self._lock:
            self.silence_recovery_count += 1
            self.silence_termination = self.silence_termination or terminated

    def record_guardrail(self, *, blocked: bool, terminated: bool = False) -> None:
        with self._lock:
            self.guardrail_event_count += 1
            self.blocked_guardrail_count += int(blocked)
            self.guardrail_session_terminated = (
                self.guardrail_session_terminated or terminated
            )

    def summary(self, *, outcome: str) -> dict[str, Any]:
        with self._lock:
            highest = max(
                (item for item in _FUNNEL_ORDER if item in self._milestones),
                key=_FUNNEL_ORDER.index,
            )
            currencies = sorted(self._currencies)
            return {
                "session_outcome": outcome,
                "customer_turn_count": self.customer_turn_count,
                "clarification_count": self.clarification_count,
                "clarification_categories": dict(sorted(self._clarifications.items())),
                "correction_count": self.correction_count,
                "correction_categories": dict(sorted(self._corrections.items())),
                "location_clarification_count": self.location_clarification_count,
                "llm_call_count": self.llm_call_count,
                "successful_llm_calls": self.successful_llm_calls,
                "failed_llm_calls": self.failed_llm_calls,
                "llm_fallback_count": self.llm_fallback_count,
                "maps_fallback_count": self.maps_fallback_count,
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "total_tokens": self.total_tokens,
                "cached_tokens": self.cached_tokens,
                "known_ai_cost": str(self.known_ai_cost),
                "fallback_known_cost": str(self.fallback_known_cost),
                "cost_currency": currencies[0] if len(currencies) == 1 else None,
                "cost_complete": self.unknown_cost_call_count == 0,
                "unknown_cost_call_count": self.unknown_cost_call_count,
                "provider_model_breakdown": [
                    {
                        "provider": provider,
                        "model": model,
                        "calls": item.calls,
                        "successful_calls": item.successful_calls,
                        "failed_calls": item.failed_calls,
                        "fallback_calls": item.fallback_calls,
                        "total_tokens": item.total_tokens,
                        "known_cost": str(item.known_cost),
                    }
                    for (provider, model), item in sorted(self._provider_models.items())
                ],
                "tool_failure_count": self.tool_failure_count,
                "tool_failure_categories": dict(sorted(self._tool_failures.items())),
                "reconciliation_pending_count": self.reconciliation_pending_count,
                "reconciliation_attempt_count": self.reconciliation_attempt_count,
                "reconciliation_success_count": self.reconciliation_success_count,
                "reconciliation_unresolved_count": self.reconciliation_unresolved_count,
                "slow_ack_count": self.slow_ack_count,
                "silence_recovery_count": self.silence_recovery_count,
                "silence_termination": self.silence_termination,
                "guardrail_event_count": self.guardrail_event_count,
                "blocked_guardrail_count": self.blocked_guardrail_count,
                "guardrail_session_terminated": self.guardrail_session_terminated,
                "interruption_count": None,
                "funnel_highest_stage": highest.value,
                "funnel_milestones": [
                    item.value for item in FunnelMilestone if item in self._milestones
                ],
            }
