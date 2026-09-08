import pytest

from boloride.domain.enums import RideStatus
from boloride.domain.exceptions import InvalidRideTransitionError
from boloride.domain.models.ride import validate_ride_transition


def test_ride_lifecycle_allows_ordered_transitions() -> None:
    validate_ride_transition(RideStatus.REQUESTED, RideStatus.CONFIRMED)
    validate_ride_transition(RideStatus.CONFIRMED, RideStatus.BOOKED)


@pytest.mark.parametrize(
    ("current", "requested"),
    [
        (RideStatus.REQUESTED, RideStatus.BOOKED),
        (RideStatus.CONFIRMED, RideStatus.REQUESTED),
        (RideStatus.BOOKED, RideStatus.CONFIRMED),
        (RideStatus.REQUESTED, RideStatus.REQUESTED),
    ],
)
def test_ride_lifecycle_rejects_invalid_transitions(
    current: RideStatus, requested: RideStatus
) -> None:
    with pytest.raises(InvalidRideTransitionError):
        validate_ride_transition(current, requested)
