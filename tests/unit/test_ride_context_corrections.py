import pytest
from datetime import datetime
import uuid
from boloride.agents.context import RideContext
from boloride.domain.models.location import ResolvedLocation
from boloride.domain.models.vehicle import PassengerCountSource

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
