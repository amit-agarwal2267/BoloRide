import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from time import perf_counter
from typing import AsyncIterator, Awaitable, Callable, Literal, TypeVar
from uuid import UUID
from zoneinfo import ZoneInfo

from livekit.agents import Agent, RunContext, function_tool
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.ext.asyncio import AsyncSession

from boloride.agents.context import RideContext
from boloride.agents.instructions import build_agent_instructions
from boloride.domain.exceptions import (
    DomainValidationError,
    LocationProviderError,
    RouteSanityError,
)
from boloride.domain.models.location import (
    LocationCandidate,
    LocationContextSource,
    LocationResolutionStatus,
    ResolvedLocation,
    customer_location_label,
)
from boloride.domain.models.scheduling import TimeResolutionStatus
from boloride.domain.models.persona import AgentPersona
from boloride.domain.models.vehicle import PassengerCountSource
from boloride.domain.policies import CustomerIdentityState
from boloride.domain.models.booking import BookingResultStatus
from boloride.domain.models.cancellation import (
    CancellationResultStatus,
    RideReferenceResolutionStatus,
    RideStatusDetails,
)
from boloride.domain.models.dispatch import DispatchResultStatus
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
from boloride.services.vehicle_service import VehicleService

logger = logging.getLogger(__name__)
_T = TypeVar("_T")
SLOW_OPERATION_ACK_THRESHOLD_SECONDS = 0.9


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
        vehicles: VehicleService | None = None,
        tracer: LangfuseTracer,
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
        self._vehicles = vehicles
        self._tracer = tracer
        self._default_country = default_country
        self._timezone = ZoneInfo(timezone)
        self._time_resolution = time_resolution or TimeResolutionService(
            lambda: datetime.now(self._timezone), timezone
        )
        self._user_service = user_service
        self._detected_phone = detected_phone
        self._persona = persona
        self._database_operation_lock = asyncio.Lock()
        self._state_operation_lock = asyncio.Lock()
        super().__init__(instructions=build_agent_instructions(base_prompt, context, persona))

    @asynccontextmanager
    async def _slow_operation(
        self, run_context: RunContext | None, operation: str
    ) -> AsyncIterator[None]:
        """Use LiveKit's interruptible filler scheduler for genuinely slow tools."""
        acknowledgement_started = False

        def acknowledgement(_: int) -> str | None:
            nonlocal acknowledgement_started
            if self._persona is None:
                return None
            acknowledgement_started = True
            logger.info(
                "slow_operation_ack_started",
                extra={
                    "event": "slow_operation_ack_started",
                    "session_id": self.ride_context.session_id,
                    "operation": operation,
                    "persona_id": self._persona.persona_id,
                },
            )
            return self._persona.progress_acknowledgement(operation)

        if run_context is None:
            yield
            return
        try:
            async with run_context.with_filler(
                acknowledgement,
                delay=SLOW_OPERATION_ACK_THRESHOLD_SECONDS,
                max_steps=1,
            ):
                yield
        finally:
            if not acknowledgement_started:
                logger.info(
                    "slow_operation_ack_skipped",
                    extra={
                        "event": "slow_operation_ack_skipped",
                        "session_id": self.ride_context.session_id,
                        "operation": operation,
                    },
                )

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

    async def _database_call(self, operation: Callable[[], Awaitable[_T]]) -> _T:
        """Prevent concurrent use of this session while leaving non-DB tools parallel."""
        async with self._database_operation_lock:
            try:
                return await operation()
            except InvalidRequestError:
                logger.exception(
                    "parallel_tool_db_boundary_failed",
                    extra={
                        "event": "parallel_tool_db_boundary_failed",
                        "session_id": self.ride_context.session_id,
                    },
                )
                raise

    def _derive_location_context(
        self,
        role: Literal["pickup", "destination"],
        explicit_city: str | None,
        explicit_state: str | None,
    ) -> tuple[str | None, str | None, LocationContextSource, bool]:
        city = " ".join(explicit_city.split()) if explicit_city else None
        state = " ".join(explicit_state.split()) if explicit_state else None
        current = (
            self.ride_context.pickup
            if role == "pickup"
            else self.ride_context.destination
        )
        opposite = (
            self.ride_context.destination
            if role == "pickup"
            else self.ride_context.pickup
        )
        if city or state:
            endpoint_city, _ = self.ride_context.endpoint_geography(role)
            opposite_role = "destination" if role == "pickup" else "pickup"
            opposite_context_city, _ = self.ride_context.endpoint_geography(
                opposite_role
            )
            lower_priority_city = (
                current.city
                if current and current.city
                else endpoint_city
                or (opposite.city if opposite else None)
                or opposite_context_city
            )
            conflict = bool(
                city
                and lower_priority_city
                and city.casefold() != lower_priority_city.casefold()
            )
            self.ride_context.remember_endpoint_geography(role, city, state)
            return city, state, LocationContextSource.EXPLICIT_CURRENT_INPUT, conflict
        if current and (current.city or current.state):
            return (
                current.city,
                current.state,
                LocationContextSource.CONFIRMED_ENDPOINT,
                False,
            )
        endpoint_city, endpoint_state = self.ride_context.endpoint_geography(role)
        if endpoint_city or endpoint_state:
            return (
                endpoint_city,
                endpoint_state,
                LocationContextSource.EXPLICIT_CONVERSATION,
                False,
            )
        if opposite and (opposite.city or opposite.state):
            return (
                opposite.city,
                opposite.state,
                LocationContextSource.OPPOSITE_ENDPOINT,
                False,
            )
        opposite_role = "destination" if role == "pickup" else "pickup"
        opposite_city, opposite_state = self.ride_context.endpoint_geography(
            opposite_role
        )
        if opposite_city or opposite_state:
            return (
                opposite_city,
                opposite_state,
                LocationContextSource.OPPOSITE_ENDPOINT,
                False,
            )
        return None, None, LocationContextSource.UNAVAILABLE, False

    def _establish_pickup_geography(
        self, city: str, state: str | None = None
    ) -> str:
        normalized_city = " ".join(city.split())
        normalized_state = " ".join(state.split()) if state else None
        if not normalized_city:
            raise DomainValidationError("pickup city cannot be blank")
        previous_city = self.ride_context.pickup_geography_city
        previous_state = self.ride_context.pickup_geography_state
        changed = bool(
            previous_city
            and (
                previous_city.casefold() != normalized_city.casefold()
                or (
                    normalized_state
                    and previous_state
                    and previous_state.casefold() != normalized_state.casefold()
                )
            )
        )
        same = bool(
            previous_city
            and previous_city.casefold() == normalized_city.casefold()
            and (
                normalized_state is None
                or (
                    previous_state is not None
                    and previous_state.casefold() == normalized_state.casefold()
                )
            )
        )
        if same:
            logger.info(
                "pickup_geography_reused",
                extra={
                    "event": "pickup_geography_reused",
                    "session_id": self.ride_context.session_id,
                },
            )
            return "pickup_geography_reused"

        self.ride_context.begin_location_operation("pickup")
        self.ride_context.clear_pending_location_candidate("pickup")
        if self.ride_context.location_candidate_role == "pickup":
            self.ride_context.clear_location_candidates()
        if changed and normalized_state is None:
            self.ride_context.pickup_geography_state = None
        self.ride_context.remember_endpoint_geography(
            "pickup", normalized_city, normalized_state
        )
        current_pickup = self.ride_context.pickup
        if current_pickup is not None and (
            changed
            or not current_pickup.city
            or current_pickup.city.casefold() != normalized_city.casefold()
        ):
            self.ride_context.update_pickup(None)
        event = "pickup_geography_corrected" if changed else "pickup_geography_established"
        logger.info(
            event,
            extra={
                "event": event,
                "session_id": self.ride_context.session_id,
            },
        )
        return event

    async def _store_resolved_location(
        self,
        role: Literal["pickup", "destination"],
        location: ResolvedLocation,
        *,
        correction: bool,
    ) -> tuple[ResolvedLocation, bool]:
        async with self._state_operation_lock:
            existing = (
                self.ride_context.pickup
                if role == "pickup"
                else self.ride_context.destination
            )
            if existing is not None and not correction:
                logger.info(
                    "location_resolved_reuse",
                    extra={
                        "event": "location_resolved_reuse",
                        "session_id": self.ride_context.session_id,
                        "location_role": role,
                    },
                )
                return existing, False
            self._set_location(role, location)
            return location, True

    @function_tool
    async def establish_pickup_geography(
        self, city: str, state: str | None = None
    ) -> str:
        """Remember a customer-provided pickup city in session context, even while identity is pending; this never authorizes provider or persisted ride access."""
        try:
            status = self._establish_pickup_geography(city, state)
        except DomainValidationError as exc:
            return json.dumps(
                {"status": "pickup_geography_invalid", "message": str(exc)}
            )
        return json.dumps(
            {
                "status": status,
                "city": self.ride_context.pickup_geography_city,
                "state": self.ride_context.pickup_geography_state,
                "next_missing": (
                    "resolved_pickup" if self.ride_context.pickup is None else None
                ),
            }
        )

    @function_tool
    async def get_booking_requirements(self) -> str:
        """Return known booking-state flags and the next missing prerequisite so the caller is not asked for information twice."""
        if self._verified_user() is None:
            return json.dumps({"status": "identity_required", "next_missing": "identity"})
        missing = []
        if self.ride_context.pickup_geography_city is None and self.ride_context.pickup is None:
            missing.append("pickup_geography")
        if self.ride_context.pickup is None:
            missing.append("resolved_pickup")
        if self.ride_context.destination is None:
            missing.append("resolved_destination")
        if self.ride_context.ride_time is None:
            missing.append("resolved_scheduled_time")
        if self.ride_context.selected_vehicle_type_code is None:
            missing.append("selected_vehicle_category")
        return json.dumps(
            {
                "status": "booking_requirements",
                "phase": self.ride_context.booking_phase,
                "next_missing": missing[0] if missing else None,
                "missing": missing,
                "known": {
                    "pickup_geography": self.ride_context.pickup_geography_city is not None,
                    "pickup": self.ride_context.pickup is not None,
                    "destination": self.ride_context.destination is not None,
                    "scheduled_time": self.ride_context.ride_time is not None,
                    "passenger_count": self.ride_context.passenger_count_source
                    is PassengerCountSource.USER_PROVIDED,
                    "vehicle": self.ride_context.selected_vehicle_type_code is not None,
                    "quote": self.ride_context.current_quote is not None,
                },
            }
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
            places = await self._database_call(
                lambda: self._saved_places.list_places(user_id)
            )
        if not places:
            return "No saved places found."
        return "\n".join(
            f"{place.label}: {place.display_name or place.address}" for place in places
        )

    @function_tool
    async def select_saved_place(
        self,
        label: str,
        role: Literal["pickup", "destination"],
        correction: bool = False,
    ) -> str:
        """Select a saved place as pickup or destination using its exact label."""
        user_id = self._verified_user()
        if user_id is None:
            return "Customer identification is required before using saved places."
        place = await self._database_call(
            lambda: self._saved_places.get_place(user_id, label)
        )
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
        selected, changed = await self._store_resolved_location(
            role, location, correction=correction
        )
        action = "Selected" if changed else "Reused"
        return f"{action} {role}: {selected.display_name or selected.address}."

    @function_tool
    async def search_locations(
        self,
        query: str,
        role: Literal["pickup", "destination"],
        explicit_city: str | None = None,
        explicit_state: str | None = None,
        correction: bool = False,
        allow_unbiased_search: bool = False,
        run_context: RunContext = None,  # type: ignore[assignment]
    ) -> str:
        """Resolve a booking endpoint with customer geography; allow unbiased search only for an explicit exploratory/recovery request, never as the normal booking default."""
        user_id = self._verified_user()
        if user_id is None:
            return "Customer identification is required before planning a ride."
        if explicit_city or explicit_state:
            if role == "pickup" and explicit_city:
                self._establish_pickup_geography(explicit_city, explicit_state)
            else:
                existing_city, _ = self.ride_context.endpoint_geography(role)
                normalized_city = (
                    " ".join(explicit_city.split()) if explicit_city else None
                )
                geography_changed = bool(
                    normalized_city
                    and (
                        (
                            existing_city
                            and normalized_city.casefold()
                            != existing_city.casefold()
                        )
                        or (
                            role == "destination"
                            and self.ride_context.destination is not None
                            and (
                                not self.ride_context.destination.city
                                or normalized_city.casefold()
                                != self.ride_context.destination.city.casefold()
                            )
                        )
                    )
                )
                if geography_changed and explicit_state is None:
                    if role == "destination":
                        self.ride_context.destination_geography_state = None
                self.ride_context.begin_location_operation(role)
                self.ride_context.clear_pending_location_candidate(role)
                self.ride_context.remember_endpoint_geography(
                    role, explicit_city, explicit_state
                )
                if geography_changed:
                    if role == "destination":
                        self.ride_context.update_destination(None)
                    logger.info(
                        "location_geography_correction_received",
                        extra={
                            "event": "location_geography_correction_received",
                            "session_id": self.ride_context.session_id,
                            "location_role": role,
                        },
                    )
        # Let sibling endpoint searches from the same model response publish any
        # explicit geography before lower-priority context is derived.
        await asyncio.sleep(0)
        existing = (
            self.ride_context.pickup
            if role == "pickup"
            else self.ride_context.destination
        )
        if existing is not None and not correction:
            logger.info(
                "location_resolved_reuse",
                extra={
                    "event": "location_resolved_reuse",
                    "session_id": self.ride_context.session_id,
                    "location_role": role,
                },
            )
            return (
                f"The resolved {role} is already "
                f"{existing.display_name or existing.address}. Reuse it unless the customer corrects it."
            )
        pending = self.ride_context.pending_location_candidate(role)
        if pending is not None and not correction and not (explicit_city or explicit_state):
            return _likely_location_response(role, pending)
        if pending is not None:
            self.ride_context.clear_pending_location_candidate(role)
            logger.info(
                "location_geography_correction_received",
                extra={
                    "event": "location_geography_correction_received",
                    "session_id": self.ride_context.session_id,
                    "location_role": role,
                },
            )
        saved = None
        if not (explicit_city or explicit_state):
            try:
                saved = await self._database_call(
                    lambda: self._saved_places.resolve_label(user_id, query)
                )
            except ValueError:
                return "More than one saved place matches that label. Ask which one they mean."
        if saved is not None:
            selected, changed = await self._store_resolved_location(
                role, saved, correction=correction
            )
            logger.info("saved_place_resolved", extra={"event": "saved_place_resolved", "session_id": self.ride_context.session_id, "location_role": role})
            action = "Selected" if changed else "Reused"
            return f"{action} saved {role}: {selected.display_name or selected.address}."
        context_city, context_state, context_source, context_conflict = (
            self._derive_location_context(role, explicit_city, explicit_state)
        )
        if context_city is None and context_state is None and not allow_unbiased_search:
            logger.info(
                "pickup_geography_requested",
                extra={
                    "event": "pickup_geography_requested",
                    "session_id": self.ride_context.session_id,
                    "location_role": role,
                },
            )
            return json.dumps(
                {
                    "status": "pickup_geography_required",
                    "next_missing": "pickup_geography",
                    "instruction": "Ask which city the ride starts in before searching ambiguous booking locations.",
                }
            )
        if context_conflict:
            logger.info(
                "location_context_conflict",
                extra={
                    "event": "location_context_conflict",
                    "session_id": self.ride_context.session_id,
                    "location_role": role,
                    "context_source": context_source.value,
                },
            )
        if context_source is LocationContextSource.EXPLICIT_CURRENT_INPUT:
            logger.info(
                "location_explicit_geography_preserved",
                extra={
                    "event": "location_explicit_geography_preserved",
                    "session_id": self.ride_context.session_id,
                    "location_role": role,
                },
            )
        if context_city or context_state:
            logger.info(
                "location_search_with_customer_geography",
                extra={
                    "event": "location_search_with_customer_geography",
                    "session_id": self.ride_context.session_id,
                    "location_role": role,
                    "context_source": context_source.value,
                },
            )
        if context_source is LocationContextSource.OPPOSITE_ENDPOINT:
            logger.info(
                "location_context_opposite_endpoint_used",
                extra={
                    "event": "location_context_opposite_endpoint_used",
                    "session_id": self.ride_context.session_id,
                    "location_role": role,
                },
            )
        operation_version = self.ride_context.begin_location_operation(role)
        try:
            with self._tracer.observe(
                "search_locations",
                observation_type="tool",
                correlation_id=self.ride_context.session_id,
                metadata=self._trace_metadata("search_locations"),
            ):
                async with self._slow_operation(run_context, "location"):
                    result = await self._locations.resolve_query(
                        query,
                        city=context_city,
                        state=context_state,
                        country=self._default_country,
                        session_id=self.ride_context.session_id,
                        location_role=role,
                        context_source=context_source.value,
                        explicit_geography_present=bool(explicit_city or explicit_state),
                        context_conflict_detected=context_conflict,
                    )
        except LocationProviderError:
            attempts = self.ride_context.record_location_clarification(role)
            return json.dumps(
                {
                    "status": "location_temporarily_unavailable",
                    "recovery_level": min(attempts, 2),
                    "instruction": "Explain briefly that the location could not be matched; do not mention provider internals.",
                }
            )
        if not self.ride_context.location_operation_is_current(
            role, operation_version
        ):
            logger.info(
                "stale_location_result_ignored",
                extra={
                    "event": "stale_location_result_ignored",
                    "session_id": self.ride_context.session_id,
                    "location_role": role,
                },
            )
            return json.dumps({"status": "stale_location_result_ignored"})
        if result.status is LocationResolutionStatus.RESOLVED and result.location:
            selected, changed = await self._store_resolved_location(
                role, result.location, correction=correction
            )
            action = "Selected" if changed else "Reused"
            return f"{action} {role}: {selected.display_name or selected.address}."
        if (
            result.status
            is LocationResolutionStatus.LIKELY_MATCH_CONFIRMATION_REQUIRED
            and result.candidates
        ):
            candidate = result.candidates[0]
            self.ride_context.set_likely_location_candidate(role, candidate)
            logger.info(
                "location_candidate_confirmation_required",
                extra={
                    "event": "location_candidate_confirmation_required",
                    "session_id": self.ride_context.session_id,
                    "location_role": role,
                    "provider": candidate.provider,
                },
            )
            return _likely_location_response(role, candidate)
        if result.status is LocationResolutionStatus.PROVIDER_UNAVAILABLE:
            attempts = self.ride_context.record_location_clarification(role)
            return json.dumps(
                {
                    "status": "location_temporarily_unavailable",
                    "recovery_level": min(attempts, 2),
                }
            )
        if result.status is LocationResolutionStatus.NOT_FOUND:
            attempts = self.ride_context.record_location_clarification(role)
            return json.dumps(
                {
                    "status": "location_clarification_required",
                    "recovery_level": min(attempts, 2),
                    "instruction": (
                        "Ask for the city once more."
                        if attempts == 1
                        else "Ask for a nearby landmark."
                    ),
                }
            )
        if not result.candidates:
            return "Please ask which city this location is in."
        candidates = list(result.candidates)
        self.ride_context.set_location_candidates(candidates, role)
        return "\n".join(
            f"{index}. {customer_location_label(candidate)}"
            for index, candidate in enumerate(candidates, start=1)
        )

    @function_tool
    async def confirm_likely_location(
        self,
        role: Literal["pickup", "destination"],
        candidate_id: str,
        explicitly_confirmed: bool,
    ) -> str:
        """Confirm or reject the exact provider-backed likely location proposed for one endpoint; a generic yes must name only the endpoint just asked about."""
        if self._verified_user() is None:
            return json.dumps({"status": "identity_required"})
        async with self._state_operation_lock:
            candidate = self.ride_context.pending_location_candidate(role)
            if candidate is None or candidate.stable_candidate_id != candidate_id:
                return json.dumps(
                    {"status": "location_confirmation_target_mismatch"}
                )
            if not explicitly_confirmed:
                self.ride_context.clear_pending_location_candidate(role)
                logger.info(
                    "location_candidate_rejected",
                    extra={
                        "event": "location_candidate_rejected",
                        "session_id": self.ride_context.session_id,
                        "location_role": role,
                    },
                )
                return json.dumps(
                    {
                        "status": "location_geography_clarification_required",
                        "location_role": role,
                        "instruction": "Ask for the city or locality, then search the original place again with that explicit customer geography.",
                    }
                )
            location = await self._locations.resolve_candidate(candidate)
            self.ride_context.clear_pending_location_candidate(role)
            self._set_location(role, location)
            logger.info(
                "location_candidate_confirmed",
                extra={
                    "event": "location_candidate_confirmed",
                    "session_id": self.ride_context.session_id,
                    "location_role": role,
                    "provider": candidate.provider,
                },
            )
            return json.dumps(
                {
                    "status": "location_confirmed",
                    "location_role": role,
                    "display_label": customer_location_label(candidate),
                }
            )

    @function_tool
    async def select_location_candidate(
        self, candidate_number: int, role: Literal["pickup", "destination"]
    ) -> str:
        """Select one numbered candidate returned by the most recent location search."""
        if self._verified_user() is None:
            return "Customer identification is required before planning a ride."
        async with self._state_operation_lock:
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
        return f"Selected {role}: {location.display_name or location.address}."

    @function_tool
    async def set_ride_time(self, time_phrase: str, correction: bool = False) -> str:
        """Resolve a bounded caller time phrase; never trust an LLM-generated datetime."""
        async with self._state_operation_lock:
            return self._set_ride_time_locked(time_phrase, correction)

    def _set_ride_time_locked(self, time_phrase: str, correction: bool = False) -> str:
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
        return json.dumps(
            {
                "status": "ride_time_corrected" if correction else "ride_time_established",
                "scheduled_at": result.scheduled_at.isoformat(),
                "quote_invalidated": changed,
                "instruction": "Acknowledge this time locally and briefly; do not repeat the full booking summary.",
            }
        )

    @function_tool
    async def get_previous_rides(self, limit: int = 3) -> str:
        """List a small number of this caller's latest rides."""
        user_id = self._verified_user()
        if user_id is None:
            return "Customer identification is required before accessing rides."
        rides = await self._database_call(
            lambda: self._rides.list_for_customer(
                user_id, limit=max(1, min(limit, 5))
            )
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
    async def get_ride_status(
        self, reference: str | None = None, candidate_number: int | None = None
    ) -> str:
        """Resolve natural customer language to one owned ride; never request an ID."""
        async with self._state_operation_lock:
            return await self._get_ride_status_locked(reference, candidate_number)

    async def _get_ride_status_locked(
        self, reference: str | None = None, candidate_number: int | None = None
    ) -> str:
        user_id = self._verified_user()
        if user_id is None:
            return "Customer identification is required before accessing rides."
        with self._tracer.observe(
            "ride_status_lookup",
            observation_type="tool",
            correlation_id=self.ride_context.session_id,
            metadata=self._trace_metadata("get_ride_status"),
        ):
            resolution = await self._database_call(
                lambda: self._ride_service.resolve_customer_ride_reference(
                    user_id,
                    self.ride_context,
                    reference=reference,
                    candidate_number=candidate_number,
                )
            )
        if resolution.status is RideReferenceResolutionStatus.NOT_FOUND:
            return "No matching ride was found for this customer."
        if resolution.status is RideReferenceResolutionStatus.AMBIGUOUS:
            return _ride_ambiguity_response(resolution.candidates, "status")
        assert resolution.ride is not None
        details = await self._database_call(
            lambda: self._ride_service.get_customer_ride_status(
                user_id, resolution.ride.ride_id, self.ride_context
            )
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
            f"{_customer_ride_summary(details)}. "
            f"Booked estimate: {details.currency} {details.estimated_fare:.0f}."
            f"{final_cost}{assignment}"
        )

    @function_tool
    async def dispatch_booked_ride(self) -> str:
        """Dispatch the ride created in this session without exposing its internal ID."""
        user_id = self._verified_user()
        if user_id is None:
            return "Customer identification is required before dispatch."
        ride_id = self.ride_context.booking_id
        if ride_id is None:
            return "No ride booked in this session is ready for dispatch."
        with self._tracer.observe(
            "dispatch_ride",
            observation_type="tool",
            correlation_id=self.ride_context.session_id,
            metadata=self._trace_metadata("dispatch_booked_ride"),
        ) as observation:
            result = await self._database_call(
                lambda: self._dispatch.dispatch(user_id, ride_id)
            )
            observation.update(metadata={"dispatch_result": result.status.value})
        if result.status is DispatchResultStatus.ASSIGNED:
            return "A driver has been assigned to this ride."
        if result.status is DispatchResultStatus.ALREADY_ASSIGNED:
            return "This ride already has an assigned driver."
        if result.status is DispatchResultStatus.NO_DRIVER_AVAILABLE:
            return "No eligible driver is currently available; the booking remains booked."
        return "The ride could not be dispatched in its current state."

    @function_tool
    async def select_ride_for_cancellation(
        self,
        reference: str | None = None,
        candidate_number: int | None = None,
        cancel_all: bool = False,
        replace_selection: bool = False,
    ) -> str:
        """Resolve cancellable rides only; use cancel_all only for an explicit all/both request, and never use this tool for status."""
        async with self._state_operation_lock:
            return await self._select_ride_for_cancellation_locked(
                reference,
                candidate_number,
                cancel_all=cancel_all,
                replace_selection=replace_selection,
            )

    async def _select_ride_for_cancellation_locked(
        self,
        reference: str | None = None,
        candidate_number: int | None = None,
        *,
        cancel_all: bool = False,
        replace_selection: bool = False,
    ) -> str:
        user_id = self._verified_user()
        if user_id is None:
            return "Customer identification is required before cancellation."
        resolution = await self._database_call(
            lambda: self._ride_service.resolve_customer_ride_reference(
                user_id,
                self.ride_context,
                reference=reference,
                candidate_number=candidate_number,
                cancellable_only=True,
                all_requested=cancel_all,
            )
        )
        if resolution.status is RideReferenceResolutionStatus.NOT_FOUND:
            self.ride_context.clear_cancellation()
            return "No matching cancellable ride was found for this customer."
        if resolution.status is RideReferenceResolutionStatus.AMBIGUOUS:
            self.ride_context.clear_cancellation()
            return _ride_ambiguity_response(resolution.candidates, "cancellation")
        if resolution.status is RideReferenceResolutionStatus.RESOLVED_SET:
            ride_ids = tuple(details.ride_id for details in resolution.candidates)
            if (
                self.ride_context.cancellation_target_ride_ids
                and self.ride_context.cancellation_target_ride_ids != ride_ids
                and not replace_selection
            ):
                logger.info(
                    "dependent_tool_sequence_rejected",
                    extra={
                        "event": "dependent_tool_sequence_rejected",
                        "session_id": self.ride_context.session_id,
                        "operation": "cancellation_selection",
                    },
                )
                return json.dumps({"status": "cancellation_target_conflict"})
            self.ride_context.select_cancellation_targets(ride_ids)
            logger.info(
                "cancellation_set_confirmation_required",
                extra={
                    "event": "cancellation_set_confirmation_required",
                    "session_id": self.ride_context.session_id,
                    "ride_count": len(ride_ids),
                },
            )
            return json.dumps(
                {
                    "status": "cancellation_set_confirmation_required",
                    "customer_safe_rides": [
                        _customer_ride_summary(details)
                        for details in resolution.candidates
                    ],
                    "instruction": "Ask for one explicit confirmation covering this complete set.",
                }
            )
        assert resolution.ride is not None
        details = resolution.ride
        if (
            self.ride_context.cancellation_target_ride_ids
            and self.ride_context.cancellation_target_ride_ids != (details.ride_id,)
            and not replace_selection
        ):
            logger.info(
                "dependent_tool_sequence_rejected",
                extra={
                    "event": "dependent_tool_sequence_rejected",
                    "session_id": self.ride_context.session_id,
                    "operation": "cancellation_selection",
                },
            )
            return json.dumps({"status": "cancellation_target_conflict"})
        self.ride_context.select_cancellation_target(details.ride_id)
        return (
            f"Selected {_customer_ride_summary(details)} for cancellation. "
            "Ask the customer to explicitly confirm cancellation."
        )

    @function_tool
    async def record_cancellation_confirmation(
        self, explicitly_confirmed: bool
    ) -> str:
        """Record confirmation bound to the internally selected customer-owned ride."""
        async with self._state_operation_lock:
            return self._record_cancellation_confirmation_locked(
                explicitly_confirmed
            )

    def _record_cancellation_confirmation_locked(
        self, explicitly_confirmed: bool
    ) -> str:
        if self._verified_user() is None:
            return "Customer identification is required before cancellation."
        if len(self.ride_context.cancellation_target_ride_ids) > 1:
            self.ride_context.record_cancellation_set_confirmation(
                explicitly_confirmed
            )
            logger.info(
                "ride_cancellation_confirmation_recorded",
                extra={
                    "event": "ride_cancellation_confirmation_recorded",
                    "session_id": self.ride_context.session_id,
                    "confirmed": explicitly_confirmed,
                    "selection_kind": "set",
                },
            )
            if explicitly_confirmed:
                return "Cancellation confirmed for all selected rides."
            return "Cancellation declined. No rides were changed."
        ride_id = self.ride_context.cancellation_target_ride_id
        if ride_id is None:
            return "Select a customer-owned ride before recording cancellation confirmation."
        try:
            self.ride_context.record_cancellation_confirmation(
                ride_id, explicitly_confirmed
            )
        except DomainValidationError:
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
    async def cancel_selected_ride(self) -> str:
        """Cancel the internally selected owned ride after explicit confirmation."""
        async with self._state_operation_lock:
            return await self._cancel_selected_ride_locked()

    async def _cancel_selected_ride_locked(self) -> str:
        user_id = self._verified_user()
        if user_id is None:
            return "Customer identification is required before cancellation."
        ride_ids = self.ride_context.cancellation_target_ride_ids
        if len(ride_ids) > 1:
            result = await self._database_call(
                lambda: self._ride_service.cancel_customer_rides(
                    user_id, ride_ids, self.ride_context
                )
            )
            outcomes = []
            for item in result.results:
                summary = (
                    _customer_ride_summary(item.ride)
                    if item.ride is not None
                    else "selected ride"
                )
                outcomes.append(f"{summary}: {item.status.value}")
            return json.dumps(
                {"status": "cancellation_set_processed", "outcomes": outcomes}
            )
        ride_id = self.ride_context.cancellation_target_ride_id
        if ride_id is None:
            return "Select a customer-owned ride before cancellation."
        with self._tracer.observe(
            "cancel_ride",
            observation_type="tool",
            correlation_id=self.ride_context.session_id,
            metadata=self._trace_metadata("cancel_selected_ride"),
        ) as observation:
            result = await self._database_call(
                lambda: self._ride_service.cancel_customer_ride(
                    user_id, ride_id, self.ride_context
                )
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
            return "Ride pehle hi cancel ho chuki hai. Final customer cost INR 0 hai."
        return "Ride cancel ho gayi hai. Final customer cost INR 0 hai."

    @function_tool
    async def record_booking_confirmation(self, explicitly_confirmed: bool) -> str:
        """Record the caller's explicit yes/no response to the final ride summary."""
        async with self._state_operation_lock:
            return self._record_booking_confirmation_locked(explicitly_confirmed)

    def _record_booking_confirmation_locked(self, explicitly_confirmed: bool) -> str:
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
    async def get_supported_vehicle_categories(
        self,
        passenger_count: int | None = None,
        cheapest: bool = False,
    ) -> str:
        """List backend-supported vehicle categories eligible by capacity and optionally compare backend prices; this is not live driver availability or promotional offers."""
        async with self._state_operation_lock:
            return await self._get_supported_vehicle_categories_locked(
                passenger_count, cheapest
            )

    async def _get_supported_vehicle_categories_locked(
        self,
        passenger_count: int | None = None,
        cheapest: bool = False,
    ) -> str:
        if self._verified_user() is None:
            return json.dumps({"status": "identity_required"})
        if self._vehicles is None:
            return json.dumps({"status": "vehicle_catalog_unavailable"})
        try:
            async def lookup():
                if passenger_count is not None:
                    await self._vehicles.update_passenger_count(
                        self.ride_context,
                        passenger_count,
                        PassengerCountSource.USER_PROVIDED,
                    )
                return await self._vehicles.get_eligible_vehicle_types(
                    self.ride_context.passenger_count
                )

            result = await self._database_call(lookup)
        except DomainValidationError as exc:
            return json.dumps({"status": "invalid_passenger_count", "message": str(exc)})
        categories = [
            {
                "code": vehicle.code,
                "display_name": vehicle.display_name,
                "passenger_capacity": vehicle.passenger_capacity,
            }
            for vehicle in result.eligible_vehicle_types
        ]
        logger.info(
            "vehicle_recommendation_requested",
            extra={
                "event": "vehicle_recommendation_requested",
                "session_id": self.ride_context.session_id,
                "passenger_count": result.passenger_count,
                "eligible_category_count": len(categories),
                "price_comparison": cheapest,
            },
        )
        cheapest_code = None
        if cheapest:
            try:
                previews = await self._database_call(
                    lambda: self._quotes.preview_vehicle_prices(
                        self.ride_context,
                        tuple(vehicle.code for vehicle in result.eligible_vehicle_types),
                    )
                )
            except (DomainValidationError, RouteSanityError) as exc:
                return json.dumps(
                    {
                        "status": "vehicle_price_comparison_prerequisites_missing",
                        "message": str(exc),
                        "vehicle_categories": categories,
                    }
                )
            if previews:
                cheapest_preview = min(
                    previews,
                    key=lambda preview: (
                        preview.estimated_total,
                        preview.vehicle_type_code,
                    ),
                )
                cheapest_code = cheapest_preview.vehicle_type_code
                preview_amounts = {
                    preview.vehicle_type_code: {
                        "estimated_total": str(preview.estimated_total),
                        "currency": preview.currency,
                    }
                    for preview in previews
                }
                for category in categories:
                    category["price_preview"] = preview_amounts[category["code"]]
        logger.info(
            "vehicle_recommendation_completed",
            extra={
                "event": "vehicle_recommendation_completed",
                "session_id": self.ride_context.session_id,
                "eligible_category_count": len(categories),
                "price_comparison": cheapest,
            },
        )
        return json.dumps(
            {
                "status": result.state.value,
                "availability_kind": "supported_eligible_categories",
                "passenger_count": result.passenger_count,
                "vehicle_categories": categories,
                "cheapest_eligible_vehicle_type_code": cheapest_code,
                "live_driver_availability": "not_checked_until_dispatch",
            }
        )

    @function_tool
    async def set_passenger_count(self, passenger_count: int) -> str:
        """Record the caller-provided passenger count and invalidate incompatible vehicle or quote state."""
        async with self._state_operation_lock:
            return await self._set_passenger_count_locked(passenger_count)

    async def _set_passenger_count_locked(self, passenger_count: int) -> str:
        if self._verified_user() is None:
            return json.dumps({"status": "identity_required"})
        if self._vehicles is None:
            return json.dumps({"status": "vehicle_catalog_unavailable"})
        had_quote = self.ride_context.current_quote is not None
        previous_vehicle = self.ride_context.selected_vehicle_type_code
        try:
            await self._database_call(
                lambda: self._vehicles.update_passenger_count(
                    self.ride_context,
                    passenger_count,
                    PassengerCountSource.USER_PROVIDED,
                )
            )
        except DomainValidationError as exc:
            return json.dumps({"status": "invalid_passenger_count", "message": str(exc)})
        logger.info(
            "passenger_count_established",
            extra={
                "event": "passenger_count_established",
                "session_id": self.ride_context.session_id,
                "quote_invalidated": had_quote,
                "vehicle_cleared": (
                    previous_vehicle is not None
                    and self.ride_context.selected_vehicle_type_code is None
                ),
            },
        )
        if had_quote or (
            previous_vehicle is not None
            and self.ride_context.selected_vehicle_type_code is None
        ):
            logger.info(
                "context_state_invalidated",
                extra={
                    "event": "context_state_invalidated",
                    "session_id": self.ride_context.session_id,
                    "reason": "passenger_count_changed",
                },
            )
        return json.dumps(
            {
                "status": "passenger_count_recorded",
                "passenger_count": self.ride_context.passenger_count,
                "selected_vehicle_type_code": self.ride_context.selected_vehicle_type_code,
            }
        )

    @function_tool
    async def select_vehicle_category(
        self, vehicle_type_code: str, passenger_count: int | None = None
    ) -> str:
        """Select one canonical backend vehicle category after deterministic passenger-capacity validation; never use this for offers."""
        async with self._state_operation_lock:
            return await self._select_vehicle_category_locked(
                vehicle_type_code, passenger_count
            )

    async def _select_vehicle_category_locked(
        self, vehicle_type_code: str, passenger_count: int | None = None
    ) -> str:
        if self._verified_user() is None:
            return json.dumps({"status": "identity_required"})
        if self._vehicles is None:
            return json.dumps({"status": "vehicle_catalog_unavailable"})
        previous_vehicle = self.ride_context.selected_vehicle_type_code
        had_quote = self.ride_context.current_quote is not None
        try:
            async def select():
                if passenger_count is not None:
                    await self._vehicles.update_passenger_count(
                        self.ride_context,
                        passenger_count,
                        PassengerCountSource.USER_PROVIDED,
                    )
                await self._vehicles.select_vehicle_type(
                    self.ride_context, vehicle_type_code
                )

            await self._database_call(select)
        except DomainValidationError as exc:
            eligible = await self._database_call(
                lambda: self._vehicles.get_eligible_vehicle_types(
                    self.ride_context.passenger_count
                )
            )
            logger.info(
                "vehicle_capacity_rejected",
                extra={
                    "event": "vehicle_capacity_rejected",
                    "session_id": self.ride_context.session_id,
                    "eligible_category_count": len(eligible.eligible_vehicle_types),
                },
            )
            return json.dumps(
                {
                    "status": "vehicle_not_eligible",
                    "message": str(exc),
                    "eligible_alternatives": [
                        vehicle.code for vehicle in eligible.eligible_vehicle_types
                    ],
                }
            )
        logger.info(
            "vehicle_selected",
            extra={
                "event": "vehicle_selected",
                "session_id": self.ride_context.session_id,
                "vehicle_type_code": self.ride_context.selected_vehicle_type_code,
            },
        )
        if had_quote and previous_vehicle != self.ride_context.selected_vehicle_type_code:
            logger.info(
                "context_state_invalidated",
                extra={
                    "event": "context_state_invalidated",
                    "session_id": self.ride_context.session_id,
                    "reason": "vehicle_changed",
                },
            )
        return json.dumps(
            {
                "status": "vehicle_selected",
                "vehicle_type_code": self.ride_context.selected_vehicle_type_code,
                "passenger_count": self.ride_context.passenger_count,
            }
        )

    @function_tool
    async def get_available_offers(self) -> str:
        """List promotional discount offers eligible for the verified customer; never use this for vehicle categories or driver availability."""
        user_id = self._verified_user()
        if user_id is None:
            return "Customer identification is required before viewing offers."
        currency = self.ride_context.current_quote.pricing.currency if self.ride_context.current_quote else "INR"
        with self._tracer.observe("offer_eligibility", observation_type="tool", correlation_id=self.ride_context.session_id, metadata=self._trace_metadata("get_available_offers")) as observation:
            offers = await self._database_call(
                lambda: self._offers.get_eligible_offers(user_id, currency)
            )
            observation.update(metadata={"eligible_offer_count": len(offers), "offer_codes": [offer.code for offer in offers]})
        if not offers:
            return "No eligible offers are currently available."
        return "\n".join(f"{offer.code}: {offer.display_name}" for offer in offers)

    @function_tool
    async def apply_offer(self, offer_code: str) -> str:
        """Apply one backend-validated offer to create a fresh estimate."""
        async with self._state_operation_lock:
            return await self._apply_offer_locked(offer_code)

    async def _apply_offer_locked(self, offer_code: str) -> str:
        user_id = self._verified_user()
        if user_id is None:
            return "Customer identification is required before applying offers."
        try:
            with self._tracer.observe("offer_application", observation_type="tool", correlation_id=self.ride_context.session_id, metadata={**self._trace_metadata("apply_offer"), "offer_code": offer_code.strip().upper()}):
                quote = await self._database_call(
                    lambda: self._offers.apply_offer(
                        user_id, self.ride_context, offer_code
                    )
                )
        except DomainValidationError as exc:
            return f"Offer could not be applied: {exc}."
        return f"Offer applied. New estimated fare: {quote.pricing.currency} {quote.pricing.estimated_total:.0f}. Fresh confirmation is required."

    @function_tool
    async def remove_applied_offer(self) -> str:
        """Remove the current offer by producing a fresh non-discounted estimate."""
        async with self._state_operation_lock:
            return await self._remove_applied_offer_locked()

    async def _remove_applied_offer_locked(self) -> str:
        if self._verified_user() is None:
            return "Customer identification is required before applying offers."
        try:
            quote = await self._database_call(
                lambda: self._offers.remove_offer(self.ride_context)
            )
        except DomainValidationError as exc:
            return f"Offer could not be removed: {exc}."
        return f"Offer removed. New estimated fare: {quote.pricing.currency} {quote.pricing.estimated_total:.0f}. Fresh confirmation is required."

    @function_tool
    async def create_fare_quote(
        self, run_context: RunContext = None  # type: ignore[assignment]
    ) -> str:
        """Create a backend-computed estimate only after location, time, passenger, and canonical vehicle prerequisites are established."""
        async with self._state_operation_lock:
            return await self._create_fare_quote_locked(run_context)

    async def _create_fare_quote_locked(
        self, run_context: RunContext | None = None
    ) -> str:
        if self._verified_user() is None:
            return json.dumps(
                {
                    "status": "identity_required",
                    "message": "Customer identification is required before creating a fare quote.",
                }
            )
        missing = []
        if self.ride_context.pickup is None:
            missing.append("resolved_pickup")
        if self.ride_context.destination is None:
            missing.append("resolved_destination")
        if self.ride_context.ride_time is None:
            missing.append("resolved_scheduled_time")
        if self.ride_context.selected_vehicle_type_code is None:
            missing.append("selected_vehicle_category")
        if missing:
            logger.info(
                "quote_prerequisite_failed",
                extra={
                    "event": "quote_prerequisite_failed",
                    "session_id": self.ride_context.session_id,
                    "failure_category": "missing_state",
                    "missing_count": len(missing),
                },
            )
            return json.dumps(
                {"status": "quote_prerequisites_missing", "missing": missing}
            )
        if self._vehicles is not None:
            try:
                await self._database_call(
                    lambda: self._vehicles.require_eligible_vehicle_type(
                        self.ride_context.selected_vehicle_type_code,
                        self.ride_context.passenger_count,
                    )
                )
            except DomainValidationError as exc:
                return json.dumps(
                    {"status": "vehicle_not_eligible", "message": str(exc)}
                )
        started = perf_counter()
        try:
            async with self._slow_operation(run_context, "quote"):
                quote = await self._database_call(
                    lambda: self._quotes.create_quote(self.ride_context)
                )
        except RouteSanityError:
            logger.info(
                "quote_blocked_by_route_sanity",
                extra={
                    "event": "quote_blocked_by_route_sanity",
                    "session_id": self.ride_context.session_id,
                },
            )
            return json.dumps(
                {
                    "status": "route_location_clarification_required",
                    "message": "Route and endpoint geography are inconsistent. Clarify the pickup or destination before quoting.",
                }
            )
        except DomainValidationError as exc:
            logger.info(
                "quote_creation_failed",
                extra={
                    "event": "quote_creation_failed",
                    "session_id": self.ride_context.session_id,
                    "failure_category": "domain_validation",
                },
            )
            return json.dumps(
                {"status": "quote_unavailable", "message": str(exc)}
            )
        logger.info(
            "quote_creation_succeeded",
            extra={
                "event": "quote_creation_succeeded",
                "session_id": self.ride_context.session_id,
                "latency_ms": round((perf_counter() - started) * 1000, 2),
                "route_provider": quote.pricing.route_provider,
                "route_distance_km": round(
                    quote.pricing.route_distance_meters / 1000, 2
                ),
                "pricing_vehicle_code": quote.pricing.vehicle_type_code,
                "pricing_components": {
                    component.component_type.value: str(component.amount)
                    for component in quote.pricing.components
                },
            },
        )
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
    async def create_booking(
        self, run_context: RunContext = None  # type: ignore[assignment]
    ) -> str:
        """Create the mock booking; BookingService independently requires prior confirmation."""
        async with self._state_operation_lock:
            return await self._create_booking_locked(run_context)

    async def _create_booking_locked(
        self, run_context: RunContext | None = None
    ) -> str:
        user_id = self._verified_user()
        if user_id is None:
            return "Booking rejected: customer identification is required."

        async def book_with_transaction_cleanup():
            try:
                return await self._booking.book_ride(user_id, self.ride_context)
            except Exception:
                await self._database_session.rollback()
                raise

        try:
            with self._tracer.observe(
                "create_booking",
                observation_type="tool",
                correlation_id=self.ride_context.session_id,
                metadata=self._trace_metadata("create_booking"),
            ) as observation:
                async with self._slow_operation(run_context, "booking"):
                    outcome = await self._database_call(book_with_transaction_cleanup)
                observation.update(
                    metadata={
                        "success": outcome.status
                        in {BookingResultStatus.SUCCESS, BookingResultStatus.IDEMPOTENT_SUCCESS},
                        "booking_result": outcome.status.value,
                        "provider": getattr(outcome.provider_result, "provider", None),
                    }
                )
        except DomainValidationError as exc:
            self.ride_context.user_confirmed = False
            return f"Booking rejected: {exc}."
        except Exception as exc:
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
        if outcome.status is BookingResultStatus.ACTIVE_RIDE_EXISTS:
            active = outcome.active_ride
            logger.info(
                "booking_blocked_active_ride",
                extra={
                    "event": "booking_blocked_active_ride",
                    "session_id": self.ride_context.session_id,
                    "active_ride_status": active.status if active else None,
                },
            )
            if active is None:
                return "A ride is already active or being booked for this customer. Complete or cancel it before booking another ride."
            local_time = active.requested_ride_at.astimezone(self._timezone)
            vehicle = f", {active.vehicle_type_code}" if active.vehicle_type_code else ""
            return (
                f"A ride from {active.pickup} to {active.destination} at "
                f"{local_time.strftime('%d %b, %I:%M %p')}{vehicle} is already "
                f"{active.status}. Complete or cancel it before booking another ride."
            )
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
            f"Ride book ho gayi hai. Driver {result.driver_name}; "
            f"vehicle {result.vehicle_description}; "
            f"accepted estimated fare {outcome.accepted_quote.pricing.currency} "
            f"{outcome.accepted_quote.pricing.estimated_total:.0f}."
        )

    def _set_location(
        self, role: Literal["pickup", "destination"], location: ResolvedLocation
    ) -> None:
        previous = self.ride_context.pickup if role == "pickup" else self.ride_context.destination
        had_route = self.ride_context.route is not None
        had_quote = self.ride_context.current_quote is not None
        if role == "pickup":
            self.ride_context.update_pickup(location)
        else:
            self.ride_context.update_destination(location)
        self.ride_context.clear_pending_location_candidate(role)
        self.ride_context.clear_location_candidates()
        if previous is not None and previous != location:
            logger.info("location_correction", extra={"event": "location_correction", "session_id": self.ride_context.session_id, "location_role": role})
            logger.info("downstream_quote_invalidated", extra={"event": "downstream_quote_invalidated", "session_id": self.ride_context.session_id, "reason": f"{role}_changed"})
        if previous != location and (had_route or had_quote):
            logger.info(
                "context_state_invalidated",
                extra={
                    "event": "context_state_invalidated",
                    "session_id": self.ride_context.session_id,
                    "reason": f"{role}_changed",
                },
            )


def _is_destination_shorthand(query: str) -> bool:
    words = query.casefold().split()
    generic = {"station", "airport", "railway", "bus", "hospital", "mall"}
    return len(words) <= 3 and bool(generic.intersection(words))


def _likely_location_response(
    role: Literal["pickup", "destination"], candidate: LocationCandidate
) -> str:
    """Expose one provider-backed proposal without treating it as resolved."""
    return json.dumps(
        {
            "status": "likely_match_confirmation_required",
            "location_role": role,
            "candidate_id": candidate.stable_candidate_id,
            "display_label": customer_location_label(candidate),
            "city": candidate.city,
            "state": candidate.state,
            "provider": candidate.provider,
            "instruction": (
                "Ask the customer to confirm this exact candidate. Do not treat it "
                "as resolved until confirm_likely_location succeeds."
            ),
        }
    )


def _customer_ride_summary(details: RideStatusDetails) -> str:
    local_time = details.requested_ride_at.astimezone(ZoneInfo("Asia/Kolkata"))
    vehicle = f", {details.vehicle_type_code}" if details.vehicle_type_code else ""
    return (
        f"ride on {local_time.strftime('%d %b at %I:%M %p')} from "
        f"{details.pickup} to {details.destination}{vehicle}, {details.status.value}"
    )


def _ride_ambiguity_response(
    candidates: tuple[RideStatusDetails, ...], purpose: str
) -> str:
    lines = [
        f"{index}. {_customer_ride_summary(details)}"
        for index, details in enumerate(candidates, start=1)
    ]
    return json.dumps(
        {
            "status": "ride_reference_ambiguous",
            "purpose": purpose,
            "customer_safe_candidates": lines,
            "instruction": "Ask the customer which numbered or naturally described ride they mean. Do not ask for an ID.",
        }
    )
