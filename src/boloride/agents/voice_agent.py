import logging
from datetime import datetime
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from livekit.agents import Agent, function_tool
from sqlalchemy.ext.asyncio import AsyncSession

from boloride.agents.context import RideContext
from boloride.agents.instructions import build_agent_instructions
from boloride.domain.exceptions import DomainValidationError, LocationProviderError
from boloride.domain.models.location import ResolvedLocation
from boloride.domain.models.location import LocationResolutionStatus
from boloride.domain.models.scheduling import TimeResolutionStatus
from boloride.domain.models.persona import AgentPersona
from boloride.domain.policies import CustomerIdentityState
from boloride.domain.models.booking import BookingResultStatus
from boloride.domain.models.cancellation import CancellationResultStatus
from boloride.domain.models.dispatch import DispatchResultStatus
from boloride.domain.enums import RideStatus
from boloride.integrations.langfuse.tracing import LangfuseTracer
from boloride.repositories.ride_repository import RideRepository
from boloride.services.booking_service import BookingService
from boloride.services.location_service import LocationService
from boloride.services.quote_service import QuoteService
from boloride.services.offer_service import OfferService
from boloride.services.ride_service import RideService
from boloride.services.dispatch_service import DispatchService
from boloride.services.saved_place_service import SavedPlaceService
from boloride.services.time_resolution_service import TimeResolutionService
from boloride.services.user_service import UserService

logger = logging.getLogger(__name__)


class BoloRideAgent(Agent):
    """LiveKit orchestration layer; business rules remain in services."""

    def __init__(
        self,
        *,
        base_prompt: str,
        context: RideContext,
        user_id: UUID | None,
        database_session: AsyncSession,
        locations: LocationService,
        saved_places: SavedPlaceService,
        rides: RideRepository,
        ride_service: RideService,
        dispatch: DispatchService,
        booking: BookingService,
        quotes: QuoteService,
        offers: OfferService,
        tracer: LangfuseTracer,
        default_city: str | None,
        default_state: str | None,
        default_country: str,
        timezone: str,
        time_resolution: TimeResolutionService | None = None,
        user_service: UserService | None = None,
        detected_phone: str | None = None,
        persona: AgentPersona | None = None,
    ) -> None:
        self.ride_context = context
        self._user_id = user_id
        self._database_session = database_session
        self._locations = locations
        self._saved_places = saved_places
        self._rides = rides
        self._ride_service = ride_service
        self._dispatch = dispatch
        self._booking = booking
        self._quotes = quotes
        self._offers = offers
        self._tracer = tracer
        self._default_city = default_city
        self._default_state = default_state
        self._default_country = default_country
        self._timezone = ZoneInfo(timezone)
        self._time_resolution = time_resolution or TimeResolutionService(
            lambda: datetime.now(self._timezone), timezone
        )
        self._user_service = user_service
        self._detected_phone = detected_phone
        self._persona = persona
        super().__init__(instructions=build_agent_instructions(base_prompt, context, persona))

    def _verified_user(self) -> UUID | None:
        if not self.ride_context.identity_verified:
            return None
        return self.ride_context.verified_customer_id

    @function_tool
    async def get_identity_requirements(self) -> str:
        """Describe the backend-selected identity branch without exposing customer data."""
        state = self.ride_context.identity_state
        if state is CustomerIdentityState.PHONE_UNAVAILABLE:
            return "Caller phone metadata is unavailable, so customer identification cannot continue."
        if state is CustomerIdentityState.IDENTITY_UNAVAILABLE:
            return "Customer identification is temporarily unavailable. Please try again."
        if state is CustomerIdentityState.NEW_CUSTOMER_ONBOARDING_REQUIRED:
            return "Collect the caller's name and age for first-time onboarding."
        if state in {
            CustomerIdentityState.RETURNING_CUSTOMER_VERIFICATION_REQUIRED,
            CustomerIdentityState.NAME_MISMATCH,
        }:
            return "Collect the caller's name for returning-customer verification. Do not ask for age."
        if self.ride_context.identity_verified:
            return "Customer identity is ready. Do not request identity details again."
        return "Customer identification is temporarily unavailable. Please try again."

    @function_tool
    async def record_identity_details(self, name: str | None = None, age: int | None = None) -> str:
        """Record or correct pending identity details without creating a customer."""
        if self.ride_context.identity_verified:
            return "Customer identity is already established."
        if self.ride_context.identity_state is CustomerIdentityState.PHONE_UNAVAILABLE:
            return "Caller identification cannot continue without phone metadata."
        if self.ride_context.identity_state is CustomerIdentityState.IDENTITY_UNAVAILABLE:
            return "Customer identification is temporarily unavailable."
        self.ride_context.update_identity_details(name=name, age=age)
        return "Pending identity details updated. Submit them for deterministic verification."

    @function_tool
    async def submit_customer_identity(self) -> str:
        """Onboard or verify using UserService; the LLM never decides identity matches."""
        if self.ride_context.identity_verified:
            return "Customer identity is already established."
        if self._user_service is None:
            return "Customer identification is temporarily unavailable."
        state = self.ride_context.identity_state
        try:
            if state is CustomerIdentityState.NEW_CUSTOMER_ONBOARDING_REQUIRED:
                if not self.ride_context.pending_customer_name or self.ride_context.pending_customer_age is None:
                    return "Both name and age are required for first-time onboarding."
                result = await self._user_service.onboard_customer(
                    self._detected_phone,
                    self.ride_context.pending_customer_name,
                    self.ride_context.pending_customer_age,
                )
            elif state in {
                CustomerIdentityState.RETURNING_CUSTOMER_VERIFICATION_REQUIRED,
                CustomerIdentityState.NAME_MISMATCH,
            }:
                if not self.ride_context.pending_customer_name:
                    return "Name is required for returning-customer verification."
                result = await self._user_service.resolve_returning_customer(
                    self._detected_phone, self.ride_context.pending_customer_name
                )
            else:
                return "Customer identification cannot proceed in the current state."
        except DomainValidationError as exc:
            return f"Identity details need correction: {exc}."
        except Exception:
            await self._database_session.rollback()
            logger.exception("customer_identity_failed", extra={"event": "customer_identity_failed", "session_id": self.ride_context.session_id})
            return "Customer identification is temporarily unavailable. Please try again."
        self.ride_context.identity_state = result.state
        if not result.verified or result.customer_id is None:
            logger.info("customer_verification_failed", extra={"event": "customer_verification_failed", "session_id": self.ride_context.session_id, "identity_result": result.state.value})
            return "The provided name did not match. Please confirm the name and try again."
        if result.state is CustomerIdentityState.ONBOARDED_NEW_CUSTOMER:
            try:
                await self._database_session.commit()
            except Exception:
                await self._database_session.rollback()
                logger.exception("customer_identity_failed", extra={"event": "customer_identity_failed", "session_id": self.ride_context.session_id})
                return "Customer identification is temporarily unavailable. Please try again."
        self.ride_context.establish_identity(result.state, result.customer_id)
        self._user_id = result.customer_id
        completed_event = "customer_onboarding_completed" if result.state is CustomerIdentityState.ONBOARDED_NEW_CUSTOMER else "customer_verification_completed"
        logger.info(completed_event, extra={"event": completed_event, "session_id": self.ride_context.session_id})
        logger.info("customer_identity_ready", extra={"event": "customer_identity_ready", "session_id": self.ride_context.session_id, "identity_result": result.state.value})
        return "Customer identity verified. Ride services are now available."

    def _trace_metadata(self, tool_name: str) -> dict[str, object]:
        return {"session_id": self.ride_context.session_id, "tool_name": tool_name}

    def _state_summary(self) -> str:
        pickup = self.ride_context.pickup
        destination = self.ride_context.destination
        pickup_name = pickup.display_name or pickup.address if pickup else "missing"
        destination_name = (
            destination.display_name or destination.address if destination else "missing"
        )
        ride_time = (
            self.ride_context.ride_time.isoformat()
            if self.ride_context.ride_time
            else "missing"
        )
        return (
            f"pickup={pickup_name}; destination={destination_name}; "
            f"ride_time={ride_time}; confirmed={self.ride_context.user_confirmed}"
        )

    @function_tool
    async def get_saved_places(self) -> str:
        """List this caller's saved places before searching labels like home or work."""
        user_id = self._verified_user()
        if user_id is None:
            return "Customer identification is required before using saved places."
        with self._tracer.observe(
            "get_saved_places",
            observation_type="tool",
            correlation_id=self.ride_context.session_id,
            metadata=self._trace_metadata("get_saved_places"),
        ):
            places = await self._saved_places.list_places(user_id)
        if not places:
            return "No saved places found."
        return "\n".join(
            f"{place.label}: {place.display_name or place.address}" for place in places
        )

    @function_tool
    async def select_saved_place(
        self, label: str, role: Literal["pickup", "destination"]
    ) -> str:
        """Select a saved place as pickup or destination using its exact label."""
        user_id = self._verified_user()
        if user_id is None:
            return "Customer identification is required before using saved places."
        place = await self._saved_places.get_place(user_id, label)
        if place is None:
            return f"No saved place has label '{label}'."
        location = ResolvedLocation(
            address=place.address,
            display_name=place.display_name,
            latitude=place.latitude,
            longitude=place.longitude,
            provider=place.provider,
            provider_place_id=place.provider_place_id,
        )
        self._set_location(role, location)
        return f"Selected {role}: {location.display_name or location.address}. {self._state_summary()}"

    @function_tool
    async def search_locations(
        self, query: str, role: Literal["pickup", "destination"]
    ) -> str:
        """Search maps and return numbered candidates; never invent a location."""
        user_id = self._verified_user()
        if user_id is None:
            return "Customer identification is required before planning a ride."
        try:
            saved = await self._saved_places.resolve_label(user_id, query)
        except ValueError:
            return "More than one saved place matches that label. Ask which one they mean."
        if saved is not None:
            self._set_location(role, saved)
            logger.info("saved_place_resolved", extra={"event": "saved_place_resolved", "session_id": self.ride_context.session_id, "location_role": role})
            return f"Selected saved {role}: {saved.display_name or saved.address}."
        source = self.ride_context.pickup if role == "destination" else None
        use_source_context = source is not None and _is_destination_shorthand(query)
        try:
            with self._tracer.observe(
                "search_locations",
                observation_type="tool",
                correlation_id=self.ride_context.session_id,
                metadata=self._trace_metadata("search_locations"),
            ):
                result = await self._locations.resolve_query(
                    query,
                    city=source.city if use_source_context else None,
                    state=source.state if use_source_context else None,
                    country=self._default_country,
                    require_city_context=not use_source_context,
                    session_id=self.ride_context.session_id,
                )
        except LocationProviderError as exc:
            return f"Location search failed: {exc}. Ask the caller to clarify or try again."
        if result.status is LocationResolutionStatus.RESOLVED and result.location:
            self._set_location(role, result.location)
            return f"Selected {role}: {result.location.display_name or result.location.address}."
        if result.status is LocationResolutionStatus.PROVIDER_UNAVAILABLE:
            return "Location providers are temporarily unavailable. Please try again."
        if result.status is LocationResolutionStatus.NOT_FOUND:
            return "No matching location was found. Ask for a more specific place."
        if not result.candidates:
            return "Please ask which city this location is in."
        candidates = list(result.candidates)
        self.ride_context.set_location_candidates(candidates, role)
        return "\n".join(
            f"{index}. {candidate.display_name}" + (f", {candidate.city}" if candidate.city else "") + (f", {candidate.state}" if candidate.state else "")
            for index, candidate in enumerate(candidates, start=1)
        )

    @function_tool
    async def select_location_candidate(
        self, candidate_number: int, role: Literal["pickup", "destination"]
    ) -> str:
        """Select one numbered candidate returned by the most recent location search."""
        if self._verified_user() is None:
            return "Customer identification is required before planning a ride."
        candidates = self.ride_context.location_candidates
        if self.ride_context.location_candidate_role not in (None, role):
            return "That candidate list belongs to a different location. Search again."
        if not 1 <= candidate_number <= len(candidates):
            return "Invalid candidate number. Search again or ask the caller to choose."
        location = await self._locations.resolve_candidate(
            candidates[candidate_number - 1]
        )
        self._set_location(role, location)
        self.ride_context.clear_location_candidates()
        return f"Selected {role}: {location.display_name or location.address}. {self._state_summary()}"

    @function_tool
    async def set_ride_time(self, time_phrase: str, correction: bool = False) -> str:
        """Resolve a bounded caller time phrase; never trust an LLM-generated datetime."""
        if self._verified_user() is None:
            return "Customer identification is required before planning a ride."
        result = self._time_resolution.resolve(
            time_phrase, previous=self.ride_context.ride_time, correction=correction
        )
        if result.status is TimeResolutionStatus.CLARIFICATION_REQUIRED:
            return f"Time clarification required: {result.clarification_reason}."
        assert result.scheduled_at is not None
        changed = self.ride_context.ride_time != result.scheduled_at
        self.ride_context.update_ride_time(result.scheduled_at)
        logger.info("time_resolved", extra={"event": "time_resolved", "session_id": self.ride_context.session_id, "resolution_type": result.resolution_type, "correction": correction})
        if correction:
            logger.info("time_correction", extra={"event": "time_correction", "session_id": self.ride_context.session_id})
        if changed:
            logger.info("scheduled_time_changed", extra={"event": "scheduled_time_changed", "session_id": self.ride_context.session_id})
            logger.info("downstream_quote_invalidated", extra={"event": "downstream_quote_invalidated", "session_id": self.ride_context.session_id, "reason": "scheduled_time_changed"})
        return f"Ride time updated to {result.scheduled_at.isoformat()}. Confirmation is now required. {self._state_summary()}"

    @function_tool
    async def get_previous_rides(self, limit: int = 3) -> str:
        """List a small number of this caller's latest rides."""
        user_id = self._verified_user()
        if user_id is None:
            return "Customer identification is required before accessing rides."
        rides = await self._rides.list_for_customer(
            user_id, limit=max(1, min(limit, 5))
        )
        if not rides:
            return "No previous rides found."
        return "\n".join(
            f"{ride.requested_ride_at.isoformat()}: "
            f"{ride.pickup_display_name or ride.pickup_address} to "
            f"{ride.destination_display_name or ride.destination_address} "
            f"({ride.status.value})"
            for ride in rides
        )

    @function_tool
    async def get_ride_status(self, ride_id: str) -> str:
        """Return the current persisted status of one customer-owned ride."""
        user_id = self._verified_user()
        if user_id is None:
            return "Customer identification is required before accessing rides."
        try:
            parsed_id = UUID(ride_id)
        except ValueError:
            return "That ride ID is invalid."
        with self._tracer.observe(
            "ride_status_lookup",
            observation_type="tool",
            correlation_id=self.ride_context.session_id,
            metadata=self._trace_metadata("get_ride_status"),
        ):
            details = await self._ride_service.get_customer_ride_status(
                user_id, parsed_id, self.ride_context
            )
        if details is None:
            return "No matching ride was found for this customer."
        final_cost = (
            f" Final customer cost: {details.currency} {details.final_customer_cost:.0f}."
            if details.final_customer_cost is not None
            else ""
        )
        assignment = (
            f" Driver: {details.driver_display_name}; vehicle: "
            f"{details.vehicle_display_name} {details.vehicle_registration}."
            if details.driver_display_name else ""
        )
        return (
            f"Ride to {details.destination} at {details.requested_ride_at.isoformat()} "
            f"is {details.status.value}. Vehicle type: {details.vehicle_type_code}. "
            f"Booked estimate: {details.currency} {details.estimated_fare:.0f}."
            f"{final_cost}{assignment}"
        )

    @function_tool
    async def dispatch_booked_ride(self, ride_id: str) -> str:
        """Deterministically assign the nearest eligible demo driver."""
        user_id = self._verified_user()
        if user_id is None:
            return "Customer identification is required before dispatch."
        try:
            parsed_id = UUID(ride_id)
        except ValueError:
            return "That ride ID is invalid."
        with self._tracer.observe(
            "dispatch_ride",
            observation_type="tool",
            correlation_id=self.ride_context.session_id,
            metadata=self._trace_metadata("dispatch_booked_ride"),
        ) as observation:
            result = await self._dispatch.dispatch(user_id, parsed_id)
            observation.update(metadata={"dispatch_result": result.status.value})
        if result.status is DispatchResultStatus.ASSIGNED:
            return "A driver has been assigned to this ride."
        if result.status is DispatchResultStatus.ALREADY_ASSIGNED:
            return "This ride already has an assigned driver."
        if result.status is DispatchResultStatus.NO_DRIVER_AVAILABLE:
            return "No eligible driver is currently available; the booking remains booked."
        return "The ride could not be dispatched in its current state."

    @function_tool
    async def select_ride_for_cancellation(self, ride_id: str) -> str:
        """Select one exact customer-owned ride and request cancellation confirmation."""
        user_id = self._verified_user()
        if user_id is None:
            return "Customer identification is required before cancellation."
        try:
            parsed_id = UUID(ride_id)
        except ValueError:
            return "That ride ID is invalid."
        details = await self._ride_service.get_customer_ride_status(
            user_id, parsed_id, self.ride_context
        )
        if details is None:
            self.ride_context.clear_cancellation()
            return "No matching ride was found for this customer."
        if details.status not in {RideStatus.BOOKED, RideStatus.ASSIGNED}:
            self.ride_context.clear_cancellation()
            return f"That ride is {details.status.value} and cannot be cancelled."
        self.ride_context.select_cancellation_target(parsed_id)
        return (
            f"Selected ride to {details.destination} at "
            f"{details.requested_ride_at.isoformat()} for cancellation. "
            "Ask the customer to explicitly confirm cancellation."
        )

    @function_tool
    async def record_cancellation_confirmation(
        self, ride_id: str, explicitly_confirmed: bool
    ) -> str:
        """Record a yes/no cancellation response for the exact selected ride."""
        if self._verified_user() is None:
            return "Customer identification is required before cancellation."
        try:
            parsed_id = UUID(ride_id)
            self.ride_context.record_cancellation_confirmation(
                parsed_id, explicitly_confirmed
            )
        except (ValueError, DomainValidationError):
            return "Cancellation confirmation did not match the selected ride."
        logger.info(
            "ride_cancellation_confirmation_recorded",
            extra={
                "event": "ride_cancellation_confirmation_recorded",
                "session_id": self.ride_context.session_id,
                "confirmed": explicitly_confirmed,
            },
        )
        if explicitly_confirmed:
            return "Cancellation confirmed for the selected ride."
        return "Cancellation declined. The ride was not changed."

    @function_tool
    async def cancel_selected_ride(self, ride_id: str) -> str:
        """Cancel the exact selected ride after explicit cancellation confirmation."""
        user_id = self._verified_user()
        if user_id is None:
            return "Customer identification is required before cancellation."
        try:
            parsed_id = UUID(ride_id)
        except ValueError:
            return "That ride ID is invalid."
        with self._tracer.observe(
            "cancel_ride",
            observation_type="tool",
            correlation_id=self.ride_context.session_id,
            metadata=self._trace_metadata("cancel_selected_ride"),
        ) as observation:
            result = await self._ride_service.cancel_customer_ride(
                user_id, parsed_id, self.ride_context
            )
            observation.update(metadata={"cancellation_result": result.status.value})
        if result.status is CancellationResultStatus.CONFIRMATION_REQUIRED:
            return "Explicit cancellation confirmation is required for this ride."
        if result.status is CancellationResultStatus.NOT_FOUND:
            return "No matching ride was found for this customer."
        if result.status is CancellationResultStatus.NOT_CANCELLABLE:
            state = result.ride.status.value if result.ride else "not cancellable"
            return f"The ride is currently {state} and cannot be cancelled."
        if result.status is CancellationResultStatus.RACE_LOST:
            state = result.ride.status.value if result.ride else "unavailable"
            return f"The ride is now {state}, so cancellation was not applied."
        if result.status is CancellationResultStatus.IDEMPOTENT_SUCCESS:
            return "This ride was already cancelled. Final customer cost is INR 0."
        return "Ride cancelled successfully. Final customer cost is INR 0."

    @function_tool
    async def record_booking_confirmation(self, explicitly_confirmed: bool) -> str:
        """Record the caller's explicit yes/no response to the final ride summary."""
        if self._verified_user() is None:
            return "Customer identification is required before booking."
        if explicitly_confirmed:
            if self.ride_context.current_quote is None:
                return "No current fare quote is available to confirm."
            self._quotes.confirm_quote(
                self.ride_context, self.ride_context.current_quote.id
            )
            return "Explicit confirmation recorded. The booking may now be created."
        self.ride_context.confirmed_quote_id = None
        self.ride_context.user_confirmed = False
        return "Confirmation declined. Do not create the booking."

    @function_tool
    async def get_available_offers(self) -> str:
        """Return offers the backend currently considers eligible."""
        user_id = self._verified_user()
        if user_id is None:
            return "Customer identification is required before viewing offers."
        currency = self.ride_context.current_quote.pricing.currency if self.ride_context.current_quote else "INR"
        with self._tracer.observe("offer_eligibility", observation_type="tool", correlation_id=self.ride_context.session_id, metadata=self._trace_metadata("get_available_offers")) as observation:
            offers = await self._offers.get_eligible_offers(user_id, currency)
            observation.update(metadata={"eligible_offer_count": len(offers), "offer_codes": [offer.code for offer in offers]})
        if not offers:
            return "No eligible offers are currently available."
        return "\n".join(f"{offer.code}: {offer.display_name}" for offer in offers)

    @function_tool
    async def apply_offer(self, offer_code: str) -> str:
        """Apply one backend-validated offer to create a fresh estimate."""
        user_id = self._verified_user()
        if user_id is None:
            return "Customer identification is required before applying offers."
        try:
            with self._tracer.observe("offer_application", observation_type="tool", correlation_id=self.ride_context.session_id, metadata={**self._trace_metadata("apply_offer"), "offer_code": offer_code.strip().upper()}):
                quote = await self._offers.apply_offer(user_id, self.ride_context, offer_code)
        except DomainValidationError as exc:
            return f"Offer could not be applied: {exc}."
        return f"Offer applied. New estimated fare: {quote.pricing.currency} {quote.pricing.estimated_total:.0f}. Fresh confirmation is required."

    @function_tool
    async def remove_applied_offer(self) -> str:
        """Remove the current offer by producing a fresh non-discounted estimate."""
        if self._verified_user() is None:
            return "Customer identification is required before applying offers."
        try:
            quote = await self._offers.remove_offer(self.ride_context)
        except DomainValidationError as exc:
            return f"Offer could not be removed: {exc}."
        return f"Offer removed. New estimated fare: {quote.pricing.currency} {quote.pricing.estimated_total:.0f}. Fresh confirmation is required."

    @function_tool
    async def create_fare_quote(self) -> str:
        """Create a backend-computed estimated fare for the current ride request."""
        if self._verified_user() is None:
            return "Customer identification is required before creating a fare quote."
        try:
            quote = await self._quotes.create_quote(self.ride_context)
        except DomainValidationError as exc:
            return f"Fare quote unavailable: {exc}."
        pricing = quote.pricing
        toll_note = (
            " Tolls may be excluded and the final ride fare may vary."
            if pricing.toll_status.value in {"may_apply", "unknown"}
            else ""
        )
        return (
            f"Estimated fare: {pricing.currency} {pricing.estimated_total:.0f}. "
            f"This estimate is valid for 20 minutes and requires explicit confirmation."
            f"{toll_note}"
        )

    @function_tool
    async def create_booking(self) -> str:
        """Create the mock booking; BookingService independently requires prior confirmation."""
        user_id = self._verified_user()
        if user_id is None:
            return "Booking rejected: customer identification is required."
        try:
            with self._tracer.observe(
                "create_booking",
                observation_type="tool",
                correlation_id=self.ride_context.session_id,
                metadata=self._trace_metadata("create_booking"),
            ) as observation:
                outcome = await self._booking.book_ride(
                    user_id, self.ride_context
                )
                observation.update(
                    metadata={
                        "success": outcome.status
                        in {BookingResultStatus.SUCCESS, BookingResultStatus.IDEMPOTENT_SUCCESS},
                        "booking_result": outcome.status.value,
                        "provider": getattr(outcome.provider_result, "provider", None),
                    }
                )
        except DomainValidationError as exc:
            await self._database_session.rollback()
            self.ride_context.user_confirmed = False
            return f"Booking rejected: {exc}."
        except Exception as exc:
            await self._database_session.rollback()
            self.ride_context.user_confirmed = False
            logger.warning(
                "booking_provider_failed",
                extra={
                    "event": "booking_provider_failed",
                    "session_id": self.ride_context.session_id,
                    "error_type": type(exc).__name__,
                },
            )
            return "We're still confirming whether the booking went through."
        if outcome.status in {
            BookingResultStatus.OUTCOME_UNKNOWN,
            BookingResultStatus.IN_PROGRESS,
        }:
            return "We're still confirming whether the booking went through."
        if outcome.status is BookingResultStatus.REQUOTE_REQUIRED:
            self.ride_context.user_confirmed = False
            return "The previous booking authorization can no longer be retried safely. A new fare estimate and confirmation are required."
        if outcome.status is BookingResultStatus.DEFINITIVE_FAILURE:
            self.ride_context.user_confirmed = False
            return "The booking provider confirmed that no ride was booked."
        result = outcome.provider_result
        if result is None or outcome.accepted_quote is None:
            return "We're still confirming whether the booking went through."
        return (
            f"Booking successful. ID {result.provider_booking_id}. "
            f"Driver {result.driver_name}; vehicle {result.vehicle_description}; "
            f"accepted estimated fare {outcome.accepted_quote.pricing.currency} "
            f"{outcome.accepted_quote.pricing.estimated_total:.0f}."
        )

    def _set_location(
        self, role: Literal["pickup", "destination"], location: ResolvedLocation
    ) -> None:
        previous = self.ride_context.pickup if role == "pickup" else self.ride_context.destination
        if role == "pickup":
            self.ride_context.update_pickup(location)
        else:
            self.ride_context.update_destination(location)
        self.ride_context.clear_location_candidates()
        if previous is not None and previous != location:
            logger.info("location_correction", extra={"event": "location_correction", "session_id": self.ride_context.session_id, "location_role": role})
            logger.info("downstream_quote_invalidated", extra={"event": "downstream_quote_invalidated", "session_id": self.ride_context.session_id, "reason": f"{role}_changed"})


def _is_destination_shorthand(query: str) -> bool:
    words = query.casefold().split()
    generic = {"station", "airport", "railway", "bus", "hospital", "mall"}
    return len(words) <= 3 and bool(generic.intersection(words))
