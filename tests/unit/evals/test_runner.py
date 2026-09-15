from dataclasses import replace

import pytest

from boloride.evals.runner import (
    EvaluationRunner,
    report_evidence_dict,
    report_markdown,
    select_cases,
    select_winner,
)
from boloride.evals.schemas import (
    CapturedToolCall,
    CaseResult,
    EvaluationCase,
    EvaluationLayer,
    EvaluationReport,
    ExecutionCapture,
    FailureOwner,
    ScoreDimension,
)


class Executor:
    def __init__(self, capture: ExecutionCapture) -> None:
        self.capture = capture

    async def execute(self, case, prompt):
        assert prompt
        return self.capture


def prompt_case() -> EvaluationCase:
    return EvaluationCase("P-1", "voice", "normal", EvaluationLayer.PROMPT_ONLY, "hello")


def integrated_case(case_id: str = "I-1") -> EvaluationCase:
    return EvaluationCase(
        case_id,
        "tool",
        "normal",
        EvaluationLayer.AGENT_TOOL_INTEGRATED,
        "book",
        tool_required=True,
        expected_tool="create_booking",
    )


def test_case_filter_selects_one_valid_case() -> None:
    selected = select_cases(
        (prompt_case(), integrated_case()), layer="all", case_ids=("I-1",)
    )
    assert [case.case_id for case in selected] == ["I-1"]


def test_case_filter_selects_multiple_cases() -> None:
    cases = (prompt_case(), integrated_case(), integrated_case("I-2"))
    selected = select_cases(cases, layer="all", case_ids=("P-1", "I-2"))
    assert [case.case_id for case in selected] == ["P-1", "I-2"]


def test_case_filter_rejects_unknown_case_id() -> None:
    with pytest.raises(ValueError, match=r"unknown evaluation case ID\(s\): missing"):
        select_cases((prompt_case(),), layer="all", case_ids=("missing",))


def test_case_and_layer_filters_compose() -> None:
    cases = (prompt_case(), integrated_case())
    selected = select_cases(
        cases, layer="integrated", case_ids=("P-1", "I-1")
    )
    assert [case.case_id for case in selected] == ["I-1"]


@pytest.mark.asyncio
async def test_aggregate_counts_only_selected_cases() -> None:
    cases = select_cases(
        (prompt_case(), replace(prompt_case(), case_id="P-2")),
        layer="prompt_only",
        case_ids=("P-2",),
    )
    report = await EvaluationRunner(Executor(ExecutionCapture("Done"))).run(
        cases, prompt_candidate="candidate", prompt="prompt"
    )
    assert len(report.results) == 1
    assert report.results[0].case.case_id == "P-2"


@pytest.mark.asyncio
async def test_prompt_only_case_execution_and_report() -> None:
    report = await EvaluationRunner(Executor(ExecutionCapture("How may I help?"))).run(
        [prompt_case()], prompt_candidate="fallback", prompt="system prompt"
    )
    assert report.results[0].passed
    assert report.results[0].failure_owner is None


@pytest.mark.asyncio
async def test_integrated_case_requires_real_tool_trace() -> None:
    target = replace(prompt_case(), layer=EvaluationLayer.AGENT_TOOL_INTEGRATED, tool_required=True, expected_tool="create_booking")
    with pytest.raises(ValueError, match="actual tool calls"):
        await EvaluationRunner(Executor(ExecutionCapture("Done"))).run(
            [target], prompt_candidate="fallback", prompt="system prompt"
        )


@pytest.mark.asyncio
async def test_tool_trace_and_critical_regression_blocking() -> None:
    target = replace(prompt_case(), severity="critical", layer=EvaluationLayer.AGENT_TOOL_INTEGRATED, tool_required=True, expected_tool="create_booking")
    good = await EvaluationRunner(Executor(ExecutionCapture("Done", (CapturedToolCall("create_booking", {}, "success"),)))).run([target], prompt_candidate="good", prompt="p")
    bad = await EvaluationRunner(Executor(ExecutionCapture("Error", (), execution_error="service: unavailable"))).run([target], prompt_candidate="bad", prompt="p")
    assert bad.results[0].failure_owner is FailureOwner.SERVICE
    assert select_winner(bad, good) is good


class Judge:
    async def score(self, case, response):
        return 0.0, "too verbose"


@pytest.mark.asyncio
async def test_optional_judge_only_changes_voice_dimension() -> None:
    report = await EvaluationRunner(Executor(ExecutionCapture("A natural response.")), Judge()).run(
        [prompt_case()], prompt_candidate="fallback", prompt="p"
    )
    result = report.results[0]
    assert result.policy.score == result.action.score == 1
    assert result.voice.score == 0
    assert result.failure_owner is FailureOwner.PROMPT


def test_human_readable_report_groups_failures() -> None:
    target = prompt_case()
    capture = ExecutionCapture("Pickup? Destination?")
    report = EvaluationReport(
        "candidate",
        (
            CaseResult(
                target,
                "candidate",
                ScoreDimension(1),
                ScoreDimension(1),
                ScoreDimension(0, ("too many questions",)),
                capture,
                FailureOwner.PROMPT,
            ),
        ),
    )
    text = report_markdown(report)
    assert "prompt: P-1" in text


def test_compact_evidence_report_excludes_fixture_and_user_input() -> None:
    target = prompt_case()
    report = EvaluationReport(
        "candidate",
        (
            CaseResult(
                target,
                "candidate",
                ScoreDimension(1),
                ScoreDimension(1),
                ScoreDimension(1),
                ExecutionCapture("Safe response"),
            ),
        ),
    )

    evidence = report_evidence_dict(report)

    assert evidence["results"][0]["case_id"] == "P-1"
    assert "fixture" not in evidence["results"][0]
    assert "user_input" not in evidence["results"][0]
