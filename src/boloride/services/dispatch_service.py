import logging
from time import monotonic
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from boloride.domain.enums import RideStatus
from boloride.domain.models.dispatch import DispatchResult, DispatchResultStatus, haversine_km
from boloride.domain.models.fleet import CITY_CENTRES, DriverAvailability
from boloride.repositories.assignment_repository import AssignmentRepository
from boloride.repositories.fleet_repository import FleetRepository
from boloride.repositories.ride_repository import RideRepository
from boloride.services.offer_service import OfferService

logger = logging.getLogger(__name__)


class DispatchService:
    def __init__(
        self,
        session: AsyncSession,
        rides: RideRepository,
        fleet: FleetRepository,
        assignments: AssignmentRepository,
        offers: OfferService | None = None,
    ) -> None:
        self._session = session
        self._rides = rides
        self._fleet = fleet
        self._assignments = assignments
        self._offers = offers

    async def dispatch(self, customer_id: UUID, ride_id: UUID) -> DispatchResult:
        started = monotonic()
        logger.info("dispatch_requested", extra={"event": "dispatch_requested"})
        row = await self._assignments.get_booked_ride_for_dispatch(customer_id, ride_id)
        if row is None:
            await self._session.rollback()
            return DispatchResult(DispatchResultStatus.NOT_FOUND)
        ride, quote = row
        persisted_ride_id = ride.id
        vehicle_category = quote.vehicle_type_code
        if ride.status is RideStatus.ASSIGNED:
            await self._session.rollback()
            return DispatchResult(DispatchResultStatus.ALREADY_ASSIGNED, persisted_ride_id)
        if ride.status is not RideStatus.BOOKED:
            await self._session.rollback()
            return DispatchResult(DispatchResultStatus.INVALID_LIFECYCLE, persisted_ride_id)

        centre = min(
            CITY_CENTRES,
            key=lambda item: haversine_km(
                float(ride.pickup_latitude), float(ride.pickup_longitude),
                float(item.latitude), float(item.longitude),
            ),
        )
        candidates = await self._fleet.list_available_in_city(
            centre.state, centre.city, vehicle_category
        )
        ranked = sorted(
            candidates,
            key=lambda item: (
                haversine_km(
                    float(ride.pickup_latitude), float(ride.pickup_longitude),
                    float(item[0].latitude), float(item[0].longitude),
                ),
                str(item[0].id),
                str(item[1].id),
            ),
        )
        logger.info(
            "dispatch_candidate_count",
            extra={"event": "dispatch_candidate_count", "candidate_count": len(ranked), "vehicle_category": vehicle_category},
        )
        for driver, vehicle in ranked:
            claimed = await self._fleet.claim_available_driver(driver.id)
            if claimed is None:
                logger.info("dispatch_claim_conflict", extra={"event": "dispatch_claim_conflict", "vehicle_category": vehicle_category})
                continue
            transitioned = await self._rides.transition_for_customer(
                customer_id, ride.id,
                expected_status=RideStatus.BOOKED,
                requested_status=RideStatus.ASSIGNED,
            )
            if transitioned is None:
                await self._session.rollback()
                logger.info("lifecycle_race_lost", extra={"event": "lifecycle_race_lost"})
                return DispatchResult(DispatchResultStatus.RACE_LOST, persisted_ride_id)
            await self._assignments.create(ride.id, driver.id, vehicle.id)
            await self._session.commit()
            logger.info(
                "dispatch_assignment_success",
                extra={"event": "dispatch_assignment_success", "vehicle_category": vehicle_category, "duration_ms": round((monotonic() - started) * 1000, 2)},
            )
            return DispatchResult(DispatchResultStatus.ASSIGNED, persisted_ride_id)

        await self._session.rollback()
        logger.info("dispatch_no_driver_available", extra={"event": "dispatch_no_driver_available", "vehicle_category": vehicle_category})
        return DispatchResult(DispatchResultStatus.NO_DRIVER_AVAILABLE, persisted_ride_id)

    async def start_trip(self, customer_id: UUID, ride_id: UUID) -> DispatchResult:
        ride = await self._rides.get_for_customer(customer_id, ride_id, for_update=True)
        if ride is None:
            await self._session.rollback()
            return DispatchResult(DispatchResultStatus.NOT_FOUND)
        persisted_ride_id = ride.id
        if ride.status is not RideStatus.ASSIGNED:
            await self._session.rollback()
            return DispatchResult(DispatchResultStatus.INVALID_LIFECYCLE, persisted_ride_id)
        assignment = await self._assignments.get_for_ride(ride.id, for_update=True)
        if assignment is None or assignment.released_at is not None:
            await self._session.rollback()
            return DispatchResult(DispatchResultStatus.INVALID_LIFECYCLE, persisted_ride_id)
        driver = await self._assignments.transition_driver(
            assignment.driver_id, DriverAvailability.ASSIGNED, DriverAvailability.ON_TRIP
        )
        transitioned = await self._rides.transition_for_customer(
            customer_id, ride.id, expected_status=RideStatus.ASSIGNED, requested_status=RideStatus.ON_TRIP
        )
        if driver is None or transitioned is None:
            await self._session.rollback()
            logger.info("lifecycle_race_lost", extra={"event": "lifecycle_race_lost"})
            return DispatchResult(DispatchResultStatus.RACE_LOST, persisted_ride_id)
        await self._session.commit()
        logger.info("trip_started", extra={"event": "trip_started"})
        return DispatchResult(DispatchResultStatus.STARTED, persisted_ride_id)

    async def complete_trip(self, customer_id: UUID, ride_id: UUID) -> DispatchResult:
        ride = await self._rides.get_for_customer(customer_id, ride_id, for_update=True)
        if ride is None:
            await self._session.rollback()
            return DispatchResult(DispatchResultStatus.NOT_FOUND)
        persisted_ride_id = ride.id
        if ride.status is not RideStatus.ON_TRIP:
            await self._session.rollback()
            return DispatchResult(DispatchResultStatus.INVALID_LIFECYCLE, persisted_ride_id)
        assignment = await self._assignments.get_for_ride(ride.id, for_update=True)
        if assignment is None or assignment.released_at is not None:
            await self._session.rollback()
            return DispatchResult(DispatchResultStatus.INVALID_LIFECYCLE, persisted_ride_id)
        driver = await self._assignments.transition_driver(
            assignment.driver_id, DriverAvailability.ON_TRIP, DriverAvailability.AVAILABLE
        )
        transitioned = await self._rides.transition_for_customer(
            customer_id, ride.id, expected_status=RideStatus.ON_TRIP, requested_status=RideStatus.COMPLETED
        )
        if driver is None or transitioned is None:
            await self._session.rollback()
            logger.info("lifecycle_race_lost", extra={"event": "lifecycle_race_lost"})
            return DispatchResult(DispatchResultStatus.RACE_LOST, persisted_ride_id)
        await self._assignments.release(assignment, "completed")
        if self._offers is not None:
            await self._offers.finalize_redemption(customer_id, ride.id, RideStatus.COMPLETED)
        await self._session.commit()
        logger.info("trip_completed", extra={"event": "trip_completed"})
        return DispatchResult(DispatchResultStatus.COMPLETED, persisted_ride_id)

    async def release_assignment_idempotently(self, ride_id: UUID) -> None:
        assignment = await self._assignments.get_for_ride(ride_id, for_update=True)
        if assignment is None or assignment.released_at is not None:
            await self._session.rollback()
            return
        driver = await self._assignments.transition_driver(
            assignment.driver_id, DriverAvailability.ASSIGNED, DriverAvailability.AVAILABLE
        )
        if driver is None:
            await self._session.rollback()
            raise RuntimeError("assigned driver could not be released safely")
        await self._assignments.release(assignment, "cancelled")
        await self._session.commit()
        logger.info("driver_released", extra={"event": "driver_released"})
