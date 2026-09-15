from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal


class EvaluationLayer(StrEnum):
    PROMPT_ONLY = "prompt_only"
    AGENT_TOOL_INTEGRATED = "agent_tool_integrated"


class FailureOwner(StrEnum):
    PROMPT = "prompt"
    ORCHESTRATION = "orchestration"
    SERVICE = "service"
    FIXTURE = "fixture"
    EVALUATOR = "evaluator"


@dataclass(frozen=True, slots=True)
class CustomerFixture:
    phone_number: str
    name: str
    age: int
    verified: bool = True


@dataclass(frozen=True, slots=True)
class LocationFixture:
    address: str
    latitude: str
    longitude: str
    display_name: str
    provider: str
    provider_place_id: str
    country: str = "IN"
    city: str | None = None
    state: str | None = None
    place_types: tuple[str, ...] = ("street_address",)


@dataclass(frozen=True, slots=True)
class RouteFixture:
    distance_meters: int
    duration_seconds: int
    provider: str
    toll_status: str = "no_toll"


@dataclass(frozen=True, slots=True)
class QuoteFixture:
    expected_estimated_total: str
    confirmed: bool = False
    quote_ref: str = "current_quote"


@dataclass(frozen=True, slots=True)
class OfferFixture:
    code: str
    expected_discount_amount: str


@dataclass(frozen=True, slots=True)
class RideFixture:
    status: str
    ride_ref: str = "target_ride"
    provider: str = "mock"
    provider_booking_id: str = "eval-booking"


@dataclass(frozen=True, slots=True)
class BookingProviderFixture:
    outcome: str
    provider_booking_id: str


@dataclass(frozen=True, slots=True)
class FixtureProfile:
    customer: CustomerFixture | None = None
    pickup: LocationFixture | None = None
    destination: LocationFixture | None = None
    scheduled_time: str | None = None
    passenger_count: int | None = None
    vehicle_code: str | None = None
    route: RouteFixture | None = None
    quote: QuoteFixture | None = None
    offer: OfferFixture | None = None
    ride: RideFixture | None = None
    booking_provider: BookingProviderFixture | None = None
    pickup_geography_city: str | None = None
    pickup_instructions: str | None = None
    pickup_instruction_handled: bool = False
    location_search_results: tuple[LocationFixture, ...] = ()
    session_active: bool = True

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> FixtureProfile:
        def build(key: str, fixture_type):
            raw = value.get(key)
            if raw is None:
                return None
            if not isinstance(raw, dict):
                raise ValueError(f"fixture.{key} must be an object")
            if fixture_type is LocationFixture and "place_types" in raw:
                raw = {**raw, "place_types": tuple(raw["place_types"])}
            return fixture_type(**raw)

        search_results = value.get("location_search_results", [])
        if not isinstance(search_results, list):
            raise ValueError("fixture.location_search_results must be an array")
        return cls(
            customer=build("customer", CustomerFixture),
            pickup=build("pickup", LocationFixture),
            destination=build("destination", LocationFixture),
            scheduled_time=value.get("scheduled_time"),
            passenger_count=value.get("passenger_count"),
            vehicle_code=value.get("vehicle_code"),
            route=build("route", RouteFixture),
            quote=build("quote", QuoteFixture),
            offer=build("offer", OfferFixture),
            ride=build("ride", RideFixture),
            booking_provider=build("booking_provider", BookingProviderFixture),
            pickup_geography_city=value.get("pickup_geography_city"),
            pickup_instructions=value.get("pickup_instructions"),
            pickup_instruction_handled=value.get(
                "pickup_instruction_handled", False
            ),
            location_search_results=tuple(
                LocationFixture(
                    **{
                        **item,
                        "place_types": tuple(item.get("place_types", ("street_address",))),
                    }
                )
                for item in search_results
            ),
            session_active=value.get("session_active", True),
        )


@dataclass(frozen=True, slots=True)
class EvaluationCase:
    case_id: str
    category: str
    severity: Literal["critical", "high", "normal"]
    layer: EvaluationLayer
    user_input: str
    initial_state: dict[str, Any] = field(default_factory=dict)
    fixture: FixtureProfile | None = None
    available_capabilities: tuple[str, ...] = ()
    expected_action: str | None = None
    required_meaning: tuple[str, ...] = ()
    hard_invariants: tuple[str, ...] = ()
    forbidden_claims: tuple[str, ...] = ()
    expected_language: Literal["english", "hindi", "hinglish", "any"] = "any"
    tool_required: bool = False
    expected_tool: str | None = None
    expected_tool_arguments: dict[str, Any] = field(default_factory=dict)
    forbidden_tools: tuple[str, ...] = ()
    expected_state_changes: dict[str, Any] = field(default_factory=dict)
    forbidden_state_changes: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> EvaluationCase:
        required = ("case_id", "category", "severity", "layer", "user_input")
        missing = [key for key in required if not value.get(key)]
        if missing:
            raise ValueError(f"evaluation case missing required fields: {', '.join(missing)}")
        severity = value["severity"]
        if severity not in {"critical", "high", "normal"}:
            raise ValueError("severity must be critical, high, or normal")
        layer = EvaluationLayer(value["layer"])
        tool_required = bool(value.get("tool_required", False))
        if tool_required != (layer is EvaluationLayer.AGENT_TOOL_INTEGRATED):
            raise ValueError("tool_required must match the evaluation layer")
        if tool_required and not value.get("expected_tool"):
            raise ValueError("tool-required cases need expected_tool")
        fixture = FixtureProfile.from_dict(value["fixture"]) if "fixture" in value else None
        if tool_required and fixture is None:
            raise ValueError("integrated evaluation cases need an explicit fixture")
        return cls(
            case_id=value["case_id"], category=value["category"],
            severity=severity, layer=layer, user_input=value["user_input"],
            initial_state=dict(value.get("initial_state", {})),
            fixture=fixture,
            available_capabilities=tuple(value.get("available_capabilities", ())),
            expected_action=value.get("expected_action"),
            required_meaning=tuple(value.get("required_meaning", ())),
            hard_invariants=tuple(value.get("hard_invariants", ())),
            forbidden_claims=tuple(value.get("forbidden_claims", ())),
            expected_language=value.get("expected_language", "any"),
            tool_required=tool_required, expected_tool=value.get("expected_tool"),
            expected_tool_arguments=dict(value.get("expected_tool_arguments", {})),
            forbidden_tools=tuple(value.get("forbidden_tools", ())),
            expected_state_changes=dict(value.get("expected_state_changes", {})),
            forbidden_state_changes=tuple(value.get("forbidden_state_changes", ())),
        )


@dataclass(frozen=True, slots=True)
class CapturedToolCall:
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    result_status: str | None = None


@dataclass(frozen=True, slots=True)
class ExecutionCapture:
    final_response: str
    tool_calls: tuple[CapturedToolCall, ...] = ()
    state_before: dict[str, Any] = field(default_factory=dict)
    state_after: dict[str, Any] = field(default_factory=dict)
    latency_ms: float | None = None
    execution_error: str | None = None


@dataclass(frozen=True, slots=True)
class ScoreDimension:
    score: float
    failures: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CaseResult:
    case: EvaluationCase
    prompt_candidate: str
    policy: ScoreDimension
    action: ScoreDimension
    voice: ScoreDimension
    capture: ExecutionCapture
    failure_owner: FailureOwner | None = None
    judge_explanation: str | None = None

    @property
    def critical_failure(self) -> bool:
        return self.case.severity == "critical" and not self.passed

    @property
    def passed(self) -> bool:
        return min(self.policy.score, self.action.score, self.voice.score) >= 1.0


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    prompt_candidate: str
    results: tuple[CaseResult, ...]

    @property
    def critical_failures(self) -> int:
        return sum(result.critical_failure for result in self.results)

    def average(self, dimension: Literal["policy", "action", "voice"]) -> float:
        if not self.results:
            return 0.0
        return sum(getattr(result, dimension).score for result in self.results) / len(self.results)
