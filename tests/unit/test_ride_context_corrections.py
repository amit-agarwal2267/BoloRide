import pytest
from datetime import datetime
import uuid
from boloride.agents.context import RideContext
from boloride.domain.models.location import ResolvedLocation, RouteResult
from boloride.domain.models.vehicle import PassengerCountSource
from boloride.domain.models.scheduling import RideTimingIntent

def test_ride_context_corrections():
    context = RideContext(session_id="test", caller_id=uuid.uuid4())
    context.user_confirmed = True
    
    from decimal import Decimal
    loc = ResolvedLocation(display_name="A", address="B", latitude=Decimal("1.0"), longitude=Decimal("1.0"), provider="mock")
    
    # Updating with same value doesn't reset confirmation
    context.update_pickup(None)
    assert context.user_confirmed is True
    
    # Updating with new value resets confirmation
    context.update_pickup(loc)
    assert context.user_confirmed is False
    
    context.user_confirmed = True
    context.update_destination(loc)
    assert context.user_confirmed is False
    
    context.user_confirmed = True
    context.update_ride_time(datetime.now())
    assert context.user_confirmed is False


def test_passenger_change_invalidates_ineligible_vehicle_and_confirmation():
    context = RideContext(
        session_id="test",
        caller_id=uuid.uuid4(),
        passenger_count=3,
        selected_vehicle_type_code="auto",
        user_confirmed=True,
    )

    context.update_passenger_count(
        4,
        PassengerCountSource.USER_PROVIDED,
        selected_vehicle_is_eligible=False,
    )

    assert context.passenger_count == 4
    assert context.passenger_count_source is PassengerCountSource.USER_PROVIDED
    assert context.selected_vehicle_type_code is None
    assert context.user_confirmed is False


def test_cancellation_confirmation_is_bound_to_exact_target_and_cleared():
    context = RideContext(session_id="test", caller_id=uuid.uuid4())
    first, second = uuid.uuid4(), uuid.uuid4()
    context.select_cancellation_target(first)
    context.record_cancellation_confirmation(first, True)
    assert context.cancellation_is_confirmed_for(first)

    context.select_cancellation_target(second)
    assert not context.cancellation_is_confirmed_for(first)
    assert not context.cancellation_is_confirmed_for(second)
    context.record_cancellation_confirmation(second, False)
    assert context.cancellation_target_ride_id is None
    assert context.cancellation_confirmed_ride_id is None


def test_location_change_invalidates_cached_route_quote_and_confirmation():
    from decimal import Decimal

    context = RideContext(session_id="test", caller_id=uuid.uuid4())
    context.route = RouteResult(1000, 100, "ola")
    context.user_confirmed = True
    location = ResolvedLocation("Place", Decimal("25"), Decimal("75"))

    context.update_pickup(location)

    assert context.route is None
    assert context.current_quote is None
    assert context.user_confirmed is False


def test_timing_correction_preserves_non_timing_state_and_invalidates_confirmation():
    from datetime import UTC
    from decimal import Decimal

    location = ResolvedLocation("Place", Decimal("25"), Decimal("75"))
    context = RideContext(
        session_id="test",
        caller_id=uuid.uuid4(),
        pickup=location,
        destination=ResolvedLocation("Other", Decimal("26"), Decimal("76")),
        passenger_count=4,
        selected_vehicle_type_code="sedan",
        user_confirmed=True,
    )

    context.update_ride_timing(
        RideTimingIntent.SCHEDULED,
        datetime(2026, 9, 12, 1, 30, tzinfo=UTC),
    )
    context.user_confirmed = True
    context.update_ride_timing(
        RideTimingIntent.IMMEDIATE,
        datetime(2026, 9, 11, 4, 0, tzinfo=UTC),
    )

    assert context.timing_intent is RideTimingIntent.IMMEDIATE
    assert context.pickup is location
    assert context.destination is not None
    assert context.passenger_count == 4
    assert context.selected_vehicle_type_code == "sedan"
    assert context.user_confirmed is False


def test_pickup_instruction_change_does_not_invalidate_route_or_confirmation():
    from decimal import Decimal

    context = RideContext(session_id="test", caller_id=uuid.uuid4())
    context.pickup = ResolvedLocation("Place", Decimal("25"), Decimal("75"))
    context.route = RouteResult(1000, 100, "ola")
    context.user_confirmed = True

    context.set_pickup_instructions("  SBI ATM ke saamne  ")

    assert context.pickup_instructions == "SBI ATM ke saamne"
    assert context.route is not None
    assert context.user_confirmed is True
