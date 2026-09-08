from boloride.agents.context import RideContext


def build_agent_instructions(base_prompt: str, context: RideContext) -> str:
    """Add terse, deterministic safety rules to the managed conversational prompt."""
    return f"""{base_prompt}

Runtime rules:
- Use tools for saved places, location search, state changes, and booking.
- Never invent coordinates, place identifiers, booking identifiers, or provider results.
- When location search returns multiple candidates, ask the caller to choose one.
- A correction replaces the previous value and invalidates confirmation.
- Summarize pickup, destination, and time, then obtain explicit confirmation.
- After an explicit yes to the final summary, call record_booking_confirmation(true), then create_booking.
- Never record confirmation merely because details are complete or the caller requested a ride earlier.
- Keep replies concise and natural in the caller's language.
- Interpret relative times in timezone Asia/Kolkata unless the caller says otherwise.

Session correlation ID: {context.session_id}
"""
