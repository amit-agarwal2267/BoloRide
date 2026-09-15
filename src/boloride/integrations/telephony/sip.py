from collections.abc import Iterable
from typing import Protocol

from livekit import rtc


class SIPParticipant(Protocol):
    kind: int
    attributes: dict[str, str]


def trusted_sip_caller_phone(
    participants: Iterable[SIPParticipant], expected_trunk_id: str | None
) -> str | None:
    """Resolve a caller only from the configured inbound SIP trust boundary."""
    if not expected_trunk_id:
        return None
    for participant in participants:
        if participant.kind != rtc.ParticipantKind.PARTICIPANT_KIND_SIP:
            continue
        attributes = participant.attributes
        if not isinstance(attributes, dict):
            continue
        if attributes.get("sip.trunkID") != expected_trunk_id:
            continue
        caller = attributes.get("sip.phoneNumber")
        if isinstance(caller, str) and caller.strip():
            return caller
    return None
