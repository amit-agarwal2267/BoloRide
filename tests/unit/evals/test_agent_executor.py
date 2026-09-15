from contextlib import contextmanager
from dataclasses import dataclass
from unittest.mock import AsyncMock

import pytest
from livekit.agents import Agent, function_tool

from boloride.agents.context import RideContext
from boloride.agents.session import BoloRideLiveKitLLM
from boloride.evals.agent_executor import LiveKitAgentExecutor
from boloride.evals.schemas import EvaluationCase, EvaluationLayer, FixtureProfile
from boloride.llm.models import LLMResponse, LLMRoute, LLMToolCall
from boloride.llm.router import LLMRouter


class Observation:
    def update(self, **kwargs):
        pass


class Tracer:
    @contextmanager
    def observe(self, *args, **kwargs):
        yield Observation()


@dataclass
class Provider:
    name: str
    generate: AsyncMock

    async def close(self):
        pass


class PassengerService:
    def set_count(self, context: RideContext, count: int) -> None:
        context.passenger_count = count


class HarnessAgent(Agent):
    def __init__(self, context: RideContext, service: PassengerService):
        self.context = context
        self.service = service
        super().__init__(instructions="Use the provided tool.")

    @function_tool
    async def set_passenger_count(self, passenger_count: int) -> str:
        """Set the passenger count through the service."""
        self.service.set_count(self.context, passenger_count)
        return '{"status":"passenger_count_recorded"}'


@pytest.mark.asyncio
async def test_livekit_executor_captures_real_tool_loop_and_state() -> None:
    provider = Provider(
        "google",
        AsyncMock(side_effect=[
            LLMResponse(None, "google", "fixture", 1, tool_calls=[LLMToolCall("call-1", "set_passenger_count", {"passenger_count": 5})]),
            LLMResponse("Passenger count updated.", "google", "fixture", 1),
        ]),
    )
    router = LLMRouter([LLMRoute("google", "fixture")], {"google": provider}, Tracer(), max_retries=0)
    llm = BoloRideLiveKitLLM(router, session_id="eval-session")

    async def factory(case, prompt):
        context = RideContext(session_id="eval-session", caller_id=None)

        async def cleanup():
            pass

        return HarnessAgent(context, PassengerService()), context, cleanup

    case = EvaluationCase(
        "I-1", "passengers", "critical", EvaluationLayer.AGENT_TOOL_INTEGRATED,
        "We are five passengers", fixture=FixtureProfile(),
        tool_required=True, expected_tool="set_passenger_count",
    )
    capture = await LiveKitAgentExecutor(llm, factory).execute(case, "prompt")

    assert capture.execution_error is None
    assert [call.name for call in capture.tool_calls] == ["set_passenger_count"]
    assert capture.tool_calls[0].arguments == {"passenger_count": 5}
    assert capture.tool_calls[0].result_status == "passenger_count_recorded"
    assert capture.state_before["passenger_count"] == 1
    assert capture.state_after["passenger_count"] == 5
    assert capture.final_response == "Passenger count updated."
