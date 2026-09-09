import pytest

from boloride.domain.enums import RideStatus
from boloride.domain.exceptions import InvalidRideTransitionError
from boloride.domain.models.ride import CANCELLABLE_RIDE_STATUSES, validate_ride_transition


@pytest.mark.parametrize(
    ("current", "requested"),
    [
        (RideStatus.BOOKED, RideStatus.ASSIGNED),
        (RideStatus.BOOKED, RideStatus.CANCELLED),
        (RideStatus.ASSIGNED, RideStatus.ON_TRIP),
        (RideStatus.ASSIGNED, RideStatus.CANCELLED),
        (RideStatus.ON_TRIP, RideStatus.COMPLETED),
    ],
)
def test_ride_lifecycle_allows_only_canonical_transitions(
    current: RideStatus, requested: RideStatus
) -> None:
    validate_ride_transition(current, requested)


@pytest.mark.parametrize(
    ("current", "requested"),
    [
        (current, requested)
        for current in RideStatus
        for requested in RideStatus
        if (current, requested)
        not in {
            (RideStatus.BOOKED, RideStatus.ASSIGNED),
            (RideStatus.BOOKED, RideStatus.CANCELLED),
            (RideStatus.ASSIGNED, RideStatus.ON_TRIP),
            (RideStatus.ASSIGNED, RideStatus.CANCELLED),
            (RideStatus.ON_TRIP, RideStatus.COMPLETED),
        }
    ],
)
def test_ride_lifecycle_rejects_every_other_transition(
    current: RideStatus, requested: RideStatus
) -> None:
    with pytest.raises(InvalidRideTransitionError):
        validate_ride_transition(current, requested)


def test_only_booked_and_assigned_are_cancellable() -> None:
    assert CANCELLABLE_RIDE_STATUSES == {
        RideStatus.BOOKED,
        RideStatus.ASSIGNED,
    }
