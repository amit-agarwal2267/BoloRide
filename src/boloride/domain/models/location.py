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


_PRECISE_PICKUP_TYPES = frozenset({
    "airport", "bus_station", "establishment", "hospital", "hotel", "lodging",
    "point_of_interest", "premise", "subpremise", "train_station", "transit_station",
    "street_address", "saved_place",
})
_BROAD_PICKUP_TYPES = frozenset({
    "administrative_area_level_1", "administrative_area_level_2", "country",
    "locality", "neighborhood", "political", "postal_code", "route", "sublocality",
    "sublocality_level_1",
})


def is_pickup_precise(location: "ResolvedLocation") -> bool:
    """Fail closed unless provider-backed types identify a findable pickup point."""
    types = frozenset(location.place_types or ())
    if not types or types.issubset(_BROAD_PICKUP_TYPES):
        return False
    return bool(types.intersection(_PRECISE_PICKUP_TYPES))


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
    """Collapse provider duplicates without erasing meaningful navigation sub-locations."""
    if (
        left.provider == right.provider
        and left.provider_place_id
        and left.provider_place_id == right.provider_place_id
    ):
        return True
    distance = _candidate_distance_meters(left, right)
    if distance > 250:
        return False
    if not _compatible_candidate_geography(left, right):
        return False
    if _meaningfully_distinct_sub_location(left, right):
        return False

    left_tokens = _semantic_place_tokens(left)
    right_tokens = _semantic_place_tokens(right)
    if not left_tokens or not right_tokens:
        return distance <= 40
    overlap = len(left_tokens & right_tokens) / min(len(left_tokens), len(right_tokens))
    same_category = bool(set(left.place_types or ()) & set(right.place_types or ()))
    transit_parent = bool(
        {"train_station", "transit_station", "bus_station", "airport"}
        & set(left.place_types or ())
        & set(right.place_types or ())
    )
    return (
        overlap >= 0.6
        or (distance <= 80 and same_category)
        or (distance <= 150 and transit_parent and overlap >= 0.25)
    )


_NAVIGATION_DISTINCTION_PATTERN = re.compile(
    r"\b(?:platform|gate|terminal|entrance|entry|exit|tower|block|wing|building|"
    r"arrival|departure|parking)\s*[-:#]?\s*([a-z0-9]+)\b",
    re.IGNORECASE,
)


def _compatible_candidate_geography(
    left: LocationCandidate, right: LocationCandidate
) -> bool:
    return all(
        not left_value
        or not right_value
        or geography_values_equivalent(left_value, right_value)
        for left_value, right_value in (
            (left.city, right.city),
            (left.state, right.state),
            (left.country, right.country),
        )
    )


def _meaningfully_distinct_sub_location(
    left: LocationCandidate, right: LocationCandidate
) -> bool:
    left_text = f"{left.display_name} {left.formatted_address}"
    right_text = f"{right.display_name} {right.formatted_address}"
    left_markers = {
        (match.group(0).split()[0].casefold(), match.group(1).casefold())
        for match in _NAVIGATION_DISTINCTION_PATTERN.finditer(left_text)
    }
    right_markers = {
        (match.group(0).split()[0].casefold(), match.group(1).casefold())
        for match in _NAVIGATION_DISTINCTION_PATTERN.finditer(right_text)
    }
    if not left_markers or not right_markers:
        return False
    left_by_kind = dict(left_markers)
    right_by_kind = dict(right_markers)
    return any(
        kind in right_by_kind and right_by_kind[kind] != value
        for kind, value in left_by_kind.items()
    )


def _semantic_place_tokens(candidate: LocationCandidate) -> set[str]:
    ignored = {
        "railway", "rail", "station", "junction", "jn", "road", "rd", "street",
        "st", "the", "near", "at", "in", "india",
    }
    return {
        token
        for token in re.findall(
            r"[\w]+",
            f"{candidate.display_name} {candidate.formatted_address}".casefold(),
        )
        if len(token) > 1 and token not in ignored
    }


def _same_known_geography(
    left: ResolvedLocation, right: ResolvedLocation
) -> bool:
    if not left.city or not right.city:
        return False
    return geography_values_equivalent(left.city, right.city)


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


def normalized_location_text(value: str) -> str:
    return " ".join(re.findall(r"[\w]+", value.casefold()))


def geography_values_equivalent(left: str | None, right: str | None) -> bool:
    """Compare geography names across case/script using provider-backed transliteration hints."""
    if not left or not right:
        return True
    left_normalized = normalized_location_text(left)
    right_normalized = normalized_location_text(right)
    if left_normalized == right_normalized:
        return True

    # Minimal generic Indic transliteration for geography comparison only. This
    # avoids city-name dictionaries while allowing common Hindi/English forms
    # such as कोटा/Kota and राजस्थान/Rajasthan to compare consistently.
    left_latin = _indic_to_latin_key(left_normalized)
    right_latin = _indic_to_latin_key(right_normalized)
    return bool(left_latin and right_latin and left_latin == right_latin)


def _indic_to_latin_key(value: str) -> str:
    independent = {
        "अ": "a", "आ": "aa", "इ": "i", "ई": "ii", "उ": "u", "ऊ": "uu",
        "ए": "e", "ऐ": "ai", "ओ": "o", "औ": "au",
    }
    consonants = {
        "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "ng",
        "च": "ch", "छ": "chh", "ज": "j", "झ": "jh", "ञ": "ny",
        "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n",
        "त": "t", "थ": "th", "द": "d", "ध": "dh", "न": "n",
        "प": "p", "फ": "ph", "ब": "b", "भ": "bh", "म": "m",
        "य": "y", "र": "r", "ल": "l", "व": "v", "श": "sh", "ष": "sh",
        "स": "s", "ह": "h", "क़": "q", "ख़": "kh", "ग़": "g", "ज़": "z",
        "ड़": "d", "ढ़": "dh", "फ़": "f",
    }
    matras = {
        "ा": "a", "ि": "i", "ी": "i", "ु": "u", "ू": "u",
        "े": "e", "ै": "ai", "ो": "o", "ौ": "au", "ृ": "ri",
    }
    marks = {"ं": "n", "ँ": "n", "ः": "h"}
    result: list[str] = []
    pending_consonant = False
    for char in value:
        if char in consonants:
            if pending_consonant:
                result.append("a")
            result.append(consonants[char])
            pending_consonant = True
        elif char in matras:
            result.append(matras[char])
            pending_consonant = False
        elif char == "्":
            pending_consonant = False
        elif char in independent:
            if pending_consonant:
                result.append("a")
                pending_consonant = False
            result.append(independent[char])
        elif char in marks:
            result.append(marks[char])
        elif char.isascii() and char.isalnum():
            if pending_consonant:
                result.append("a")
                pending_consonant = False
            result.append(char.casefold())
        else:
            if pending_consonant:
                result.append("a")
                pending_consonant = False
    if pending_consonant:
        result.append("a")
    key = re.sub(r"[^a-z0-9]+", "", "".join(result)).replace("aa", "a").replace("ii", "i").replace("uu", "u")
    # Hindi commonly drops the final inherent schwa in Latin spellings:
    # राजस्थान -> rajasthana -> rajasthan. Apply this as a script rule,
    # not a city/state dictionary.
    if value and not value[-1].isascii() and key.endswith("a"):
        key = key[:-1]
    return key


_normalized_location_text = normalized_location_text
