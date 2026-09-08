# BoloRide — Codex Instructions

This file is the primary operating guide for any coding agent working in this repository.

## 1. Project status

BoloRide is an early-stage hackathon project. The repository structure already exists, but **almost every source file is currently empty**. Do not assume that a file name means the feature is implemented.

Currently implemented or configured:
- project skeleton
- `pyproject.toml`
- `uv.lock`
- Alembic initialized
- `.env.example`
- `docker-compose.yml`
- `docker-compose.langfuse.yml`

Everything else must be implemented incrementally.

## 2. Mandatory workflow before coding

**Do not start implementation immediately.**

Before every task:
1. Inspect the relevant existing files.
2. Explain what you believe the task requires.
3. Produce a concise implementation plan.
4. List files that will be created or changed.
5. List dependencies, migrations, environment variables, and tests affected.
6. Call out assumptions, trade-offs, or risky decisions.
7. **Wait for explicit user approval before editing code.**

Do not silently make architectural decisions that have not been approved.

If the requested change conflicts with this documentation, point out the conflict before implementation.

## 3. Package and command rules

Use **`uv` only** for Python dependency and command management.

Allowed examples:

```bash
uv add fastapi
uv add --dev pytest
uv sync
uv run alembic upgrade head
uv run pytest
uv run ruff check .
```

Do not use:

```bash
pip install ...
python app.py
python -m pytest
```

When a command needs to execute the BoloRide application, tests, migrations, or application services, run it through Docker unless the user explicitly says otherwise.

## 4. Docker-only runtime rule

Do not run the application directly on the host machine.

Use Docker for:
- starting BoloRide
- running tests
- running Alembic migrations
- integration checks
- local application debugging
- service-to-service validation

Preferred patterns:

```bash
docker compose up -d --build

docker compose exec boloride uv run pytest

docker compose exec boloride uv run alembic upgrade head
```

Langfuse runs separately through:

```bash
docker compose -f docker-compose.langfuse.yml up -d
```

Do not replace Docker-based verification with local execution for convenience.

## 5. Core product

BoloRide is a multilingual conversational ride-booking system intended for people who find app-based ride booking difficult.

Initial interaction path:

```text
LiveKit console / voice session
        ↓
STT
        ↓
BoloRide conversational agent
        ↓
LLM + explicit RideContext
        ↓
Tool calls
        ↓
Business services
        ↓
Location provider / mock ride provider / persistence
        ↓
TTS response
```

Initial development uses the LiveKit console. Telephony adapters are introduced later, beginning with Twilio and later optionally Exotel or Plivo.

The hackathon does **not** depend on a real Uber/Ola/Rapido booking API. The ride-provider boundary must support a mock provider for the demonstration.

## 6. Architectural boundaries

Respect these responsibilities:

```text
agents/          decides what the conversation needs next
tools/           safe capabilities exposed to the agent
services/        business logic and validation
domain/          core business models, rules, enums, policies
repositories/    persistence interfaces / database access
integrations/    external provider adapters
schemas/         API/tool transport schemas
speech/          STT/TTS provider abstractions
llm/             model/provider abstractions and routing
prompts/         Langfuse prompt access + local emergency fallbacks
observability/   tracing, metrics, correlation, structured logging
```

Avoid shortcuts such as:

```text
Agent → raw SQL
Agent → Google Maps SDK directly
Agent → ride provider directly
API route → business rules embedded inline
```

Preferred flow:

```text
Agent
  ↓
Tool
  ↓
Service
  ↓
Domain validation
  ↓
Integration / Repository
```

## 7. Conversation design

Do not implement the voice conversation as a rigid step-by-step graph unless a later requirement justifies it.

A caller may provide pickup, destination, time, corrections, or a new intent in any order.

Maintain explicit structured session state such as:

```text
RideContext
- session_id
- caller_id
- intent
- pickup
- destination
- ride_time
- ride_type
- selected_offer
- user_confirmed
- booking_id
- booking_confirmed
- clarification state
```

The LLM may decide what information is missing, but **business logic must decide what actions are allowed**.

Example: `create_ride` must reject a booking if required fields or confirmation are missing, even if the LLM calls the tool incorrectly.

## 8. Langfuse is required from day one

Langfuse is not optional infrastructure in this project.

It is used for:
- prompt management
- prompt versioning / labels
- traces
- generations
- tool spans
- evaluation results
- model / prompt comparison

Langfuse is the source of truth for actively managed prompts.

Local prompt files under `src/boloride/prompts/fallback/` exist only as outage-safe fallbacks.

Do not hard-code large production prompts in Python modules.

Prefer prompt lookup by stable name and label, for example:

```text
boloride-voice-agent
boloride-location-clarification
boloride-booking-confirmation
boloride-error-recovery
```

Use environment-controlled labels such as `development` and `production` instead of hard-coding a prompt version number.

## 9. Observability rules

Create traceable boundaries from the beginning.

A voice session should be correlatable across:
- application logs
- Langfuse trace
- RideContext
- tool execution
- provider calls
- booking events

Use a shared `session_id` / correlation ID.

Typical trace shape:

```text
voice_session
├── stt
├── llm_turn
├── resolve_location
├── estimate_fare
├── create_booking
└── tts
```

Structured logs should be JSON-friendly and include fields such as:
- timestamp
- level
- event
- request_id
- session_id
- tool/provider name
- latency
- error type

Do not blindly log:
- raw phone numbers
- API keys
- tokens
- full addresses
- unredacted transcripts
- sensitive personal information

## 10. Database and Alembic rules

Database design must be deliberate before migration files are written.

For every database change:
1. Define the domain entities and relationships first.
2. Decide data types and constraints.
3. Normalize the schema appropriately.
4. Decide required PostgreSQL extensions.
5. Decide indexes based on actual query patterns.
6. Consider uniqueness, foreign keys, delete behavior, nullability, timestamps, and idempotency.
7. Then create the migration.

Do not create a single giant initial migration.

Use small, ordered, descriptive migrations, for example:

```text
001_create_extensions.py
002_create_user_table.py
003_create_saved_place_table.py
004_create_driver_table.py
005_create_ride_table.py
006_create_offer_table.py
007_create_indexes.py
```

Names may differ based on the approved schema, but the versioning principle must remain.

Every migration must define a meaningful `upgrade()` and `downgrade()` when technically safe.

Do not add indexes "just in case". State the query pattern each non-trivial index supports.

Do not denormalize merely for convenience unless the trade-off is explicitly approved.

## 11. Provider abstractions

External providers must remain replaceable.

Planned boundaries include:

```text
STT
- Groq Whisper during early development
- AssemblyAI for hackathon-compatible evaluation/integration

LLM
- provider-neutral router
- Google models
- Groq fallback models

TTS
- local provider during prototype
- replaceable in production

Telephony
- LiveKit development interaction
- Twilio later
- Exotel / Plivo optional near submission

Maps
- Google Maps initially behind `maps/base.py`

Ride provider
- mock implementation for hackathon
- future real provider adapters
```

Do not couple business logic to any specific vendor SDK.

## 12. LLM routing

Do not introduce a separate LLM gateway solely because multiple models exist.

Start with the repository's thin provider-neutral router under `llm/`.

A gateway may be introduced later only if centralized routing, usage accounting, rate limiting, failover, or provider management becomes complex enough to justify it.

Fallbacks should handle infrastructure/model failures. They must not silently hide deterministic business-rule failures.

## 13. Tool design

Tools should be narrow, typed, auditable capabilities.

Examples:

```text
location
- resolve_location
- search_location
- get_saved_places

rides
- create_ride
- get_previous_rides
- get_ride
- modify_ride
- cancel_ride

offers
- estimate_fare
- get_available_offers
```

A tool should not contain large amounts of business logic. Delegate to services.

Use structured input/output schemas for tool calls.

## 14. Testing expectations

A feature is not complete merely because the happy path works.

Use:
- unit tests for business logic and deterministic utilities
- integration tests for database/provider boundaries
- contract tests for provider adapters
- voice-pipeline integration tests where practical

Prioritize failure cases such as:
- missing confirmation
- ambiguous location
- invalid state transition
- provider timeout
- fallback provider failure
- duplicate booking request
- database failure
- malformed tool arguments

Do not mock everything. Tests should validate meaningful boundaries.

## 15. Evaluation strategy

Conversation evaluations belong in the project from an early stage.

Existing `.txt` conversations should be converted into explicit evaluation cases rather than scored as raw text blobs.

Each case should include:
- transcript/input
- expected intent
- expected extracted fields
- expected tool behavior
- whether clarification is required
- whether booking is permitted
- expected business outcome

Use deterministic evaluators whenever the answer can be checked exactly, such as:
- intent equality
- slot extraction
- destination resolution
- confirmation requirement
- tool selection
- booking-state correctness

Use LLM-as-a-judge only for subjective dimensions such as:
- clarity
- naturalness
- unnecessary repetition
- quality of clarification
- Hindi/Hinglish conversational quality

Store experiment results and scores in Langfuse.

## 16. Scope discipline

Initial hackathon scope:
- conversational ride request
- multilingual / Hindi-Hinglish capable interaction
- pickup/destination resolution
- saved places
- time handling
- correction handling
- confirmation
- mock booking
- driver/vehicle response
- traces and evals

Avoid expanding the first version into:
- passenger mobile app
- driver mobile app
- payment gateway
- dispatch optimization
- complex maps UI
- general-purpose assistant
- multi-agent architecture without need
- LangGraph without a concrete workflow requirement
- real marketplace integration as a demo blocker

## 17. Definition of done for each task

Before claiming a task is complete, verify:
- approved implementation plan was followed
- dependencies were added through `uv`
- configuration is represented in `.env.example` if needed
- application/tests were run through Docker
- migrations were applied/tested if relevant
- unit/integration tests were added where relevant
- health/readiness behavior still works
- structured logs/traces are meaningful
- no secrets or sensitive data were committed
- README/docs were updated if developer workflow changed

If verification cannot be completed, clearly state what remains unverified.
