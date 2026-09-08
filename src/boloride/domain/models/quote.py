import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from boloride.domain.exceptions import DomainValidationError
from boloride.domain.models.location import ResolvedLocation, TollStatus


class FareComponentType(StrEnum):
    BASE_FARE = "base_fare"
    DISTANCE_FARE = "distance_fare"
    NIGHT_CHARGE = "night_charge"
    AIRPORT_FEE = "airport_fee"
    TOLL_ESTIMATE = "toll_estimate"


@dataclass(frozen=True, slots=True)
class PricingRuleDetails:
    id: UUID
    vehicle_type_code: str
    base_fare: Decimal
    per_km_rate: Decimal
    night_charge: Decimal
    airport_fee: Decimal
    currency: str
    active: bool


@dataclass(frozen=True, slots=True)
class FareComponent:
    component_type: FareComponentType
    amount: Decimal


@dataclass(frozen=True, slots=True)
class PricingResult:
    pricing_rule_id: UUID
    vehicle_type_code: str
    route_distance_meters: int
    route_duration_seconds: int | None
    route_provider: str
    components: tuple[FareComponent, ...]
    toll_status: TollStatus
    estimated_total: Decimal
    currency: str

    def component(self, component_type: FareComponentType) -> Decimal:
        return next(
            item.amount
            for item in self.components
            if item.component_type is component_type
        )


@dataclass(frozen=True, slots=True)
class Quote:
    id: UUID
    session_id: str
    request_fingerprint: str
    pricing: PricingResult
    quoted_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        if self.quoted_at.tzinfo is None or self.expires_at.tzinfo is None:
            raise DomainValidationError("quote timestamps must be timezone-aware")
        if self.expires_at <= self.quoted_at:
            raise DomainValidationError("quote expiry must follow creation")

    def is_time_valid(self, now: datetime) -> bool:
        if now.tzinfo is None:
            raise DomainValidationError("quote validation time must be timezone-aware")
        return now < self.expires_at


def request_fingerprint(
    pickup: ResolvedLocation,
    destination: ResolvedLocation,
    requested_ride_at: datetime,
    passenger_count: int,
    vehicle_type_code: str,
) -> str:
    if requested_ride_at.tzinfo is None:
        raise DomainValidationError("requested ride time must be timezone-aware")
    payload = {
        "pickup": _location_identity(pickup),
        "destination": _location_identity(destination),
        "requested_ride_at": requested_ride_at.astimezone(UTC).isoformat(),
        "passenger_count": passenger_count,
        "vehicle_type_code": vehicle_type_code,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _location_identity(location: ResolvedLocation) -> dict[str, str | None]:
    return {
        "provider": location.provider,
        "provider_place_id": location.provider_place_id,
        "latitude": str(location.latitude),
        "longitude": str(location.longitude),
    }
