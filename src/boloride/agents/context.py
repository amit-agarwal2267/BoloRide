from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from boloride.domain.models.location import LocationCandidate, ResolvedLocation


@dataclass(slots=True)
class RideContext:
	session_id: str
	caller_id: UUID
	intent: str | None = None
	pickup: ResolvedLocation | None = None
	destination: ResolvedLocation | None = None
	ride_time: datetime | None = None
	ride_type: str = "standard"
	selected_offer: str | None = None
	user_confirmed: bool = False
	booking_id: UUID | None = None
	booking_confirmed: bool = False
	clarification_required: bool = False
	location_candidates: tuple[LocationCandidate, ...] = ()

	@property
	def confirmation_received(self) -> bool:
		return self.user_confirmed or self.booking_confirmed

	def update_pickup(self, pickup: ResolvedLocation | None) -> None:
		if self.pickup != pickup:
			self.pickup = pickup
			self.user_confirmed = False
			self.booking_confirmed = False

	def update_destination(self, destination: ResolvedLocation | None) -> None:
		if self.destination != destination:
			self.destination = destination
			self.user_confirmed = False
			self.booking_confirmed = False

	def update_ride_time(self, ride_time: datetime | None) -> None:
		if self.ride_time != ride_time:
			self.ride_time = ride_time
			self.user_confirmed = False
			self.booking_confirmed = False

	def set_location_candidates(self, candidates: list[LocationCandidate]) -> None:
		self.location_candidates = tuple(candidates)
		self.clarification_required = len(candidates) != 1

	def clear_location_candidates(self) -> None:
		self.location_candidates = ()
		self.clarification_required = False
