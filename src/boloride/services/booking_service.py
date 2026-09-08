from dataclasses import dataclass
from uuid import UUID, uuid4

from boloride.agents.context import RideContext
from boloride.domain.exceptions import DomainValidationError
from boloride.integrations.rideprovider.base import (
	RideBookingRequest,
	RideBookingResult,
	RideProvider,
)
from boloride.repositories.ride_repository import RideRepository


@dataclass(frozen=True, slots=True)
class BookingOutcome:
	ride: object
	provider_result: RideBookingResult


class BookingService:
	def __init__(self, rides: RideRepository, provider: RideProvider) -> None:
		self._rides = rides
		self._provider = provider

	async def book_ride(self, user_id: UUID, context: RideContext) -> BookingOutcome:
		if context.pickup is None:
			raise DomainValidationError("pickup is required before booking")
		if context.destination is None:
			raise DomainValidationError("destination is required before booking")
		if context.ride_time is None:
			raise DomainValidationError("ride time is required before booking")
		if context.ride_time.tzinfo is None:
			raise DomainValidationError("ride time must be timezone-aware")
		if not context.confirmation_received:
			raise DomainValidationError("explicit booking confirmation is required")
		if context.clarification_required:
			raise DomainValidationError("location clarification is required")
		if context.booking_id is not None:
			raise DomainValidationError("ride has already been booked")

		ride = await self._rides.create(
			user_id,
			context.pickup,
			context.destination,
			context.ride_time,
		)
		await self._rides.confirm(ride.id)
		provider_result = await self._provider.create_booking(
			RideBookingRequest(
				request_id=ride.id or uuid4(),
				pickup=context.pickup,
				destination=context.destination,
				requested_ride_at=context.ride_time,
				ride_type=context.ride_type,
			)
		)
		booked_ride = await self._rides.mark_booked(
			ride.id,
			provider=provider_result.provider,
			provider_booking_id=provider_result.provider_booking_id,
			fare_amount=provider_result.fare_amount,
			fare_currency=provider_result.fare_currency,
		)
		if booked_ride is None:
			raise DomainValidationError("ride disappeared during booking")
		context.booking_id = booked_ride.id
		context.booking_confirmed = True
		return BookingOutcome(booked_ride, provider_result)
