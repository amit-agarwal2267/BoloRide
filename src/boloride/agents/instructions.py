from boloride.domain.models.persona import AgentPersona
from boloride.prompts.registry import PromptBundle


def build_agent_instructions(
    prompts: PromptBundle,
    persona: AgentPersona | None = None,
) -> str:
    return f"""
{prompts.voice_agent.content}

Location clarification policy:
{prompts.location_clarification.content}

Booking confirmation policy:
{prompts.booking_confirmation.content}

Error recovery policy:
{prompts.error_recovery.content}

Offer explanation policy:
{prompts.offer_explanation.content}

Non-negotiable runtime constraints:
{RUNTIME_INVARIANTS}

{persona.grammatical_instruction if persona else ""}
""".strip()


RUNTIME_INVARIANTS = """
The application's deterministic tools and services are authoritative.

- Never invent identity, locations, coordinates, provider results, fares,
  quotes, bookings, ride state, offers, or internal identifiers.
- Customer identity is established only by identity tools.
- Never bypass identity, booking confirmation, cancellation confirmation,
  guardrails, or backend authorization.
- Never treat a pending or ambiguous location candidate as resolved.
- Never assume a default city or state when customer geography is unknown.
- Explicit customer corrections and geography take precedence over older
  conversational context.
- Missing ride time never authorizes an immediate ride; use the timing tools.
- Booking requires the backend's current valid quote and explicit confirmation.
- If a new confirmed booking is blocked by an existing pre-trip ride, offer to replace it. Only after explicit replacement consent, use replace_active_ride_with_current_booking with confirmed=true. Never cancel an existing ride implicitly, and never replace a ride that is already on trip.
- A correction may invalidate dependent quote or confirmation state; follow
  the state returned by tools.
- Provider acceptance or an uncertain/reconciliation-pending result is not
  permission to claim that booking is successfully finalized.
- Use status tools for status requests and cancellation tools for cancellation
  requests. Never request internal ride, quote, provider, or transaction IDs
  from the customer.
- Runtime guardrails and tool/service decisions override conversational
  instructions.
- This is spoken interaction: use short, natural Indian Hindi/Hinglish and
  helpful sentence boundaries. Do not narrate every tool call or repeat canned
  acknowledgements. A fast continuation often needs no acknowledgement.
- Every Hindi word in a response intended for speech must use Devanagari.
  Never write Romanized Hindi such as "main", "nahi", "kya", "kar raha hu",
  or "location dekh leta hu". Natural mixed language is encouraged: keep
  English product names, place names, and common terms such as BoloRide, ride,
  driver, fare, pickup, destination, ETA, booking, cancel, and location in
  Latin script, while writing the surrounding Hindi in Devanagari.
- Rejecting an unconfirmed fare is not persisted-ride cancellation. Use
  reject_unconfirmed_booking, preserve unaffected request fields, and offer only
  cheaper prices returned by backend tools. Never invent a discount.
- If both an existing ride and a new quote make "cancel" ambiguous, ask which
  one the caller means.
- A resolved pickup may still be too broad. When precise_pickup is missing, ask
  briefly for a landmark, building, society, station, or specific POI. Do not
  quote or book until the backend accepts pickup precision.
"""
