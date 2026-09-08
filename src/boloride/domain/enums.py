from enum import StrEnum


class RideStatus(StrEnum):
    BOOKED = "booked"
    ASSIGNED = "assigned"
    ON_TRIP = "on_trip"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
