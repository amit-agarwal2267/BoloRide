import asyncio
from decimal import Decimal

from boloride.observability.session_metrics import FunnelMilestone, SessionMetrics


def test_funnel_is_monotonic_and_confirmation_is_not_booking() -> None:
    metrics = SessionMetrics()
    metrics.mark_milestone(FunnelMilestone.IDENTIFIED)
    metrics.mark_milestone(FunnelMilestone.QUOTED)
    metrics.mark_milestone(FunnelMilestone.CONFIRMED)

    summary = metrics.summary(outcome="completed_without_booking")

    assert summary["funnel_highest_stage"] == "CONFIRMED"
    assert "BOOKED" not in summary["funnel_milestones"]
    assert summary["clarification_count"] == 0


def test_booked_then_cancelled_retains_both_milestones() -> None:
    metrics = SessionMetrics()
    metrics.mark_milestone(FunnelMilestone.BOOKED)
    metrics.mark_milestone(FunnelMilestone.CANCELLED)

    summary = metrics.summary(outcome="cancelled")

    assert summary["session_outcome"] == "cancelled"
    assert summary["funnel_highest_stage"] == "BOOKED"
    assert {"BOOKED", "CANCELLED"}.issubset(summary["funnel_milestones"])


def test_clarification_correction_and_turn_semantics() -> None:
    metrics = SessionMetrics()
    metrics.record_customer_turn()
    metrics.record_clarification("location", location=True)
    metrics.record_clarification("timing")
    metrics.record_correction("pickup")

    summary = metrics.summary(outcome="abandoned")

    assert summary["customer_turn_count"] == 1
    assert summary["clarification_count"] == 2
    assert summary["location_clarification_count"] == 1
    assert summary["clarification_categories"] == {"location": 1, "timing": 1}
    assert summary["correction_categories"] == {"pickup": 1}


def test_llm_usage_cost_fallback_and_provider_model_breakdown() -> None:
    metrics = SessionMetrics()
    metrics.record_llm_call(
        provider="google",
        model="exact",
        success=True,
        fallback=False,
        input_tokens=10,
        output_tokens=5,
        total_tokens=15,
        cached_tokens=2,
        total_cost=Decimal("0.001"),
        currency="USD",
    )
    metrics.record_llm_call(
        provider="groq",
        model="fallback",
        success=True,
        fallback=True,
        input_tokens=4,
        output_tokens=3,
        total_tokens=7,
    )

    summary = metrics.summary(outcome="booked")

    assert summary["llm_call_count"] == 2
    assert summary["llm_fallback_count"] == 1
    assert summary["total_tokens"] == 22
    assert summary["cached_tokens"] == 2
    assert summary["known_ai_cost"] == "0.001"
    assert summary["unknown_cost_call_count"] == 1
    assert summary["cost_complete"] is False
    assert len(summary["provider_model_breakdown"]) == 2


def test_all_known_costs_are_complete_and_fallback_cost_is_separate() -> None:
    metrics = SessionMetrics()
    metrics.record_llm_call(
        provider="google", model="a", success=False, fallback=False,
        total_cost=Decimal("0.01"), currency="USD",
    )
    metrics.record_llm_call(
        provider="groq", model="b", success=True, fallback=True,
        total_cost=Decimal("0.02"), currency="USD",
    )

    summary = metrics.summary(outcome="completed_without_booking")

    assert summary["cost_complete"] is True
    assert summary["known_ai_cost"] == "0.03"
    assert summary["fallback_known_cost"] == "0.02"
    assert summary["failed_llm_calls"] == 1


def test_reliability_silence_guardrail_and_tool_counts() -> None:
    metrics = SessionMetrics()
    metrics.record_tool_failure("booking")
    metrics.record_reconciliation("pending")
    metrics.record_reconciliation("attempted")
    metrics.record_reconciliation("success")
    metrics.record_slow_ack()
    metrics.record_silence_recovery()
    metrics.record_silence_recovery(terminated=True)
    metrics.record_guardrail(blocked=True, terminated=True)

    summary = metrics.summary(outcome="guardrail_terminated")

    assert summary["tool_failure_categories"] == {"booking": 1}
    assert summary["reconciliation_pending_count"] == 1
    assert summary["reconciliation_attempt_count"] == 1
    assert summary["reconciliation_success_count"] == 1
    assert summary["slow_ack_count"] == 1
    assert summary["silence_recovery_count"] == 2
    assert summary["silence_termination"] is True
    assert summary["guardrail_session_terminated"] is True
    assert summary["interruption_count"] is None


def test_summary_schema_cannot_contain_customer_text_or_pii() -> None:
    summary = SessionMetrics().summary(outcome="completed_without_booking")
    forbidden = {"name", "phone", "address", "transcript", "prompt", "response"}
    assert forbidden.isdisjoint(summary)


def test_two_concurrent_session_metrics_do_not_share_state() -> None:
    first = SessionMetrics()
    second = SessionMetrics()

    async def update(metrics: SessionMetrics, count: int) -> None:
        for _ in range(count):
            metrics.record_customer_turn()
            await asyncio.sleep(0)

    async def run_updates() -> None:
        await asyncio.gather(update(first, 2), update(second, 3))

    asyncio.run(run_updates())

    assert first.summary(outcome="abandoned")["customer_turn_count"] == 2
    assert second.summary(outcome="abandoned")["customer_turn_count"] == 3
