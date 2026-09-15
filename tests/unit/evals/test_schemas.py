import json
from pathlib import Path

import pytest

from boloride.evals.runner import load_cases
from boloride.evals.schemas import EvaluationCase, EvaluationLayer


CASES = Path("src/boloride/evals/cases/voice_agent_v2.json")


def test_voice_agent_v2_dataset_is_valid_and_unique() -> None:
    cases = load_cases(CASES)
    assert len(cases) == 20
    assert len({case.case_id for case in cases}) == 20
    assert {case.layer for case in cases} == set(EvaluationLayer)


def test_tool_required_must_match_integrated_layer() -> None:
    with pytest.raises(ValueError, match="tool_required"):
        EvaluationCase.from_dict({
            "case_id": "bad", "category": "bad", "severity": "normal",
            "layer": "prompt_only", "user_input": "hello", "tool_required": True,
            "expected_tool": "some_tool",
        })


def test_dataset_uses_one_canonical_json_representation() -> None:
    payload = json.loads(CASES.read_text(encoding="utf-8"))
    assert isinstance(payload, list)
    assert all("case_id" in item for item in payload)


def test_all_integrated_cases_have_explicit_typed_fixtures() -> None:
    cases = load_cases(CASES)
    integrated = [case for case in cases if case.tool_required]
    assert [case.case_id for case in integrated] == [
        "VA2-001", "VA2-002", "VA2-005", "VA2-006", "VA2-008",
        "VA2-009", "VA2-010", "VA2-014", "VA2-015", "VA2-019",
        "VA2-020",
    ]
    assert all(case.fixture is not None for case in integrated)


def test_integrated_case_rejects_missing_fixture() -> None:
    with pytest.raises(ValueError, match="explicit fixture"):
        EvaluationCase.from_dict({
            "case_id": "bad-integrated", "category": "bad",
            "severity": "normal", "layer": "agent_tool_integrated",
            "user_input": "hello", "tool_required": True,
            "expected_tool": "some_tool",
        })


def test_symbolic_integrated_shortcuts_are_removed() -> None:
    payload = json.loads(CASES.read_text(encoding="utf-8"))
    integrated = [item for item in payload if item["layer"] == "agent_tool_integrated"]
    forbidden = {"current_quote", "quote_prerequisites_complete", "has_ride", "offer_available"}
    assert all(not forbidden.intersection(item.get("initial_state", {})) for item in integrated)
