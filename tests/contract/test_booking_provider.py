from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from boloride.domain.models.location import ResolvedLocation
from boloride.integrations.rideprovider.base import ProviderCreateStatus, RideBookingRequest
from boloride.integrations.rideprovider.mock_provider import MockRideProvider


@pytest.mark.asyncio
async def test_mock_provider_returns_provider_neutral_booking_result() -> None:
    result = await MockRideProvider().create_booking(
        RideBookingRequest(
            request_id=uuid4(),
            pickup=ResolvedLocation("Home", Decimal("25.18"), Decimal("75.83")),
            destination=ResolvedLocation(
                "Station", Decimal("25.22"), Decimal("75.88")
            ),
            requested_ride_at=datetime.now(UTC),
            passenger_count=4,
            vehicle_type_code="sedan",
        ),
        idempotency_key="stable-key",
    )

    assert result.status is ProviderCreateStatus.CONFIRMED
    assert result.booking is not None
    assert result.booking.provider == "mock"
    assert result.booking.provider_booking_id == "mock-stable-key"
    assert not hasattr(result.booking, "fare_amount")


@pytest.mark.asyncio
async def test_same_idempotency_key_returns_same_logical_booking() -> None:
    provider = MockRideProvider()
    request = RideBookingRequest(
        uuid4(), ResolvedLocation("Home", Decimal("25.18"), Decimal("75.83")),
        ResolvedLocation("Station", Decimal("25.22"), Decimal("75.88")),
        datetime.now(UTC), 4, "sedan",
    )
    first = await provider.create_booking(request, idempotency_key="same")
    second = await provider.create_booking(request, idempotency_key="same")
    assert first.booking == second.booking
    assert provider.logical_booking_count == 1
