from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from boloride.agents.context import RideContext
from boloride.agents.voice_agent import BoloRideAgent
from boloride.domain.policies import CustomerIdentityResult, CustomerIdentityState
from boloride.services.time_resolution_service import TimeResolutionService


class Tracer:
    @contextmanager
    def observe(self, *args, **kwargs):
        yield SimpleNamespace(update=lambda **values: None)


def agent_for(state, result, *, phone="9876543210"):
    context = RideContext(session_id="identity-test", caller_id=None, identity_state=state)
    database = AsyncMock()
    users = SimpleNamespace(
        onboard_customer=AsyncMock(return_value=result),
        resolve_returning_customer=AsyncMock(return_value=result),
    )
    agent = BoloRideAgent(
        base_prompt="BoloRide", context=context, user_id=None, database_session=database,
        locations=SimpleNamespace(), saved_places=SimpleNamespace(list_places=AsyncMock()),
        rides=SimpleNamespace(), ride_service=SimpleNamespace(), dispatch=SimpleNamespace(),
        booking=SimpleNamespace(), quotes=SimpleNamespace(), offers=SimpleNamespace(),
        tracer=Tracer(), default_city=None, default_state=None, default_country="IN",
        timezone="Asia/Kolkata", time_resolution=TimeResolutionService(lambda: datetime.now(UTC)),
        user_service=users, detected_phone=phone,
    )
    return agent, context, users, database


@pytest.mark.asyncio
async def test_new_customer_corrections_are_submitted_once_and_unlock_tools():
    customer_id = uuid4()
    result = CustomerIdentityResult(CustomerIdentityState.ONBOARDED_NEW_CUSTOMER, customer_id)
    agent, context, users, database = agent_for(CustomerIdentityState.NEW_CUSTOMER_ONBOARDING_REQUIRED, result)
    await agent.record_identity_details("Amit", 24)
    await agent.record_identity_details("Amit Agarwal", 25)
    assert "verified" in (await agent.submit_customer_identity()).lower()
    users.onboard_customer.assert_awaited_once_with("9876543210", "Amit Agarwal", 25)
    database.commit.assert_awaited_once()
    assert context.verified_customer_id == customer_id


@pytest.mark.asyncio
async def test_returning_customer_uses_name_only_and_unlocks_tools():
    customer_id = uuid4()
    result = CustomerIdentityResult(CustomerIdentityState.VERIFIED_RETURNING_CUSTOMER, customer_id)
    agent, context, users, _ = agent_for(CustomerIdentityState.RETURNING_CUSTOMER_VERIFICATION_REQUIRED, result)
    assert "do not ask for age" in (await agent.get_identity_requirements()).lower()
    await agent.record_identity_details(name="Amit Agarwal")
    await agent.submit_customer_identity()
    users.resolve_returning_customer.assert_awaited_once_with("9876543210", "Amit Agarwal")
    assert context.identity_verified


@pytest.mark.asyncio
async def test_mismatch_keeps_tools_locked_and_allows_name_retry():
    mismatch = CustomerIdentityResult(CustomerIdentityState.NAME_MISMATCH)
    agent, context, users, _ = agent_for(CustomerIdentityState.RETURNING_CUSTOMER_VERIFICATION_REQUIRED, mismatch)
    await agent.record_identity_details(name="Wrong Name")
    assert "did not match" in (await agent.submit_customer_identity()).lower()
    assert not context.identity_verified
    assert "identification is required" in (await agent.get_previous_rides()).lower()
    await agent.record_identity_details(name="Corrected Name")
    await agent.submit_customer_identity()
    assert users.resolve_returning_customer.await_count == 2


@pytest.mark.asyncio
async def test_missing_phone_never_establishes_customer_or_unlocks_tools():
    agent, context, users, _ = agent_for(CustomerIdentityState.PHONE_UNAVAILABLE, CustomerIdentityResult(CustomerIdentityState.PHONE_UNAVAILABLE), phone=None)
    assert "cannot continue" in (await agent.get_identity_requirements()).lower()
    assert "cannot continue" in (await agent.record_identity_details(name="Amit")).lower()
    assert "identification is required" in (await agent.create_fare_quote()).lower()
    users.onboard_customer.assert_not_awaited()
