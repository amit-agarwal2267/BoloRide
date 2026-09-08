from boloride.domain.enums import RideStatus
from boloride.domain.exceptions import InvalidRideTransitionError

_ALLOWED_TRANSITIONS = {
    RideStatus.REQUESTED: RideStatus.CONFIRMED,
    RideStatus.CONFIRMED: RideStatus.BOOKED,
}


def validate_ride_transition(
    current: RideStatus, requested: RideStatus
) -> None:
    if _ALLOWED_TRANSITIONS.get(current) != requested:
        raise InvalidRideTransitionError(
            f"ride cannot transition from {current.value} to {requested.value}"
        )
