import json
import logging
from datetime import UTC, datetime, timedelta

from livekit.agents import AgentServer, AgentSession, JobContext, cli, room_io
from livekit.plugins import silero
from livekit.plugins import dtln

from boloride.agents.context import RideContext
from boloride.agents.lifecycle import voice_session_trace
from boloride.agents.session import BoloRideLiveKitLLM
from boloride.agents.voice_agent import BoloRideAgent
from boloride.config import get_settings
from boloride.domain.exceptions import DomainValidationError
from boloride.domain.models.persona import AgentPersona, PersonaGender
from boloride.domain.policies import CustomerIdentityResult, CustomerIdentityState
from boloride.db.session import create_database_engine, create_session_factory
from boloride.integrations.langfuse.client import LangfuseClient
from boloride.integrations.langfuse.tracing import LangfuseTracer
from boloride.integrations.maps.router import MapsRouter
from boloride.integrations.rideprovider.mock_provider import MockRideProvider
from boloride.llm.router import create_llm_router
from boloride.observability.logger import configure_logging
from boloride.prompts.registry import PromptKey, PromptRegistry
from boloride.repositories.booking_attempt_repository import BookingAttemptRepository
from boloride.repositories.assignment_repository import AssignmentRepository
from boloride.repositories.fleet_repository import FleetRepository
from boloride.repositories.ride_repository import RideRepository
from boloride.repositories.pricing_rule_repository import PricingRuleRepository
from boloride.repositories.offer_repository import OfferRepository
from boloride.repositories.saved_place_repository import SavedPlaceRepository
from boloride.repositories.user_repository import UserRepository
from boloride.repositories.vehicle_type_repository import VehicleTypeRepository
from boloride.services.booking_service import BookingService
from boloride.services.dispatch_service import DispatchService
from boloride.services.location_service import LocationService
from boloride.services.pricing_service import PricingService
from boloride.services.quote_service import QuoteService
from boloride.services.ride_service import RideService
from boloride.services.offer_service import OfferService
from boloride.services.persona_service import PersonaSelector
from boloride.services.saved_place_service import SavedPlaceService
from boloride.services.user_service import UserService
from boloride.services.time_resolution_service import TimeResolutionService
from boloride.services.vehicle_service import VehicleService
from boloride.speech.stt.router import STTRouter
from boloride.speech.tts.router import TTSRouter

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)

server = AgentServer(
    ws_url=settings.livekit_url,
    api_key=(settings.livekit_api_key.get_secret_value() if settings.livekit_api_key else None),
    api_secret=(
        settings.livekit_api_secret.get_secret_value()
        if settings.livekit_api_secret
        else None
    ),
)


@server.rtc_session(agent_name=settings.livekit_agent_name)
async def entrypoint(ctx: JobContext) -> None:
    session_id = ctx.job.id
    ctx.log_context_fields = {"session_id": session_id}
    engine = create_database_engine(settings)
    database_session = create_session_factory(engine)()
    langfuse = LangfuseClient(settings)
    tracer = LangfuseTracer(langfuse)
    trace_manager = voice_session_trace(tracer, session_id)
    trace = trace_manager.__enter__()
    llm_router = create_llm_router(settings, tracer)
    maps_router = MapsRouter(settings)
    persona = PersonaSelector(
        (
            AgentPersona("formal-male", PersonaGender.MALE, settings.tts_male_voice),
            AgentPersona("formal-female", PersonaGender.FEMALE, settings.tts_female_voice),
        )
    ).select()
    logger.info(
        "persona_selected",
        extra={"event": "persona_selected", "session_id": session_id, "persona_id": persona.persona_id, "gender": persona.gender.value},
    )

    async def shutdown() -> None:
        quotes.disconnect(ride_context)
        trace.update(metadata={"success": True})
        trace_manager.__exit__(None, None, None)
        await maps_router.aclose()
        await llm_router.close()
        await database_session.close()
        await engine.dispose()
        langfuse.shutdown()

    users = UserRepository(database_session)
    user_service = UserService(users)
    detected_phone = _caller_phone(ctx, settings.development_caller_phone)
    logger.info("customer_identity_started", extra={"event": "customer_identity_started", "session_id": session_id})
    try:
        identity = await user_service.begin_identity(detected_phone)
    except DomainValidationError:
        identity = CustomerIdentityResult(CustomerIdentityState.PHONE_UNAVAILABLE)
    except Exception:
        logger.exception("customer_identity_failed", extra={"event": "customer_identity_failed", "session_id": session_id})
        identity = CustomerIdentityResult(CustomerIdentityState.IDENTITY_UNAVAILABLE)
    branch_event = "new_customer_detected" if identity.state is CustomerIdentityState.NEW_CUSTOMER_ONBOARDING_REQUIRED else "returning_customer_detected" if identity.state is CustomerIdentityState.RETURNING_CUSTOMER_VERIFICATION_REQUIRED else "customer_phone_unavailable" if identity.state is CustomerIdentityState.PHONE_UNAVAILABLE else "customer_identity_failed"
    logger.info(branch_event, extra={"event": branch_event, "session_id": session_id, "identity_result": identity.state.value})

    rides = RideRepository(database_session)
    vehicles = VehicleService(VehicleTypeRepository(database_session))
    saved_places = SavedPlaceService(SavedPlaceRepository(database_session))
    locations = LocationService(
        maps_router,
        max_candidates=settings.maps_max_candidates,
        default_country=settings.default_country,
        default_language=settings.default_language,
        urban_radius_meters=settings.maps_urban_context_radius_meters,
        rural_radius_meters=settings.maps_rural_context_radius_meters,
    )
    quotes = QuoteService(
        PricingService(PricingRuleRepository(database_session)), locations
    )
    offers = OfferService(OfferRepository(database_session), quotes)
    dispatch = DispatchService(
        database_session,
        rides,
        FleetRepository(database_session),
        AssignmentRepository(database_session),
        offers,
    )
    ride_service = RideService(database_session, rides, offers, dispatch)
    prompt = PromptRegistry(
        langfuse,
        label=settings.langfuse_prompt_label,
        fallback_enabled=settings.prompt_fallback_enabled,
    ).get(PromptKey.VOICE_AGENT)
    ride_context = RideContext(
        session_id=session_id,
        caller_id=None,
        identity_state=identity.state,
        verified_customer_id=None,
    )
    agent = BoloRideAgent(
        base_prompt=prompt.content,
        context=ride_context,
        user_id=None,
        database_session=database_session,
        locations=locations,
        saved_places=saved_places,
        rides=rides,
        ride_service=ride_service,
        dispatch=dispatch,
        booking=BookingService(
            database_session,
            rides,
            BookingAttemptRepository(database_session),
            MockRideProvider(),
            vehicles,
            quotes,
            offers,
            provider_call_lease=timedelta(seconds=settings.provider_call_lease_seconds),
        ),
        quotes=quotes,
        offers=offers,
        tracer=tracer,
        default_city=settings.default_city,
        default_state=settings.default_state,
        default_country=settings.default_country,
        timezone=settings.default_timezone,
        time_resolution=TimeResolutionService(lambda: datetime.now(UTC), settings.default_timezone),
        user_service=user_service,
        detected_phone=detected_phone,
        persona=persona,
    )
    ctx.add_shutdown_callback(shutdown)
    session = AgentSession(
        stt=STTRouter(settings).get_provider().get_livekit_stt(),
        llm=BoloRideLiveKitLLM(llm_router, session_id=session_id),
        tts=TTSRouter(settings, voice=persona.edge_tts_voice).get_provider().get_livekit_tts(),
        vad=silero.VAD.load(),
    )
    room_options = room_io.RoomOptions(
        audio_input=room_io.AudioInputOptions(
            noise_cancellation=dtln.noise_suppression(
                debug_logging=settings.debug,
            ),
        )
    )
    session.input.set_audio_enabled(False)
    await session.start(agent=agent, room=ctx.room, room_options=room_options)
    await play_deterministic_welcome(session, persona, session_id)
    logger.info(
        "voice_session_started",
        extra={
            "event": "voice_session_started",
            "session_id": session_id,
            "stt_provider": settings.stt_provider,
            "maps_provider": settings.maps_provider,
            "tts_provider": settings.tts_provider,
            "prompt_source": prompt.source,
        },
    )


async def play_deterministic_welcome(
    session: AgentSession, persona: AgentPersona, session_id: str
) -> bool:
    """Speak the fixed welcome once, with caller audio disabled and no LLM call."""
    logger.info("deterministic_welcome_started", extra={"event": "deterministic_welcome_started", "session_id": session_id, "gender": persona.gender.value})
    try:
        handle = session.say(persona.welcome, allow_interruptions=False, add_to_chat_ctx=True)
        await handle.wait_for_playout()
    except Exception:
        logger.exception("deterministic_welcome_failed", extra={"event": "deterministic_welcome_failed", "session_id": session_id, "gender": persona.gender.value})
        return False
    finally:
        session.input.set_audio_enabled(True)
    logger.info("deterministic_welcome_completed", extra={"event": "deterministic_welcome_completed", "session_id": session_id, "gender": persona.gender.value})
    return True


def _caller_phone(ctx: JobContext, development_phone: str | None) -> str | None:
    """Read adapter-owned phone metadata, falling back only to explicit dev config."""
    metadata = getattr(ctx.job, "metadata", None)
    if isinstance(metadata, str) and metadata.strip():
        try:
            payload = json.loads(metadata)
        except ValueError:
            payload = {}
        if isinstance(payload, dict):
            for key in ("phone_number", "caller_phone", "sip_phone_number"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return value
    for participant in getattr(ctx.room, "remote_participants", {}).values():
        attributes = getattr(participant, "attributes", {})
        for key in ("sip.phoneNumber", "sip.trunkPhoneNumber", "phone_number"):
            value = attributes.get(key) if isinstance(attributes, dict) else None
            if isinstance(value, str) and value.strip():
                return value
    return development_phone


if __name__ == "__main__":
    cli.run_app(server)
