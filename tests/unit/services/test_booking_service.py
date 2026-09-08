from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from boloride.agents.context import RideContext
from boloride.domain.enums import RideStatus
from boloride.domain.exceptions import DomainValidationError
from boloride.domain.models.location import ResolvedLocation
from boloride.integrations.rideprovider.base import RideBookingRequest, RideBookingResult
from boloride.services.booking_service import BookingService


class RecordingRideRepository:
    def __init__(self) -> None:
        self.create_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    async def create_booked(self, *args: object, **kwargs: object) -> object:
        self.create_calls.append((args, kwargs))
        return SimpleNamespace(id=args[0], status=RideStatus.BOOKED)


class RecordingProvider:
    def __init__(self, *, failure: Exception | None = None) -> None:
        self.calls = 0
        self.requests: list[RideBookingRequest] = []
        self.failure = failure

    async def create_booking(self, request: RideBookingRequest) -> RideBookingResult:
        self.calls += 1
        self.requests.append(request)
        if self.failure is not None:
            raise self.failure
        return RideBookingResult(
            "mock", "booking-1", Decimal("100"), "INR", "Driver", "Vehicle"
        )


def ready_context() -> RideContext:
    return RideContext(
        session_id="session-1",
        caller_id=uuid4(),
        pickup=ResolvedLocation("Home", Decimal("25.18"), Decimal("75.83")),
        destination=ResolvedLocation("Station", Decimal("25.22"), Decimal("75.88")),
        ride_time=datetime.now(UTC) + timedelta(hours=1),
        user_confirmed=True,
    )


@pytest.mark.asyncio
async def test_booking_requires_confirmation_before_provider_call() -> None:
    repository = RecordingRideRepository()
    provider = RecordingProvider()
    service = BookingService(repository, provider)  # type: ignore[arg-type]
    context = ready_context()
    context.user_confirmed = False

    with pytest.raises(DomainValidationError, match="confirmation"):
        await service.book_ride(uuid4(), context)

    assert repository.create_calls == []
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_successful_provider_booking_is_persisted_directly_as_booked() -> None:
    repository = RecordingRideRepository()
    provider = RecordingProvider()
    service = BookingService(repository, provider)  # type: ignore[arg-type]
    customer_id = uuid4()
    context = ready_context()

    outcome = await service.book_ride(customer_id, context)

    assert provider.calls == 1
    assert len(repository.create_calls) == 1
    args, kwargs = repository.create_calls[0]
    assert isinstance(args[0], UUID)
    assert args[0] == provider.requests[0].request_id
    assert args[1] == customer_id
    assert kwargs == {
        "provider": "mock",
        "provider_booking_id": "booking-1",
        "fare_amount": Decimal("100"),
        "fare_currency": "INR",
    }
    assert outcome.ride.status is RideStatus.BOOKED
    assert context.booking_id == args[0]
    assert context.booking_confirmed is True


@pytest.mark.asyncio
async def test_provider_failure_does_not_create_a_durable_ride() -> None:
    repository = RecordingRideRepository()
    provider = RecordingProvider(failure=RuntimeError("provider unavailable"))
    service = BookingService(repository, provider)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="provider unavailable"):
        await service.book_ride(uuid4(), ready_context())

    assert repository.create_calls == []
