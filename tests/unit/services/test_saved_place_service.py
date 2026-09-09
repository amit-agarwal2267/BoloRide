from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from boloride.services.saved_place_service import SavedPlaceService


def place(label: str, provider: str = "google") -> SimpleNamespace:
    return SimpleNamespace(
        label=label,
        address="Saved address",
        display_name="Saved home",
        latitude=Decimal("25.1"),
        longitude=Decimal("75.1"),
        provider=provider,
        provider_place_id="saved-provider-id",
    )


class Places:
    def __init__(self, by_user):
        self.by_user = by_user

    async def list_for_user(self, user_id):
        return self.by_user.get(user_id, [])


@pytest.mark.asyncio
async def test_home_and_ghar_alias_resolves_only_customer_owned_snapshot():
    customer, other = uuid4(), uuid4()
    service = SavedPlaceService(Places({customer: [place("home")], other: [place("home", "ola")]}))
    resolved = await service.resolve_label(customer, " Ghar ")
    assert resolved is not None
    assert resolved.provider == "google"
    assert resolved.provider_place_id == "saved-provider-id"


@pytest.mark.asyncio
async def test_another_customers_place_cannot_resolve():
    customer, other = uuid4(), uuid4()
    service = SavedPlaceService(Places({other: [place("home")]}))
    assert await service.resolve_label(customer, "home") is None


@pytest.mark.asyncio
async def test_alias_ambiguity_is_not_selected_arbitrarily():
    customer = uuid4()
    service = SavedPlaceService(Places({customer: [place("home"), place("ghar")]}))
    with pytest.raises(ValueError, match="ambiguous"):
        await service.resolve_label(customer, "home")
