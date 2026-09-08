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
from boloride.services.vehicle_service import VehicleService
from boloride.services.quote_service import QuoteService


@dataclass(frozen=True, slots=True)
class BookingOutcome:
	ride: object
	provider_result: RideBookingResult
	accepted_quote: object


class BookingService:
	def __init__(
		self,
		rides: RideRepository,
		provider: RideProvider,
		vehicles: VehicleService,
		quotes: QuoteService,
	) -> None:
		self._rides = rides
		self._provider = provider
		self._vehicles = vehicles
		self._quotes = quotes

	async def book_ride(self, user_id: UUID, context: RideContext) -> BookingOutcome:
		if not context.identity_verified or context.verified_customer_id != user_id:
			raise DomainValidationError("verified customer identity is required before booking")
		if context.pickup is None:
			raise DomainValidationError("pickup is required before booking")
		if context.destination is None:
			raise DomainValidationError("destination is required before booking")
		if context.ride_time is None:
			raise DomainValidationError("ride time is required before booking")
		if context.ride_time.tzinfo is None:
			raise DomainValidationError("ride time must be timezone-aware")
		if context.clarification_required:
			raise DomainValidationError("location clarification is required")
		if context.booking_id is not None:
			raise DomainValidationError("ride has already been booked")
		if context.selected_vehicle_type_code is None:
			raise DomainValidationError("vehicle type must be selected before booking")
		vehicle = await self._vehicles.require_eligible_vehicle_type(
			context.selected_vehicle_type_code,
			context.passenger_count,
		)
		accepted_quote = await self._quotes.require_bookable_quote(context)

		request_id = uuid4()
		provider_result = await self._provider.create_booking(
			RideBookingRequest(
				request_id=request_id,
				pickup=context.pickup,
				destination=context.destination,
				requested_ride_at=context.ride_time,
				passenger_count=context.passenger_count,
				vehicle_type_code=vehicle.code,
			)
		)
		booked_ride = await self._rides.create_booked(
			request_id,
			user_id,
			context.pickup,
			context.destination,
			context.ride_time,
			provider=provider_result.provider,
			provider_booking_id=provider_result.provider_booking_id,
			accepted_quote=accepted_quote,
		)
		context.booking_id = booked_ride.id
		context.booking_confirmed = True
		return BookingOutcome(booked_ride, provider_result, accepted_quote)
