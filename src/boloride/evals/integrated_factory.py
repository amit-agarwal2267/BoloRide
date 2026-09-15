from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from boloride.agents.voice_agent import BoloRideAgent
from boloride.domain.models.location import (
    LocationCandidate,
    LocationSearchContext,
    ResolvedLocation,
    RouteResult,
)
from boloride.domain.models.persona import AgentPersona, PersonaGender
from boloride.evals.fixture_builder import EvaluationFixtureBuilder
from boloride.evals.schemas import EvaluationCase, LocationFixture
from boloride.integrations.rideprovider.base import (
    ProviderCreateOutcome,
    ProviderCreateStatus,
    ProviderReconciliationOutcome,
    ProviderReconciliationStatus,
    RideBookingRequest,
    RideBookingResult,
)
from boloride.prompts.registry import PromptBundle
from boloride.repositories.assignment_repository import AssignmentRepository
from boloride.repositories.booking_attempt_repository import BookingAttemptRepository
from boloride.repositories.fleet_repository import FleetRepository
from boloride.repositories.offer_repository import OfferRepository
from boloride.repositories.pricing_rule_repository import PricingRuleRepository
from boloride.repositories.ride_repository import RideRepository
from boloride.repositories.saved_place_repository import SavedPlaceRepository
from boloride.repositories.user_repository import UserRepository
from boloride.repositories.vehicle_type_repository import VehicleTypeRepository
from boloride.services.booking_service import BookingService
from boloride.services.dispatch_service import DispatchService
from boloride.services.location_service import LocationService
from boloride.services.offer_service import OfferService
from boloride.services.pricing_service import PricingService
from boloride.services.quote_service import QuoteService
from boloride.services.ride_service import RideService
from boloride.services.saved_place_service import SavedPlaceService
from boloride.services.time_resolution_service import TimeResolutionService
from boloride.services.user_service import UserService
from boloride.services.vehicle_service import VehicleService


class _NullTracer:
    @contextmanager
    def observe(self, *_args, **_kwargs):
        yield SimpleNamespace(update=lambda **_values: None)


class _FixtureMapsProvider:
    provider_name = "fixture_maps"

    def __init__(
        self,
        locations: tuple[LocationFixture, ...],
        route: RouteResult | None,
    ) -> None:
        self._locations = locations
        self._route = route

    async def search_location(
        self, query: str, context: LocationSearchContext | None = None
    ) -> list[LocationCandidate]:
        del context
        normalized = " ".join(query.casefold().split())
        candidates = [_candidate(item) for item in self._locations]
        matching = [
            item
            for item in candidates
            if item.display_name.casefold() in normalized
            or normalized in item.display_name.casefold()
        ]
        return matching or candidates

    async def enrich_candidate(self, candidate: LocationCandidate) -> LocationCandidate:
        return candidate

    async def get_route(
        self, origin: ResolvedLocation, destination: ResolvedLocation
    ) -> RouteResult:
        del origin, destination
        if self._route is None:
            raise AssertionError("route result was not declared by the fixture")
        return self._route

    async def aclose(self) -> None:
        return None


class _FixtureMapsRouter:
    def __init__(self, provider: _FixtureMapsProvider) -> None:
        self._provider = provider

    def get_provider(self):
        return self._provider

    def get_search_providers(self):
        return [self._provider]

    def get_route_providers(self):
        return [self._provider]

    def is_fallback_provider(self, provider_name: str) -> bool:
        del provider_name
        return False

    def record_fallback_attempt(self) -> None:
        return None

    async def search_location(self, query: str, context: LocationSearchContext):
        candidates = await self._provider.search_location(query, context)
        return candidates, self._provider.provider_name, False, False

    @contextmanager
    def provider_observation(self, *_args, **_kwargs):
        yield None


class _FixtureRideProvider:
    provider_name = "fixture"
    supports_safe_retry_after_definitive_absence = True

    def __init__(self, outcome: str | None, booking_id: str | None) -> None:
        self._outcome = outcome
        self._booking_id = booking_id
        self._bookings: dict[str, RideBookingResult] = {}

    async def create_booking(
        self, request: RideBookingRequest, *, idempotency_key: str
    ) -> ProviderCreateOutcome:
        del request
        existing = self._bookings.get(idempotency_key)
        if existing:
            return ProviderCreateOutcome(ProviderCreateStatus.CONFIRMED, existing)
        if self._outcome != "success" or not self._booking_id:
            return ProviderCreateOutcome(
                ProviderCreateStatus.REJECTED, failure_category="fixture_rejected"
            )
        booking = RideBookingResult(
            provider=self.provider_name,
            provider_booking_id=self._booking_id,
            driver_name="Fixture Driver",
            vehicle_description="Fixture Vehicle",
        )
        self._bookings[idempotency_key] = booking
        return ProviderCreateOutcome(ProviderCreateStatus.CONFIRMED, booking)

    async def reconcile_booking(
        self, idempotency_key: str
    ) -> ProviderReconciliationOutcome:
        booking = self._bookings.get(idempotency_key)
        if booking:
            return ProviderReconciliationOutcome(
                ProviderReconciliationStatus.CONFIRMED, booking
            )
        return ProviderReconciliationOutcome(
            ProviderReconciliationStatus.DEFINITIVELY_ABSENT
        )


class FixtureBackedAgentFactory:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        prompt_bundle: PromptBundle,
    ) -> None:
        self._session_factory = session_factory
        self._prompt_bundle = prompt_bundle

    async def __call__(self, case: EvaluationCase, prompt: str):
        del prompt
        session = self._session_factory()
        try:
            runtime = await EvaluationFixtureBuilder(session).build(case)
            fixture = case.fixture
            assert fixture is not None
            route = runtime.context.route
            maps_provider = _FixtureMapsProvider(
                fixture.location_search_results, route
            )
            locations = LocationService(
                _FixtureMapsRouter(maps_provider),  # type: ignore[arg-type]
                default_country="IN",
                default_language="en",
            )
            rides = RideRepository(session)
            vehicles = VehicleService(VehicleTypeRepository(session))
            quotes = QuoteService(
                PricingService(PricingRuleRepository(session)), locations
            )
            offers = OfferService(OfferRepository(session), quotes)
            dispatch = DispatchService(
                session,
                rides,
                FleetRepository(session),
                AssignmentRepository(session),
                offers,
            )
            ride_service = RideService(session, rides, offers, dispatch)
            provider = _FixtureRideProvider(
                runtime.booking_provider_outcome, runtime.provider_booking_id
            )
            tracer = _NullTracer()
            agent = BoloRideAgent(
                prompt_bundle=self._prompt_bundle,
                context=runtime.context,
                user_id=runtime.customer_id,
                database_session=session,
                locations=locations,
                saved_places=SavedPlaceService(SavedPlaceRepository(session)),
                rides=rides,
                ride_service=ride_service,
                dispatch=dispatch,
                booking=BookingService(
                    session,
                    rides,
                    BookingAttemptRepository(session),
                    provider,
                    vehicles,
                    quotes,
                    offers,
                    provider_call_lease=timedelta(seconds=30),
                ),
                quotes=quotes,
                offers=offers,
                vehicles=vehicles,
                tracer=tracer,  # type: ignore[arg-type]
                default_country="IN",
                timezone="Asia/Kolkata",
                time_resolution=TimeResolutionService(
                    lambda: runtime.context.ride_time
                    or datetime.now(UTC),
                    "Asia/Kolkata",
                ),
                user_service=UserService(UserRepository(session)),
                detected_phone=(
                    fixture.customer.phone_number if fixture.customer else None
                ),
                persona=AgentPersona(
                    "eval-aditi", "Aditi", PersonaGender.FEMALE, "hi-IN-SwaraNeural"
                ),
            )
        except Exception:
            await session.close()
            raise

        async def cleanup() -> None:
            await session.rollback()
            await session.close()

        return agent, runtime.context, cleanup


def _candidate(fixture: LocationFixture) -> LocationCandidate:
    return LocationCandidate(
        display_name=fixture.display_name,
        formatted_address=fixture.address,
        latitude=Decimal(fixture.latitude),
        longitude=Decimal(fixture.longitude),
        provider=fixture.provider,
        provider_place_id=fixture.provider_place_id,
        city=fixture.city,
        state=fixture.state,
        country=fixture.country,
        place_types=fixture.place_types,
    )
