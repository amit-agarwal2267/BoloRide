from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from boloride.db.models.offer import Offer
from boloride.db.models.offer_redemption import OfferRedemption
from boloride.db.models.accepted_quote import AcceptedQuote
from boloride.domain.enums import RideStatus
from boloride.domain.exceptions import DomainValidationError
from boloride.domain.models.location import ResolvedLocation, TollStatus
from boloride.domain.models.offer import AppliedOfferSnapshot, DiscountType, RedemptionStatus
from boloride.domain.models.quote import FareComponent, FareComponentType, PricingResult, Quote
from boloride.repositories.offer_repository import OfferRepository
from boloride.repositories.ride_repository import RideRepository
from boloride.repositories.user_repository import UserRepository
from boloride.services.offer_service import OfferService
from boloride.services.ride_service import RideService


@pytest.mark.asyncio
async def test_seeded_new_customer_offer(db_session: AsyncSession):
    offer = await OfferRepository(db_session).get_by_code("NEW_CUSTOMER")
    assert offer is not None
    assert (offer.percentage, offer.maximum_discount, offer.maximum_redemptions_per_customer, offer.currency, offer.active) == (Decimal("10.00"), Decimal("50.00"), 3, "INR", True)


def discounted_quote(offer: Offer) -> Quote:
    now = datetime.now(UTC)
    applied = AppliedOfferSnapshot(offer.id, offer.code, offer.display_name, DiscountType.PERCENTAGE, offer.percentage, offer.maximum_discount, Decimal("20.00"), offer.currency, offer.version)
    components = (
        FareComponent(FareComponentType.BASE_FARE, Decimal("40.00")),
        FareComponent(FareComponentType.DISTANCE_FARE, Decimal("160.00")),
        FareComponent(FareComponentType.NIGHT_CHARGE, Decimal("0.00")),
        FareComponent(FareComponentType.AIRPORT_FEE, Decimal("0.00")),
    )
    pricing = PricingResult(uuid4(), "mini", 10000, 600, "mock", components, TollStatus.UNKNOWN, Decimal("180.00"), "INR", Decimal("200.00"), applied)
    return Quote(uuid4(), "offer-integration", "c" * 64, pricing, now, now + timedelta(minutes=20))


async def create_discounted_ride(db_session, user_id, offer, suffix):
    ride = await RideRepository(db_session).create_booked(
        uuid4(), user_id,
        ResolvedLocation("Home", Decimal("25.18"), Decimal("75.83")),
        ResolvedLocation("Station", Decimal("25.22"), Decimal("75.88")),
        datetime.now(UTC) + timedelta(hours=1), provider="mock",
        provider_booking_id=f"offer-{suffix}", accepted_quote=discounted_quote(offer),
    )
    return ride


@pytest.mark.asyncio
async def test_pending_reserves_capacity_cancel_releases_and_completion_consumes_once(db_session: AsyncSession):
    user = await UserRepository(db_session).create("9876543298", "Offer User", 30)
    repo = OfferRepository(db_session); service = OfferService(repo)
    offer = await repo.get_by_code("NEW_CUSTOMER"); assert offer is not None
    ride_repo = RideRepository(db_session)
    cancelled = await create_discounted_ride(db_session, user.id, offer, 0)
    assert await ride_repo.cancel_for_customer(
        user.id, cancelled.id, expected_status=RideStatus.BOOKED
    )
    historical = []
    for index in (2, 3):
        completed = await create_discounted_ride(db_session, user.id, offer, index)
        for current, requested in (
            (RideStatus.BOOKED, RideStatus.ASSIGNED),
            (RideStatus.ASSIGNED, RideStatus.ON_TRIP),
            (RideStatus.ON_TRIP, RideStatus.COMPLETED),
        ):
            assert await ride_repo.transition_internal(
                completed.id,
                expected_status=current,
                requested_status=requested,
            )
        historical.append(completed)
    active = await create_discounted_ride(db_session, user.id, offer, 1)
    rides = [cancelled, active, *historical]
    snapshot = await db_session.scalar(select(AcceptedQuote).where(AcceptedQuote.ride_id == rides[0].id))
    assert snapshot.offer_percentage == Decimal("10.00")
    await service.update_offer("NEW_CUSTOMER", percentage=Decimal("15.00"))
    await db_session.refresh(snapshot)
    assert snapshot.offer_percentage == Decimal("10.00")
    offer.percentage = Decimal("10.00")
    offer.version -= 1
    await db_session.flush()
    for ride in rides[:3]:
        await service.create_pending_redemption(user.id, offer, ride.id)
    with pytest.raises(DomainValidationError, match="capacity"):
        await service.create_pending_redemption(user.id, offer, rides[3].id)
    assert await db_session.scalar(select(func.count()).select_from(OfferRedemption).where(OfferRedemption.status == RedemptionStatus.CONSUMED.value)) == 0

    await service.finalize_redemption(user.id, rides[0].id, RideStatus.CANCELLED)
    await service.create_pending_redemption(user.id, offer, rides[3].id)
    lifecycle = RideService(db_session, RideRepository(db_session), service)
    await lifecycle.transition_customer_ride(user.id, rides[1].id, expected_status=RideStatus.BOOKED, requested_status=RideStatus.ASSIGNED)
    await lifecycle.transition_customer_ride(user.id, rides[1].id, expected_status=RideStatus.ASSIGNED, requested_status=RideStatus.ON_TRIP)
    await lifecycle.transition_customer_ride(user.id, rides[1].id, expected_status=RideStatus.ON_TRIP, requested_status=RideStatus.COMPLETED)
    await service.finalize_redemption(user.id, rides[1].id, RideStatus.COMPLETED)
    assert await db_session.scalar(select(func.count()).select_from(OfferRedemption).where(OfferRedemption.status == RedemptionStatus.CONSUMED.value)) == 1


@pytest.mark.asyncio
async def test_admin_service_create_update_list_and_deactivate_without_public_route(db_session: AsyncSession):
    service = OfferService(OfferRepository(db_session))
    created = await service.create_offer(
        code="DEMO_OFFER", display_name="Demo Offer", discount_type="percentage",
        percentage=Decimal("5.00"), maximum_discount=Decimal("25.00"),
        currency="INR", maximum_redemptions_per_customer=1,
        eligibility_type="new_customer", active=True,
        effective_from=datetime.now(UTC), effective_until=None, version=1,
    )
    updated = await service.update_offer(created.code, percentage=Decimal("7.50"))
    assert updated.version == 2 and updated.percentage == Decimal("7.50")
    assert created.id in {item.id for item in await service.list_offers()}
    assert (await service.deactivate_offer(created.code)).active is False
    with pytest.raises(DomainValidationError):
        await service.update_offer(created.code, percentage=Decimal("101"))
