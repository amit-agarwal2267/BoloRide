from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from boloride.db.models.vehicle_type import VehicleType
from boloride.domain.models.vehicle import VehicleTypeDetails


def _to_details(vehicle: VehicleType) -> VehicleTypeDetails:
    return VehicleTypeDetails(
        code=vehicle.code,
        display_name=vehicle.display_name,
        passenger_capacity=vehicle.passenger_capacity,
        active=vehicle.active,
    )


class VehicleTypeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_code(self, code: str) -> VehicleTypeDetails | None:
        vehicle = await self._session.scalar(
            select(VehicleType).where(VehicleType.code == code)
        )
        return _to_details(vehicle) if vehicle is not None else None

    async def list_capacity_eligible(
        self, passenger_count: int
    ) -> list[VehicleTypeDetails]:
        vehicles = await self._session.scalars(
            select(VehicleType)
            .where(
                VehicleType.active.is_(True),
                VehicleType.passenger_capacity >= passenger_count,
            )
            .order_by(VehicleType.passenger_capacity, VehicleType.code)
        )
        return [_to_details(vehicle) for vehicle in vehicles]
