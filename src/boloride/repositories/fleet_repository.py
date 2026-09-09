from collections import Counter
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from boloride.db.models.driver import Driver
from boloride.db.models.vehicle import Vehicle
from boloride.db.models.vehicle_type import VehicleType
from boloride.domain.models.fleet import DemoFleetMember, DriverAvailability


class FleetRepository:
    """Explicit persistence and lookup operations for the dispatch fleet."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_driver(self, driver_id: UUID) -> Driver | None:
        return await self._session.get(Driver, driver_id)

    async def get_vehicle(self, vehicle_id: UUID) -> Vehicle | None:
        return await self._session.get(Vehicle, vehicle_id)

    async def get_vehicle_for_driver(self, driver_id: UUID) -> Vehicle | None:
        return await self._session.scalar(
            select(Vehicle).where(Vehicle.driver_id == driver_id)
        )

    async def list_available_in_city(
        self, state: str, city: str, vehicle_type_code: str
    ) -> list[tuple[Driver, Vehicle]]:
        rows = await self._session.execute(
            select(Driver, Vehicle)
            .join(Vehicle, Vehicle.driver_id == Driver.id)
            .join(VehicleType, VehicleType.code == Vehicle.vehicle_type_code)
            .where(
                Driver.availability == DriverAvailability.AVAILABLE,
                Driver.state == state,
                Driver.city == city,
                Vehicle.vehicle_type_code == vehicle_type_code,
                Vehicle.active.is_(True),
                VehicleType.active.is_(True),
                Driver.seed_version.is_not(None),
            )
            .order_by(Driver.id)
            .limit(100)
        )
        return list(rows.tuples())

    async def claim_available_driver(self, driver_id: UUID) -> Driver | None:
        result = await self._session.execute(
            update(Driver)
            .where(
                Driver.id == driver_id,
                Driver.availability == DriverAvailability.AVAILABLE,
            )
            .values(availability=DriverAvailability.ASSIGNED)
            .returning(Driver)
        )
        return result.scalar_one_or_none()

    async def seeded_counts(self, seed_version: str) -> tuple[int, int]:
        driver_count = await self._session.scalar(
            select(func.count()).select_from(Driver).where(Driver.seed_version == seed_version)
        )
        vehicle_count = await self._session.scalar(
            select(func.count())
            .select_from(Vehicle)
            .join(Driver, Driver.id == Vehicle.driver_id)
            .where(Driver.seed_version == seed_version)
        )
        return int(driver_count or 0), int(vehicle_count or 0)

    async def category_counts(self, seed_version: str) -> dict[str, int]:
        rows = await self._session.execute(
            select(Vehicle.vehicle_type_code, func.count())
            .join(Driver, Driver.id == Vehicle.driver_id)
            .where(Driver.seed_version == seed_version)
            .group_by(Vehicle.vehicle_type_code)
        )
        return {code: int(count) for code, count in rows}

    async def seeded_signatures(self, seed_version: str) -> set[tuple[object, ...]]:
        rows = await self._session.execute(
            select(
                Driver.id,
                Vehicle.id,
                Driver.seed_key,
                Driver.name,
                Driver.availability,
                Driver.latitude,
                Driver.longitude,
                Driver.city,
                Driver.state,
                Vehicle.vehicle_type_code,
                Vehicle.registration_number,
                Vehicle.active,
            )
            .join(Vehicle, Vehicle.driver_id == Driver.id)
            .where(Driver.seed_version == seed_version)
        )
        return set(rows.tuples())

    async def insert_seed(self, members: tuple[DemoFleetMember, ...], seed_version: str) -> None:
        self._session.add_all(
            [
                Driver(
                    id=member.driver_id,
                    name=member.driver_name,
                    availability=member.availability,
                    latitude=member.latitude,
                    longitude=member.longitude,
                    city=member.city,
                    state=member.state,
                    seed_version=seed_version,
                    seed_key=member.seed_key,
                )
                for member in members
            ]
        )
        await self._session.flush()
        self._session.add_all(
            [
                Vehicle(
                    id=member.vehicle_id,
                    driver_id=member.driver_id,
                    vehicle_type_code=member.vehicle_type_code,
                    registration_number=member.registration_number,
                    active=True,
                )
                for member in members
            ]
        )
        await self._session.flush()

    async def geography_counts(self, seed_version: str) -> dict[str, int]:
        states = await self._session.scalars(
            select(Driver.state).where(Driver.seed_version == seed_version)
        )
        return dict(Counter(states))
