from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from boloride.domain.models.location import ResolvedLocation
from boloride.integrations.rideprovider.base import RideBookingRequest
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
        )
    )

    assert result.provider == "mock"
    assert result.provider_booking_id.startswith("mock-")
    assert result.fare_currency == "INR"
    assert result.driver_name
    assert result.vehicle_description