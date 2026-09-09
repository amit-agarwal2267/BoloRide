from uuid import UUID

from boloride.agents.context import RideContext
from boloride.domain.models.cancellation import CancellationResult, RideStatusDetails
from boloride.services.ride_service import RideService


async def get_ride_status(
    service: RideService,
    customer_id: UUID,
    ride_id: UUID,
    context: RideContext,
) -> RideStatusDetails | None:
    return await service.get_customer_ride_status(customer_id, ride_id, context)


async def cancel_ride(
    service: RideService,
    customer_id: UUID,
    ride_id: UUID,
    context: RideContext,
) -> CancellationResult:
    return await service.cancel_customer_ride(customer_id, ride_id, context)
