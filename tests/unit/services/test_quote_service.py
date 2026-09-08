from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from boloride.agents.context import RideContext
from boloride.domain.exceptions import DomainValidationError
from boloride.domain.models.location import ResolvedLocation, RouteResult, TollStatus
from boloride.domain.models.quote import FareComponent, FareComponentType, PricingResult
from boloride.services.quote_service import QuoteService


class Locations:
    async def get_route(self, origin, destination): return RouteResult(1000, 100, "ola")


class Pricing:
    def __init__(self): self.active = True
    async def calculate(self, vehicle, pickup, destination, ride_at, route):
        components = tuple(FareComponent(k, Decimal(v)) for k, v in ((FareComponentType.BASE_FARE, "40.00"), (FareComponentType.DISTANCE_FARE, "12.00"), (FareComponentType.NIGHT_CHARGE, "0.00"), (FareComponentType.AIRPORT_FEE, "0.00")))
        return PricingResult(uuid4(), vehicle, route.distance_meters, route.duration_seconds, route.provider, components, TollStatus.UNKNOWN, Decimal("52.00"), "INR")
    async def is_rule_active(self, rule_id): return self.active


def context():
    return RideContext(session_id="s1", caller_id=uuid4(), pickup=ResolvedLocation("A", Decimal("1"), Decimal("1")), destination=ResolvedLocation("B", Decimal("2"), Decimal("2")), ride_time=datetime.now(UTC) + timedelta(hours=1), selected_vehicle_type_code="mini")


@pytest.mark.asyncio
async def test_quote_creation_expiry_immutability_and_confirmation_binding():
    now = datetime(2026, 9, 8, tzinfo=UTC)
    pricing = Pricing(); service = QuoteService(pricing, Locations())  # type: ignore[arg-type]
    ctx = context(); quote = await service.create_quote(ctx, now=now)
    assert quote.expires_at == now + timedelta(minutes=20)
    with pytest.raises(FrozenInstanceError): quote.expires_at = now  # type: ignore[misc]
    with pytest.raises(DomainValidationError, match="confirmation"):
        await service.require_bookable_quote(ctx, now=quote.expires_at - timedelta(microseconds=1))
    service.confirm_quote(ctx, quote.id)
    assert await service.require_bookable_quote(ctx, now=quote.expires_at - timedelta(microseconds=1)) is quote
    with pytest.raises(DomainValidationError, match="expired"):
        await service.require_bookable_quote(ctx, now=quote.expires_at)


@pytest.mark.asyncio
async def test_material_change_invalidates_quote_and_requote_needs_fresh_confirmation():
    service = QuoteService(Pricing(), Locations())  # type: ignore[arg-type]
    ctx = context(); old = await service.create_quote(ctx); service.confirm_quote(ctx, old.id)
    ctx.update_passenger_count(2, ctx.passenger_count_source, selected_vehicle_is_eligible=True)
    assert ctx.current_quote is None and ctx.confirmed_quote_id is None
    new = await service.create_quote(ctx)
    assert new.request_fingerprint != old.request_fingerprint
    assert old.pricing.estimated_total == Decimal("52.00")
    with pytest.raises(DomainValidationError, match="confirmation"):
        await service.require_bookable_quote(ctx)


@pytest.mark.asyncio
async def test_quote_a_confirmation_cannot_authorize_quote_b_or_disconnected_session():
    service = QuoteService(Pricing(), Locations())  # type: ignore[arg-type]
    ctx = context(); first = await service.create_quote(ctx); service.confirm_quote(ctx, first.id)
    second = await service.create_quote(ctx)
    assert second.id != first.id and ctx.confirmed_quote_id is None
    with pytest.raises(DomainValidationError): service.confirm_quote(ctx, first.id)
    service.disconnect(ctx)
    with pytest.raises(DomainValidationError, match="active session"):
        await service.require_bookable_quote(ctx)
