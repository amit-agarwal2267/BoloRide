from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from boloride.db.models.accepted_quote import AcceptedQuote
from boloride.db.models.driver import Driver
from boloride.db.models.ride import Ride
from boloride.db.models.ride_assignment import RideAssignment
from boloride.db.models.vehicle import Vehicle
from boloride.db.models.vehicle_type import VehicleType
from boloride.domain.enums import RideStatus
from boloride.domain.models.fleet import DriverAvailability


class AssignmentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_booked_ride_for_dispatch(
        self, customer_id: UUID, ride_id: UUID
    ) -> tuple[Ride, AcceptedQuote] | None:
        row = (
            await self._session.execute(
                select(Ride, AcceptedQuote)
                .join(AcceptedQuote, AcceptedQuote.ride_id == Ride.id)
                .where(Ride.id == ride_id, Ride.user_id == customer_id)
                .with_for_update(of=Ride)
            )
        ).one_or_none()
        return row._tuple() if row else None

    async def create(self, ride_id: UUID, driver_id: UUID, vehicle_id: UUID) -> RideAssignment:
        assignment = RideAssignment(ride_id=ride_id, driver_id=driver_id, vehicle_id=vehicle_id)
        self._session.add(assignment)
        await self._session.flush()
        return assignment

    async def get_for_ride(
        self, ride_id: UUID, *, for_update: bool = False
    ) -> RideAssignment | None:
        statement = select(RideAssignment).where(RideAssignment.ride_id == ride_id)
        if for_update:
            statement = statement.with_for_update()
        return await self._session.scalar(statement)

    async def assignment_status_details(
        self, ride_id: UUID
    ) -> tuple[str, str, str] | None:
        row = (
            await self._session.execute(
                select(Driver.name, Vehicle.registration_number, VehicleType.display_name)
                .join(Vehicle, Vehicle.driver_id == Driver.id)
                .join(VehicleType, VehicleType.code == Vehicle.vehicle_type_code)
                .join(RideAssignment, RideAssignment.vehicle_id == Vehicle.id)
                .where(RideAssignment.ride_id == ride_id)
            )
        ).one_or_none()
        return row._tuple() if row else None

    async def transition_driver(
        self,
        driver_id: UUID,
        expected: DriverAvailability,
        requested: DriverAvailability,
    ) -> Driver | None:
        result = await self._session.execute(
            update(Driver)
            .where(Driver.id == driver_id, Driver.availability == expected)
            .values(availability=requested)
            .returning(Driver)
        )
        return result.scalar_one_or_none()

    async def release(
        self, assignment: RideAssignment, reason: str
    ) -> RideAssignment | None:
        result = await self._session.execute(
            update(RideAssignment)
            .where(RideAssignment.id == assignment.id, RideAssignment.released_at.is_(None))
            .values(released_at=datetime.now(UTC), release_reason=reason)
            .returning(RideAssignment)
        )
        return result.scalar_one_or_none()
