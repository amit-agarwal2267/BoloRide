# BoloRide Langfuse Final Hackathon Assets

This directory contains the source-freeze prompt, compact dataset, and minimal
evaluator artifacts for manual Langfuse configuration. Runtime prompts remain
managed in Langfuse with checked-in outage fallbacks; these files do not mutate
Langfuse automatically.

## Manifest

| Langfuse prompt name | Selected source | Version | Dataset | Rows | Evaluator |
|---|---|---|---|---:|---|
| `boloride-voice-agent` | `src/boloride/prompts/candidates/voice_agent_v5.md` | Candidate 4 / `v1.0.5` | `datasets/boloride-voice-agent.csv` | 10 | `voice_response_quality` |
| `boloride-location-clarification` | `src/boloride/prompts/fallback/location_clarification.md` | Current repository fallback; semantic version not recorded | `datasets/boloride-location-clarification.csv` | 10 | `voice_response_quality` |
| `boloride-booking-confirmation` | `src/boloride/prompts/fallback/booking_confirmation.md` | Current repository fallback; semantic version not recorded | `datasets/boloride-booking-confirmation.csv` | 10 | `voice_response_quality` |
| `boloride-error-recovery` | `src/boloride/prompts/fallback/error_recovery.md` | Current repository fallback; semantic version not recorded | `datasets/boloride-error-recovery.csv` | 10 | `voice_response_quality` |
| `boloride-offer-explanation` | `src/boloride/prompts/fallback/offer_explanation.md` | Current repository fallback; semantic version not recorded | `datasets/boloride-offer-explanation.csv` | 10 | `voice_response_quality` |

Authoritative Voice Agent selection:

```yaml
name: boloride-voice-agent
candidate: Candidate 4
semantic_version: v1.0.5
source: src/boloride/prompts/candidates/voice_agent_v5.md
```

Candidate 5 and Candidate 6 are rejected experiments and are not represented
as selected production prompt history.

## Dataset format

Every JSON item has `input.input`, structured `expected_output`, and metadata.
Every CSV has `id`, `input`, `expected_output`, and `metadata` columns; the last
three columns contain compact JSON. The compact Voice Agent dataset selects ten
high-value cases from the unchanged 20-case local regression dataset. The other
four datasets contain ten prompt-only demonstration cases each.

Only `voice_response_quality` is intended for Langfuse. Deterministic policy,
tool, argument, state, quote, confirmation, booking, cancellation, and provider
checks remain in the local evaluation harness.
