from enum import StrEnum


class RideStatus(StrEnum):
    REQUESTED = "requested"
    CONFIRMED = "confirmed"
    BOOKED = "booked"
