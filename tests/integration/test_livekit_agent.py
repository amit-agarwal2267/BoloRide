from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from boloride.agents.context import RideContext
from boloride.agents.voice_agent import BoloRideAgent
from boloride.domain.exceptions import DomainValidationError
from boloride.domain.models.location import LocationCandidate


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
    context = RideContext(session_id="voice-test", caller_id=user_id)
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
        saved_places=SimpleNamespace(list_places=AsyncMock(return_value=[])),
        rides=SimpleNamespace(list_for_customer=AsyncMock(return_value=[])),
        booking=ConfirmationGuard(),
        tracer=NullTracer(),  # type: ignore[arg-type]
        default_city="Kota",
        default_state="Rajasthan",
        default_country="IN",
        timezone="Asia/Kolkata",
    )
    return agent, context, database_session


@pytest.mark.asyncio
async def test_ambiguous_location_then_correction_invalidates_confirmation() -> None:
    agent, context, _ = make_agent()
    output = await agent.search_locations("Kota station")
    assert "1. Kota Junction" in output
    assert "2. Dakaniya Talav" in output
    assert context.clarification_required is True

    await agent.select_location_candidate(1, "destination")
    assert context.destination is not None
    assert context.destination.provider_place_id == "place-1"
    assert context.clarification_required is False

    await agent.set_ride_time("2026-09-07T07:00:00+05:30")
    context.user_confirmed = True
    await agent.set_ride_time("2026-09-07T06:30:00+05:30")
    assert context.ride_time == datetime.fromisoformat("2026-09-07T06:30:00+05:30")
    assert context.user_confirmed is False


@pytest.mark.asyncio
async def test_booking_tool_requires_separately_recorded_confirmation() -> None:
    agent, context, database_session = make_agent()
    result = await agent.create_booking()
    assert "rejected" in result.lower()
    assert context.user_confirmed is False
    database_session.commit.assert_not_awaited()
