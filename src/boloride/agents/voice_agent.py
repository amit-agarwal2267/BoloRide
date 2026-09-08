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
from boloride.integrations.langfuse.tracing import LangfuseTracer
from boloride.repositories.ride_repository import RideRepository
from boloride.services.booking_service import BookingService
from boloride.services.location_service import LocationService
from boloride.services.saved_place_service import SavedPlaceService

logger = logging.getLogger(__name__)


class BoloRideAgent(Agent):
    """LiveKit orchestration layer; business rules remain in services."""

    def __init__(
        self,
        *,
        base_prompt: str,
        context: RideContext,
        user_id: UUID,
        database_session: AsyncSession,
        locations: LocationService,
        saved_places: SavedPlaceService,
        rides: RideRepository,
        booking: BookingService,
        tracer: LangfuseTracer,
        default_city: str | None,
        default_state: str | None,
        default_country: str,
        timezone: str,
    ) -> None:
        self.ride_context = context
        self._user_id = user_id
        self._database_session = database_session
        self._locations = locations
        self._saved_places = saved_places
        self._rides = rides
        self._booking = booking
        self._tracer = tracer
        self._default_city = default_city
        self._default_state = default_state
        self._default_country = default_country
        self._timezone = ZoneInfo(timezone)
        super().__init__(instructions=build_agent_instructions(base_prompt, context))

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
        with self._tracer.observe(
            "get_saved_places",
            observation_type="tool",
            correlation_id=self.ride_context.session_id,
            metadata=self._trace_metadata("get_saved_places"),
        ):
            places = await self._saved_places.list_places(self._user_id)
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
        place = await self._saved_places.get_place(self._user_id, label)
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
    async def search_locations(self, query: str) -> str:
        """Search maps and return numbered candidates; never invent a location."""
        try:
            with self._tracer.observe(
                "search_locations",
                observation_type="tool",
                correlation_id=self.ride_context.session_id,
                metadata=self._trace_metadata("search_locations"),
            ):
                candidates = await self._locations.search_locations(
                    query,
                    city=self._default_city,
                    state=self._default_state,
                    country=self._default_country,
                    session_id=self.ride_context.session_id,
                )
        except LocationProviderError as exc:
            return f"Location search failed: {exc}. Ask the caller to clarify or try again."
        self.ride_context.set_location_candidates(candidates)
        return "\n".join(
            f"{index}. {candidate.display_name} — {candidate.formatted_address}"
            for index, candidate in enumerate(candidates, start=1)
        )

    @function_tool
    async def select_location_candidate(
        self, candidate_number: int, role: Literal["pickup", "destination"]
    ) -> str:
        """Select one numbered candidate returned by the most recent location search."""
        candidates = self.ride_context.location_candidates
        if not 1 <= candidate_number <= len(candidates):
            return "Invalid candidate number. Search again or ask the caller to choose."
        location = self._locations.resolve_candidate(candidates[candidate_number - 1])
        self._set_location(role, location)
        self.ride_context.clear_location_candidates()
        return f"Selected {role}: {location.display_name or location.address}. {self._state_summary()}"

    @function_tool
    async def set_ride_time(self, iso_datetime: str) -> str:
        """Set or replace the requested ride time as an ISO-8601 datetime."""
        try:
            value = datetime.fromisoformat(iso_datetime)
        except ValueError:
            return "Invalid datetime. Provide an ISO-8601 date and time."
        if value.tzinfo is None:
            value = value.replace(tzinfo=self._timezone)
        self.ride_context.update_ride_time(value)
        return f"Ride time updated to {value.isoformat()}. Confirmation is now required. {self._state_summary()}"

    @function_tool
    async def get_previous_rides(self, limit: int = 3) -> str:
        """List a small number of this caller's latest rides."""
        rides = await self._rides.list_for_customer(
            self._user_id, limit=max(1, min(limit, 5))
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
    async def record_booking_confirmation(self, explicitly_confirmed: bool) -> str:
        """Record the caller's explicit yes/no response to the final ride summary."""
        self.ride_context.user_confirmed = explicitly_confirmed
        if explicitly_confirmed:
            return "Explicit confirmation recorded. The booking may now be created."
        return "Confirmation declined. Do not create the booking."

    @function_tool
    async def create_booking(self) -> str:
        """Create the mock booking; BookingService independently requires prior confirmation."""
        try:
            with self._tracer.observe(
                "create_booking",
                observation_type="tool",
                correlation_id=self.ride_context.session_id,
                metadata=self._trace_metadata("create_booking"),
            ) as observation:
                outcome = await self._booking.book_ride(
                    self._user_id, self.ride_context
                )
                await self._database_session.commit()
                observation.update(
                    metadata={
                        "success": True,
                        "provider": outcome.provider_result.provider,
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
            return "Booking provider is temporarily unavailable. No booking was saved."
        result = outcome.provider_result
        return (
            f"Booking successful. ID {result.provider_booking_id}. "
            f"Driver {result.driver_name}; vehicle {result.vehicle_description}; "
            f"fare {result.fare_currency} {result.fare_amount}."
        )

    def _set_location(
        self, role: Literal["pickup", "destination"], location: ResolvedLocation
    ) -> None:
        if role == "pickup":
            self.ride_context.update_pickup(location)
        else:
            self.ride_context.update_destination(location)
