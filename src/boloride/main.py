import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from boloride.api.routes.health import router as health_router
from boloride.config import Settings, get_settings
from boloride.db.session import create_database_engine, create_session_factory
from boloride.integrations.langfuse.client import LangfuseClient
from boloride.integrations.langfuse.tracing import LangfuseTracer
from boloride.integrations.maps.router import MapsRouter
from boloride.middleware.request_id import RequestIdMiddleware
from boloride.llm.router import create_llm_router
from boloride.observability.logger import configure_logging
from boloride.prompts.registry import PromptRegistry
from boloride.services.location_service import LocationService


def create_app(settings: Settings | None = None) -> FastAPI:
    application_settings = settings or get_settings()
    configure_logging(application_settings.log_level)
    logger = logging.getLogger(__name__)
    engine = create_database_engine(application_settings)
    langfuse_client = LangfuseClient(application_settings)
    prompt_registry = PromptRegistry(
        langfuse_client,
        label=application_settings.langfuse_prompt_label,
        fallback_enabled=application_settings.prompt_fallback_enabled,
    )
    tracer = LangfuseTracer(langfuse_client)
    llm_router = create_llm_router(application_settings, tracer)
    maps_router = MapsRouter(application_settings)
    location_service = LocationService(
        maps_router,
        max_candidates=application_settings.maps_max_candidates,
        default_country=application_settings.default_country,
        default_language=application_settings.default_language,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        logger.info("application_started", extra={"event": "application_started"})
        try:
            yield
        finally:
            await maps_router.aclose()
            await llm_router.close()
            langfuse_client.shutdown()
            await engine.dispose()
            logger.info("application_stopped", extra={"event": "application_stopped"})

    application = FastAPI(
        title=application_settings.app_name,
        debug=application_settings.debug,
        lifespan=lifespan,
    )
    application.state.settings = application_settings
    application.state.db_engine = engine
    application.state.db_session_factory = create_session_factory(engine)
    application.state.langfuse_client = langfuse_client
    application.state.prompt_registry = prompt_registry
    application.state.tracer = tracer
    application.state.llm_router = llm_router
    application.state.maps_router = maps_router
    application.state.location_service = location_service
    application.add_middleware(RequestIdMiddleware)
    application.include_router(health_router)
    return application


app = create_app()
