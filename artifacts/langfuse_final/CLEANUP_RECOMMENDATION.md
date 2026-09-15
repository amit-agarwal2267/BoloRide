# Cleanup Recommendation

Do not delete anything until the five prompts, compact datasets, and evaluator
have been imported and verified manually in Langfuse.

## KEEP

- All five checked-in fallback prompts needed for outage resilience.
- Candidate 4 source (`voice_agent_v5.md`) until it is deliberately installed
  as the permanent Voice Agent fallback and its provenance is retained.
- The complete 20-case Voice Agent dataset for local regression.
- `schemas.py`, `scorers.py`, `runner.py`, `agent_executor.py`,
  `fixture_builder.py`, `integrated_factory.py`, and database-isolation support.
- Tests protecting policy, real tool behavior, state mutation, quote and
  confirmation invalidation, booking, cancellation, and provider outcomes.
- Existing BoloRide-owned Langfuse client, prompt, tracing, and observability
  boundaries.
- This compact final artifact set, or an equivalent version-controlled seed.

## MOVE

- In a later task, move the final prompt/dataset/evaluator definitions that must
  seed Langfuse into a compact version-controlled seed directory beside the
  existing Langfuse integration.
- Keep the executable deterministic harness under `boloride.evals`; it should
  remain independent of Langfuse availability.

Suggested future shape:

```text
src/boloride/integrations/langfuse/
├── client.py
├── prompts.py
├── bootstrap.py
└── seed/
    ├── prompts/
    ├── datasets/
    └── evaluators/
```

Any future bootstrap must be explicit, idempotent, and manual or
deployment-time. It must not mutate Langfuse during normal application startup
or silently overwrite production prompt versions.

## DELETE_AFTER_VERIFICATION

- Rejected Voice Agent candidates and temporary comparison reports after the
  selected Candidate 4 prompt and decision evidence are safely retained.
- Candidate 5 (`voice_agent_v6.md`) and Candidate 6 (`voice_agent_v7.md`) are
  rejected experiments, not production selections.
- One-off stability-run outputs and disposable candidate-specific datasets.
- The older `artifacts/langfuse_export/voice_agent/` manual export once this
  final compact export is verified and retained.
- Other temporary Stage 12 migration/export artifacts proven obsolete during
  the dedicated cleanup task.

Do not perform these deletions as part of Langfuse preparation.
