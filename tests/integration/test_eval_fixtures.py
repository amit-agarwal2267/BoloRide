from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from boloride.domain.enums import RideStatus
from boloride.domain.models.quote import request_fingerprint
from boloride.evals.fixture_builder import EvaluationFixtureBuilder
from boloride.evals.integrated_factory import FixtureBackedAgentFactory
from boloride.evals.runner import load_cases
from boloride.prompts.client import ResolvedPrompt
from boloride.prompts.registry import PromptBundle
from boloride.repositories.ride_repository import RideRepository


CASES = Path("src/boloride/evals/cases/voice_agent_v2.json")


@pytest.mark.asyncio
async def test_all_integrated_fixture_profiles_build_real_state(
    db_session: AsyncSession,
) -> None:
    integrated = [case for case in load_cases(CASES) if case.tool_required]

    for case in integrated:
        runtime = await EvaluationFixtureBuilder(db_session).build(case)
        fixture = case.fixture
        assert fixture is not None
        assert runtime.context.session_active is fixture.session_active

        if fixture.customer:
            assert runtime.customer_id is not None
            assert runtime.context.identity_verified is fixture.customer.verified
            assert runtime.context.verified_customer_id == runtime.customer_id
        assert (
            runtime.context.pickup_instruction_handled
            is fixture.pickup_instruction_handled
        )
        if fixture.location_search_results:
            assert len(runtime.location_search_results) == len(
                fixture.location_search_results
            )
        if fixture.quote:
            quote = runtime.quote
            assert quote is runtime.context.current_quote
            assert quote is not None
            assert quote.pricing.estimated_total == Decimal(
                fixture.quote.expected_estimated_total
            )
            assert quote.request_fingerprint == request_fingerprint(
                runtime.context.pickup,
                runtime.context.destination,
                runtime.context.ride_time,
                runtime.context.passenger_count,
                runtime.context.selected_vehicle_type_code,
            )
            assert runtime.references[fixture.quote.quote_ref] == quote.id
            assert runtime.context.user_confirmed is fixture.quote.confirmed
        if fixture.offer:
            assert runtime.offer is not None
            assert runtime.offer.code == fixture.offer.code
        if fixture.ride:
            assert runtime.customer_id is not None
            assert runtime.ride_id is not None
            ride = await RideRepository(db_session).get_for_customer(
                runtime.customer_id, runtime.ride_id
            )
            assert ride is not None
            assert ride.status is RideStatus(fixture.ride.status)
            assert runtime.references[fixture.ride.ride_ref] == ride.id
        if fixture.booking_provider:
            assert runtime.booking_provider_outcome == fixture.booking_provider.outcome
            assert runtime.provider_booking_id == fixture.booking_provider.provider_booking_id


@pytest.mark.asyncio
async def test_cancellation_fixture_is_customer_owned_and_cancellable(
    db_session: AsyncSession,
) -> None:
    case = next(case for case in load_cases(CASES) if case.case_id == "VA2-015")
    runtime = await EvaluationFixtureBuilder(db_session).build(case)

    ride = await RideRepository(db_session).get_for_customer(
        runtime.customer_id, runtime.ride_id
    )
    assert ride is not None
    assert ride.status is RideStatus.BOOKED


@pytest.mark.asyncio
async def test_offer_fixture_is_real_and_discount_matches_declared_amount(
    db_session: AsyncSession,
) -> None:
    case = next(case for case in load_cases(CASES) if case.case_id == "VA2-014")
    runtime = await EvaluationFixtureBuilder(db_session).build(case)
    fixture = case.fixture
    assert fixture is not None and fixture.offer is not None

    raw_discount = (
        runtime.quote.pricing.estimated_total
        * runtime.offer.percentage
        / Decimal("100")
    ).quantize(Decimal("0.01"))
    assert raw_discount == Decimal(fixture.offer.expected_discount_amount)


@pytest.mark.asyncio
async def test_fixture_backed_factory_exposes_real_agent_tools(
    db_session: AsyncSession,
) -> None:
    case = next(case for case in load_cases(CASES) if case.case_id == "VA2-006")
    resolved = ResolvedPrompt(
        "evaluation", "Use the available tools.", "fallback", "evaluation"
    )
    bundle = PromptBundle(resolved, resolved, resolved, resolved, resolved)
    factory = FixtureBackedAgentFactory(lambda: db_session, bundle)  # type: ignore[arg-type]

    agent, context, cleanup = await factory(case, "ignored")
    try:
        assert context.current_quote is not None
        assert context.user_confirmed is False
        result = await agent.record_booking_confirmation(True)
        assert "confirmation recorded" in result.casefold()
        assert context.confirmation_received
    finally:
        await cleanup()
