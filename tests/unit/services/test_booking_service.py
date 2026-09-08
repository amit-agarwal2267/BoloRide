from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from boloride.agents.context import RideContext
from boloride.domain.enums import RideStatus
from boloride.domain.exceptions import DomainValidationError
from boloride.domain.models.location import ResolvedLocation, TollStatus
from boloride.domain.models.quote import FareComponent, FareComponentType, PricingResult, Quote
from boloride.domain.models.vehicle import VehicleTypeDetails
from boloride.domain.policies import CustomerIdentityState
from boloride.integrations.rideprovider.base import RideBookingRequest, RideBookingResult
from boloride.services.booking_service import BookingService


def quote(session_id: str = "session-1") -> Quote:
    components = tuple(FareComponent(kind, amount) for kind, amount in (
        (FareComponentType.BASE_FARE, Decimal("50.00")),
        (FareComponentType.DISTANCE_FARE, Decimal("140.00")),
        (FareComponentType.NIGHT_CHARGE, Decimal("0.00")),
        (FareComponentType.AIRPORT_FEE, Decimal("0.00")),
    ))
    now = datetime.now(UTC)
    return Quote(uuid4(), session_id, "a" * 64, PricingResult(
        uuid4(), "sedan", 10000, 1200, "google", components,
        TollStatus.UNKNOWN, Decimal("190.00"), "INR"
    ), now, now + timedelta(minutes=20))


class RecordingRideRepository:
    def __init__(self) -> None:
        self.create_calls = []

    async def create_booked(self, *args, **kwargs):
        self.create_calls.append((args, kwargs))
        return SimpleNamespace(id=args[0], status=RideStatus.BOOKED)


class RecordingProvider:
    def __init__(self, failure=None) -> None:
        self.calls = 0
        self.requests: list[RideBookingRequest] = []
        self.failure = failure

    async def create_booking(self, request: RideBookingRequest) -> RideBookingResult:
        self.calls += 1
        self.requests.append(request)
        if self.failure:
            raise self.failure
        return RideBookingResult("mock", "booking-1", "Driver", "Vehicle")


class RecordingVehicleService:
    def __init__(self, failure=None) -> None:
        self.calls = []
        self.failure = failure

    async def require_eligible_vehicle_type(self, code, passenger_count):
        self.calls.append((code, passenger_count))
        if self.failure:
            raise self.failure
        return VehicleTypeDetails(code, "Sedan", 4, True)


class QuoteGuard:
    def __init__(self, failure=None) -> None:
        self.failure = failure
        self.calls = 0

    async def require_bookable_quote(self, context):
        self.calls += 1
        if self.failure:
            raise self.failure
        return context.current_quote


def ready_context() -> RideContext:
    customer_id = uuid4()
    context = RideContext(
        session_id="session-1", caller_id=customer_id,
        identity_state=CustomerIdentityState.VERIFIED_RETURNING_CUSTOMER,
        verified_customer_id=customer_id,
        pickup=ResolvedLocation("Home", Decimal("25.18"), Decimal("75.83")),
        destination=ResolvedLocation("Station", Decimal("25.22"), Decimal("75.88")),
        ride_time=datetime.now(UTC) + timedelta(hours=1), passenger_count=4,
        selected_vehicle_type_code="sedan",
    )
    current = quote()
    context.set_quote(current)
    context.confirm_quote(current.id)
    return context


@pytest.mark.asyncio
async def test_booking_requires_current_confirmed_quote_before_provider_call() -> None:
    repository, provider, vehicles = RecordingRideRepository(), RecordingProvider(), RecordingVehicleService()
    quotes = QuoteGuard(DomainValidationError("confirmation for current quote required"))
    service = BookingService(repository, provider, vehicles, quotes)  # type: ignore[arg-type]
    context = ready_context()
    with pytest.raises(DomainValidationError, match="confirmation"):
        await service.book_ride(context.verified_customer_id, context)
    assert provider.calls == 0
    assert repository.create_calls == []


@pytest.mark.asyncio
async def test_successful_provider_booking_persists_accepted_quote() -> None:
    repository, provider, vehicles, quotes = RecordingRideRepository(), RecordingProvider(), RecordingVehicleService(), QuoteGuard()
    service = BookingService(repository, provider, vehicles, quotes)  # type: ignore[arg-type]
    context = ready_context()
    customer_id = context.verified_customer_id
    outcome = await service.book_ride(customer_id, context)
    args, kwargs = repository.create_calls[0]
    assert isinstance(args[0], UUID)
    assert args[1] == customer_id
    assert kwargs["accepted_quote"] is context.current_quote
    assert not hasattr(outcome.provider_result, "fare_amount")
    assert outcome.accepted_quote.pricing.estimated_total == Decimal("190.00")
    assert context.booking_confirmed is True


@pytest.mark.asyncio
async def test_provider_failure_does_not_create_a_durable_ride() -> None:
    repository = RecordingRideRepository()
    service = BookingService(repository, RecordingProvider(RuntimeError("provider unavailable")), RecordingVehicleService(), QuoteGuard())  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="provider unavailable"):
        context = ready_context()
        await service.book_ride(context.verified_customer_id, context)
    assert repository.create_calls == []


@pytest.mark.asyncio
async def test_capacity_invalid_vehicle_is_rejected_before_quote_and_provider() -> None:
    provider, quotes = RecordingProvider(), QuoteGuard()
    vehicles = RecordingVehicleService(DomainValidationError("cannot accommodate"))
    service = BookingService(RecordingRideRepository(), provider, vehicles, quotes)  # type: ignore[arg-type]
    with pytest.raises(DomainValidationError, match="cannot accommodate"):
        context = ready_context()
        await service.book_ride(context.verified_customer_id, context)
    assert provider.calls == 0
    assert quotes.calls == 0
