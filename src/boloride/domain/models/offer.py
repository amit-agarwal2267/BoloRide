from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from enum import StrEnum
import re
from uuid import UUID

from boloride.domain.exceptions import DomainValidationError

MONEY = Decimal("0.01")
WHOLE_INR = Decimal("1")


class DiscountType(StrEnum):
    PERCENTAGE = "percentage"


class OfferEligibilityType(StrEnum):
    NEW_CUSTOMER = "new_customer"


class RedemptionStatus(StrEnum):
    PENDING = "pending"
    CONSUMED = "consumed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class OfferDetails:
    id: UUID
    code: str
    display_name: str
    discount_type: DiscountType
    percentage: Decimal
    maximum_discount: Decimal
    currency: str
    maximum_redemptions_per_customer: int
    eligibility_type: OfferEligibilityType
    active: bool
    effective_from: datetime
    effective_until: datetime | None
    version: int

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", self.code):
            raise DomainValidationError("offer code must use stable uppercase identifier format")
        if not self.display_name.strip():
            raise DomainValidationError("offer code and display name cannot be blank")
        if not Decimal("0") < self.percentage <= Decimal("100"):
            raise DomainValidationError("offer percentage must be greater than 0 and at most 100")
        if self.maximum_discount < 0:
            raise DomainValidationError("maximum discount cannot be negative")
        if self.maximum_redemptions_per_customer <= 0:
            raise DomainValidationError("maximum redemptions must be positive")
        if self.currency != "INR":
            raise DomainValidationError("Prototype v1 offers must use INR")
        if self.effective_from.tzinfo is None or (
            self.effective_until is not None and self.effective_until.tzinfo is None
        ):
            raise DomainValidationError("offer effective timestamps must be timezone-aware")
        if self.effective_until is not None and self.effective_until <= self.effective_from:
            raise DomainValidationError("offer effective end must follow start")
        if self.version <= 0:
            raise DomainValidationError("offer version must be positive")

    def is_effective(self, now: datetime) -> bool:
        return self.active and self.effective_from <= now and (
            self.effective_until is None or now < self.effective_until
        )


@dataclass(frozen=True, slots=True)
class AppliedOfferSnapshot:
    offer_id: UUID
    code: str
    display_name: str
    discount_type: DiscountType
    percentage: Decimal
    maximum_discount: Decimal
    discount_amount: Decimal
    currency: str
    version: int


def calculate_discount(pre_discount_total: Decimal, offer: OfferDetails) -> tuple[Decimal, Decimal]:
    if pre_discount_total < 0:
        raise DomainValidationError("pre-discount estimate cannot be negative")
    raw = (pre_discount_total * offer.percentage / Decimal("100")).quantize(
        MONEY, rounding=ROUND_HALF_UP
    )
    discount = min(raw, offer.maximum_discount).quantize(MONEY, rounding=ROUND_HALF_UP)
    discounted = max(pre_discount_total - discount, Decimal("0")).quantize(
        WHOLE_INR, rounding=ROUND_HALF_UP
    ).quantize(MONEY)
    return discount, discounted
