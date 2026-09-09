from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class CustomerIdentityState(StrEnum):
    NEW_CUSTOMER_ONBOARDING_REQUIRED = "new_customer_onboarding_required"
    RETURNING_CUSTOMER_VERIFICATION_REQUIRED = "returning_customer_verification_required"
    ONBOARDED_NEW_CUSTOMER = "onboarded_new_customer"
    VERIFIED_RETURNING_CUSTOMER = "verified_returning_customer"
    NAME_MISMATCH = "name_mismatch"
    PHONE_UNAVAILABLE = "phone_unavailable"
    IDENTITY_UNAVAILABLE = "identity_unavailable"


@dataclass(frozen=True, slots=True)
class CustomerIdentityResult:
    state: CustomerIdentityState
    customer_id: UUID | None = None

    def __post_init__(self) -> None:
        verified = self.state in {
            CustomerIdentityState.ONBOARDED_NEW_CUSTOMER,
            CustomerIdentityState.VERIFIED_RETURNING_CUSTOMER,
        }
        if verified != (self.customer_id is not None):
            raise ValueError(
                "customer_id must be present only for an established customer identity"
            )

    @property
    def verified(self) -> bool:
        return self.state in {
            CustomerIdentityState.ONBOARDED_NEW_CUSTOMER,
            CustomerIdentityState.VERIFIED_RETURNING_CUSTOMER,
        }
