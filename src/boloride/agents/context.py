from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from boloride.domain.models.location import LocationCandidate, ResolvedLocation
from boloride.domain.models.quote import Quote
from boloride.domain.models.vehicle import PassengerCountSource
from boloride.domain.exceptions import DomainValidationError
from boloride.domain.policies import CustomerIdentityState


@dataclass(slots=True)
class RideContext:
	session_id: str
	caller_id: UUID | None
	identity_state: CustomerIdentityState | None = None
	verified_customer_id: UUID | None = None
	intent: str | None = None
	pickup: ResolvedLocation | None = None
	destination: ResolvedLocation | None = None
	ride_time: datetime | None = None
	passenger_count: int = 1
	passenger_count_source: PassengerCountSource = PassengerCountSource.DEFAULT
	selected_vehicle_type_code: str | None = None
	selected_offer: str | None = None
	user_confirmed: bool = False
	booking_id: UUID | None = None
	booking_confirmed: bool = False
	current_quote: Quote | None = None
	confirmed_quote_id: UUID | None = None
	session_active: bool = True
	clarification_required: bool = False
	location_candidates: tuple[LocationCandidate, ...] = ()

	@property
	def identity_verified(self) -> bool:
		return (
			self.identity_state
			in {
				CustomerIdentityState.ONBOARDED_NEW_CUSTOMER,
				CustomerIdentityState.VERIFIED_RETURNING_CUSTOMER,
			}
			and self.verified_customer_id is not None
		)

	@property
	def confirmation_received(self) -> bool:
		return (
			self.user_confirmed
			and self.current_quote is not None
			and self.confirmed_quote_id == self.current_quote.id
		)

	def _invalidate_quote(self) -> None:
		self.current_quote = None
		self.confirmed_quote_id = None
		self.user_confirmed = False
		self.booking_confirmed = False

	def set_quote(self, quote: Quote) -> None:
		if not self.session_active or quote.session_id != self.session_id:
			raise DomainValidationError("quote must belong to the active session")
		self.current_quote = quote
		self.confirmed_quote_id = None
		self.user_confirmed = False

	def confirm_quote(self, quote_id: UUID) -> None:
		if not self.session_active or self.current_quote is None or self.current_quote.id != quote_id:
			raise DomainValidationError("only the current session quote can be confirmed")
		self.confirmed_quote_id = quote_id
		self.user_confirmed = True

	def disconnect(self) -> None:
		self.session_active = False
		self._invalidate_quote()

	def update_pickup(self, pickup: ResolvedLocation | None) -> None:
		if self.pickup != pickup:
			self.pickup = pickup
			self._invalidate_quote()

	def update_destination(self, destination: ResolvedLocation | None) -> None:
		if self.destination != destination:
			self.destination = destination
			self._invalidate_quote()

	def update_ride_time(self, ride_time: datetime | None) -> None:
		if self.ride_time != ride_time:
			self.ride_time = ride_time
			self._invalidate_quote()

	def update_passenger_count(
		self,
		passenger_count: int,
		source: PassengerCountSource,
		*,
		selected_vehicle_is_eligible: bool,
	) -> None:
		if self.passenger_count != passenger_count:
			self.passenger_count = passenger_count
			self._invalidate_quote()
		self.passenger_count_source = source
		if not selected_vehicle_is_eligible:
			self.selected_vehicle_type_code = None
			self._invalidate_quote()

	def update_selected_vehicle_type(self, code: str | None) -> None:
		if self.selected_vehicle_type_code != code:
			self.selected_vehicle_type_code = code
			self._invalidate_quote()

	def set_location_candidates(self, candidates: list[LocationCandidate]) -> None:
		self.location_candidates = tuple(candidates)
		self.clarification_required = len(candidates) != 1

	def clear_location_candidates(self) -> None:
		self.location_candidates = ()
		self.clarification_required = False
