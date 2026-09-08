# BoloRide — Evaluation Strategy

## Purpose

BoloRide should use evaluations as a regression system, not as a decorative "AI score".

The goal is to answer questions such as:
- Did a prompt change break location extraction?
- Did a cheaper model start booking before confirmation?
- Which STT provider better understands Indian place names?
- Does a fallback model preserve tool behavior?
- Did clarification quality improve without reducing booking accuracy?

Results should be stored in Langfuse so prompt/model experiments are comparable over time.

## Raw transcript files are source material, not the final dataset

If existing conversations are stored as `.txt`, keep them, but convert each relevant transcript into a structured evaluation case.

Suggested structure:

```text
evals/
├── conversations/
│   ├── booking_basic.txt
│   ├── ambiguous_station.txt
│   ├── change_time.txt
│   └── saved_place.txt
│
├── expected.json
└── README.md
```

A transcript might be:

```text
User: Mujhe kal subah ghar se Kota station jaana hai.
Assistant: Kis time jaana hai?
User: 6:30.
Assistant: Ghar se Kota Junction ke liye kal 6:30 AM ride book karun?
User: Haan.
```

The corresponding expected record should describe behavior, not exact prose:

```json
{
  "booking_basic": {
    "intent": "book_ride",
    "pickup": "home",
    "destination": "Kota Junction",
    "ride_time": "06:30",
    "confirmation_required": true,
    "should_book": true
  }
}
```

Do not require exact assistant wording unless wording itself is what the test is measuring.

## Evaluate structured state

For evaluation, the agent should expose structured outputs in addition to natural language.

Conceptual output:

```json
{
  "assistant_response": "...",
  "state": {
    "intent": "book_ride",
    "pickup": "home",
    "destination": "Kota Junction",
    "ride_time": "06:30",
    "user_confirmed": true,
    "booking_created": true
  },
  "tool_calls": [
    "resolve_location",
    "create_ride"
  ]
}
```

This allows evaluation of actual decisions instead of re-parsing assistant text.

## Evaluation layers

### 1. STT/entity evaluation

Useful for comparing speech providers.

Measure important entities such as:
- place names
- names
- dates
- times
- numbers
- corrections

Generic word error rate is less important than whether critical ride-booking entities survive transcription.

### 2. Deterministic agent evaluation

Use exact code-based evaluators for properties with a known answer.

Examples:
- intent accuracy
- expected destination
- expected pickup
- expected time
- expected tool selection
- confirmation obtained before booking
- booking created only when allowed
- clarification requested when ambiguity exists

Prefer binary or clearly defined numeric scores.

### 3. LLM-as-a-judge

Use only for subjective dimensions.

Examples:
- was the clarification concise?
- was the response natural in Hindi/Hinglish?
- did the agent unnecessarily repeat information?
- was the response suitable for a voice interaction?

Judge prompts should have narrow rubrics and return structured JSON.

Do not ask an LLM judge vague questions such as "How good was this conversation?"

## Initial dataset size

Start with a small, high-value regression set rather than hundreds of low-quality transcripts.

Aim first for roughly 15–25 cases covering distinct failure modes such as:
- basic booking
- ambiguous pickup
- ambiguous destination
- saved place
- missing time
- change time
- change destination
- user correction
- cancellation
- previous ride reference
- Hindi
- English
- Hinglish
- noisy/STT-corrupted place name
- attempted booking before confirmation

Every dataset item should exist for a reason.

## Langfuse experiment naming

Use experiment names that capture the variable being tested.

Examples:

```text
prompt-v3-gemini-primary
prompt-v4-short-confirmation
assemblyai-vs-groq-stt-kota-entities
fallback-router-v2
```

Store metadata such as:
- prompt name/version/label
- primary model
- fallback model used
- STT provider
- dataset version
- git commit when practical

## Example score set

A run may report:

```text
intent_accuracy             1.00
slot_accuracy               0.92
confirmation_safety         1.00
location_resolution         0.88
booking_success             0.92
clarification_quality       0.83
```

Avoid compressing everything into a single score too early. A single number can hide a critical regression such as perfect conversational style but unsafe booking behavior.

## Safety/business invariants

Some evaluations should be treated as hard invariants.

Examples:
- never create a booking without explicit confirmation
- never create a booking without valid pickup and destination
- do not silently resolve a seriously ambiguous location
- do not duplicate a booking because of a retry

A failure on these should be surfaced prominently rather than averaged away.
