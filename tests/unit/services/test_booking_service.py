from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from boloride.agents.context import RideContext
from boloride.domain.exceptions import DomainValidationError
from boloride.domain.models.location import ResolvedLocation
from boloride.integrations.rideprovider.base import RideBookingRequest, RideBookingResult
from boloride.services.booking_service import BookingService


class RecordingRideRepository:
    def __init__(self) -> None:
        self.create_calls = 0

    async def create(self, *args: object) -> object:
        self.create_calls += 1
        return object()


class RecordingProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def create_booking(self, request: RideBookingRequest) -> RideBookingResult:
        self.calls += 1
        return RideBookingResult(
            "mock", "booking-1", Decimal("100"), "INR", "Driver", "Vehicle"
        )


@pytest.mark.asyncio
async def test_booking_requires_confirmation_before_provider_call() -> None:
    repository = RecordingRideRepository()
    provider = RecordingProvider()
    service = BookingService(repository, provider)  # type: ignore[arg-type]
    context = RideContext(
        session_id="session-1",
        caller_id=uuid4(),
        pickup=ResolvedLocation("Home", Decimal("25.18"), Decimal("75.83")),
        destination=ResolvedLocation("Station", Decimal("25.22"), Decimal("75.88")),
        ride_time=datetime.now(UTC) + timedelta(hours=1),
    )

    with pytest.raises(DomainValidationError, match="confirmation"):
        await service.book_ride(uuid4(), context)

    assert repository.create_calls == 0
    assert provider.calls == 0