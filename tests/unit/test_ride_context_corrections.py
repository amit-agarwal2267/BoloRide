import pytest
from datetime import datetime
import uuid
from boloride.agents.context import RideContext
from boloride.domain.models.location import ResolvedLocation

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
