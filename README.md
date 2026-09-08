# BoloRide

BoloRide is an early-stage multilingual conversational ride-booking service.
This repository currently provides only the application foundation: FastAPI,
typed environment configuration, structured logging, PostgreSQL connectivity,
health checks, and Alembic migrations.

## Local setup

Copy `.env.example` to `.env` and replace its development placeholders. At a
minimum, `POSTGRES_PASSWORD` and the matching async `DATABASE_URL` must be set.

All application operations run in Docker:

```bash
docker compose up -d --build
docker compose exec boloride uv run alembic upgrade head
docker compose exec boloride uv run pytest
```

If the local Docker CLI does not have the `buildx` plugin, build with Docker's
legacy builder and then let Compose start the tagged image:

```bash
DOCKER_BUILDKIT=0 docker build -t boloride-boloride .
docker compose up -d --no-build
```

The health endpoints are:

- `GET /health/live` for process liveness
- `GET /health/ready` for PostgreSQL readiness

Application logs are emitted as JSON to stdout. Do not put real secrets in
`.env.example` or commit `.env`.

## Langfuse

Langfuse is the primary prompt source and local prompt files are outage-only
fallbacks. Configure the `LANGFUSE_*` values in `.env`, then start the separate
stack on the shared Docker network:

```bash
docker compose -f docker-compose.langfuse.yml up -d
```

The application remains live when Langfuse is unavailable. Prompt retrieval
uses the local fallback only when the configured managed prompt cannot be read.

## LiveKit voice demo

Set `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`,
`ASSEMBLYAI_API_KEY`, the configured LLM and maps provider credentials, and a
normalized Indian `DEVELOPMENT_CALLER_PHONE`. Then run:

```bash
docker compose up -d --build postgres boloride
docker compose exec boloride uv run alembic upgrade head
docker compose --profile voice up -d voice-agent
docker compose logs -f voice-agent
```

Open the LiveKit Agents Playground for the project, dispatch/connect to the
`boloride-dev` agent, and enable the microphone. A useful manual script is:

```text
Kal subah 7 baje ghar se Kota railway station jaana hai.
Nahi, 6:30 kar do.
Haan, book kar do.
```

Expected behavior: the agent checks saved places, searches the selected Google
or Ola maps provider, asks you to select among ambiguous candidates, replaces
the time and invalidates any earlier confirmation, summarizes the final ride,
then persists a booked ride only after the final confirmation. Inspect JSON
logs with the command above and traces at `http://localhost:3000`. Confirm the
database row with:

```bash
docker compose exec postgres psql -U boloride -d boloride -c "select id,status,requested_ride_at,provider from rides order by created_at desc limit 5;"
```

Edge TTS is keyless but network-backed, so the voice container needs outbound
network access. It is intended only for this development demo.
