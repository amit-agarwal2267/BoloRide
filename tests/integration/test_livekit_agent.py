from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from boloride.agents.context import RideContext
from boloride.agents.voice_agent import BoloRideAgent
from boloride.domain.exceptions import DomainValidationError
from boloride.domain.models.location import LocationCandidate
from boloride.domain.policies import CustomerIdentityState
from boloride.services.time_resolution_service import TimeResolutionService


class NullTracer:
    @contextmanager
    def observe(self, *args: object, **kwargs: object):
        yield SimpleNamespace(update=lambda **values: None)


class ConfirmationGuard:
    async def book_ride(self, user_id, context):
        if not context.user_confirmed:
            raise DomainValidationError("explicit booking confirmation is required")


def make_agent() -> tuple[BoloRideAgent, RideContext, AsyncMock]:
    user_id = uuid4()
    context = RideContext(
        session_id="voice-test",
        caller_id=user_id,
        identity_state=CustomerIdentityState.VERIFIED_RETURNING_CUSTOMER,
        verified_customer_id=user_id,
    )
    database_session = AsyncMock()
    locations = SimpleNamespace(
        search_locations=AsyncMock(
            return_value=[
                LocationCandidate(
                    "Kota Junction",
                    "Kota Junction, Rajasthan",
                    Decimal("25.2138"),
                    Decimal("75.8648"),
                    "google",
                    "place-1",
                ),
                LocationCandidate(
                    "Dakaniya Talav",
                    "Dakaniya Talav, Kota",
                    Decimal("25.145"),
                    Decimal("75.857"),
                    "google",
                    "place-2",
                ),
            ]
        ),
        resolve_candidate=AsyncMock(
            side_effect=lambda candidate: candidate.to_resolved_location()
        ),
    )
    agent = BoloRideAgent(
        base_prompt="You are BoloRide.",
        context=context,
        user_id=user_id,
        database_session=database_session,
        locations=locations,
        saved_places=SimpleNamespace(list_places=AsyncMock(return_value=[]), resolve_label=AsyncMock(return_value=None)),
        rides=SimpleNamespace(list_for_customer=AsyncMock(return_value=[])),
        ride_service=SimpleNamespace(
            get_customer_ride_status=AsyncMock(return_value=None),
            cancel_customer_ride=AsyncMock(),
        ),
        dispatch=SimpleNamespace(dispatch=AsyncMock()),
        booking=ConfirmationGuard(),
        quotes=SimpleNamespace(
            confirm_quote=lambda context, quote_id: context.confirm_quote(quote_id),
            create_quote=AsyncMock(),
        ),
        offers=SimpleNamespace(get_eligible_offers=AsyncMock(return_value=[])),
        tracer=NullTracer(),  # type: ignore[arg-type]
        default_city="Kota",
        default_state="Rajasthan",
        default_country="IN",
        timezone="Asia/Kolkata",
        time_resolution=TimeResolutionService(lambda: datetime(2026, 9, 6, 12, tzinfo=UTC)),
    )
    return agent, context, database_session


@pytest.mark.asyncio
async def test_ambiguous_location_then_correction_invalidates_confirmation() -> None:
    agent, context, _ = make_agent()
    locations = agent._locations
    locations.resolve_query = AsyncMock(return_value=SimpleNamespace(
        status=__import__("boloride.domain.models.location", fromlist=["LocationResolutionStatus"]).LocationResolutionStatus.CLARIFICATION_REQUIRED,
        candidates=tuple(await locations.search_locations("Kota station")),
    ))
    output = await agent.search_locations("Kota station", "destination")
    assert "1. Kota Junction" in output
    assert "2. Dakaniya Talav" in output
    assert context.clarification_required is True

    await agent.select_location_candidate(1, "destination")
    assert context.destination is not None
    assert context.destination.provider_place_id == "place-1"
    assert context.clarification_required is False

    await agent.set_ride_time("tomorrow 7 AM")
    context.user_confirmed = True
    await agent.set_ride_time("6:30", correction=True)
    assert context.ride_time == datetime.fromisoformat("2026-09-07T01:00:00+00:00")
    assert context.user_confirmed is False


@pytest.mark.asyncio
async def test_booking_tool_requires_separately_recorded_confirmation() -> None:
    agent, context, database_session = make_agent()
    result = await agent.create_booking()
    assert "rejected" in result.lower()
    assert context.user_confirmed is False
    database_session.commit.assert_not_awaited()
