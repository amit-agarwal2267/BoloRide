from dataclasses import dataclass
from enum import StrEnum
from math import asin, cos, radians, sin, sqrt
from uuid import UUID


class DispatchResultStatus(StrEnum):
    ASSIGNED = "assigned"
    STARTED = "started"
    COMPLETED = "completed"
    ALREADY_ASSIGNED = "already_assigned"
    NO_DRIVER_AVAILABLE = "no_driver_available"
    NOT_FOUND = "not_found"
    INVALID_LIFECYCLE = "invalid_lifecycle"
    RACE_LOST = "race_lost"


@dataclass(frozen=True, slots=True)
class DispatchResult:
    status: DispatchResultStatus
    ride_id: UUID | None = None


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Dispatch-only straight-line ranking distance; never a pricing input."""
    latitude_delta = radians(lat2 - lat1)
    longitude_delta = radians(lon2 - lon1)
    value = (
        sin(latitude_delta / 2) ** 2
        + cos(radians(lat1)) * cos(radians(lat2)) * sin(longitude_delta / 2) ** 2
    )
    return 6371.0088 * 2 * asin(sqrt(value))
