from uuid import UUID

from boloride.agents.context import RideContext
from boloride.services.booking_service import BookingOutcome, BookingService


async def create_ride(
	service: BookingService, user_id: UUID, context: RideContext
) -> BookingOutcome:
	return await service.book_ride(user_id, context)
