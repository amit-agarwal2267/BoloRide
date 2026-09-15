# Evaluation Boundary

Create only `voice_response_quality` in Langfuse. It evaluates conversational
delivery and expected-language compatibility, not business correctness.

Keep the existing deterministic evaluators local. They require evidence that a
plain prompt experiment does not possess: actual tool calls and arguments,
tool outcomes, `RideContext` before/after state, passenger and vehicle state,
quote identifiers and fingerprints, confirmation invalidation, booking and
cancellation state, provider results, and session lifecycle state.

The minimal Langfuse evaluator supplements these checks; it does not replace
them and does not justify expanding the evaluation framework for source freeze.
