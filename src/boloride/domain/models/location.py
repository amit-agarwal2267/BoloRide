from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

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
class ResolvedLocation:
    address: str
    latitude: Decimal
    longitude: Decimal
    display_name: str | None = None
    provider: str | None = None
    provider_place_id: str | None = None
    place_types: tuple[str, ...] | None = None

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

    def __post_init__(self) -> None:
        for field_name in ("country", "city", "state", "language"):
            value = getattr(self, field_name)
            if value is not None:
                normalized = " ".join(value.split())
                object.__setattr__(self, field_name, normalized or None)
        if self.country:
            object.__setattr__(self, "country", self.country.casefold())


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

    def to_resolved_location(self) -> ResolvedLocation:
        return ResolvedLocation(
            address=self.formatted_address,
            latitude=self.latitude,
            longitude=self.longitude,
            display_name=self.display_name,
            provider=self.provider,
            provider_place_id=self.provider_place_id,
            place_types=self.place_types,
        )
