from dataclasses import dataclass
from decimal import Decimal

from boloride.domain.exceptions import DomainValidationError


@dataclass(frozen=True, slots=True)
class ResolvedLocation:
    address: str
    latitude: Decimal
    longitude: Decimal
    display_name: str | None = None
    provider: str | None = None
    provider_place_id: str | None = None

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

    def to_resolved_location(self) -> ResolvedLocation:
        return ResolvedLocation(
            address=self.formatted_address,
            latitude=self.latitude,
            longitude=self.longitude,
            display_name=self.display_name,
            provider=self.provider,
            provider_place_id=self.provider_place_id,
        )
