import logging

from sqlalchemy.ext.asyncio import AsyncSession

from boloride.domain.exceptions import DomainValidationError
from boloride.domain.models.fleet import (
    FLEET_SEED_VERSION,
    VEHICLE_COUNTS,
    generate_demo_fleet,
)
from boloride.repositories.fleet_repository import FleetRepository

logger = logging.getLogger(__name__)


class FleetSeedService:
    def __init__(self, session: AsyncSession, fleet: FleetRepository) -> None:
        self._session = session
        self._fleet = fleet

    async def seed_demo_fleet(self) -> dict[str, int]:
        members = generate_demo_fleet()
        expected_total = len(members)
        logger.info(
            "fleet_seed_started",
            extra={"event": "fleet_seed_started", "seed_version": FLEET_SEED_VERSION},
        )
        try:
            driver_count, vehicle_count = await self._fleet.seeded_counts(
                FLEET_SEED_VERSION
            )
            if driver_count or vehicle_count:
                counts = await self._fleet.category_counts(FLEET_SEED_VERSION)
                actual_signatures = await self._fleet.seeded_signatures(
                    FLEET_SEED_VERSION
                )
                expected_signatures = {
                    (
                        member.driver_id,
                        member.vehicle_id,
                        member.seed_key,
                        member.driver_name,
                        member.availability,
                        member.latitude,
                        member.longitude,
                        member.city,
                        member.state,
                        member.vehicle_type_code,
                        member.registration_number,
                        True,
                    )
                    for member in members
                }
                if (
                    driver_count != expected_total
                    or vehicle_count != expected_total
                    or counts != VEHICLE_COUNTS
                    or actual_signatures != expected_signatures
                ):
                    raise DomainValidationError(
                        "existing demo fleet seed is incomplete or inconsistent"
                    )
                logger.info(
                    "fleet_seed_existing_detected",
                    extra={
                        "event": "fleet_seed_existing_detected",
                        "seed_version": FLEET_SEED_VERSION,
                        "driver_count": driver_count,
                        "vehicle_count": vehicle_count,
                        "category_counts": counts,
                    },
                )
                return counts

            await self._fleet.insert_seed(members, FLEET_SEED_VERSION)
            await self._session.commit()
            counts = await self._fleet.category_counts(FLEET_SEED_VERSION)
            geography = await self._fleet.geography_counts(FLEET_SEED_VERSION)
            logger.info(
                "fleet_seed_completed",
                extra={
                    "event": "fleet_seed_completed",
                    "seed_version": FLEET_SEED_VERSION,
                    "driver_count": expected_total,
                    "vehicle_count": expected_total,
                    "category_counts": counts,
                    "state_counts": geography,
                },
            )
            return counts
        except Exception as exc:
            await self._session.rollback()
            logger.error(
                "fleet_seed_failed",
                extra={
                    "event": "fleet_seed_failed",
                    "seed_version": FLEET_SEED_VERSION,
                    "error_type": type(exc).__name__,
                },
            )
            raise
