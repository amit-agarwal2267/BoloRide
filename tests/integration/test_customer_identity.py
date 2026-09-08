import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import delete

from boloride.db.models.user import User
from boloride.domain.policies import CustomerIdentityState
from boloride.repositories.user_repository import UserRepository
from boloride.services.user_service import UserService


def unique_phone() -> str:
    return "9" + str(uuid4().int % 1_000_000_000).zfill(9)


@pytest.mark.asyncio
async def test_new_customer_is_stored_with_complete_normalized_profile(app) -> None:
    async with app.state.db_session_factory() as session:
        phone = unique_phone()
        service = UserService(UserRepository(session))
        result = await service.onboard_customer(
            phone, "  Amit   Agarwal ", 1
        )
        user = await UserRepository(session).get_by_phone(phone)

    assert result.state is CustomerIdentityState.ONBOARDED_NEW_CUSTOMER
    assert user is not None
    assert user.id == result.customer_id
    assert user.name == "Amit Agarwal"
    assert user.normalized_name == "amit agarwal"
    assert user.age == 1


@pytest.mark.asyncio
async def test_duplicate_concurrent_onboarding_creates_one_customer(app) -> None:
    phone = unique_phone()

    async def onboard_once():
        async with app.state.db_session_factory() as session:
            result = await UserService(UserRepository(session)).onboard_customer(
                phone, "Amit Agarwal", 120
            )
            await session.commit()
            return result

    first, second = await asyncio.gather(onboard_once(), onboard_once())

    assert {first.customer_id, second.customer_id} == {first.customer_id}
    assert {first.state, second.state} == {
        CustomerIdentityState.ONBOARDED_NEW_CUSTOMER,
        CustomerIdentityState.VERIFIED_RETURNING_CUSTOMER,
    }
    async with app.state.db_session_factory() as session:
        await session.execute(delete(User).where(User.phone_number == f"+91{phone}"))
        await session.commit()


@pytest.mark.asyncio
async def test_different_phone_cannot_resolve_first_customer(app) -> None:
    async with app.state.db_session_factory() as session:
        first_phone = unique_phone()
        other_phone = unique_phone()
        service = UserService(UserRepository(session))
        created = await service.onboard_customer(first_phone, "Amit Agarwal", 35)
        other = await service.resolve_returning_customer(
            other_phone, "Amit Agarwal"
        )

    assert created.customer_id is not None
    assert other.state is CustomerIdentityState.NEW_CUSTOMER_ONBOARDING_REQUIRED
    assert other.customer_id is None
