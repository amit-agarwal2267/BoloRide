# voice_response_quality

- Type: LLM judge
- Purpose: Judge naturalness, conciseness, friendliness, spoken clarity, and compatibility with the expected language.
- Inputs: `expected_language`, `required_meaning`, `response`
- Output: JSON with numeric Boolean `score` and a short `explanation`
- Score range: `0` or `1`
- Pass criterion: `score == 1`
- Model configuration: use the configured Langfuse evaluator model; the current BoloRide implementation does not prescribe a model or sampling parameters.

## Exact current system prompt

```text
Evaluate only naturalness, conciseness, friendliness, and spoken clarity. Do not judge tool or business-policy correctness. Return JSON with score 0 or 1 and a short explanation.
```

## Current input representation

```json
{"expected_language":"{{expected_language}}","required_meaning":"{{required_meaning}}","response":"{{response}}"}
```

## Expected judge output

```json
{"score":1,"explanation":"Short explanation"}
```

This evaluator must not judge tool selection, backend state, booking, pricing,
identity, cancellation, or other deterministic business correctness.
