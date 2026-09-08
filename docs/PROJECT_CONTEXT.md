# BoloRide — Project Context

## Product summary

**BoloRide** is a multilingual voice-first ride-booking experience for people who find conventional smartphone ride-booking workflows difficult.

The user should be able to speak naturally, for example:

> "Kal subah 6:30 ghar se Kota station jaana hai."

The system should understand the request, resolve saved places and spoken locations, ask only necessary clarifying questions, confirm the journey, perform a mock booking, and return driver/vehicle details through voice.

The product is intentionally framed as an **accessible conversational mobility interface**, not merely "Uber by phone".

## Hackathon implementation strategy

Development is staged to reduce cost and integration risk.

### Stage 1 — LiveKit console

Build and stabilize the conversational agent without PSTN telephony costs.

Focus on:
- voice session lifecycle
- STT/LLM/TTS loop
- explicit conversation state
- location resolution
- tools
- booking business rules
- mock ride provider
- Langfuse prompts/traces/evals

### Stage 2 — Twilio

Add real telephone calling after the core interaction is stable.

Keep telephony behind an adapter so that Twilio-specific logic never enters the domain or booking services.

### Stage 3 — Exotel / Plivo near submission

If useful for the final India-focused demonstration, swap or add a telephony provider near submission time while preserving the same agent and business logic.

## Demo target

A strong demonstration should show more than a happy-path chatbot.

Example flow:
1. Caller speaks in Hindi/Hinglish.
2. Caller asks for a ride from a saved place such as "Ghar" to a station.
3. Agent identifies an ambiguous location and asks a focused clarification.
4. Caller changes the requested time.
5. Agent updates state correctly instead of restarting the booking.
6. Agent asks for final confirmation.
7. Mock ride provider returns a booking.
8. Agent speaks driver and vehicle information.
9. Langfuse trace shows the STT/LLM/tool/booking path.

## Why the mock provider is deliberate

The hackathon should demonstrate the conversational accessibility layer, location reasoning, corrections, safe tool use, and booking workflow.

A real ride-hailing marketplace API is not required to prove those capabilities and must not become a blocker.

Therefore:

```text
RideService
    ↓
RideProvider interface
    ↓
MockRideProvider     ← hackathon
FutureUberAdapter    ← optional future work
FutureOlaAdapter     ← optional future work
```

## Key product problem

Conventional ride-booking systems generally assume that users can navigate a digital interface. BoloRide explores whether modern multilingual voice systems can reduce that interface burden by making the booking process conversational.

The difficult technical parts are not merely speech recognition or text generation. They include:
- grounding informal location descriptions
- resolving saved places
- correcting previously supplied information
- handling partial information
- avoiding premature bookings
- preserving state over several turns
- dealing with STT errors on Indian place names and names
- providing concise voice-friendly responses

## Non-goals for the initial version

The first hackathon version does not need:
- payments
- driver dispatch algorithms
- maps dashboard
- customer mobile application
- driver application
- production-scale marketplace matching
- multiple ride marketplaces
- sophisticated identity/authentication system
- multi-agent system
- LangGraph solely for visual complexity

## Identity and verification

Do not present the last four digits of a phone number as strong authentication.

Caller identification, ride verification, and account security are separate concerns.

For an early prototype, caller identity may be restricted to a trusted test caller. If ride verification is demonstrated, prefer an explicit ride PIN or other clearly scoped mechanism rather than over-claiming security.

## Voice-specific design principles

Voice interactions should be shorter than equivalent chat interactions.

Avoid:
- long explanations
- repeatedly restating every field
- asking for data that is already known
- forcing a strict question sequence

Prefer:
- short confirmations
- focused ambiguity resolution
- natural corrections
- interruption-friendly state updates
- clear final confirmation before side effects
