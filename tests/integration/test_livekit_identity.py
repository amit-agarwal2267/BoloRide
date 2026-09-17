from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from boloride.agents.context import RideContext
from boloride.agents.voice_agent import BoloRideAgent
from boloride.domain.policies import (
    CustomerIdentityResult,
    CustomerIdentityState,
)
from boloride.prompts.client import (
    PromptFetchResult,
    PromptFetchStatus,
)
from boloride.prompts.registry import (
    PromptBundle,
    PromptRegistry,
)
from boloride.services.time_resolution_service import (
    TimeResolutionService,
)


class Tracer:
    @contextmanager
    def observe(self, *args, **kwargs):
        yield SimpleNamespace(
            update=lambda **values: None
        )


def fallback_prompt_bundle() -> PromptBundle:
    client = SimpleNamespace(
        fetch_text_prompt=lambda name, label: PromptFetchResult(
            PromptFetchStatus.NOT_CONFIGURED
        )
    )

    return PromptRegistry(
        client,
        label="development",
    ).get_bundle()


def agent_for(
    state,
    result,
    *,
    phone="9876543210",
):
    context = RideContext(
        session_id="identity-test",
        caller_id=None,
        identity_state=state,
    )

    database = AsyncMock()

    users = SimpleNamespace(
        onboard_customer=AsyncMock(
            return_value=result
        ),
        resolve_returning_customer=AsyncMock(
            return_value=result
        ),
    )

    agent = BoloRideAgent(
        prompt_bundle=fallback_prompt_bundle(),
        context=context,
        user_id=None,
        database_session=database,
        locations=SimpleNamespace(),
        saved_places=SimpleNamespace(
            list_places=AsyncMock()
        ),
        rides=SimpleNamespace(),
        ride_service=SimpleNamespace(),
        dispatch=SimpleNamespace(),
        booking=SimpleNamespace(),
        quotes=SimpleNamespace(),
        offers=SimpleNamespace(),
        tracer=Tracer(),
        default_country="IN",
        timezone="Asia/Kolkata",
        time_resolution=TimeResolutionService(
            lambda: datetime.now(UTC)
        ),
        user_service=users,
        detected_phone=phone,
    )

    return agent, context, users, database


@pytest.mark.asyncio
async def test_new_customer_corrections_are_submitted_once_and_unlock_tools():
    customer_id = uuid4()

    result = CustomerIdentityResult(
        CustomerIdentityState.ONBOARDED_NEW_CUSTOMER,
        customer_id,
    )

    agent, context, users, database = agent_for(
        CustomerIdentityState.NEW_CUSTOMER_ONBOARDING_REQUIRED,
        result,
    )

    await agent.record_identity_details(
        "Amit",
        24,
    )

    await agent.record_identity_details(
        "Amit Agarwal",
        25,
    )

    response = await agent.submit_customer_identity()

    assert "registration completed" in response.lower()

    users.onboard_customer.assert_awaited_once_with(
        "9876543210",
        "Amit Agarwal",
        25,
    )

    database.commit.assert_awaited_once()

    assert (
        context.verified_customer_id
        == customer_id
    )


@pytest.mark.asyncio
async def test_returning_customer_is_already_established_and_never_collects_profile():
    customer_id = uuid4()

    result = CustomerIdentityResult(
        CustomerIdentityState.VERIFIED_RETURNING_CUSTOMER,
        customer_id,
    )

    agent, context, users, _ = agent_for(
        CustomerIdentityState.VERIFIED_RETURNING_CUSTOMER,
        result,
    )
    context.establish_identity(CustomerIdentityState.VERIFIED_RETURNING_CUSTOMER, customer_id)
    context.customer_display_name = "Amit Agarwal"

    requirements = await agent.get_identity_requirements()

    assert "do not request identity details again" in requirements.lower()
    assert "already established" in (await agent.record_identity_details(name="Wrong")).lower()
    users.resolve_returning_customer.assert_not_awaited()

    assert context.identity_verified


@pytest.mark.asyncio
async def test_obsolete_returning_verification_state_cannot_run_name_matching():
    mismatch = CustomerIdentityResult(
        CustomerIdentityState.NAME_MISMATCH
    )

    agent, context, users, _ = agent_for(
        CustomerIdentityState.RETURNING_CUSTOMER_VERIFICATION_REQUIRED,
        mismatch,
    )

    response = await agent.submit_customer_identity()
    assert "cannot proceed" in response.lower()
    assert not context.identity_verified

    previous_rides = await agent.get_previous_rides()

    assert (
        "identification is required"
        in previous_rides.lower()
    )

    users.resolve_returning_customer.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_phone_never_establishes_customer_or_unlocks_tools():
    agent, context, users, _ = agent_for(
        CustomerIdentityState.PHONE_UNAVAILABLE,
        CustomerIdentityResult(
            CustomerIdentityState.PHONE_UNAVAILABLE
        ),
        phone=None,
    )

    requirements = await agent.get_identity_requirements()

    assert (
        "cannot continue"
        in requirements.lower()
    )

    record = await agent.record_identity_details(
        name="Amit"
    )

    assert "cannot continue" in record.lower()

    quote = await agent.create_fare_quote()

    assert (
        "identification is required"
        in quote.lower()
    )

    users.onboard_customer.assert_not_awaited()

    assert not context.identity_verified


@pytest.mark.asyncio
async def test_pickup_city_can_be_remembered_before_identity_without_unlocking_search():
    agent, context, _, _ = agent_for(
        CustomerIdentityState.NEW_CUSTOMER_ONBOARDING_REQUIRED,
        CustomerIdentityResult(
            CustomerIdentityState.NEW_CUSTOMER_ONBOARDING_REQUIRED
        ),
    )

    geography = await agent.establish_pickup_geography(
        "Indore"
    )

    search = await agent.search_locations(
        "Sarafa Bazaar",
        "pickup",
    )

    assert (
        "pickup_geography_established"
        in geography
    )

    assert (
        context.pickup_geography_city
        == "Indore"
    )

    assert (
        "identification is required"
        in search.casefold()
    )

    context.establish_identity(
        CustomerIdentityState.ONBOARDED_NEW_CUSTOMER,
        uuid4(),
    )

    requirements = (
        await agent.get_booking_requirements()
    )

    assert (
        '"next_missing": "resolved_pickup"'
        in requirements
    )
