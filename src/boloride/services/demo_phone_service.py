from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from secrets import choice, randbelow
from uuid import UUID, uuid4

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from boloride.db.models.accepted_quote import AcceptedQuote
from boloride.db.models.booking_attempt import BookingAttempt
from boloride.db.models.driver import Driver
from boloride.db.models.offer_redemption import OfferRedemption
from boloride.db.models.ride import Ride
from boloride.db.models.ride_assignment import RideAssignment
from boloride.db.models.saved_place import SavedPlace
from boloride.db.models.user import User
from boloride.domain.models.fleet import DriverAvailability
from boloride.repositories.demo_phone_repository import DemoPhoneRepository


class DemoPhoneInUseError(RuntimeError):
    pass


class DemoPhoneAllocationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DemoPhoneView:
    masked_number: str
    in_use: bool


@dataclass(frozen=True, slots=True)
class DemoPhoneCallLease:
    phone_number: str
    masked_number: str
    call_id: UUID
    expires_at: datetime


class DemoPhoneService:
    def __init__(
        self,
        session: AsyncSession,
        repository: DemoPhoneRepository,
        *,
        call_ttl: timedelta = timedelta(minutes=15),
    ) -> None:
        self._session = session
        self._repository = repository
        self._call_ttl = call_ttl

    async def get_or_allocate(self, auth_user_id: UUID) -> DemoPhoneView:
        lease = await self._repository.get(auth_user_id)
        if lease is None:
            lease = await self._allocate(auth_user_id)
        return self._view(lease)

    async def start_call(self, auth_user_id: UUID) -> DemoPhoneCallLease:
        lease = await self._repository.get(auth_user_id, for_update=True)
        if lease is None:
            lease = await self._allocate(auth_user_id)
            lease = await self._repository.get(auth_user_id, for_update=True)
        if lease is None:
            raise DemoPhoneAllocationError("unable to allocate demo phone")

        now = datetime.now(UTC)
        if self._is_active(lease, now):
            raise DemoPhoneInUseError("demo number is already in an active call")

        call_id = uuid4()
        expires_at = now + self._call_ttl
        lease.active_call_id = call_id
        lease.active_call_expires_at = expires_at
        await self._session.flush()
        return DemoPhoneCallLease(
            phone_number=lease.phone_number,
            masked_number=self.mask(lease.phone_number),
            call_id=call_id,
            expires_at=expires_at,
        )

    async def end_call(self, auth_user_id: UUID, call_id: UUID) -> DemoPhoneView:
        lease = await self._repository.get(auth_user_id, for_update=True)
        if lease is None:
            lease = await self._allocate(auth_user_id)
            return self._view(lease)

        if lease.active_call_id == call_id:
            lease.active_call_id = None
            lease.active_call_expires_at = None
            await self._session.flush()
        elif lease.active_call_expires_at is not None and lease.active_call_expires_at <= datetime.now(UTC):
            lease.active_call_id = None
            lease.active_call_expires_at = None
            await self._session.flush()
        return self._view(lease)

    async def roll(self, auth_user_id: UUID) -> DemoPhoneView:
        lease = await self._repository.get(auth_user_id, for_update=True)
        if lease is None:
            lease = await self._allocate(auth_user_id)
            return self._view(lease)

        now = datetime.now(UTC)
        if self._is_active(lease, now):
            raise DemoPhoneInUseError("demo number cannot be rolled during an active call")

        old_phone = lease.phone_number
        await self._delete_demo_customer_data(old_phone)

        for _ in range(40):
            candidate = self._generate_phone()
            if candidate == old_phone or not await self._repository.phone_available(candidate):
                continue
            lease.phone_number = candidate
            lease.active_call_id = None
            lease.active_call_expires_at = None
            try:
                async with self._session.begin_nested():
                    await self._session.flush()
                return self._view(lease)
            except IntegrityError:
                continue
        raise DemoPhoneAllocationError("unable to roll a unique demo phone")

    async def _allocate(self, auth_user_id: UUID):
        existing = await self._repository.get(auth_user_id)
        if existing is not None:
            return existing
        for _ in range(40):
            try:
                candidate = self._generate_phone()
                if not await self._repository.phone_available(candidate):
                    continue
                return await self._repository.create(
                    auth_user_id, candidate
                )
            except IntegrityError:
                existing = await self._repository.get(auth_user_id)
                if existing is not None:
                    return existing
        raise DemoPhoneAllocationError("unable to allocate a unique demo phone")

    async def _delete_demo_customer_data(self, phone_number: str) -> None:
        user_id = await self._session.scalar(
            select(User.id).where(User.phone_number == phone_number)
        )
        if user_id is None:
            return

        ride_ids = list(
            await self._session.scalars(
                select(Ride.id).where(Ride.user_id == user_id)
            )
        )
        if ride_ids:
            driver_ids = list(
                await self._session.scalars(
                    select(RideAssignment.driver_id).where(
                        RideAssignment.ride_id.in_(ride_ids),
                        RideAssignment.released_at.is_(None),
                    )
                )
            )
            if driver_ids:
                await self._session.execute(
                    update(Driver)
                    .where(Driver.id.in_(driver_ids))
                    .values(availability=DriverAvailability.AVAILABLE)
                )
            await self._session.execute(
                delete(RideAssignment).where(RideAssignment.ride_id.in_(ride_ids))
            )

        await self._session.execute(
            delete(OfferRedemption).where(OfferRedemption.customer_id == user_id)
        )
        await self._session.execute(
            delete(BookingAttempt).where(BookingAttempt.customer_id == user_id)
        )
        if ride_ids:
            await self._session.execute(
                delete(AcceptedQuote).where(AcceptedQuote.ride_id.in_(ride_ids))
            )
            await self._session.execute(
                delete(Ride).where(Ride.id.in_(ride_ids))
            )
        await self._session.execute(
            delete(SavedPlace).where(SavedPlace.user_id == user_id)
        )
        await self._session.execute(delete(User).where(User.id == user_id))
        await self._session.flush()

    @staticmethod
    def _is_active(lease, now: datetime) -> bool:
        return (
            lease.active_call_id is not None
            and lease.active_call_expires_at is not None
            and lease.active_call_expires_at > now
        )

    @classmethod
    def _view(cls, lease) -> DemoPhoneView:
        return DemoPhoneView(
            masked_number=cls.mask(lease.phone_number),
            in_use=cls._is_active(lease, datetime.now(UTC)),
        )

    @staticmethod
    def mask(phone_number: str) -> str:
        national = phone_number[-10:]
        return f"XXXXXX{national[-4:]}"

    @staticmethod
    def _generate_phone() -> str:
        national = choice("6789") + "".join(str(randbelow(10)) for _ in range(9))
        return f"+91{national}"
