from boloride.agents.context import RideContext
from boloride.domain.exceptions import DomainValidationError
from boloride.domain.models.vehicle import (
    PassengerCountSource,
    VehicleEligibilityResult,
    VehicleEligibilityState,
    VehicleTypeDetails,
    validate_passenger_count,
    vehicle_has_capacity,
)
from boloride.repositories.vehicle_type_repository import VehicleTypeRepository


class VehicleService:
    def __init__(self, vehicle_types: VehicleTypeRepository) -> None:
        self._vehicle_types = vehicle_types

    async def get_eligible_vehicle_types(
        self, passenger_count: int
    ) -> VehicleEligibilityResult:
        normalized_count = validate_passenger_count(passenger_count)
        eligible = tuple(
            await self._vehicle_types.list_capacity_eligible(normalized_count)
        )
        state = (
            VehicleEligibilityState.ELIGIBLE_VEHICLE_TYPES
            if eligible
            else VehicleEligibilityState.NO_ELIGIBLE_VEHICLE_TYPE
        )
        return VehicleEligibilityResult(state, normalized_count, eligible)

    async def require_eligible_vehicle_type(
        self, code: str, passenger_count: int
    ) -> VehicleTypeDetails:
        normalized_count = validate_passenger_count(passenger_count)
        normalized_code = code.strip().casefold()
        vehicle = await self._vehicle_types.get_by_code(normalized_code)
        if vehicle is None:
            raise DomainValidationError("unknown vehicle type")
        if not vehicle.active:
            raise DomainValidationError("vehicle type is inactive")
        if not vehicle_has_capacity(vehicle, normalized_count):
            raise DomainValidationError(
                "selected vehicle type cannot accommodate the passenger count"
            )
        return vehicle

    async def select_vehicle_type(self, context: RideContext, code: str) -> None:
        vehicle = await self.require_eligible_vehicle_type(
            code, context.passenger_count
        )
        context.update_selected_vehicle_type(vehicle.code)

    async def update_passenger_count(
        self,
        context: RideContext,
        passenger_count: int,
        source: PassengerCountSource,
    ) -> None:
        normalized_count = validate_passenger_count(passenger_count)
        selected_vehicle_is_eligible = True
        if context.selected_vehicle_type_code is not None:
            selected = await self._vehicle_types.get_by_code(
                context.selected_vehicle_type_code
            )
            selected_vehicle_is_eligible = (
                selected is not None
                and vehicle_has_capacity(selected, normalized_count)
            )
        context.update_passenger_count(
            normalized_count,
            source,
            selected_vehicle_is_eligible=selected_vehicle_is_eligible,
        )
