from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from pathlib import Path
from typing import Iterable

from boloride.evals.agent_executor import EvaluationExecutor, require_valid_capture
from boloride.evals.schemas import CaseResult, EvaluationCase, EvaluationReport, ScoreDimension
from boloride.evals.scorers import VoiceJudge, classify_failure, score_action, score_policy, score_voice_deterministically


def load_cases(path: Path) -> tuple[EvaluationCase, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("evaluation dataset must be a JSON list")
    cases = tuple(EvaluationCase.from_dict(item) for item in payload)
    ids = [case.case_id for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("evaluation case IDs must be unique")
    return cases


def select_cases(
    cases: Iterable[EvaluationCase],
    *,
    layer: str,
    case_ids: Iterable[str] = (),
) -> tuple[EvaluationCase, ...]:
    available = tuple(cases)
    requested = tuple(dict.fromkeys(case_ids))
    known_ids = {case.case_id for case in available}
    unknown = [case_id for case_id in requested if case_id not in known_ids]
    if unknown:
        raise ValueError(f"unknown evaluation case ID(s): {', '.join(unknown)}")
    if requested:
        requested_ids = set(requested)
        available = tuple(case for case in available if case.case_id in requested_ids)
    if layer == "prompt_only":
        return tuple(case for case in available if not case.tool_required)
    if layer == "integrated":
        return tuple(case for case in available if case.tool_required)
    return available


class EvaluationRunner:
    def __init__(self, executor: EvaluationExecutor, judge: VoiceJudge | None = None) -> None:
        self._executor = executor
        self._judge = judge

    async def run(self, cases: Iterable[EvaluationCase], *, prompt_candidate: str, prompt: str) -> EvaluationReport:
        results: list[CaseResult] = []
        for case in cases:
            capture = await self._executor.execute(case, prompt)
            require_valid_capture(case, capture)
            policy = score_policy(case, capture)
            action = score_action(case, capture)
            voice = score_voice_deterministically(case, capture)
            explanation = None
            if self._judge is not None and policy.score == action.score == voice.score == 1.0:
                judge_score, explanation = await self._judge.score(case, capture.final_response)
                voice = ScoreDimension(judge_score, () if judge_score else ("semantic voice judge failed",))
            owner = classify_failure(case, capture, policy=policy, action=action, voice=voice)
            results.append(CaseResult(case, prompt_candidate, policy, action, voice, capture, owner, explanation))
        return EvaluationReport(prompt_candidate, tuple(results))


def select_winner(baseline: EvaluationReport, candidate: EvaluationReport) -> EvaluationReport:
    def rank(report: EvaluationReport) -> tuple[float, ...]:
        critical = [result for result in report.results if result.case.severity == "critical"]
        critical_pass_rate = sum(result.passed for result in critical) / len(critical) if critical else 1.0
        return (-report.critical_failures, critical_pass_rate, report.average("policy"), report.average("action"), report.average("voice"))
    return max((baseline, candidate), key=rank)


def report_dict(report: EvaluationReport) -> dict:
    return {
        "prompt_candidate": report.prompt_candidate,
        "total_cases": len(report.results),
        "pass_rate": sum(item.passed for item in report.results) / len(report.results) if report.results else 0.0,
        "critical_failures": report.critical_failures,
        "policy_score": report.average("policy"),
        "action_score": report.average("action"),
        "voice_score": report.average("voice"),
        "results": [asdict(item) for item in report.results],
    }


def report_markdown(report: EvaluationReport) -> str:
    grouped: dict[str, list[str]] = {}
    for result in report.results:
        if result.failure_owner is not None:
            grouped.setdefault(result.failure_owner.value, []).append(result.case.case_id)
    lines = [
        f"# {report.prompt_candidate}",
        "",
        f"Cases: {len(report.results)}",
        f"Critical failures: {report.critical_failures}",
        f"Policy: {report.average('policy'):.1%}",
        f"Action: {report.average('action'):.1%}",
        f"Voice: {report.average('voice'):.1%}",
        "",
        "## Failure ownership",
    ]
    lines.extend(f"- {owner}: {', '.join(case_ids)}" for owner, case_ids in sorted(grouped.items()))
    return "\n".join(lines) + "\n"


def report_evidence_dict(report: EvaluationReport) -> dict:
    """Compact, privacy-safe execution evidence for integrated review."""
    return {
        "prompt_candidate": report.prompt_candidate,
        "total_cases": len(report.results),
        "passed": sum(item.passed for item in report.results),
        "critical_failures": report.critical_failures,
        "policy_score": report.average("policy"),
        "action_score": report.average("action"),
        "voice_score": report.average("voice"),
        "results": [
            {
                "case_id": item.case.case_id,
                "severity": item.case.severity,
                "passed": item.passed,
                "policy": asdict(item.policy),
                "action": asdict(item.action),
                "voice": asdict(item.voice),
                "tools": [asdict(call) for call in item.capture.tool_calls],
                "state_before": item.capture.state_before,
                "state_after": item.capture.state_after,
                "final_response": item.capture.final_response,
                "latency_ms": item.capture.latency_ms,
                "execution_error": item.capture.execution_error,
                "failure_owner": (
                    item.failure_owner.value if item.failure_owner else None
                ),
            }
            for item in report.results
        ],
    }


async def _run_prompt(
    layer: str,
    *,
    prompt_candidate: str,
    voice_prompt_path: Path | None = None,
    case_ids: tuple[str, ...] = (),
    database_url: str | None = None,
) -> EvaluationReport:
    from boloride.agents.instructions import build_agent_instructions
    from boloride.config import get_settings
    from boloride.agents.session import BoloRideLiveKitLLM
    from boloride.db.session import create_database_engine, create_session_factory
    from boloride.evals.agent_executor import (
        LayeredExecutor,
        LiveKitAgentExecutor,
        PromptOnlyLLMExecutor,
        UnconfiguredIntegratedExecutor,
    )
    from boloride.evals.integrated_factory import FixtureBackedAgentFactory
    from boloride.integrations.langfuse.client import LangfuseClient
    from boloride.integrations.langfuse.tracing import LangfuseTracer
    from boloride.llm.router import create_llm_router
    from boloride.prompts.registry import PromptRegistry

    settings = get_settings()
    langfuse = LangfuseClient(settings)
    tracer = LangfuseTracer(langfuse)
    router = create_llm_router(settings, tracer)
    engine = None
    try:
        prompts = PromptRegistry(langfuse, label=settings.langfuse_prompt_label, fallback_enabled=True).get_bundle()
        if voice_prompt_path is not None:
            from dataclasses import replace

            content = voice_prompt_path.read_text(encoding="utf-8").strip()
            if not content:
                raise ValueError("candidate prompt must not be empty")
            prompts = replace(
                prompts,
                voice_agent=replace(
                    prompts.voice_agent,
                    content=content,
                    source="fallback",
                    version=None,
                ),
            )
        prompt = build_agent_instructions(prompts)
        cases = select_cases(
            load_cases(Path("src/boloride/evals/cases/voice_agent_v2.json")),
            layer=layer,
            case_ids=case_ids,
        )
        integrated: EvaluationExecutor = UnconfiguredIntegratedExecutor()
        if layer in {"all", "integrated"}:
            database_settings = (
                settings.model_copy(update={"database_url": database_url})
                if database_url is not None
                else settings
            )
            engine = create_database_engine(database_settings)
            integrated = LiveKitAgentExecutor(
                BoloRideLiveKitLLM(router, session_id="evaluation"),
                FixtureBackedAgentFactory(create_session_factory(engine), prompts),
            )
        executor = LayeredExecutor(PromptOnlyLLMExecutor(router), integrated)
        return await EvaluationRunner(executor).run(
            cases,
            prompt_candidate=prompt_candidate,
            prompt=prompt,
        )
    finally:
        if engine is not None:
            await engine.dispose()
        await router.close()
        langfuse.shutdown()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the temporary BoloRide prompt evaluation lab")
    parser.add_argument("--baseline", action="store_true", help="run the checked-in fallback prompt")
    parser.add_argument(
        "--candidate",
        type=Path,
        help="run one temporary Voice Agent candidate",
    )
    parser.add_argument(
        "--layer", choices=("prompt_only", "integrated", "all"),
        default="prompt_only",
    )
    parser.add_argument(
        "--format", choices=("json", "evidence", "markdown"),
        default="markdown",
    )
    parser.add_argument(
        "--case",
        dest="case_ids",
        action="append",
        default=[],
        metavar="CASE_ID",
        help="run only the named case; may be repeated",
    )
    parser.add_argument(
        "--database-url",
        help="explicit disposable database URL for integrated evaluation",
    )
    args = parser.parse_args()
    if args.baseline == (args.candidate is not None):
        parser.error("choose exactly one of --baseline or --candidate")
    report = asyncio.run(
        _run_prompt(
            args.layer,
            prompt_candidate=(args.candidate.stem if args.candidate else "fallback"),
            voice_prompt_path=args.candidate,
            case_ids=tuple(args.case_ids),
            database_url=args.database_url,
        )
    )
    if args.format == "json":
        print(json.dumps(report_dict(report), default=str, indent=2))
    elif args.format == "evidence":
        print(json.dumps(report_evidence_dict(report), default=str, indent=2))
    else:
        print(report_markdown(report))


if __name__ == "__main__":
    main()
