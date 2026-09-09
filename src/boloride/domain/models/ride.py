from boloride.domain.enums import RideStatus
from boloride.domain.exceptions import InvalidRideTransitionError

_ALLOWED_TRANSITIONS = {
    RideStatus.BOOKED: frozenset({RideStatus.ASSIGNED, RideStatus.CANCELLED}),
    RideStatus.ASSIGNED: frozenset({RideStatus.ON_TRIP, RideStatus.CANCELLED}),
    RideStatus.ON_TRIP: frozenset({RideStatus.COMPLETED}),
    RideStatus.COMPLETED: frozenset(),
    RideStatus.CANCELLED: frozenset(),
}

CANCELLABLE_RIDE_STATUSES = frozenset({RideStatus.BOOKED, RideStatus.ASSIGNED})


def validate_ride_transition(
    current: RideStatus, requested: RideStatus
) -> None:
    if requested not in _ALLOWED_TRANSITIONS[current]:
        raise InvalidRideTransitionError(
            f"ride cannot transition from {current.value} to {requested.value}"
        )
