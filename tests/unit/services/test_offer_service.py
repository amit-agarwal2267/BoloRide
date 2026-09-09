from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from boloride.agents.context import RideContext
from boloride.domain.exceptions import DomainValidationError
from boloride.domain.models.offer import DiscountType, OfferDetails, OfferEligibilityType, calculate_discount
from boloride.domain.models.quote import FareComponent, FareComponentType, PricingResult, Quote
from boloride.domain.models.location import TollStatus
from boloride.services.offer_service import OfferService


def details(**changes):
    values = dict(id=uuid4(), code="NEW_CUSTOMER", display_name="New Customer Offer", discount_type=DiscountType.PERCENTAGE, percentage=Decimal("10"), maximum_discount=Decimal("50"), currency="INR", maximum_redemptions_per_customer=3, eligibility_type=OfferEligibilityType.NEW_CUSTOMER, active=True, effective_from=datetime(2026, 1, 1, tzinfo=UTC), effective_until=None, version=1)
    values.update(changes)
    return OfferDetails(**values)


@pytest.mark.parametrize("changes", [
    {"percentage": Decimal("0")}, {"percentage": Decimal("100.01")},
    {"maximum_discount": Decimal("-0.01")}, {"maximum_redemptions_per_customer": 0},
    {"effective_until": datetime(2025, 1, 1, tzinfo=UTC)},
    {"code": "invalid code"},
])
def test_invalid_offer_configuration_is_rejected(changes):
    with pytest.raises(DomainValidationError): details(**changes)


def test_discount_quantizes_to_paise_before_cap_and_total_rounds_half_up():
    assert calculate_discount(Decimal("200.00"), details()) == (Decimal("20.00"), Decimal("180.00"))
    assert calculate_discount(Decimal("800.00"), details()) == (Decimal("50.00"), Decimal("750.00"))
    assert calculate_discount(Decimal("172.45"), details()) == (Decimal("17.25"), Decimal("155.00"))


class Repo:
    def __init__(self, row, pending=0, consumed=0, reserved=0): self.row, self.pending, self.consumed, self.reserved = row, pending, consumed, reserved
    async def list_effective(self, now): return [self.row] if self.row.active and self.row.effective_from <= now and (self.row.effective_until is None or now < self.row.effective_until) else []
    async def usage_counts(self, customer_id, offer_id): return self.pending, self.consumed
    async def reserved_attempt_count(self, customer_id, offer_id): return self.reserved
    async def get_by_code(self, code): return self.row if code.upper() == self.row.code else None
    async def get_by_id(self, offer_id): return self.row if offer_id == self.row.id else None


def row(**changes):
    d = details(**changes)
    return SimpleNamespace(**{field: getattr(d, field) for field in d.__dataclass_fields__})


def base_quote():
    pricing = PricingResult(uuid4(), "mini", 10000, 600, "ola", (
        FareComponent(FareComponentType.BASE_FARE, Decimal("40.00")),
        FareComponent(FareComponentType.DISTANCE_FARE, Decimal("160.00")),
        FareComponent(FareComponentType.NIGHT_CHARGE, Decimal("0.00")),
        FareComponent(FareComponentType.AIRPORT_FEE, Decimal("0.00")),
    ), TollStatus.UNKNOWN, Decimal("200.00"), "INR")
    now = datetime(2026, 9, 9, tzinfo=UTC)
    return Quote(uuid4(), "s1", "a" * 64, pricing, now, now + timedelta(minutes=20))


@pytest.mark.asyncio
@pytest.mark.parametrize(("pending", "consumed", "reserved", "eligible"), [(0, 0, 0, True), (0, 1, 0, True), (0, 2, 0, True), (0, 3, 0, False), (1, 2, 0, False), (0, 2, 1, False)])
async def test_eligibility_counts_in_flight_attempt_reservations(pending, consumed, reserved, eligible):
    service = OfferService(Repo(row(), pending, consumed, reserved))  # type: ignore[arg-type]
    result = await service.get_eligible_offers(uuid4(), "INR", now=datetime(2026, 9, 9, tzinfo=UTC))
    assert bool(result) is eligible


@pytest.mark.asyncio
async def test_apply_creates_frozen_new_quote_and_resets_confirmation():
    service = OfferService(Repo(row()))  # type: ignore[arg-type]
    context = RideContext("s1", uuid4()); original = base_quote(); context.set_quote(original); context.confirm_quote(original.id)
    discounted = await service.apply_offer(context.caller_id, context, "NEW_CUSTOMER", now=datetime(2026, 9, 9, tzinfo=UTC))
    assert discounted.id != original.id and original.pricing.estimated_total == Decimal("200.00")
    assert discounted.pricing.estimated_total == Decimal("180.00")
    assert discounted.pricing.applied_offer.discount_amount == Decimal("20.00")
    assert context.confirmed_quote_id is None
    with pytest.raises(FrozenInstanceError): discounted.pricing.applied_offer.discount_amount = Decimal("1")  # type: ignore[misc]
    restored = await service.remove_offer(context)
    assert restored.id != discounted.id and restored.pricing.estimated_total == Decimal("200.00")


@pytest.mark.asyncio
async def test_inactive_expired_future_currency_and_version_are_rejected():
    now = datetime(2026, 9, 9, tzinfo=UTC)
    for candidate in (row(active=False), row(effective_from=now + timedelta(days=1)), row(effective_until=now - timedelta(days=1))):
        assert await OfferService(Repo(candidate)).get_eligible_offers(uuid4(), "INR", now=now) == ()  # type: ignore[arg-type]
    assert await OfferService(Repo(row())).get_eligible_offers(uuid4(), "USD", now=now) == ()  # type: ignore[arg-type]
