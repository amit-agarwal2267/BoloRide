from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from boloride.db.models.user import User
from boloride.repositories.demo_phone_repository import DemoPhoneRepository
from boloride.repositories.user_repository import UserRepository
from boloride.services.demo_phone_service import DemoPhoneInUseError, DemoPhoneService


@pytest.mark.asyncio
async def test_demo_phone_persists_per_auth_user_and_roll_clears_customer_identity(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    auth_user_id = uuid4()
    generated = iter(("+919880486586", "+919770001234"))
    monkeypatch.setattr(
        DemoPhoneService,
        "_generate_phone",
        staticmethod(lambda: next(generated)),
    )
    service = DemoPhoneService(db_session, DemoPhoneRepository(db_session))

    first = await service.get_or_allocate(auth_user_id)
    await db_session.commit()
    again = await service.get_or_allocate(auth_user_id)

    assert first.masked_number == "XXXXXX6586"
    assert again.masked_number == first.masked_number

    customer = await UserRepository(db_session).create(
        "+919880486586", "Demo Customer", 30
    )
    customer_id = customer.id
    await db_session.commit()

    rolled = await service.roll(auth_user_id)
    await db_session.commit()

    assert rolled.masked_number == "XXXXXX1234"
    assert await db_session.scalar(
        select(User).where(User.id == customer_id)
    ) is None


@pytest.mark.asyncio
async def test_demo_phone_cannot_roll_during_active_call(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    auth_user_id = uuid4()
    monkeypatch.setattr(
        DemoPhoneService,
        "_generate_phone",
        staticmethod(lambda: "+919880486586"),
    )
    service = DemoPhoneService(db_session, DemoPhoneRepository(db_session))

    await service.get_or_allocate(auth_user_id)
    call = await service.start_call(auth_user_id)
    await db_session.commit()

    with pytest.raises(DemoPhoneInUseError):
        await service.roll(auth_user_id)

    await db_session.rollback()
    ended = await service.end_call(auth_user_id, call.call_id)
    await db_session.commit()

    assert ended.in_use is False
