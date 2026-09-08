# BoloRide — Architecture Guide

## High-level architecture

```text
                    ┌──────────────────────────┐
                    │ LiveKit Console / PSTN   │
                    │ Twilio / Exotel / Plivo  │
                    └────────────┬─────────────┘
                                 │
                                 ▼
                    ┌──────────────────────────┐
                    │      Agent Session       │
                    │     session/context      │
                    └────────────┬─────────────┘
                                 │
               ┌─────────────────┼──────────────────┐
               ▼                 ▼                  ▼
             STT               LLM/TTS          Langfuse
               │                 │           prompts/traces/evals
               └──────────┬──────┘
                          ▼
                    Voice Agent
                          │
                          ▼
                        Tools
                          │
                          ▼
                       Services
                 ┌────────┼─────────┐
                 ▼        ▼         ▼
             Location    Ride      Offer
             Service    Service    Service
                 │        │
                 ▼        ▼
              Maps     RideProvider
             adapter      adapter
                          │
                          ▼
                    MockRideProvider

                         +

                    Repositories
                          │
                          ▼
                      PostgreSQL
```

## Repository responsibilities

### `agents/`

Owns conversation/session behavior.

Should contain:
- agent construction
- lifecycle hooks
- session setup
- context/state management
- voice-agent instructions wiring

Should not contain:
- raw SQL
- maps SDK calls
- ride-provider SDK calls
- large business-rule implementations

### `tools/`

The tool boundary exposed to the LLM.

Tools should:
- accept validated structured inputs
- call a service
- return structured results
- expose only capabilities the model is allowed to invoke

Tools should not become a second service layer.

### `services/`

Owns application/business use cases.

Examples:
- resolving a location
- preparing a booking
- checking whether a ride can be booked
- saving a place
- listing previous rides
- estimating offers

Services coordinate domain rules, repositories, and external integrations.

### `domain/`

Owns provider-independent business concepts.

Examples:
- Ride
- Location
- User
- Offer
- ride status
- booking policies
- validation rules
- domain exceptions

Domain code should not import LiveKit, Langfuse, Google Maps, Twilio, SQLAlchemy session objects, or vendor SDKs.

### `repositories/`

Owns persistence access.

Repositories should hide database query details from services.

Avoid generic "god repositories". Prefer capability/entity-specific repositories.

### `integrations/`

Owns external-provider adapters.

Current categories:
- Langfuse
- maps
- ride provider
- telephony

Provider-specific errors should be translated into application/domain-level errors before crossing architectural boundaries where practical.

### `llm/`

Owns model abstraction and routing.

Responsibilities:
- provider-neutral request configuration
- primary/fallback selection
- timeout/retry policy
- error classification
- model metadata for observability

Do not put business decisions in the LLM router.

### `speech/`

Owns STT/TTS provider adapters and provider routing.

Important evaluation focus:
- Indian names
- Indian place names
- Hindi/Hinglish code-switching
- times
- digits
- corrections

### `prompts/`

Runtime prompt access.

Langfuse is the primary source.

`fallback/` contains only minimal outage-safe prompts.

### `observability/`

Owns cross-cutting observability concerns such as:
- correlation IDs
- structured logging
- trace helpers
- metrics

The rest of the application should call wrappers rather than scatter vendor-specific tracing calls everywhere.

## RideContext

The conversation must maintain explicit structured state.

A conceptual shape:

```python
RideContext(
    session_id,
    caller_id,
    intent,
    pickup,
    destination,
    ride_time,
    ride_type,
    selected_offer,
    user_confirmed,
    booking_id,
    booking_confirmed,
    clarification_required,
)
```

This is illustrative, not a frozen schema. Any implementation must first propose the exact fields and types for approval.

## Agent vs business rules

The LLM is allowed to reason about what should happen next.

It is **not** trusted to authorize side effects.

Example:

```text
LLM decides:
"I now have enough information to call create_ride."

BookingService checks:
- pickup exists
- destination exists
- time is valid
- pickup != destination
- user explicitly confirmed
- no conflicting active request exists
- idempotency conditions are satisfied

Only then:
RideProvider.create_ride(...)
```

This prevents prompt/model errors from becoming business-side effects.

## LangGraph decision

Do not add LangGraph in the initial version merely because the application is agentic.

The conversation is naturally non-linear:
- user can provide multiple slots at once
- user can correct previously supplied data
- user can change intent
- user can interrupt

A rigid graph may make this harder.

Consider LangGraph only when there is a concrete requirement such as:
- long-running workflows
- approval checkpoints
- deterministic branching across several independent subsystems
- complex cancellation/refund/reschedule workflows
- human escalation
- persistent resumable workflow state

## Telephony abstraction

Telephony is transport, not business logic.

Desired boundary:

```text
integrations/telephony/
├── livekit.py
├── twilio.py
├── exotel.py
└── ...
```

The application must not require the booking code to know whether the caller came from LiveKit console, Twilio, Exotel, or another provider.

## Location resolution

Location grounding is a first-class service.

It should support concepts such as:
- free-text place search
- candidate ranking
- ambiguity handling
- saved places
- coordinates
- normalized display name

The agent should not silently pick a low-confidence place when multiple meaningful candidates exist.

## Persistence

The database schema must be designed from query and lifecycle requirements rather than mirrored directly from API request models.

Likely entity areas include:
- users/callers
- saved places
- rides
- ride status/history where justified
- offers if persisted
- provider metadata where justified

Do not create all tables until their required fields and relationships have been reviewed.
