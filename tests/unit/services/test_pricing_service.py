from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from boloride.domain.exceptions import DomainValidationError
from boloride.domain.models.location import ResolvedLocation, RouteResult, TollStatus
from boloride.domain.models.quote import FareComponentType
from boloride.services.pricing_service import INDIA_PRICING_TIMEZONE, PricingService


RATES = {
    "auto": ("30", "10", "50"), "mini": ("40", "12", "100"),
    "sedan": ("50", "14", "150"), "suv": ("70", "18", "200"),
    "premium": ("90", "22", "250"),
}


class Rules:
    def __init__(self, active=True): self.active = active
    async def get_active_for_vehicle(self, code):
        if not self.active or code not in RATES: return None
        base, rate, night = RATES[code]
        return SimpleNamespace(id=uuid4(), vehicle_type_code=code, base_fare=Decimal(base), per_km_rate=Decimal(rate), night_charge=Decimal(night), airport_fee=Decimal("150"), currency="INR", active=True)
    async def is_active(self, rule_id): return self.active


def location(*, airport=False, country="India"):
    return ResolvedLocation("Place", Decimal("25"), Decimal("75"), place_types=("airport" if airport else "street_address",), country=country)


async def priced(code="sedan", at=None, distance=12345, pickup=None, destination=None, toll_status=TollStatus.UNKNOWN, toll=None):
    route = RouteResult(distance, 600, "google", toll_status, toll, "INR" if toll is not None else None)
    return await PricingService(Rules()).calculate(code, pickup or location(), destination or location(), at or datetime(2026, 9, 8, 12, tzinfo=INDIA_PRICING_TIMEZONE), route)


@pytest.mark.asyncio
@pytest.mark.parametrize(("code", "base", "rate", "night"), [(k, *v) for k, v in RATES.items()])
async def test_approved_vehicle_rates_and_fixed_night_charges(code, base, rate, night):
    result = await priced(code, datetime(2026, 9, 8, 23, tzinfo=INDIA_PRICING_TIMEZONE), distance=1000)
    assert result.component(FareComponentType.BASE_FARE) == Decimal(base).quantize(Decimal(".01"))
    assert result.component(FareComponentType.DISTANCE_FARE) == Decimal(rate).quantize(Decimal(".01"))
    assert result.component(FareComponentType.NIGHT_CHARGE) == Decimal(night).quantize(Decimal(".01"))


@pytest.mark.asyncio
@pytest.mark.parametrize(("clock", "expected"), [("22:59:59", "0.00"), ("23:00:00", "150.00"), ("04:59:59", "150.00"), ("05:00:00", "0.00")])
async def test_india_night_boundaries(clock, expected):
    at = datetime.fromisoformat(f"2026-09-08T{clock}+05:30")
    assert (await priced(at=at)).component(FareComponentType.NIGHT_CHARGE) == Decimal(expected)


@pytest.mark.asyncio
async def test_utc_instant_is_converted_to_asia_kolkata():
    assert INDIA_PRICING_TIMEZONE.key == "Asia/Kolkata"
    result = await priced(at=datetime(2026, 9, 8, 17, 30, tzinfo=UTC))
    assert result.component(FareComponentType.NIGHT_CHARGE) == Decimal("150.00")


@pytest.mark.asyncio
async def test_exact_distance_decimal_airport_once_toll_and_half_up():
    result = await priced(distance=8750, pickup=location(airport=True), destination=location(airport=True), toll_status=TollStatus.ESTIMATE_AVAILABLE, toll=Decimal("50.50"))
    assert result.component(FareComponentType.DISTANCE_FARE) == Decimal("122.50")
    assert result.component(FareComponentType.AIRPORT_FEE) == Decimal("150.00")
    assert result.component(FareComponentType.TOLL_ESTIMATE) == Decimal("50.50")
    assert result.estimated_total == Decimal("373.00")


@pytest.mark.asyncio
@pytest.mark.parametrize(("distance", "expected"), [(8749, "172.00"), (8750, "173.00")])
async def test_customer_total_rounds_to_whole_inr_half_up(distance, expected):
    assert (await priced(distance=distance)).estimated_total == Decimal(expected)


@pytest.mark.asyncio
async def test_unavailable_toll_is_not_fabricated():
    result = await priced(toll_status=TollStatus.MAY_APPLY)
    assert all(c.component_type is not FareComponentType.TOLL_ESTIMATE for c in result.components)
    assert result.toll_status is TollStatus.MAY_APPLY


@pytest.mark.asyncio
async def test_unknown_airport_and_known_non_india_pickup_fail_safely():
    unknown = ResolvedLocation("Unknown", Decimal("25"), Decimal("75"), country="India")
    with pytest.raises(DomainValidationError, match="airport classification"):
        await priced(pickup=unknown)
    with pytest.raises(DomainValidationError, match="India only"):
        await priced(pickup=location(country="United States"))


@pytest.mark.asyncio
async def test_missing_or_inactive_pricing_rule_rejected():
    route = RouteResult(1000, None, "ola")
    with pytest.raises(DomainValidationError, match="active pricing rule"):
        await PricingService(Rules(False)).calculate("sedan", location(), location(), datetime.now(UTC), route)
