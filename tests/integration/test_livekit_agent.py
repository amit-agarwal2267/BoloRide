import asyncio
from contextlib import asynccontextmanager, contextmanager
import json
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from livekit.agents.llm import utils as llm_utils

from boloride.agents.context import RideContext
from boloride.agents.voice_agent import BoloRideAgent
from boloride.domain.exceptions import DomainValidationError
from boloride.domain.enums import RideStatus
from boloride.domain.models.cancellation import (
    CancellationResult,
    CancellationResultStatus,
    CancellationSetResult,
    RideReferenceResolution,
    RideReferenceResolutionStatus,
    RideStatusDetails,
)
from boloride.domain.models.booking import (
    ActiveRideSummary,
    BookingOutcome,
    BookingResultStatus,
)
from boloride.domain.models.location import (
    LocationCandidate,
    LocationResolutionResult,
    LocationResolutionStatus,
    ResolvedLocation,
    TollStatus,
)
from boloride.domain.models.persona import AgentPersona, PersonaGender
from boloride.domain.models.vehicle import VehicleTypeDetails
from boloride.domain.policies import CustomerIdentityState
from boloride.services.time_resolution_service import TimeResolutionService
from boloride.services.vehicle_service import VehicleService
from boloride.prompts.client import PromptFetchResult, PromptFetchStatus
from boloride.prompts.registry import PromptKey, PromptRegistry


class NullTracer:
    @contextmanager
    def observe(self, *args: object, **kwargs: object):
        yield SimpleNamespace(update=lambda **values: None)


class ConfirmationGuard:
    async def book_ride(self, user_id, context):
        if not context.user_confirmed:
            raise DomainValidationError("explicit booking confirmation is required")


class FillerRunContext:
    def __init__(self, *, fire: bool) -> None:
        self.fire = fire
        self.messages = []
        self.delay = None
        self.max_steps = None

    @asynccontextmanager
    async def with_filler(self, source, *, delay, max_steps, **kwargs):
        self.delay = delay
        self.max_steps = max_steps
        if self.fire:
            self.messages.append(source(0))
        yield


class VehicleCatalog:
    vehicles = (
        VehicleTypeDetails("auto", "Auto", 3, True),
        VehicleTypeDetails("mini", "Mini", 4, True),
        VehicleTypeDetails("sedan", "Sedan", 4, True),
        VehicleTypeDetails("suv", "SUV", 6, True),
        VehicleTypeDetails("premium", "Premium Cab", 4, True),
    )

    async def get_by_code(self, code):
        return next((vehicle for vehicle in self.vehicles if vehicle.code == code), None)

    async def list_capacity_eligible(self, passenger_count):
        return [
            vehicle
            for vehicle in self.vehicles
            if vehicle.active and vehicle.passenger_capacity >= passenger_count
        ]


def make_agent(
    base_prompt: str = "You are BoloRide.",
    persona: AgentPersona | None = None,
) -> tuple[BoloRideAgent, RideContext, AsyncMock]:
    user_id = uuid4()
    context = RideContext(
        session_id="voice-test",
        caller_id=user_id,
        identity_state=CustomerIdentityState.VERIFIED_RETURNING_CUSTOMER,
        verified_customer_id=user_id,
    )
    database_session = AsyncMock()
    locations = SimpleNamespace(
        resolve_query=AsyncMock(),
        search_locations=AsyncMock(
            return_value=[
                LocationCandidate(
                    "Kota Junction",
                    "Kota Junction, Rajasthan",
                    Decimal("25.2138"),
                    Decimal("75.8648"),
                    "google",
                    "place-1",
                ),
                LocationCandidate(
                    "Dakaniya Talav",
                    "Dakaniya Talav, Kota",
                    Decimal("25.145"),
                    Decimal("75.857"),
                    "google",
                    "place-2",
                ),
            ]
        ),
        resolve_candidate=AsyncMock(
            side_effect=lambda candidate: candidate.to_resolved_location()
        ),
    )
    agent = BoloRideAgent(
        base_prompt=base_prompt,
        context=context,
        user_id=user_id,
        database_session=database_session,
        locations=locations,
        saved_places=SimpleNamespace(list_places=AsyncMock(return_value=[]), resolve_label=AsyncMock(return_value=None)),
        rides=SimpleNamespace(list_for_customer=AsyncMock(return_value=[])),
        ride_service=SimpleNamespace(
            get_customer_ride_status=AsyncMock(return_value=None),
            resolve_customer_ride_reference=AsyncMock(
                return_value=RideReferenceResolution(
                    RideReferenceResolutionStatus.NOT_FOUND
                )
            ),
            cancel_customer_ride=AsyncMock(),
        ),
        dispatch=SimpleNamespace(dispatch=AsyncMock()),
        booking=ConfirmationGuard(),
        quotes=SimpleNamespace(
            confirm_quote=lambda context, quote_id: context.confirm_quote(quote_id),
            create_quote=AsyncMock(),
            preview_vehicle_prices=AsyncMock(),
        ),
        offers=SimpleNamespace(get_eligible_offers=AsyncMock(return_value=[])),
        vehicles=VehicleService(VehicleCatalog()),  # type: ignore[arg-type]
        tracer=NullTracer(),  # type: ignore[arg-type]
        default_country="IN",
        timezone="Asia/Kolkata",
        time_resolution=TimeResolutionService(lambda: datetime(2026, 9, 6, 12, tzinfo=UTC)),
        persona=persona
        or AgentPersona(
            "staff-aditi", "Aditi", PersonaGender.FEMALE, "hi-IN-SwaraNeural"
        ),
    )
    return agent, context, database_session


def test_agent_construction_uses_fallback_when_langfuse_is_unavailable() -> None:
    client = SimpleNamespace(fetch_text_prompt=lambda name, label: PromptFetchResult(PromptFetchStatus.NOT_CONFIGURED))
    prompt = PromptRegistry(client, label="development").get(PromptKey.VOICE_AGENT)
    agent, _, _ = make_agent(prompt.content)
    assert prompt.source == "fallback"
    assert "BoloRide" in agent.instructions


@pytest.mark.asyncio
async def test_ambiguous_location_then_correction_invalidates_confirmation() -> None:
    agent, context, _ = make_agent()
    locations = agent._locations
    locations.resolve_query = AsyncMock(return_value=SimpleNamespace(
        status=__import__("boloride.domain.models.location", fromlist=["LocationResolutionStatus"]).LocationResolutionStatus.CLARIFICATION_REQUIRED,
        candidates=tuple(await locations.search_locations("Kota station")),
    ))
    output = await agent.search_locations(
        "Kota station",
        "destination",
        explicit_city="Kota",
        explicit_state="Rajasthan",
    )
    assert "1. Kota Junction" in output
    assert "2. Dakaniya Talav" in output
    assert context.clarification_required is True
    assert locations.resolve_query.await_args.kwargs["city"] == "Kota"
    assert locations.resolve_query.await_args.kwargs["state"] == "Rajasthan"

    await agent.select_location_candidate(1, "destination")
    assert context.destination is not None
    assert context.destination.provider_place_id == "place-1"
    assert context.clarification_required is False

    await agent.set_ride_time("tomorrow 7 AM")
    context.user_confirmed = True
    correction = json.loads(await agent.set_ride_time("6:30", correction=True))
    assert context.ride_time == datetime.fromisoformat("2026-09-07T01:00:00+00:00")
    assert context.user_confirmed is False
    assert correction["status"] == "ride_time_corrected"
    assert "pickup" not in correction
    assert "destination" not in correction


@pytest.mark.asyncio
async def test_booking_tool_requires_separately_recorded_confirmation() -> None:
    agent, context, database_session = make_agent()
    result = await agent.create_booking()
    assert "rejected" in result.lower()
    assert context.user_confirmed is False
    database_session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_vehicle_tools_use_backend_catalog_and_canonical_selection() -> None:
    agent, context, _ = make_agent()

    categories = json.loads(await agent.get_supported_vehicle_categories(2))
    assert categories["availability_kind"] == "supported_eligible_categories"
    assert {item["code"] for item in categories["vehicle_categories"]} == {
        "auto", "mini", "sedan", "suv", "premium"
    }
    assert "micro" not in {item["code"] for item in categories["vehicle_categories"]}

    selected = json.loads(await agent.select_vehicle_category("AUTO", 2))
    assert selected == {
        "status": "vehicle_selected",
        "vehicle_type_code": "auto",
        "passenger_count": 2,
    }
    assert context.selected_vehicle_type_code == "auto"


@pytest.mark.asyncio
async def test_vehicle_capacity_failure_returns_backend_alternatives() -> None:
    agent, context, _ = make_agent()

    result = json.loads(await agent.select_vehicle_category("auto", 4))

    assert result["status"] == "vehicle_not_eligible"
    assert set(result["eligible_alternatives"]) == {"mini", "sedan", "suv", "premium"}
    assert context.selected_vehicle_type_code is None


@pytest.mark.asyncio
async def test_quote_tool_returns_structured_missing_state_then_creates_quote() -> None:
    agent, context, _ = make_agent()

    missing = json.loads(await agent.create_fare_quote())
    assert missing == {
        "status": "quote_prerequisites_missing",
        "missing": [
            "resolved_pickup",
            "resolved_destination",
            "resolved_scheduled_time",
            "selected_vehicle_category",
        ],
    }

    context.update_pickup(ResolvedLocation("Pickup", Decimal("25"), Decimal("75")))
    context.update_destination(ResolvedLocation("Destination", Decimal("26"), Decimal("76")))
    context.update_ride_time(datetime.now(UTC))
    await agent.select_vehicle_category("auto", 2)
    agent._quotes.create_quote.return_value = SimpleNamespace(
        pricing=SimpleNamespace(
            currency="INR",
            estimated_total=Decimal("123"),
            toll_status=TollStatus.NO_TOLL,
            route_provider="ola",
            route_distance_meters=1_000,
            vehicle_type_code="auto",
            components=(),
        )
    )

    result = await agent.create_fare_quote()

    assert "Estimated fare: INR 123" in result
    agent._quotes.create_quote.assert_awaited_once_with(context)


def test_vehicle_and_offer_tool_contracts_are_semantically_distinct() -> None:
    vehicle_description = BoloRideAgent.get_supported_vehicle_categories.info.description
    offer_description = BoloRideAgent.get_available_offers.info.description
    assert "vehicle categories" in vehicle_description
    assert "not live driver availability" in vehicle_description
    assert "promotional discount offers" in offer_description
    assert "never use this for vehicle categories" in offer_description


def ride_details(destination: str = "Kota Junction") -> RideStatusDetails:
    return RideStatusDetails(
        ride_id=uuid4(),
        status=RideStatus.BOOKED,
        pickup="Silicon City",
        destination=destination,
        requested_ride_at=datetime(2026, 9, 10, 12, 30, tzinfo=UTC),
        vehicle_type_code="auto",
        estimated_fare=Decimal("120"),
        currency="INR",
        final_customer_cost=None,
    )


@pytest.mark.asyncio
async def test_status_resolves_single_ride_without_exposing_or_requesting_uuid() -> None:
    agent, _, _ = make_agent()
    details = ride_details()
    agent._ride_service.resolve_customer_ride_reference.return_value = (
        RideReferenceResolution(RideReferenceResolutionStatus.RESOLVED, details)
    )
    agent._ride_service.get_customer_ride_status.return_value = details

    output = await agent.get_ride_status()

    assert "Kota Junction" in output
    assert str(details.ride_id) not in output
    assert "ride id" not in output.casefold()


@pytest.mark.asyncio
async def test_status_ambiguity_uses_customer_safe_numbered_summaries() -> None:
    agent, _, _ = make_agent()
    first, second = ride_details("Kota Junction"), ride_details("City Mall")
    agent._ride_service.resolve_customer_ride_reference.return_value = (
        RideReferenceResolution(
            RideReferenceResolutionStatus.AMBIGUOUS,
            candidates=(first, second),
        )
    )

    output = await agent.get_ride_status()

    assert "Kota Junction" in output and "City Mall" in output
    assert str(first.ride_id) not in output and str(second.ride_id) not in output
    assert "Do not ask for an ID" in output


@pytest.mark.asyncio
async def test_cancellation_uses_natural_reference_and_internal_target() -> None:
    agent, context, _ = make_agent()
    details = ride_details()
    agent._ride_service.resolve_customer_ride_reference.return_value = (
        RideReferenceResolution(RideReferenceResolutionStatus.RESOLVED, details)
    )

    selected = await agent.select_ride_for_cancellation("Kota Junction wali")
    confirmed = await agent.record_cancellation_confirmation(True)

    assert str(details.ride_id) not in selected
    assert context.cancellation_target_ride_id == details.ride_id
    assert "confirmed" in confirmed.casefold()


@pytest.mark.asyncio
async def test_parallel_location_searches_serialize_shared_session_lookup() -> None:
    agent, _, _ = make_agent()
    active = 0
    maximum_active = 0

    async def guarded_saved_lookup(user_id, query):
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        await asyncio.sleep(0)
        active -= 1
        return None

    agent._saved_places.resolve_label = guarded_saved_lookup
    agent._locations.resolve_query = AsyncMock(
        side_effect=lambda query, **kwargs: SimpleNamespace(
            status=__import__(
                "boloride.domain.models.location",
                fromlist=["LocationResolutionStatus"],
            ).LocationResolutionStatus.RESOLVED,
            location=ResolvedLocation(
                query,
                Decimal("25.2"),
                Decimal("75.8"),
                display_name=query,
            ),
        )
    )

    await asyncio.gather(
        agent.search_locations("Pickup", "pickup"),
        agent.search_locations("Destination", "destination"),
    )

    assert maximum_active == 1


def likely_candidate(
    name: str, city: str, *, provider_id: str
) -> LocationCandidate:
    return LocationCandidate(
        name,
        f"{name}, {city}, India",
        Decimal("22.72"),
        Decimal("75.86"),
        "ola",
        provider_id,
        city=city,
        state="Madhya Pradesh",
        country="India",
    )


@pytest.mark.asyncio
async def test_normal_booking_requires_customer_pickup_geography_before_search() -> None:
    agent, context, _ = make_agent()

    required = json.loads(await agent.search_locations("Sarafa Bazaar", "pickup"))

    assert required["status"] == "pickup_geography_required"
    assert required["next_missing"] == "pickup_geography"
    assert context.pickup is None
    agent._locations.resolve_query.assert_not_awaited()


@pytest.mark.asyncio
async def test_customer_pickup_city_is_reused_for_pickup_and_destination_searches() -> None:
    agent, context, _ = make_agent()
    seen = []

    async def resolve(query, **kwargs):
        seen.append((kwargs["location_role"], kwargs["city"]))
        return LocationResolutionResult(
            LocationResolutionStatus.CLARIFICATION_REQUIRED,
            candidates=(
                likely_candidate(query, kwargs["city"], provider_id=query),
                likely_candidate(f"{query} 2", kwargs["city"], provider_id=f"{query}-2"),
            ),
        )

    agent._locations.resolve_query = AsyncMock(side_effect=resolve)

    established = json.loads(await agent.establish_pickup_geography(" Indore "))
    await agent.search_locations("Sarafa Bazaar", "pickup")
    context.clear_location_candidates()
    await agent.search_locations("Phoenix Mall", "destination")
    reused = json.loads(await agent.establish_pickup_geography("INDORE"))

    assert established["status"] == "pickup_geography_established"
    assert reused["status"] == "pickup_geography_reused"
    assert seen == [("pickup", "Indore"), ("destination", "Indore")]
    assert context.pickup_geography_city == "Indore"


@pytest.mark.asyncio
async def test_explicit_destination_geography_does_not_overwrite_pickup_city() -> None:
    agent, context, _ = make_agent()
    seen = {}

    async def resolve(query, **kwargs):
        seen[kwargs["location_role"]] = kwargs["city"]
        return LocationResolutionResult(
            LocationResolutionStatus.RESOLVED,
            location=ResolvedLocation(
                query,
                Decimal("22.7"),
                Decimal("75.8"),
                city=kwargs["city"],
            ),
        )

    agent._locations.resolve_query = AsyncMock(side_effect=resolve)
    await agent.establish_pickup_geography("Indore")

    await asyncio.gather(
        agent.search_locations("Sarafa Bazaar", "pickup"),
        agent.search_locations(
            "Jaipur Railway Station", "destination", explicit_city="Jaipur"
        ),
    )

    assert seen == {"pickup": "Indore", "destination": "Jaipur"}
    assert context.pickup_geography_city == "Indore"
    assert context.destination_geography_city == "Jaipur"


@pytest.mark.asyncio
async def test_pickup_geography_correction_preserves_destination_and_invalidates_pickup() -> None:
    agent, context, _ = make_agent()
    pickup = ResolvedLocation(
        "Vijay Nagar, Indore", Decimal("22.7"), Decimal("75.8"), city="Indore"
    )
    destination = ResolvedLocation(
        "Airport, Jaipur", Decimal("26.8"), Decimal("75.8"), city="Jaipur"
    )
    context.update_pickup(pickup)
    context.update_destination(destination)
    context.route = SimpleNamespace()
    context.user_confirmed = True

    corrected = json.loads(await agent.establish_pickup_geography("Gwalior"))

    assert corrected["status"] == "pickup_geography_corrected"
    assert context.pickup is None
    assert context.destination == destination
    assert context.route is None
    assert context.user_confirmed is False


@pytest.mark.asyncio
async def test_newer_geography_correction_wins_over_slow_location_result() -> None:
    agent, context, _ = make_agent()
    started = asyncio.Event()
    release = asyncio.Event()

    async def resolve(query, **kwargs):
        started.set()
        await release.wait()
        return LocationResolutionResult(
            LocationResolutionStatus.RESOLVED,
            location=ResolvedLocation(
                "Sarafa Bazaar, Indore",
                Decimal("22.7"),
                Decimal("75.8"),
                city="Indore",
            ),
        )

    agent._locations.resolve_query = AsyncMock(side_effect=resolve)
    await agent.establish_pickup_geography("Indore")
    old_search = asyncio.create_task(
        agent.search_locations("Sarafa Bazaar", "pickup")
    )
    await started.wait()

    await agent.establish_pickup_geography("Gwalior")
    release.set()
    result = json.loads(await old_search)

    assert result["status"] == "stale_location_result_ignored"
    assert context.pickup is None
    assert context.pickup_geography_city == "Gwalior"


@pytest.mark.asyncio
async def test_booking_requirements_reuse_known_fields_and_derive_phase() -> None:
    agent, context, _ = make_agent()
    initial = json.loads(await agent.get_booking_requirements())
    assert initial["phase"] == "geography"
    assert initial["next_missing"] == "pickup_geography"

    await agent.establish_pickup_geography("Indore")
    known = json.loads(await agent.get_booking_requirements())

    assert known["known"]["pickup_geography"] is True
    assert known["next_missing"] == "resolved_pickup"


@pytest.mark.asyncio
async def test_repeated_location_failure_escalates_to_landmark_without_provider_details() -> None:
    agent, _, _ = make_agent()
    await agent.establish_pickup_geography("Indore")
    agent._locations.resolve_query = AsyncMock(
        return_value=LocationResolutionResult(LocationResolutionStatus.NOT_FOUND)
    )

    first = json.loads(await agent.search_locations("Unknown place", "pickup"))
    second = json.loads(await agent.search_locations("Unknown place", "pickup"))

    assert first["recovery_level"] == 1
    assert first["instruction"] == "Ask for the city once more."
    assert second["recovery_level"] == 2
    assert second["instruction"] == "Ask for a nearby landmark."
    assert "google" not in json.dumps(second).casefold()


def test_conversation_contract_is_short_turn_language_and_confirmation_aware() -> None:
    agent, _, _ = make_agent()
    instructions = agent.instructions

    assert "ask only which city" in instructions
    assert "Never ask again for a known city" in instructions
    assert "one concise complete summary" in instructions
    assert "pickup, destination, scheduled time, vehicle" in instructions
    assert "Mirror the caller's Hindi, Hinglish, or English" in instructions
    assert "Never change or reintroduce your name" in instructions


@pytest.mark.asyncio
async def test_fast_location_operation_skips_progress_acknowledgement() -> None:
    agent, _, _ = make_agent()
    await agent.establish_pickup_geography("Indore")
    agent._locations.resolve_query = AsyncMock(
        return_value=LocationResolutionResult(
            LocationResolutionStatus.RESOLVED,
            location=ResolvedLocation(
                "Sarafa Bazaar, Indore",
                Decimal("22.7"),
                Decimal("75.8"),
                city="Indore",
            ),
        )
    )
    run_context = FillerRunContext(fire=False)

    result = await agent.search_locations(
        "Sarafa Bazaar", "pickup", run_context=run_context
    )

    assert result.startswith("Selected pickup")
    assert run_context.messages == []
    assert run_context.delay == 0.9
    assert run_context.max_steps == 1


@pytest.mark.asyncio
async def test_slow_location_operation_uses_one_gender_correct_acknowledgement() -> None:
    persona = AgentPersona(
        "staff-aarav", "Aarav", PersonaGender.MALE, "hi-IN-MadhurNeural"
    )
    agent, _, _ = make_agent(persona=persona)
    await agent.establish_pickup_geography("Indore")
    agent._locations.resolve_query = AsyncMock(
        return_value=LocationResolutionResult(
            LocationResolutionStatus.RESOLVED,
            location=ResolvedLocation(
                "Sarafa Bazaar, Indore",
                Decimal("22.7"),
                Decimal("75.8"),
                city="Indore",
            ),
        )
    )
    run_context = FillerRunContext(fire=True)

    result = await agent.search_locations(
        "Sarafa Bazaar", "pickup", run_context=run_context
    )

    assert result.startswith("Selected pickup")
    assert run_context.messages == [
        "Ji, ek moment, main location check kar raha hoon."
    ]


def test_livekit_tool_schema_keeps_run_context_internal() -> None:
    agent, _, _ = make_agent()
    for tool in (
        agent.search_locations,
        agent.create_fare_quote,
        agent.create_booking,
    ):
        schema = llm_utils.build_legacy_openai_schema(tool)
        assert "run_context" not in schema["function"]["parameters"]["properties"]


@pytest.mark.asyncio
async def test_unknown_geography_requires_exact_candidate_confirmation() -> None:
    agent, context, _ = make_agent()
    candidate = likely_candidate(
        "Sarafa Bazaar", "Indore", provider_id="sarafa-indore"
    )
    agent._locations.resolve_query = AsyncMock(
        return_value=LocationResolutionResult(
            LocationResolutionStatus.LIKELY_MATCH_CONFIRMATION_REQUIRED,
            candidates=(candidate,),
            provider="ola",
        )
    )

    proposal = json.loads(
        await agent.search_locations(
            "Sarafa Bazaar", "pickup", allow_unbiased_search=True
        )
    )

    assert proposal["status"] == "likely_match_confirmation_required"
    assert proposal["candidate_id"] == candidate.stable_candidate_id
    assert context.pickup is None
    assert context.pending_pickup_candidate == candidate
    assert context.clarification_required is True
    assert agent._locations.resolve_query.await_args.kwargs["city"] is None
    assert agent._locations.resolve_query.await_args.kwargs["state"] is None

    mismatch = json.loads(
        await agent.confirm_likely_location("pickup", "wrong-candidate", True)
    )
    assert mismatch["status"] == "location_confirmation_target_mismatch"
    assert context.pickup is None

    confirmed = json.loads(
        await agent.confirm_likely_location(
            "pickup", candidate.stable_candidate_id, True
        )
    )
    assert confirmed["status"] == "location_confirmed"
    assert context.pickup is not None
    assert context.pickup.provider_place_id == "sarafa-indore"
    assert context.pending_pickup_candidate is None
    assert context.clarification_required is False


@pytest.mark.asyncio
async def test_likely_location_rejection_then_explicit_correction_researches() -> None:
    agent, context, _ = make_agent()
    indore = likely_candidate("Sarafa Bazaar", "Indore", provider_id="indore")
    gwalior = ResolvedLocation(
        "Sarafa Bazaar, Gwalior, India",
        Decimal("26.21"),
        Decimal("78.18"),
        display_name="Sarafa Bazaar",
        provider="ola",
        provider_place_id="gwalior",
        city="Gwalior",
        state="Madhya Pradesh",
    )
    agent._locations.resolve_query = AsyncMock(
        side_effect=(
            LocationResolutionResult(
                LocationResolutionStatus.LIKELY_MATCH_CONFIRMATION_REQUIRED,
                candidates=(indore,),
                provider="ola",
            ),
            LocationResolutionResult(
                LocationResolutionStatus.RESOLVED,
                location=gwalior,
                provider="ola",
            ),
        )
    )

    await agent.search_locations(
        "Sarafa Bazaar", "pickup", allow_unbiased_search=True
    )
    rejected = json.loads(
        await agent.confirm_likely_location(
            "pickup", indore.stable_candidate_id, False
        )
    )
    assert rejected["status"] == "location_geography_clarification_required"
    assert context.pending_pickup_candidate is None
    assert context.pickup is None

    await agent.search_locations(
        "Sarafa Bazaar", "pickup", explicit_city="Gwalior", correction=True
    )

    assert agent._locations.resolve_query.await_args.kwargs["city"] == "Gwalior"
    assert context.pickup is not None
    assert context.pickup.city == "Gwalior"


@pytest.mark.asyncio
async def test_two_unknown_endpoints_remain_independently_pending() -> None:
    agent, context, _ = make_agent()
    pickup = likely_candidate("Sarafa Bazaar", "Indore", provider_id="pickup")
    destination = likely_candidate(
        "Phoenix Citadel", "Indore", provider_id="destination"
    )

    async def resolve(query, **kwargs):
        candidate = pickup if kwargs["location_role"] == "pickup" else destination
        assert kwargs["city"] is None
        assert kwargs["state"] is None
        return LocationResolutionResult(
            LocationResolutionStatus.LIKELY_MATCH_CONFIRMATION_REQUIRED,
            candidates=(candidate,),
            provider="ola",
        )

    agent._locations.resolve_query = AsyncMock(side_effect=resolve)

    await asyncio.gather(
        agent.search_locations(
            "Sarafa Bazaar", "pickup", allow_unbiased_search=True
        ),
        agent.search_locations(
            "Phoenix Mall", "destination", allow_unbiased_search=True
        ),
    )

    assert context.pickup is None and context.destination is None
    assert context.pending_pickup_candidate == pickup
    assert context.pending_destination_candidate == destination

    await agent.confirm_likely_location(
        "pickup", pickup.stable_candidate_id, True
    )

    assert context.pickup is not None
    assert context.destination is None
    assert context.pending_destination_candidate == destination
    assert context.clarification_required is True


@pytest.mark.asyncio
async def test_pending_likely_endpoint_cannot_create_quote() -> None:
    agent, context, _ = make_agent()
    candidate = likely_candidate("Phoenix Citadel", "Indore", provider_id="phoenix")
    context.set_likely_location_candidate("destination", candidate)
    context.update_pickup(
        ResolvedLocation("Pickup", Decimal("22.7"), Decimal("75.8"))
    )
    context.update_ride_time(datetime.now(UTC))
    await agent.select_vehicle_category("auto")

    result = json.loads(await agent.create_fare_quote())

    assert result["status"] == "quote_prerequisites_missing"
    assert result["missing"] == ["resolved_destination"]
    agent._quotes.create_quote.assert_not_awaited()


@pytest.mark.asyncio
async def test_cheapest_vehicle_uses_backend_price_previews_without_quote() -> None:
    agent, context, _ = make_agent()
    context.update_pickup(ResolvedLocation("Pickup", Decimal("25"), Decimal("75")))
    context.update_destination(ResolvedLocation("Destination", Decimal("26"), Decimal("76")))
    context.update_ride_time(datetime.now(UTC))
    agent._quotes.preview_vehicle_prices.return_value = (
        SimpleNamespace(vehicle_type_code="auto", estimated_total=Decimal("100"), currency="INR"),
        SimpleNamespace(vehicle_type_code="mini", estimated_total=Decimal("90"), currency="INR"),
        SimpleNamespace(vehicle_type_code="sedan", estimated_total=Decimal("120"), currency="INR"),
        SimpleNamespace(vehicle_type_code="suv", estimated_total=Decimal("180"), currency="INR"),
        SimpleNamespace(vehicle_type_code="premium", estimated_total=Decimal("250"), currency="INR"),
    )

    output = json.loads(await agent.get_supported_vehicle_categories(2, cheapest=True))

    assert output["cheapest_eligible_vehicle_type_code"] == "mini"
    assert context.current_quote is None


@pytest.mark.asyncio
async def test_suspicious_route_returns_structured_quote_block() -> None:
    from boloride.domain.exceptions import RouteSanityError

    agent, context, _ = make_agent()
    context.update_pickup(ResolvedLocation("Pickup", Decimal("25"), Decimal("75")))
    context.update_destination(ResolvedLocation("Destination", Decimal("26"), Decimal("76")))
    context.update_ride_time(datetime.now(UTC))
    await agent.select_vehicle_category("auto")
    agent._quotes.create_quote.side_effect = RouteSanityError("inconsistent route")

    output = json.loads(await agent.create_fare_quote())

    assert output["status"] == "route_location_clarification_required"
    assert context.current_quote is None


@pytest.mark.asyncio
async def test_parallel_endpoint_searches_share_explicit_trip_geography_not_default() -> None:
    agent, _, _ = make_agent()
    seen = {}

    async def resolve(query, **kwargs):
        seen[kwargs["location_role"]] = (kwargs["city"], kwargs["context_source"])
        return SimpleNamespace(
            status=__import__(
                "boloride.domain.models.location",
                fromlist=["LocationResolutionStatus"],
            ).LocationResolutionStatus.RESOLVED,
            location=ResolvedLocation(
                query,
                Decimal("22.7"),
                Decimal("75.8"),
                display_name=query,
                city=kwargs["city"],
                state=kwargs["state"],
            ),
        )

    agent._locations.resolve_query = AsyncMock(side_effect=resolve)

    await asyncio.gather(
        agent.search_locations("Silicon City", "pickup"),
        agent.search_locations(
            "Indore Junction", "destination", explicit_city="Indore"
        ),
    )

    assert seen["pickup"][0] == "Indore"
    assert seen["pickup"][1] == "opposite_endpoint"
    assert seen["destination"] == ("Indore", "explicit_current_input")


@pytest.mark.asyncio
async def test_explicit_intercity_contexts_remain_distinct() -> None:
    agent, _, _ = make_agent()
    seen = {}

    async def resolve(query, **kwargs):
        seen[kwargs["location_role"]] = kwargs["city"]
        latitude = "25.2" if kwargs["city"] == "Kota" else "22.7"
        return SimpleNamespace(
            status=__import__(
                "boloride.domain.models.location",
                fromlist=["LocationResolutionStatus"],
            ).LocationResolutionStatus.RESOLVED,
            location=ResolvedLocation(
                query,
                Decimal(latitude),
                Decimal("75.8"),
                display_name=query,
                city=kwargs["city"],
            ),
        )

    agent._locations.resolve_query = AsyncMock(side_effect=resolve)

    await asyncio.gather(
        agent.search_locations(
            "Kota Junction", "pickup", explicit_city="Kota"
        ),
        agent.search_locations(
            "Indore Junction", "destination", explicit_city="Indore"
        ),
    )

    assert seen == {"pickup": "Kota", "destination": "Indore"}


@pytest.mark.asyncio
async def test_explicit_geography_bypasses_conflicting_saved_place_and_default() -> None:
    agent, _, _ = make_agent()
    agent._saved_places.resolve_label.return_value = ResolvedLocation(
        "Home, Kota", Decimal("25.2"), Decimal("75.8"), city="Kota"
    )
    agent._locations.resolve_query = AsyncMock(
        return_value=SimpleNamespace(
            status=__import__(
                "boloride.domain.models.location",
                fromlist=["LocationResolutionStatus"],
            ).LocationResolutionStatus.RESOLVED,
            location=ResolvedLocation(
                "Home, Indore", Decimal("22.7"), Decimal("75.8"), city="Indore"
            ),
        )
    )

    await agent.search_locations(
        "home in Indore", "pickup", explicit_city="Indore"
    )

    agent._saved_places.resolve_label.assert_not_awaited()
    assert agent._locations.resolve_query.await_args.kwargs["city"] == "Indore"
    assert agent.ride_context.pickup.city == "Indore"


def test_location_context_precedence_ends_in_unknown_geography() -> None:
    agent, context, _ = make_agent()
    context.remember_endpoint_geography("pickup", "Indore", "Madhya Pradesh")

    city, state, source, _ = agent._derive_location_context(
        "pickup", None, None
    )
    assert (city, state, source.value) == (
        "Indore",
        "Madhya Pradesh",
        "explicit_conversation",
    )

    context.pickup_geography_city = None
    context.pickup_geography_state = None
    context.update_destination(
        ResolvedLocation(
            "Kota Junction", Decimal("25.2"), Decimal("75.8"), city="Kota"
        )
    )
    city, state, source, _ = agent._derive_location_context(
        "pickup", None, None
    )
    assert (city, state, source.value) == ("Kota", None, "opposite_endpoint")

    context.update_destination(None)
    context.destination_geography_city = None
    context.destination_geography_state = None
    city, state, source, _ = agent._derive_location_context(
        "pickup", None, None
    )
    assert (city, state, source.value) == (None, None, "unavailable")


@pytest.mark.asyncio
async def test_resolved_location_is_reused_until_explicit_correction() -> None:
    agent, context, _ = make_agent()
    context.update_pickup(
        ResolvedLocation(
            "Kota Junction", Decimal("25.2"), Decimal("75.8"), city="Kota"
        )
    )
    agent._locations.resolve_query = AsyncMock()

    reused = await agent.search_locations("station", "pickup")

    assert "already" in reused
    agent._locations.resolve_query.assert_not_awaited()

    agent._locations.resolve_query.return_value = SimpleNamespace(
        status=__import__(
            "boloride.domain.models.location",
            fromlist=["LocationResolutionStatus"],
        ).LocationResolutionStatus.RESOLVED,
        location=ResolvedLocation(
            "Indore Junction", Decimal("22.7"), Decimal("75.8"), city="Indore"
        ),
    )
    corrected = await agent.search_locations(
        "Indore Junction",
        "pickup",
        explicit_city="Indore",
        correction=True,
    )
    assert context.pickup.city == "Indore"
    assert corrected.startswith("Selected pickup")
    assert "destination=" not in corrected


@pytest.mark.asyncio
async def test_vehicle_selection_is_observed_before_parallel_quote() -> None:
    agent, context, _ = make_agent()
    context.update_pickup(ResolvedLocation("Pickup", Decimal("25"), Decimal("75")))
    context.update_destination(
        ResolvedLocation("Destination", Decimal("26"), Decimal("76"))
    )
    context.update_ride_time(datetime.now(UTC))
    agent._quotes.create_quote.return_value = SimpleNamespace(
        pricing=SimpleNamespace(
            currency="INR",
            estimated_total=Decimal("123"),
            toll_status=TollStatus.NO_TOLL,
            route_provider="ola",
            route_distance_meters=1_000,
            vehicle_type_code="auto",
            components=(),
        )
    )

    selected, quoted = await asyncio.gather(
        agent.select_vehicle_category("auto"),
        agent.create_fare_quote(),
    )

    assert json.loads(selected)["vehicle_type_code"] == "auto"
    assert "Estimated fare" in quoted


@pytest.mark.asyncio
async def test_contradictory_parallel_cancellation_selections_do_not_both_mutate() -> None:
    agent, context, _ = make_agent()
    first, second = ride_details("Kota Junction"), ride_details("City Mall")
    agent._ride_service.resolve_customer_ride_reference.side_effect = (
        RideReferenceResolution(RideReferenceResolutionStatus.RESOLVED, first),
        RideReferenceResolution(RideReferenceResolutionStatus.RESOLVED, second),
    )

    results = await asyncio.gather(
        agent.select_ride_for_cancellation("Kota Junction"),
        agent.select_ride_for_cancellation("City Mall"),
    )

    assert context.cancellation_target_ride_ids == (first.ride_id,)
    assert "cancellation_target_conflict" in results[1]


@pytest.mark.asyncio
async def test_active_ride_booking_result_is_customer_safe() -> None:
    agent, context, _ = make_agent()
    active = ActiveRideSummary(
        "booked",
        "Home",
        "Kota Junction",
        datetime.now(UTC),
        "auto",
    )
    agent._booking = SimpleNamespace(
        book_ride=AsyncMock(
            return_value=BookingOutcome(
                BookingResultStatus.ACTIVE_RIDE_EXISTS, active_ride=active
            )
        )
    )

    output = await agent.create_booking()

    assert "already booked" in output
    assert "Kota Junction" in output
    assert "uuid" not in output.casefold()


@pytest.mark.asyncio
async def test_explicit_multi_ride_cancellation_uses_one_set_confirmation() -> None:
    agent, context, _ = make_agent()
    first, second = ride_details("Kota Junction"), ride_details("City Mall")
    agent._ride_service.resolve_customer_ride_reference.return_value = (
        RideReferenceResolution(
            RideReferenceResolutionStatus.RESOLVED_SET,
            candidates=(first, second),
        )
    )
    async def cancel_set(customer_id, ride_ids, ride_context):
        if not ride_context.cancellation_set_is_confirmed_for(ride_ids):
            return CancellationSetResult(
                tuple(
                    CancellationResult(CancellationResultStatus.CONFIRMATION_REQUIRED)
                    for _ in ride_ids
                )
            )
        return CancellationSetResult(
            (
                CancellationResult(CancellationResultStatus.SUCCESS, first),
                CancellationResult(CancellationResultStatus.NOT_CANCELLABLE, second),
            )
        )

    agent._ride_service.cancel_customer_rides = AsyncMock(side_effect=cancel_set)

    selected = json.loads(
        await agent.select_ride_for_cancellation("dono rides", cancel_all=True)
    )
    assert selected["status"] == "cancellation_set_confirmation_required"
    assert context.cancellation_target_ride_ids == (first.ride_id, second.ride_id)

    unconfirmed = await agent.cancel_selected_ride()
    assert "confirmation_required" in unconfirmed

    await agent.record_cancellation_confirmation(True)
    processed = json.loads(await agent.cancel_selected_ride())

    assert processed["status"] == "cancellation_set_processed"
    assert any("not_cancellable" in value for value in processed["outcomes"])
    assert all(str(item.ride_id) not in processed["outcomes"] for item in (first, second))
