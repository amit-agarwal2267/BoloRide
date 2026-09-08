from dataclasses import dataclass
from enum import StrEnum

from boloride.domain.exceptions import DomainValidationError


class PassengerCountSource(StrEnum):
    DEFAULT = "default"
    USER_PROVIDED = "user_provided"


class VehicleEligibilityState(StrEnum):
    ELIGIBLE_VEHICLE_TYPES = "eligible_vehicle_types"
    NO_ELIGIBLE_VEHICLE_TYPE = "no_eligible_vehicle_type"


@dataclass(frozen=True, slots=True)
class VehicleTypeDetails:
    code: str
    display_name: str
    passenger_capacity: int
    active: bool


@dataclass(frozen=True, slots=True)
class VehicleEligibilityResult:
    state: VehicleEligibilityState
    passenger_count: int
    eligible_vehicle_types: tuple[VehicleTypeDetails, ...]

    def __post_init__(self) -> None:
        has_eligible_types = bool(self.eligible_vehicle_types)
        if has_eligible_types != (
            self.state is VehicleEligibilityState.ELIGIBLE_VEHICLE_TYPES
        ):
            raise ValueError("vehicle eligibility state must match its result items")


def validate_passenger_count(passenger_count: int) -> int:
    if isinstance(passenger_count, bool) or not isinstance(passenger_count, int):
        raise DomainValidationError("passenger count must be a whole number")
    if passenger_count <= 0:
        raise DomainValidationError("passenger count must be positive")
    return passenger_count


def vehicle_has_capacity(
    vehicle: VehicleTypeDetails, passenger_count: int
) -> bool:
    return vehicle.active and vehicle.passenger_capacity >= validate_passenger_count(
        passenger_count
    )
