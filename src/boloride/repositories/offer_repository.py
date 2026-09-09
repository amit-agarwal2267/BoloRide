from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from boloride.db.models.accepted_quote import AcceptedQuote
from boloride.db.models.booking_attempt import BookingAttempt
from boloride.db.models.offer import Offer
from boloride.db.models.offer_redemption import OfferRedemption
from boloride.db.models.user import User
from boloride.domain.exceptions import DomainValidationError
from boloride.domain.models.offer import RedemptionStatus


class OfferRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_code(self, code: str) -> Offer | None:
        return await self._session.scalar(select(Offer).where(Offer.code == code.strip().upper()))

    async def get_by_id(self, offer_id: UUID) -> Offer | None:
        return await self._session.get(Offer, offer_id)

    async def list_all(self) -> list[Offer]:
        return list(await self._session.scalars(select(Offer).order_by(Offer.code)))

    async def list_effective(self, now: datetime) -> list[Offer]:
        return list(await self._session.scalars(select(Offer).where(
            Offer.active.is_(True), Offer.effective_from <= now,
            (Offer.effective_until.is_(None) | (Offer.effective_until > now)),
        ).order_by(Offer.code)))

    async def create(self, **values) -> Offer:
        offer = Offer(**values)
        self._session.add(offer)
        await self._session.flush()
        return offer

    async def update(self, offer: Offer, **values) -> Offer:
        for key, value in values.items():
            setattr(offer, key, value)
        offer.version += 1
        await self._session.flush()
        return offer

    async def deactivate(self, offer: Offer) -> Offer:
        offer.active = False
        offer.version += 1
        await self._session.flush()
        return offer

    async def usage_counts(self, customer_id: UUID, offer_id: UUID) -> tuple[int, int]:
        rows = await self._session.execute(
            select(OfferRedemption.status, func.count()).where(
                OfferRedemption.customer_id == customer_id,
                OfferRedemption.offer_id == offer_id,
            ).group_by(OfferRedemption.status)
        )
        counts = dict(rows.all())
        return int(counts.get(RedemptionStatus.PENDING.value, 0)), int(counts.get(RedemptionStatus.CONSUMED.value, 0))

    async def reserved_attempt_count(self, customer_id: UUID, offer_id: UUID) -> int:
        return int(await self._session.scalar(
            select(func.count()).select_from(BookingAttempt).where(
                BookingAttempt.customer_id == customer_id,
                BookingAttempt.offer_id == offer_id,
                BookingAttempt.capacity_reserved.is_(True),
            )
        ) or 0)

    async def reserve_attempt_capacity(
        self, customer_id: UUID, offer: Offer, quote_id: UUID
    ) -> bool:
        await self._session.scalar(select(User.id).where(User.id == customer_id).with_for_update())
        existing = await self._session.scalar(
            select(BookingAttempt.id).where(BookingAttempt.quote_id == quote_id)
        )
        if existing is not None:
            return False
        pending, consumed = await self.usage_counts(customer_id, offer.id)
        reserved = await self.reserved_attempt_count(customer_id, offer.id)
        if pending + consumed + reserved >= offer.maximum_redemptions_per_customer:
            raise DomainValidationError("offer redemption capacity has been reached")
        return True

    async def create_pending(self, customer_id: UUID, offer: Offer, ride_id: UUID) -> OfferRedemption:
        await self._session.scalar(select(User.id).where(User.id == customer_id).with_for_update())
        pending, consumed = await self.usage_counts(customer_id, offer.id)
        reserved = await self.reserved_attempt_count(customer_id, offer.id)
        if pending + consumed + reserved >= offer.maximum_redemptions_per_customer:
            raise DomainValidationError("offer redemption capacity has been reached")
        accepted_quote_id = await self._session.scalar(select(AcceptedQuote.id).where(AcceptedQuote.ride_id == ride_id))
        if accepted_quote_id is None:
            raise DomainValidationError("accepted quote is required for offer redemption")
        redemption = OfferRedemption(
            offer_id=offer.id, customer_id=customer_id, ride_id=ride_id,
            accepted_quote_id=accepted_quote_id, status=RedemptionStatus.PENDING.value,
        )
        self._session.add(redemption)
        await self._session.flush()
        return redemption

    async def create_pending_from_reservation(
        self, customer_id: UUID, offer_id: UUID, ride_id: UUID
    ) -> OfferRedemption:
        existing = await self._session.scalar(
            select(OfferRedemption).where(OfferRedemption.ride_id == ride_id)
        )
        if existing is not None:
            return existing
        accepted_quote_id = await self._session.scalar(
            select(AcceptedQuote.id).where(AcceptedQuote.ride_id == ride_id)
        )
        if accepted_quote_id is None:
            raise DomainValidationError("accepted quote is required for offer redemption")
        redemption = OfferRedemption(
            offer_id=offer_id,
            customer_id=customer_id,
            ride_id=ride_id,
            accepted_quote_id=accepted_quote_id,
            status=RedemptionStatus.PENDING.value,
        )
        self._session.add(redemption)
        await self._session.flush()
        return redemption

    async def finalize_for_ride(self, customer_id: UUID, ride_id: UUID, status: RedemptionStatus) -> tuple[OfferRedemption | None, bool]:
        await self._session.scalar(select(User.id).where(User.id == customer_id).with_for_update())
        redemption = await self._session.scalar(select(OfferRedemption).where(
            OfferRedemption.customer_id == customer_id,
            OfferRedemption.ride_id == ride_id,
        ).with_for_update())
        if redemption is None or redemption.status == status.value:
            return redemption, False
        if redemption.status != RedemptionStatus.PENDING.value:
            return redemption, False
        redemption.status = status.value
        redemption.consumed_at = datetime.now(UTC) if status is RedemptionStatus.CONSUMED else None
        await self._session.flush()
        return redemption, True
