# BoloRide — Implementation Plan Template

Use this template before beginning any code change. Submit the completed plan to the user and wait for approval.

## Task

Describe the requested change in one or two sentences.

## Current state

State what currently exists in the relevant files. Do not assume empty skeleton files are implemented.

## Proposed implementation

Explain the approach and architectural boundaries involved.

## Files to change

```text
path/to/file.py      — reason
path/to/test.py      — reason
...
```

## Dependencies

State either:

```text
No new dependencies.
```

or list each package, why it is needed, and the planned `uv add` command.

## Configuration changes

List:
- new environment variables
- `.env.example` changes
- Docker/Compose changes

If none, say so.

## Database changes

State whether the task changes persistence.

If yes, propose before coding:
- entity/table changes
- columns/types
- constraints
- relationships
- indexes and their query rationale
- PostgreSQL extensions
- migration filenames/order
- downgrade behavior

Example:

```text
003_create_saved_place_table.py
004_create_saved_place_indexes.py
```

Do not create migrations before the schema design is approved.

## Error/failure behavior

List expected failure cases and how they should be handled.

## Observability

Describe:
- log events
- Langfuse spans/generations if relevant
- correlation identifiers
- sensitive values that must not be logged

## Test plan

Specify:
- unit tests
- integration tests
- contract tests
- migration checks
- important edge cases

All application/tests/migrations will be executed through Docker.

## Commands to verify after approval

Example only; adapt to the task:

```bash
docker compose up -d --build

docker compose exec boloride uv run alembic upgrade head

docker compose exec boloride uv run pytest
```

## Trade-offs / open decisions

Clearly state anything that needs user approval.

## Approval checkpoint

End the plan with:

> Waiting for approval before implementation.
