from types import SimpleNamespace
from uuid import uuid4

import pytest

from boloride.domain.exceptions import DomainValidationError
from boloride.domain.policies import CustomerIdentityState
from boloride.repositories.user_repository import UserCreationResult
from boloride.services.user_service import UserService


class UserRepositoryStub:
    def __init__(self, user=None, *, created: bool = True) -> None:
        self.user = user
        self.created = created

    async def get_by_phone(self, phone_number: str):
        return self.user

    async def create_or_get(self, phone_number: str, name: str, age: int):
        user = self.user or SimpleNamespace(
            id=uuid4(), normalized_name=" ".join(name.split()).casefold(), age=age
        )
        return UserCreationResult(user, self.created)


@pytest.mark.asyncio
async def test_phone_is_required_to_establish_identity() -> None:
    service = UserService(UserRepositoryStub())  # type: ignore[arg-type]
    result = await service.resolve_returning_customer(None, "Amit Agarwal")
    assert result.state is CustomerIdentityState.PHONE_UNAVAILABLE
    assert result.customer_id is None


@pytest.mark.asyncio
async def test_unknown_phone_requires_onboarding() -> None:
    service = UserService(UserRepositoryStub())  # type: ignore[arg-type]
    result = await service.resolve_returning_customer("9876543210", "Amit")
    assert result.state is CustomerIdentityState.NEW_CUSTOMER_ONBOARDING_REQUIRED


@pytest.mark.asyncio
async def test_identity_discovery_distinguishes_returning_without_verifying_phone_alone() -> None:
    user = SimpleNamespace(id=uuid4(), normalized_name="amit agarwal")
    service = UserService(UserRepositoryStub(user))  # type: ignore[arg-type]
    result = await service.begin_identity("9876543210")
    assert result.state is CustomerIdentityState.RETURNING_CUSTOMER_VERIFICATION_REQUIRED
    assert result.customer_id is None


@pytest.mark.asyncio
async def test_phone_alone_does_not_verify_returning_customer() -> None:
    user = SimpleNamespace(id=uuid4(), normalized_name="amit agarwal")
    service = UserService(UserRepositoryStub(user))  # type: ignore[arg-type]
    result = await service.resolve_returning_customer("9876543210", None)
    assert result.state is CustomerIdentityState.NAME_MISMATCH
    assert result.verified is False


@pytest.mark.asyncio
@pytest.mark.parametrize("provided", ["amit agarwal", "  Amit Agarwal  ", "AMIT   AGARWAL"])
async def test_returning_name_match_uses_canonical_normalization(provided: str) -> None:
    user = SimpleNamespace(id=uuid4(), normalized_name="amit agarwal")
    service = UserService(UserRepositoryStub(user))  # type: ignore[arg-type]
    result = await service.resolve_returning_customer("9876543210", provided)
    assert result.state is CustomerIdentityState.VERIFIED_RETURNING_CUSTOMER
    assert result.customer_id == user.id


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("stored", "provided"),
    [
        ("amit agarwal", "अमित अग्रवाल"),
        ("अमित अग्रवाल", "Amit Agarwal"),
        ("rahul sharma", "राहुल शर्मा"),
        ("सुनीता वर्मा", "Sunita Verma"),
    ],
)
async def test_returning_name_matches_conservative_cross_script_equivalent(
    stored: str, provided: str
) -> None:
    user = SimpleNamespace(id=uuid4(), normalized_name=stored)
    result = await UserService(UserRepositoryStub(user)).resolve_returning_customer(  # type: ignore[arg-type]
        "9876543210", provided
    )
    assert result.state is CustomerIdentityState.VERIFIED_RETURNING_CUSTOMER


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("stored", "provided"),
    [
        ("amit agarwal", "अजय अग्रवाल"),
        ("अमित अग्रवाल", "Sumit Agarwal"),
        ("aman sharma", "मन शर्मा"),
    ],
)
async def test_cross_script_matching_rejects_clearly_different_names(
    stored: str, provided: str
) -> None:
    user = SimpleNamespace(id=uuid4(), normalized_name=stored)
    result = await UserService(UserRepositoryStub(user)).resolve_returning_customer(  # type: ignore[arg-type]
        "9876543210", provided
    )
    assert result.state is CustomerIdentityState.NAME_MISMATCH
    assert result.customer_id is None


@pytest.mark.asyncio
async def test_wrong_name_does_not_expose_customer_id() -> None:
    user = SimpleNamespace(id=uuid4(), normalized_name="amit agarwal")
    service = UserService(UserRepositoryStub(user))  # type: ignore[arg-type]
    result = await service.resolve_returning_customer("9876543210", "Someone Else")
    assert result.state is CustomerIdentityState.NAME_MISMATCH
    assert result.customer_id is None


@pytest.mark.asyncio
async def test_onboarding_requires_nonempty_name() -> None:
    service = UserService(UserRepositoryStub())  # type: ignore[arg-type]
    with pytest.raises(DomainValidationError, match="name"):
        await service.onboard_customer("9876543210", "   ", 30)


@pytest.mark.asyncio
@pytest.mark.parametrize("age", [0, 121])
async def test_onboarding_rejects_age_outside_data_integrity_bounds(age: int) -> None:
    service = UserService(UserRepositoryStub())  # type: ignore[arg-type]
    with pytest.raises(DomainValidationError, match="between 1 and 120"):
        await service.onboard_customer("9876543210", "Amit Agarwal", age)


@pytest.mark.asyncio
async def test_existing_customer_does_not_require_age_for_verification() -> None:
    user = SimpleNamespace(id=uuid4(), normalized_name="amit agarwal", age=30)
    service = UserService(UserRepositoryStub(user))  # type: ignore[arg-type]
    result = await service.resolve_returning_customer("9876543210", "Amit Agarwal")
    assert result.verified is True


@pytest.mark.asyncio
async def test_racing_existing_customer_with_other_name_is_not_verified() -> None:
    user = SimpleNamespace(id=uuid4(), normalized_name="amit agarwal", age=30)
    service = UserService(UserRepositoryStub(user, created=False))  # type: ignore[arg-type]
    result = await service.onboard_customer("9876543210", "Someone Else", 40)
    assert result.state is CustomerIdentityState.NAME_MISMATCH
    assert result.customer_id is None
