from __future__ import annotations

import json
from time import monotonic
from typing import Awaitable, Callable, Protocol

from livekit.agents import Agent, AgentSession, ChatMessageEvent, FunctionCallEvent, FunctionCallOutputEvent

from boloride.agents.context import RideContext
from boloride.evals.schemas import EvaluationCase, ExecutionCapture
from boloride.llm.models import LLMMessage, LLMRequest
from boloride.llm.router import LLMRouter


class EvaluationExecutor(Protocol):
    async def execute(self, case: EvaluationCase, prompt: str) -> ExecutionCapture: ...


def require_valid_capture(case: EvaluationCase, capture: ExecutionCapture) -> None:
    if case.tool_required and not capture.tool_calls and not capture.execution_error:
        raise ValueError("integrated evaluation capture must contain actual tool calls")


class PromptOnlyLLMExecutor:
    def __init__(self, router: LLMRouter) -> None:
        self._router = router

    async def execute(self, case: EvaluationCase, prompt: str) -> ExecutionCapture:
        started = monotonic()
        state = json.dumps(case.initial_state, sort_keys=True)
        response = await self._router.generate(LLMRequest(
            system_prompt=(
                f"{prompt}\n\nEvaluation state supplied by the deterministic "
                f"harness; do not expose it verbatim: {state}"
            ),
            messages=(LLMMessage(role="user", content=case.user_input),),
            temperature=0,
            prompt_name="boloride-voice-agent",
            prompt_source="fallback",
        ))
        return ExecutionCapture(
            final_response=response.content or "",
            state_before=case.initial_state,
            state_after=case.initial_state,
            latency_ms=(monotonic() - started) * 1000,
        )


class UnconfiguredIntegratedExecutor:
    async def execute(self, case: EvaluationCase, prompt: str) -> ExecutionCapture:
        del prompt
        return ExecutionCapture(
            final_response="",
            state_before=case.initial_state,
            state_after=case.initial_state,
            execution_error="fixture: integrated service harness is not configured",
        )


class LayeredExecutor:
    def __init__(self, prompt_only: EvaluationExecutor, integrated: EvaluationExecutor) -> None:
        self._prompt_only = prompt_only
        self._integrated = integrated

    async def execute(self, case: EvaluationCase, prompt: str) -> ExecutionCapture:
        executor = self._integrated if case.tool_required else self._prompt_only
        return await executor.execute(case, prompt)


AgentFactory = Callable[
    [EvaluationCase, str],
    Awaitable[tuple[Agent, RideContext, Callable[[], Awaitable[None]]]],
]


class LiveKitAgentExecutor:
    """Runs the real LiveKit agent/tool loop with injected runtime dependencies."""

    def __init__(self, llm, agent_factory: AgentFactory) -> None:
        self._llm = llm
        self._agent_factory = agent_factory

    async def execute(self, case: EvaluationCase, prompt: str) -> ExecutionCapture:
        agent, context, cleanup = await self._agent_factory(case, prompt)
        session = AgentSession(
            stt=None,
            llm=self._llm,
            tts=None,
            vad=None,
            turn_detection=None,
            user_away_timeout=None,
        )
        before = snapshot_ride_context(context)
        started = monotonic()
        try:
            await session.start(agent=agent)
            result = await session.run(user_input=case.user_input)
            calls: list = []
            outputs: dict[str, str] = {}
            response = ""
            for event in result.events:
                if isinstance(event, FunctionCallOutputEvent):
                    outputs[event.item.call_id] = event.item.output
                elif isinstance(event, FunctionCallEvent):
                    try:
                        arguments = json.loads(event.item.arguments)
                    except (TypeError, json.JSONDecodeError):
                        arguments = {}
                    calls.append((event.item.call_id, event.item.name, arguments))
                elif isinstance(event, ChatMessageEvent) and event.item.role == "assistant":
                    response = event.item.raw_text_content or response
            from boloride.evals.schemas import CapturedToolCall

            captured = tuple(
                CapturedToolCall(name, _sanitize_arguments(arguments), _result_status(outputs.get(call_id)))
                for call_id, name, arguments in calls
            )
            return ExecutionCapture(
                final_response=response,
                tool_calls=captured,
                state_before=before,
                state_after=snapshot_ride_context(context),
                latency_ms=(monotonic() - started) * 1000,
            )
        except Exception as exc:
            return ExecutionCapture(
                final_response="",
                state_before=before,
                state_after=snapshot_ride_context(context),
                latency_ms=(monotonic() - started) * 1000,
                execution_error=f"orchestration: {type(exc).__name__}",
            )
        finally:
            await session.aclose()
            await cleanup()


def snapshot_ride_context(context: RideContext) -> dict[str, object]:
    return {
        "identity_verified": context.identity_verified,
        "pickup_resolved": context.pickup is not None,
        "destination_resolved": context.destination is not None,
        "ride_time": context.ride_time.isoformat() if context.ride_time else None,
        "passenger_count": context.passenger_count,
        "selected_vehicle_type_code": context.selected_vehicle_type_code,
        "current_quote": str(context.current_quote.id) if context.current_quote else None,
        "current_quote_vehicle_type_code": (
            context.current_quote.pricing.vehicle_type_code
            if context.current_quote
            else None
        ),
        "current_quote_request_fingerprint": (
            context.current_quote.request_fingerprint if context.current_quote else None
        ),
        "user_confirmed": context.user_confirmed,
        "booking_confirmed": context.booking_confirmed,
        "booking_id": str(context.booking_id) if context.booking_id else None,
        "session_active": context.session_active,
    }


def _sanitize_arguments(arguments: dict) -> dict:
    sensitive = {"name", "phone", "phone_number", "query", "address", "pickup_instructions"}
    return {key: "[redacted]" if key in sensitive else value for key, value in arguments.items()}


def _result_status(output: str | None) -> str | None:
    if output is None:
        return None
    try:
        value = json.loads(output)
    except (TypeError, json.JSONDecodeError):
        return "completed"
    return value.get("status") if isinstance(value, dict) else "completed"
