from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from boloride.domain.models.location import LocationCandidate, ResolvedLocation, RouteResult
from boloride.domain.models.quote import Quote
from boloride.domain.models.scheduling import RideTimingIntent
from boloride.domain.models.vehicle import PassengerCountSource
from boloride.domain.models.pickup_instruction import normalize_pickup_instruction
from boloride.domain.exceptions import DomainValidationError
from boloride.domain.policies import CustomerIdentityState


@dataclass(slots=True)
class RideContext:
	session_id: str
	caller_id: UUID | None
	identity_state: CustomerIdentityState | None = None
	verified_customer_id: UUID | None = None
	pending_customer_name: str | None = None
	pending_customer_age: int | None = None
	intent: str | None = None
	pickup: ResolvedLocation | None = None
	destination: ResolvedLocation | None = None
	route: RouteResult | None = None
	ride_time: datetime | None = None
	timing_intent: RideTimingIntent | None = None
	pickup_instructions: str | None = None
	pickup_instruction_handled: bool = False
	passenger_count: int = 1
	passenger_count_source: PassengerCountSource = PassengerCountSource.DEFAULT
	selected_vehicle_type_code: str | None = None
	selected_offer: str | None = None
	user_confirmed: bool = False
	booking_id: UUID | None = None
	booking_confirmed: bool = False
	current_quote: Quote | None = None
	confirmed_quote_id: UUID | None = None
	cancellation_target_ride_id: UUID | None = None
	cancellation_confirmed_ride_id: UUID | None = None
	cancellation_target_ride_ids: tuple[UUID, ...] = ()
	cancellation_confirmed_ride_ids: tuple[UUID, ...] = ()
	session_active: bool = True
	clarification_required: bool = False
	location_candidates: tuple[LocationCandidate, ...] = ()
	location_candidate_role: str | None = None
	pending_pickup_candidate: LocationCandidate | None = None
	pending_destination_candidate: LocationCandidate | None = None
	pickup_geography_city: str | None = None
	pickup_geography_state: str | None = None
	destination_geography_city: str | None = None
	destination_geography_state: str | None = None
	pickup_location_operation: int = 0
	destination_location_operation: int = 0
	pickup_clarification_count: int = 0
	destination_clarification_count: int = 0
	ride_reference_candidates: tuple[UUID, ...] = ()
	ride_reference_purpose: str | None = None
	guardrail_block_count: int = 0

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

	def update_identity_details(self, *, name: str | None = None, age: int | None = None) -> None:
		if name is not None:
			self.pending_customer_name = " ".join(name.split())
		if age is not None:
			self.pending_customer_age = age

	def establish_identity(self, state: CustomerIdentityState, customer_id: UUID) -> None:
		if state not in {
			CustomerIdentityState.ONBOARDED_NEW_CUSTOMER,
			CustomerIdentityState.VERIFIED_RETURNING_CUSTOMER,
		}:
			raise DomainValidationError("only a verified identity can establish a customer")
		self.identity_state = state
		self.verified_customer_id = customer_id
		self.caller_id = customer_id
		self.pending_customer_name = None
		self.pending_customer_age = None

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
		self.clear_cancellation()

	def select_cancellation_target(self, ride_id: UUID) -> None:
		if self.cancellation_target_ride_id != ride_id:
			self.cancellation_confirmed_ride_id = None
			self.cancellation_target_ride_id = ride_id
			self.cancellation_target_ride_ids = (ride_id,)
			self.cancellation_confirmed_ride_ids = ()

	def select_cancellation_targets(self, ride_ids: tuple[UUID, ...]) -> None:
		if not ride_ids:
			raise DomainValidationError("at least one cancellation target is required")
		if len(set(ride_ids)) != len(ride_ids):
			raise DomainValidationError("cancellation targets must be unique")
		self.cancellation_target_ride_ids = ride_ids
		self.cancellation_confirmed_ride_ids = ()
		self.cancellation_target_ride_id = ride_ids[0] if len(ride_ids) == 1 else None
		self.cancellation_confirmed_ride_id = None

	def record_cancellation_confirmation(
		self, ride_id: UUID, explicitly_confirmed: bool
	) -> None:
		if self.cancellation_target_ride_id != ride_id:
			raise DomainValidationError("cancellation confirmation must match the selected ride")
		if explicitly_confirmed:
			self.cancellation_confirmed_ride_id = ride_id
			self.cancellation_confirmed_ride_ids = (ride_id,)
		else:
			self.clear_cancellation()

	def record_cancellation_set_confirmation(
		self, explicitly_confirmed: bool
	) -> None:
		if not self.cancellation_target_ride_ids:
			raise DomainValidationError("cancellation targets are required")
		if explicitly_confirmed:
			self.cancellation_confirmed_ride_ids = self.cancellation_target_ride_ids
		else:
			self.clear_cancellation()

	def clear_cancellation(self) -> None:
		self.cancellation_target_ride_id = None
		self.cancellation_confirmed_ride_id = None
		self.cancellation_target_ride_ids = ()
		self.cancellation_confirmed_ride_ids = ()

	def cancellation_is_confirmed_for(self, ride_id: UUID) -> bool:
		return (
			self.session_active
			and self.cancellation_target_ride_id == ride_id
			and self.cancellation_confirmed_ride_id == ride_id
		)

	def cancellation_set_is_confirmed_for(self, ride_ids: tuple[UUID, ...]) -> bool:
		return (
			self.session_active
			and self.cancellation_target_ride_ids == ride_ids
			and self.cancellation_confirmed_ride_ids == ride_ids
		)

	def update_pickup(self, pickup: ResolvedLocation | None) -> None:
		if self.pickup != pickup:
			self.pickup = pickup
			self.route = None
			self._invalidate_quote()
		if pickup is not None:
			if (
				pickup.city
				and self.pickup_geography_city
				and pickup.city.casefold() != self.pickup_geography_city.casefold()
			):
				self.pickup_geography_state = None
			self.remember_endpoint_geography("pickup", pickup.city, pickup.state)
			self.pickup_clarification_count = 0

	def update_destination(self, destination: ResolvedLocation | None) -> None:
		if self.destination != destination:
			self.destination = destination
			self.route = None
			self._invalidate_quote()
		if destination is not None:
			if (
				destination.city
				and self.destination_geography_city
				and destination.city.casefold()
				!= self.destination_geography_city.casefold()
			):
				self.destination_geography_state = None
			self.remember_endpoint_geography(
				"destination", destination.city, destination.state
			)
			self.destination_clarification_count = 0

	def set_route(self, route: RouteResult) -> None:
		self.route = route

	def update_ride_time(self, ride_time: datetime | None) -> None:
		if self.ride_time != ride_time:
			self.ride_time = ride_time
			self._invalidate_quote()

	def update_ride_timing(
		self, intent: RideTimingIntent, ride_time: datetime
	) -> None:
		if ride_time.tzinfo is None:
			raise DomainValidationError("ride time must be timezone-aware")
		if self.timing_intent != intent or self.ride_time != ride_time:
			self.timing_intent = intent
			self.ride_time = ride_time
			self._invalidate_quote()

	def set_incomplete_timing_intent(self, intent: RideTimingIntent) -> None:
		if self.timing_intent != intent or self.ride_time is not None:
			self.timing_intent = intent
			self.ride_time = None
			self._invalidate_quote()

	def set_pickup_instructions(self, instructions: str) -> None:
		self.pickup_instructions = normalize_pickup_instruction(instructions)
		self.pickup_instruction_handled = True

	def decline_pickup_instructions(self) -> None:
		self.pickup_instructions = None
		self.pickup_instruction_handled = True

	def remove_pickup_instructions(self) -> None:
		self.pickup_instructions = None
		self.pickup_instruction_handled = True

	def record_guardrail_block(self) -> int:
		self.guardrail_block_count += 1
		return self.guardrail_block_count

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

	def set_location_candidates(self, candidates: list[LocationCandidate], role: str | None = None) -> None:
		self.location_candidates = tuple(candidates)
		self.location_candidate_role = role
		self._refresh_location_clarification()

	def clear_location_candidates(self) -> None:
		self.location_candidates = ()
		self.location_candidate_role = None
		self._refresh_location_clarification()

	def set_likely_location_candidate(
		self, role: str, candidate: LocationCandidate
	) -> None:
		if role == "pickup":
			self.pending_pickup_candidate = candidate
		elif role == "destination":
			self.pending_destination_candidate = candidate
		else:
			raise DomainValidationError("location role must be pickup or destination")
		self._refresh_location_clarification()

	def pending_location_candidate(self, role: str) -> LocationCandidate | None:
		if role == "pickup":
			return self.pending_pickup_candidate
		if role == "destination":
			return self.pending_destination_candidate
		raise DomainValidationError("location role must be pickup or destination")

	def clear_pending_location_candidate(self, role: str) -> None:
		if role == "pickup":
			self.pending_pickup_candidate = None
		elif role == "destination":
			self.pending_destination_candidate = None
		else:
			raise DomainValidationError("location role must be pickup or destination")
		self._refresh_location_clarification()

	def _refresh_location_clarification(self) -> None:
		self.clarification_required = bool(
			self.location_candidates
			or self.pending_pickup_candidate
			or self.pending_destination_candidate
		)

	def remember_endpoint_geography(
		self, role: str, city: str | None, state: str | None
	) -> None:
		if role not in {"pickup", "destination"}:
			raise DomainValidationError("location role must be pickup or destination")
		prefix = "pickup" if role == "pickup" else "destination"
		if city is not None:
			setattr(self, f"{prefix}_geography_city", " ".join(city.split()) or None)
		if state is not None:
			setattr(self, f"{prefix}_geography_state", " ".join(state.split()) or None)

	def endpoint_geography(self, role: str) -> tuple[str | None, str | None]:
		if role == "pickup":
			return self.pickup_geography_city, self.pickup_geography_state
		if role == "destination":
			return self.destination_geography_city, self.destination_geography_state
		raise DomainValidationError("location role must be pickup or destination")

	def begin_location_operation(self, role: str) -> int:
		field_name = (
			"pickup_location_operation"
			if role == "pickup"
			else "destination_location_operation"
		)
		if role not in {"pickup", "destination"}:
			raise DomainValidationError("location role must be pickup or destination")
		value = getattr(self, field_name) + 1
		setattr(self, field_name, value)
		return value

	def location_operation_is_current(self, role: str, value: int) -> bool:
		current = (
			self.pickup_location_operation
			if role == "pickup"
			else self.destination_location_operation
		)
		if role not in {"pickup", "destination"}:
			raise DomainValidationError("location role must be pickup or destination")
		return current == value

	def record_location_clarification(self, role: str) -> int:
		field_name = (
			"pickup_clarification_count"
			if role == "pickup"
			else "destination_clarification_count"
		)
		if role not in {"pickup", "destination"}:
			raise DomainValidationError("location role must be pickup or destination")
		value = getattr(self, field_name) + 1
		setattr(self, field_name, value)
		return value

	@property
	def booking_phase(self) -> str:
		"""Derive conversational guidance without constraining user intent."""
		if not self.identity_verified:
			return "identity"
		if self.pickup is None and self.pickup_geography_city is None:
			return "geography"
		if self.pickup is None or self.destination is None:
			return "locations"
		if self.ride_time is None:
			return "time"
		if self.selected_vehicle_type_code is None:
			return "vehicle"
		if self.current_quote is None:
			return "quote"
		if not self.confirmation_received:
			return "confirmation"
		if self.booking_id is None:
			return "confirmation"
		return "booked"

	def set_ride_reference_candidates(
		self, ride_ids: tuple[UUID, ...], purpose: str
	) -> None:
		self.ride_reference_candidates = ride_ids
		self.ride_reference_purpose = purpose

	def clear_ride_reference_candidates(self) -> None:
		self.ride_reference_candidates = ()
		self.ride_reference_purpose = None
