from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256
from math import asin, cos, radians, sin, sqrt
import re

from boloride.domain.exceptions import DomainValidationError


class AirportClassification(StrEnum):
    AIRPORT = "airport"
    NOT_AIRPORT = "not_airport"
    UNKNOWN = "unknown"


class TollStatus(StrEnum):
    ESTIMATE_AVAILABLE = "estimate_available"
    MAY_APPLY = "may_apply"
    NO_TOLL = "no_toll"
    UNKNOWN = "unknown"


class LocationResolutionStatus(StrEnum):
    RESOLVED = "resolved"
    LIKELY_MATCH_CONFIRMATION_REQUIRED = "likely_match_confirmation_required"
    CLARIFICATION_REQUIRED = "clarification_required"
    NOT_FOUND = "not_found"
    PROVIDER_UNAVAILABLE = "provider_unavailable"


class LocationClarificationReason(StrEnum):
    AMBIGUOUS_CANDIDATES = "ambiguous_candidates"
    AMBIGUOUS_STATE = "ambiguous_state"


class LocationContextSource(StrEnum):
    EXPLICIT_CURRENT_INPUT = "explicit_current_input"
    CONFIRMED_ENDPOINT = "confirmed_endpoint"
    EXPLICIT_CONVERSATION = "explicit_conversation"
    OPPOSITE_ENDPOINT = "opposite_endpoint"
    UNAVAILABLE = "unavailable"


class RouteSanityStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"


_AIRPORT_PLACE_TYPES = frozenset({"airport", "international_airport"})


def _normalize_place_types(value: tuple[str, ...] | None) -> tuple[str, ...] | None:
    if value is None:
        return None
    return tuple(sorted({item.strip().casefold() for item in value if item.strip()}))


def classify_airport(place_types: tuple[str, ...] | None) -> AirportClassification:
    normalized = _normalize_place_types(place_types)
    if not normalized:
        return AirportClassification.UNKNOWN
    if _AIRPORT_PLACE_TYPES.intersection(normalized):
        return AirportClassification.AIRPORT
    return AirportClassification.NOT_AIRPORT


@dataclass(frozen=True, slots=True)
class RouteResult:
    distance_meters: int
    duration_seconds: int | None
    provider: str
    toll_status: TollStatus = TollStatus.UNKNOWN
    toll_estimate: Decimal | None = None
    toll_currency: str | None = None

    def __post_init__(self) -> None:
        if (
            isinstance(self.distance_meters, bool)
            or not isinstance(self.distance_meters, int)
            or self.distance_meters < 0
        ):
            raise DomainValidationError("route distance must be a nonnegative integer")
        if self.duration_seconds is not None and (
            isinstance(self.duration_seconds, bool)
            or not isinstance(self.duration_seconds, int)
            or self.duration_seconds < 0
        ):
            raise DomainValidationError("route duration must be a nonnegative integer")
        provider = self.provider.strip().casefold()
        if not provider:
            raise DomainValidationError("route provider cannot be blank")
        object.__setattr__(self, "provider", provider)
        has_estimate = self.toll_estimate is not None
        if has_estimate != (self.toll_status is TollStatus.ESTIMATE_AVAILABLE):
            raise DomainValidationError("toll estimate must match toll status")
        if has_estimate:
            if not isinstance(self.toll_estimate, Decimal):
                raise DomainValidationError("toll estimate must use Decimal")
            if self.toll_estimate < 0:
                raise DomainValidationError("toll estimate cannot be negative")
            currency = (self.toll_currency or "").strip().upper()
            if len(currency) != 3 or not currency.isalpha():
                raise DomainValidationError("toll currency must be a three-letter code")
            object.__setattr__(self, "toll_currency", currency)
        elif self.toll_currency is not None:
            raise DomainValidationError("toll currency requires an estimate")


@dataclass(frozen=True, slots=True)
class RouteSanityResult:
    status: RouteSanityStatus
    reason: str
    direct_distance_meters: int


@dataclass(frozen=True, slots=True)
class ResolvedLocation:
    address: str
    latitude: Decimal
    longitude: Decimal
    display_name: str | None = None
    provider: str | None = None
    provider_place_id: str | None = None
    place_types: tuple[str, ...] | None = None
    country: str | None = None
    city: str | None = None
    state: str | None = None

    def __post_init__(self) -> None:
        address = self.address.strip()
        if not address:
            raise DomainValidationError("location address cannot be blank")
        if not Decimal("-90") <= self.latitude <= Decimal("90"):
            raise DomainValidationError("latitude must be between -90 and 90")
        if not Decimal("-180") <= self.longitude <= Decimal("180"):
            raise DomainValidationError("longitude must be between -180 and 180")
        display_name = self.display_name.strip() if self.display_name else None
        provider = self.provider.strip().casefold() if self.provider else None
        provider_place_id = (
            self.provider_place_id.strip() if self.provider_place_id else None
        )
        if provider_place_id and not provider:
            raise DomainValidationError(
                "provider is required when provider place ID is provided"
            )
        object.__setattr__(self, "address", address)
        object.__setattr__(self, "display_name", display_name)
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "provider_place_id", provider_place_id)
        object.__setattr__(self, "place_types", _normalize_place_types(self.place_types))
        country = " ".join(self.country.split()).casefold() if self.country else None
        object.__setattr__(self, "country", country or None)
        for field_name in ("city", "state"):
            value = getattr(self, field_name)
            object.__setattr__(self, field_name, " ".join(value.split()) if value else None)

    @property
    def airport_classification(self) -> AirportClassification:
        return classify_airport(self.place_types)

    @property
    def formatted_address(self) -> str:
        return self.address


@dataclass(frozen=True, slots=True)
class LocationSearchContext:
    country: str | None = None
    city: str | None = None
    state: str | None = None
    language: str | None = None
    radius_meters: int | None = None

    def __post_init__(self) -> None:
        for field_name in ("country", "city", "state", "language"):
            value = getattr(self, field_name)
            if value is not None:
                normalized = " ".join(value.split())
                object.__setattr__(self, field_name, normalized or None)
        if self.country:
            object.__setattr__(self, "country", self.country.casefold())
        if self.radius_meters is not None and self.radius_meters <= 0:
            raise DomainValidationError("search radius must be positive")


@dataclass(frozen=True, slots=True)
class LocationCandidate:
    display_name: str
    formatted_address: str
    latitude: Decimal
    longitude: Decimal
    provider: str
    provider_place_id: str | None = None
    confidence: float | None = None
    locality: str | None = None
    city: str | None = None
    state: str | None = None
    country: str | None = None
    place_types: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        for field_name in ("display_name", "formatted_address", "provider"):
            value = " ".join(getattr(self, field_name).split())
            if not value:
                raise DomainValidationError(f"{field_name} cannot be blank")
            object.__setattr__(self, field_name, value)
        if not Decimal("-90") <= self.latitude <= Decimal("90"):
            raise DomainValidationError("latitude must be between -90 and 90")
        if not Decimal("-180") <= self.longitude <= Decimal("180"):
            raise DomainValidationError("longitude must be between -180 and 180")
        if self.provider_place_id:
            object.__setattr__(
                self, "provider_place_id", self.provider_place_id.strip()
            )
        if self.confidence is not None and not 0 <= self.confidence <= 1:
            raise DomainValidationError("confidence must be between 0 and 1")
        object.__setattr__(self, "place_types", _normalize_place_types(self.place_types))

    @property
    def airport_classification(self) -> AirportClassification:
        return classify_airport(self.place_types)

    @property
    def stable_candidate_id(self) -> str:
        material = f"{self.provider}|{self.provider_place_id or ''}|{self.formatted_address}|{self.latitude}|{self.longitude}"
        return sha256(material.encode()).hexdigest()[:20]

    def to_resolved_location(self) -> ResolvedLocation:
        return ResolvedLocation(
            address=self.formatted_address,
            latitude=self.latitude,
            longitude=self.longitude,
            display_name=self.display_name,
            provider=self.provider,
            provider_place_id=self.provider_place_id,
            place_types=self.place_types,
            country=self.country,
            city=self.city,
            state=self.state,
        )


@dataclass(frozen=True, slots=True)
class LocationResolutionResult:
    status: LocationResolutionStatus
    location: ResolvedLocation | None = None
    candidates: tuple[LocationCandidate, ...] = ()
    clarification_reason: LocationClarificationReason | None = None
    provider: str | None = None
    fallback_used: bool = False

    def __post_init__(self) -> None:
        if self.status is LocationResolutionStatus.RESOLVED and self.location is None:
            raise DomainValidationError("resolved result requires a location")
        if self.status is LocationResolutionStatus.LIKELY_MATCH_CONFIRMATION_REQUIRED:
            if self.location is not None or len(self.candidates) != 1:
                raise DomainValidationError(
                    "likely-match result requires exactly one unconfirmed candidate"
                )
        if len(self.candidates) > 3:
            raise DomainValidationError("at most three location candidates may be exposed")


def deduplicate_location_candidates(
    candidates: list[LocationCandidate],
) -> list[LocationCandidate]:
    """Collapse only provider-identical or geographically equivalent results."""
    unique: list[LocationCandidate] = []
    for candidate in candidates:
        if not any(_same_practical_place(candidate, existing) for existing in unique):
            unique.append(candidate)
    return unique


def customer_location_label(candidate: LocationCandidate) -> str:
    """Build a concise distinction using provider-backed fields only."""
    parts: list[str] = [candidate.display_name]
    for value in (candidate.locality, candidate.city, candidate.state):
        if value and _normalized_location_text(value) not in {
            _normalized_location_text(part) for part in parts
        }:
            parts.append(value)
    category = next(
        (
            kind.replace("_", " ")
            for kind in (candidate.place_types or ())
            if kind in {"train_station", "transit_station", "airport", "bus_station"}
        ),
        None,
    )
    if category and category not in candidate.display_name.casefold():
        parts.insert(1, category)
    return ", ".join(parts)


def assess_route_sanity(
    origin: ResolvedLocation,
    destination: ResolvedLocation,
    route: RouteResult,
) -> RouteSanityResult:
    """Reject structured geographic contradictions, never distance alone."""
    direct = _direct_distance_meters(origin, destination)
    if route.duration_seconds == 0 and route.distance_meters > 1000:
        return RouteSanityResult(
            RouteSanityStatus.FAILED, "invalid_duration", direct
        )
    if direct > 250 and route.distance_meters < direct * 0.85:
        return RouteSanityResult(
            RouteSanityStatus.FAILED, "route_shorter_than_geographic_separation", direct
        )
    same_locality = _same_known_geography(origin, destination)
    if same_locality and direct > 500 and route.distance_meters > direct * 8:
        return RouteSanityResult(
            RouteSanityStatus.FAILED, "same_locality_route_detour", direct
        )
    return RouteSanityResult(RouteSanityStatus.PASSED, "consistent", direct)


def _same_practical_place(
    left: LocationCandidate, right: LocationCandidate
) -> bool:
    if (
        left.provider == right.provider
        and left.provider_place_id
        and left.provider_place_id == right.provider_place_id
    ):
        return True
    if _candidate_distance_meters(left, right) > 30:
        return False
    same_geography = all(
        not left_value
        or not right_value
        or _normalized_location_text(left_value)
        == _normalized_location_text(right_value)
        for left_value, right_value in (
            (left.city, right.city),
            (left.state, right.state),
            (left.country, right.country),
        )
    )
    same_text = (
        _normalized_location_text(left.display_name)
        == _normalized_location_text(right.display_name)
        or _normalized_location_text(left.formatted_address)
        == _normalized_location_text(right.formatted_address)
    )
    return same_geography and same_text


def _same_known_geography(
    left: ResolvedLocation, right: ResolvedLocation
) -> bool:
    if not left.city or not right.city:
        return False
    return _normalized_location_text(left.city) == _normalized_location_text(
        right.city
    )


def _candidate_distance_meters(
    left: LocationCandidate, right: LocationCandidate
) -> int:
    return _spherical_distance_meters(
        left.latitude, left.longitude, right.latitude, right.longitude
    )


def _direct_distance_meters(
    left: ResolvedLocation, right: ResolvedLocation
) -> int:
    return _spherical_distance_meters(
        left.latitude, left.longitude, right.latitude, right.longitude
    )


def _spherical_distance_meters(
    latitude_one: Decimal,
    longitude_one: Decimal,
    latitude_two: Decimal,
    longitude_two: Decimal,
) -> int:
    lat_one, lat_two = radians(float(latitude_one)), radians(float(latitude_two))
    delta_latitude = lat_two - lat_one
    delta_longitude = radians(float(longitude_two - longitude_one))
    value = sin(delta_latitude / 2) ** 2 + (
        cos(lat_one) * cos(lat_two) * sin(delta_longitude / 2) ** 2
    )
    return round(6_371_000 * 2 * asin(sqrt(min(1.0, value))))


def _normalized_location_text(value: str) -> str:
    return " ".join(re.findall(r"[\w]+", value.casefold()))
