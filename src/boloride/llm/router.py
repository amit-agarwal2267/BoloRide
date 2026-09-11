import asyncio
import logging
from dataclasses import replace
from decimal import Decimal
from time import monotonic

from boloride.config import Settings
from boloride.observability.tracing import Tracer
from boloride.llm.base import (
    AllProvidersFailedError,
    LLMConfigurationError,
    LLMError,
    LLMProvider,
    LLMProviderError,
)
from boloride.llm.models import LLMRequest, LLMResponse, LLMRoute, ProviderName
from boloride.llm.providers.google import GoogleLLMProvider
from boloride.llm.providers.groq import GroqLLMProvider
from boloride.observability.llm_pricing import apply_llm_cost

logger = logging.getLogger(__name__)


class LLMRouter:
    def __init__(
        self,
        routes: list[LLMRoute],
        providers: dict[ProviderName, LLMProvider],
        tracer: Tracer,
        *,
        max_retries: int = 1,
    ) -> None:
        if not routes:
            raise LLMConfigurationError("at least one LLM route is required")
        if len(set(routes)) != len(routes):
            raise LLMConfigurationError("duplicate LLM routes are not allowed")
        missing = {route.provider for route in routes} - providers.keys()
        if missing:
            raise LLMConfigurationError(
                f"providers are not configured for routes: {', '.join(sorted(missing))}"
            )
        if not 0 <= max_retries <= 2:
            raise LLMConfigurationError("LLM max retries must be between 0 and 2")
        self._routes = routes
        self._providers = providers
        self._tracer = tracer
        self._max_retries = max_retries

    async def generate(self, request: LLMRequest) -> LLMResponse:
        failures: list[str] = []
        invocation_order = 0
        for route_index, route in enumerate(self._routes):
            provider = self._providers[route.provider]
            for attempt in range(self._max_retries + 1):
                fallback_used = route_index > 0
                invocation_order += 1
                trace_metadata = {
                    "provider": route.provider,
                    "model": route.model,
                    "attempt": attempt + 1,
                    "attempt_order": invocation_order,
                    "route_role": "fallback" if fallback_used else "primary",
                    "fallback_used": fallback_used,
                    "prompt_name": request.prompt_name,
                    "prompt_version": request.prompt_version,
                    "prompt_label": request.prompt_label,
                    "prompt_source": request.prompt_source,
                }
                with self._tracer.observe(
                    "voice.llm",
                    observation_type="generation",
                    correlation_id=request.session_id,
                    metadata=trace_metadata,
                ) as observation:
                    started_at = monotonic()
                    try:
                        response = await provider.generate(request, route.model)
                    except LLMProviderError as exc:
                        duration_ms = (monotonic() - started_at) * 1000
                        self._record_metrics(
                            route.provider, route.model, False, fallback_used
                        )
                        observation.update(
                            metadata={
                                **trace_metadata,
                                "success": False,
                                "failure_category": _failure_category(exc),
                                "duration_ms": duration_ms,
                            }
                        )
                        if not exc.transient:
                            raise
                        failures.append(
                            f"{route.provider}/{route.model}: {type(exc).__name__}"
                        )
                        logger.warning(
                            "llm_route_attempt_failed",
                            extra={
                                "event": "llm_route_attempt_failed",
                                "session_id": request.session_id,
                                "provider": route.provider,
                                "model": route.model,
                                "error_type": _failure_category(exc),
                                "duration_ms": duration_ms,
                                "fallback_used": fallback_used,
                            },
                        )
                        if attempt < self._max_retries:
                            await asyncio.sleep(0.25 * (2**attempt))
                            continue
                        break
                    except LLMError as exc:
                        duration_ms = (monotonic() - started_at) * 1000
                        self._record_metrics(
                            route.provider, route.model, False, fallback_used
                        )
                        observation.update(
                            metadata={
                                **trace_metadata,
                                "success": False,
                                "failure_category": _failure_category(exc),
                                "duration_ms": duration_ms,
                            }
                        )
                        raise
                    except Exception as exc:
                        duration_ms = (monotonic() - started_at) * 1000
                        self._record_metrics(
                            route.provider, route.model, False, fallback_used
                        )
                        observation.update(
                            metadata={
                                **trace_metadata,
                                "success": False,
                                "failure_category": "unknown",
                                "duration_ms": duration_ms,
                            }
                        )
                        raise

                    duration_ms = (monotonic() - started_at) * 1000
                    usage = apply_llm_cost(route.provider, route.model, response.usage)
                    normalized = replace(
                        response, fallback_used=fallback_used, usage=usage
                    )
                    self._record_metrics(
                        route.provider,
                        route.model,
                        True,
                        fallback_used,
                        usage=usage,
                    )
                    metadata = {
                        **trace_metadata,
                        "success": True,
                        "duration_ms": duration_ms,
                        "provider_latency_ms": normalized.latency_ms,
                        "input_tokens": usage.input_tokens,
                        "output_tokens": usage.output_tokens,
                        "total_tokens": usage.total_tokens,
                        "cached_tokens": usage.cached_tokens,
                        "usage_source": usage.usage_source,
                        "input_cost": _decimal_text(usage.input_cost),
                        "output_cost": _decimal_text(usage.output_cost),
                        "total_cost": _decimal_text(usage.total_cost),
                        "currency": usage.currency,
                        "cost_source": usage.cost_source,
                        "finish_reason": normalized.finish_reason,
                    }
                    observation.update(
                        metadata=metadata,
                        model=route.model,
                        usage_details=_usage_details(usage),
                        cost_details=_cost_details(usage),
                    )
                    logger.info(
                        "llm_generation_completed",
                        extra={"event": "llm_generation_completed", "session_id": request.session_id, **metadata},
                    )
                    return normalized

        detail = "; ".join(failures)
        raise AllProvidersFailedError(f"all configured LLM routes failed: {detail}")

    async def close(self) -> None:
        for provider in self._providers.values():
            await provider.close()

    def _record_metrics(
        self,
        provider: str,
        model: str,
        success: bool,
        fallback: bool,
        *,
        usage=None,
    ) -> None:
        metrics = getattr(self._tracer, "metrics", None)
        if metrics is None:
            return
        metrics.record_llm_call(
            provider=provider,
            model=model,
            success=success,
            fallback=fallback,
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
            total_tokens=getattr(usage, "total_tokens", None),
            cached_tokens=getattr(usage, "cached_tokens", None),
            total_cost=getattr(usage, "total_cost", None),
            currency=getattr(usage, "currency", None),
        )


def create_llm_router(settings: Settings, tracer: Tracer) -> LLMRouter:
    route_values = (
        (settings.llm_primary_provider, settings.llm_primary_model),
        (settings.llm_fallback_1_provider, settings.llm_fallback_1_model),
        (settings.llm_fallback_2_provider, settings.llm_fallback_2_model),
    )
    routes: list[LLMRoute] = []
    for index, (provider, model) in enumerate(route_values):
        if provider is None and model is None:
            continue
        if provider is None or not model:
            name = "primary" if index == 0 else f"fallback {index}"
            raise LLMConfigurationError(f"LLM {name} provider and model are required")
        routes.append(LLMRoute(provider=provider, model=model))

    providers: dict[ProviderName, LLMProvider] = {}
    configured_names = {route.provider for route in routes}
    if "google" in configured_names:
        if settings.google_api_key is None:
            raise LLMConfigurationError("GOOGLE_API_KEY is required for Google routes")
        providers["google"] = GoogleLLMProvider(
            settings.google_api_key.get_secret_value(),
            timeout_seconds=settings.llm_timeout_seconds,
        )
    if "groq" in configured_names:
        if settings.groq_api_key is None:
            raise LLMConfigurationError("GROQ_API_KEY is required for Groq routes")
        providers["groq"] = GroqLLMProvider(
            settings.groq_api_key.get_secret_value(),
            timeout_seconds=settings.llm_timeout_seconds,
        )
    return LLMRouter(
        routes, providers, tracer, max_retries=settings.llm_max_retries
    )


def _failure_category(exc: LLMError) -> str:
    name = type(exc).__name__
    return {
        "LLMTimeoutError": "timeout",
        "LLMRateLimitError": "rate_limited",
        "LLMConfigurationError": "authentication_or_configuration",
        "LLMRequestError": "malformed_request",
        "LLMProviderError": "provider_unavailable",
    }.get(name, "unknown")


def _decimal_text(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def _usage_details(usage) -> dict[str, int] | None:
    values = {
        "input": usage.input_tokens,
        "output": usage.output_tokens,
        "total": usage.total_tokens,
        "cache_read_input_tokens": usage.cached_tokens,
    }
    result = {key: value for key, value in values.items() if value is not None}
    return result or None


def _cost_details(usage) -> dict[str, float] | None:
    values = {
        "input": usage.input_cost,
        "output": usage.output_cost,
        "total": usage.total_cost,
    }
    result = {key: float(value) for key, value in values.items() if value is not None}
    return result or None
