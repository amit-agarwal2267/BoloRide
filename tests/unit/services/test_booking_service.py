from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from boloride.agents.context import RideContext
from boloride.domain.exceptions import DomainValidationError
from boloride.domain.models.location import ResolvedLocation, TollStatus
from boloride.domain.models.quote import FareComponent, FareComponentType, PricingResult, Quote
from boloride.domain.policies import CustomerIdentityState
from boloride.integrations.rideprovider.base import RideBookingRequest
from boloride.services.booking_service import BookingService
from boloride.services.booking_snapshots import deserialize_authorization, serialize_authorization


def ready_context() -> RideContext:
    customer_id = uuid4()
    now = datetime.now(UTC)
    context = RideContext(
        session_id="session-1", caller_id=customer_id,
        identity_state=CustomerIdentityState.VERIFIED_RETURNING_CUSTOMER,
        verified_customer_id=customer_id,
        pickup=ResolvedLocation("Home", Decimal("25.18"), Decimal("75.83")),
        destination=ResolvedLocation("Station", Decimal("25.22"), Decimal("75.88")),
        ride_time=now + timedelta(hours=1), passenger_count=4,
        selected_vehicle_type_code="sedan",
    )
    components = tuple(FareComponent(kind, amount) for kind, amount in (
        (FareComponentType.BASE_FARE, Decimal("50.00")),
        (FareComponentType.DISTANCE_FARE, Decimal("140.00")),
        (FareComponentType.NIGHT_CHARGE, Decimal("0.00")),
        (FareComponentType.AIRPORT_FEE, Decimal("0.00")),
    ))
    quote = Quote(uuid4(), context.session_id, "a" * 64, PricingResult(
        uuid4(), "sedan", 10000, 1200, "google", components,
        TollStatus.UNKNOWN, Decimal("190.00"), "INR",
    ), now, now + timedelta(minutes=20))
    context.set_quote(quote)
    context.confirm_quote(quote.id)
    return context


def test_authorization_snapshot_round_trip_is_explicit_and_versioned() -> None:
    context = ready_context()
    request = RideBookingRequest(
        uuid4(), context.pickup, context.destination, context.ride_time,
        context.passenger_count, context.selected_vehicle_type_code,
    )
    value = serialize_authorization(request, context.current_quote)
    recovered_request, recovered_quote = deserialize_authorization(value)
    assert value["version"] == 1
    assert recovered_request == request
    assert recovered_quote == context.current_quote


def test_invalid_authorization_snapshot_is_rejected() -> None:
    with pytest.raises(DomainValidationError, match="recovery snapshot"):
        deserialize_authorization({"version": 99})


def test_booking_requires_verified_matching_customer() -> None:
    context = ready_context()
    context.verified_customer_id = uuid4()
    with pytest.raises(DomainValidationError, match="verified customer"):
        BookingService._validate_identity_and_inputs(context.caller_id, context)


def test_booking_requires_timezone_aware_time() -> None:
    context = ready_context()
    context.ride_time = datetime.now()
    with pytest.raises(DomainValidationError, match="timezone-aware"):
        BookingService._validate_identity_and_inputs(context.caller_id, context)
