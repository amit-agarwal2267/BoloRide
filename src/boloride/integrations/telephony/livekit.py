import logging

from livekit.agents import AgentServer, AgentSession, JobContext, cli, room_io
from livekit.plugins import silero
from livekit.plugins import dtln

from boloride.agents.context import RideContext
from boloride.agents.lifecycle import voice_session_trace
from boloride.agents.session import BoloRideLiveKitLLM
from boloride.agents.voice_agent import BoloRideAgent
from boloride.config import get_settings
from boloride.db.session import create_database_engine, create_session_factory
from boloride.integrations.langfuse.client import LangfuseClient
from boloride.integrations.langfuse.tracing import LangfuseTracer
from boloride.integrations.maps.router import MapsRouter
from boloride.integrations.rideprovider.mock_provider import MockRideProvider
from boloride.llm.router import create_llm_router
from boloride.observability.logger import configure_logging
from boloride.prompts.registry import PromptKey, PromptRegistry
from boloride.repositories.ride_repository import RideRepository
from boloride.repositories.saved_place_repository import SavedPlaceRepository
from boloride.repositories.user_repository import UserRepository
from boloride.services.booking_service import BookingService
from boloride.services.location_service import LocationService
from boloride.services.saved_place_service import SavedPlaceService
from boloride.services.user_service import UserService
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
    if not settings.development_caller_phone:
        raise RuntimeError(
            "DEVELOPMENT_CALLER_PHONE is required until participant identity is implemented"
        )
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

    async def shutdown() -> None:
        trace.update(metadata={"success": True})
        trace_manager.__exit__(None, None, None)
        await maps_router.aclose()
        await llm_router.close()
        await database_session.close()
        await engine.dispose()
        langfuse.shutdown()

    ctx.add_shutdown_callback(shutdown)

    users = UserRepository(database_session)
    identity = await UserService(users).resolve_returning_customer(
        settings.development_caller_phone,
        provided_name=None,
    )
    if not identity.verified or identity.customer_id is None:
        raise RuntimeError(
            "LiveKit customer onboarding and phone-plus-name verification must be "
            "integrated before persisted customer operations are enabled"
        )
    user_id = identity.customer_id

    rides = RideRepository(database_session)
    saved_places = SavedPlaceService(SavedPlaceRepository(database_session))
    locations = LocationService(
        maps_router,
        max_candidates=settings.maps_max_candidates,
        default_country=settings.default_country,
        default_language=settings.default_language,
    )
    prompt = PromptRegistry(
        langfuse,
        label=settings.langfuse_prompt_label,
        fallback_enabled=settings.prompt_fallback_enabled,
    ).get(PromptKey.VOICE_AGENT)
    ride_context = RideContext(session_id=session_id, caller_id=user_id)
    agent = BoloRideAgent(
        base_prompt=prompt.content,
        context=ride_context,
        user_id=user_id,
        database_session=database_session,
        locations=locations,
        saved_places=saved_places,
        rides=rides,
        booking=BookingService(rides, MockRideProvider()),
        tracer=tracer,
        default_city=settings.default_city,
        default_state=settings.default_state,
        default_country=settings.default_country,
        timezone=settings.default_timezone,
    )
    session = AgentSession(
        stt=STTRouter(settings).get_provider().get_livekit_stt(),
        llm=BoloRideLiveKitLLM(llm_router, session_id=session_id),
        tts=TTSRouter(settings).get_provider().get_livekit_tts(),
        vad=silero.VAD.load(),
    )
    room_options = room_io.RoomOptions(
        audio_input=room_io.AudioInputOptions(
            noise_cancellation=dtln.noise_suppression(
                debug_logging=settings.debug,
            ),
        )
    )
    await session.start(agent=agent, room=ctx.room, room_options=room_options)
    session.generate_reply(
        instructions="Greet the caller briefly and ask where they want to go."
    )
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


if __name__ == "__main__":
    cli.run_app(server)
