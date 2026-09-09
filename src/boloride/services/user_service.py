from boloride.domain.models.user import (
    normalize_customer_age,
    normalize_customer_name,
    normalize_indian_phone_number,
)
from boloride.domain.policies import CustomerIdentityResult, CustomerIdentityState
from boloride.repositories.user_repository import UserRepository


class UserService:
    def __init__(self, users: UserRepository) -> None:
        self._users = users

    async def begin_identity(self, detected_phone: str | None) -> CustomerIdentityResult:
        """Discover the required branch without treating phone alone as verification."""
        if detected_phone is None or not detected_phone.strip():
            return CustomerIdentityResult(CustomerIdentityState.PHONE_UNAVAILABLE)
        normalized_phone = normalize_indian_phone_number(detected_phone)
        customer = await self._users.get_by_phone(normalized_phone)
        state = (
            CustomerIdentityState.NEW_CUSTOMER_ONBOARDING_REQUIRED
            if customer is None
            else CustomerIdentityState.RETURNING_CUSTOMER_VERIFICATION_REQUIRED
        )
        return CustomerIdentityResult(state)

    async def resolve_returning_customer(
        self, detected_phone: str | None, provided_name: str | None
    ) -> CustomerIdentityResult:
        if detected_phone is None or not detected_phone.strip():
            return CustomerIdentityResult(CustomerIdentityState.PHONE_UNAVAILABLE)

        normalized_phone = normalize_indian_phone_number(detected_phone)
        customer = await self._users.get_by_phone(normalized_phone)
        if customer is None:
            return CustomerIdentityResult(
                CustomerIdentityState.NEW_CUSTOMER_ONBOARDING_REQUIRED
            )
        if provided_name is None or not provided_name.strip():
            return CustomerIdentityResult(CustomerIdentityState.NAME_MISMATCH)
        if normalize_customer_name(provided_name) != customer.normalized_name:
            return CustomerIdentityResult(CustomerIdentityState.NAME_MISMATCH)
        return CustomerIdentityResult(
            CustomerIdentityState.VERIFIED_RETURNING_CUSTOMER,
            customer_id=customer.id,
        )

    async def onboard_customer(
        self, detected_phone: str | None, name: str, age: int
    ) -> CustomerIdentityResult:
        if detected_phone is None or not detected_phone.strip():
            return CustomerIdentityResult(CustomerIdentityState.PHONE_UNAVAILABLE)

        # Validate in the service boundary before reaching persistence.
        normalize_indian_phone_number(detected_phone)
        normalize_customer_name(name)
        normalize_customer_age(age)
        creation = await self._users.create_or_get(detected_phone, name, age)

        if not creation.created:
            if creation.user.normalized_name != normalize_customer_name(name):
                return CustomerIdentityResult(CustomerIdentityState.NAME_MISMATCH)
            return CustomerIdentityResult(
                CustomerIdentityState.VERIFIED_RETURNING_CUSTOMER,
                customer_id=creation.user.id,
            )
        return CustomerIdentityResult(
            CustomerIdentityState.ONBOARDED_NEW_CUSTOMER,
            customer_id=creation.user.id,
        )
