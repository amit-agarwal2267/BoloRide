# 🚕 BoloRide

[![AssemblyAI](https://img.shields.io/badge/AssemblyAI-Universal--3.5--Pro-6C47FF)](https://www.assemblyai.com/)
[![Python](https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![LiveKit](https://img.shields.io/badge/LiveKit-Voice_AI-111111)](https://livekit.io/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-Database-4169E1?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?logo=docker&logoColor=white)](https://www.docker.com/)
[![Langfuse](https://img.shields.io/badge/Langfuse-Observability-111111)](https://langfuse.com/)
[![CI](https://img.shields.io/github/actions/workflow/status/amit-agarwal2267/BoloRide/ci.yml?branch=main&label=CI)](https://github.com/amit-agarwal2267/BoloRide/actions)

**BoloRide** is a voice-first cab-booking prototype that lets a customer book and manage rides through a natural phone conversation.

AssemblyAI Universal-3.5 Pro powers speech-to-text, while BoloRide handles identity, locations, pricing, booking and driver assignment through application-controlled services.

A caller can describe a trip, clarify locations, choose a vehicle, hear
the fare, confirm the ride and receive a simulated driver assignment.

## Why BoloRide?

App-first booking can be difficult for users who are less comfortable
with smartphones or who simply need a faster conversational flow.
BoloRide explores a phone-call-first interface while keeping important
booking decisions inside deterministic backend services.

## What works today

-   Voice-driven booking flow
-   Customer onboarding and verification
-   Pickup and destination clarification
-   Saved places
-   Passenger and vehicle validation
-   Backend-computed fares and eligible offers
-   Booking confirmation, status and cancellation
-   Deterministic demo fleet and nearby-driver assignment
-   Session safeguards and recovery handling
-   Langfuse traces and evaluation artifacts

## Architecture

``` text
Caller
  │
  ▼
LiveKit Voice Session
  │
  ▼
BoloRide Agent
  │
  ├── Identity / Session
  ├── Location & Routing
  ├── Pricing & Offers
  ├── Booking
  └── Driver Dispatch
  │
  ▼
PostgreSQL

Observability ──► Langfuse
```

The LLM handles conversation and tool selection. Identity, pricing,
booking state, ownership and dispatch rules remain
application-controlled.

## Run locally

``` bash
git clone https://github.com/amit-agarwal2267/BoloRide.git
cd BoloRide
cp .env.example .env
docker compose up --build
```

Configure the required provider credentials in `.env` before starting
the voice session.

## Tests

``` bash
pytest
```

For the Docker test environment:

``` bash
docker compose -f docker-compose.test.yml up --build --abort-on-container-exit
```

## Evaluation

BoloRide keeps prompt/evaluation material under
`artifacts/langfuse_final/` and application tests under `tests/`. The
focus is on booking correctness, conversational recovery and observable
voice-agent behaviour.

## Prototype boundaries

BoloRide currently uses a simulated fleet and is not connected to a
commercial cab network or payment system. The project demonstrates the
conversational booking workflow, backend safeguards and operational
architecture rather than claiming production-scale deployment.

## Built for the hackathon 🛠️

BoloRide is an experimental voice interface for making cab booking
accessible through conversation.
