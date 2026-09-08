import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from boloride.agents.context import RideContext
from boloride.db.models.vehicle_type import VehicleType
from boloride.domain.exceptions import DomainValidationError
from boloride.domain.models.vehicle import (
    PassengerCountSource,
    VehicleEligibilityState,
)
from boloride.repositories.vehicle_type_repository import VehicleTypeRepository
from boloride.services.vehicle_service import VehicleService


EXPECTED_CATALOG = {
    "auto": ("Auto", 3),
    "mini": ("Mini", 4),
    "sedan": ("Sedan", 4),
    "suv": ("SUV", 6),
    "premium": ("Premium Cab", 4),
}


def vehicle_service(db_session: AsyncSession) -> VehicleService:
    return VehicleService(VehicleTypeRepository(db_session))


@pytest.mark.asyncio
async def test_seeded_vehicle_catalog_has_approved_values(
    db_session: AsyncSession,
) -> None:
    repository = VehicleTypeRepository(db_session)

    for code, (display_name, capacity) in EXPECTED_CATALOG.items():
        vehicle = await repository.get_by_code(code)
        assert vehicle is not None
        assert vehicle.display_name == display_name
        assert vehicle.passenger_capacity == capacity
        assert vehicle.active is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("passenger_count", "expected_codes"),
    [
        (1, {"auto", "mini", "sedan", "suv", "premium"}),
        (3, {"auto", "mini", "sedan", "suv", "premium"}),
        (4, {"mini", "sedan", "suv", "premium"}),
        (5, {"suv"}),
        (6, {"suv"}),
    ],
)
async def test_only_capacity_eligible_vehicle_types_are_returned(
    db_session: AsyncSession,
    passenger_count: int,
    expected_codes: set[str],
) -> None:
    result = await vehicle_service(db_session).get_eligible_vehicle_types(
        passenger_count
    )

    assert result.state is VehicleEligibilityState.ELIGIBLE_VEHICLE_TYPES
    assert {vehicle.code for vehicle in result.eligible_vehicle_types} == expected_codes


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("code", "exact_capacity", "ineligible_count"),
    [
        ("auto", 3, 4),
        ("mini", 4, 5),
        ("sedan", 4, 5),
        ("suv", 6, 7),
        ("premium", 4, 5),
    ],
)
async def test_each_vehicle_exact_capacity_and_capacity_plus_one(
    db_session: AsyncSession,
    code: str,
    exact_capacity: int,
    ineligible_count: int,
) -> None:
    service = vehicle_service(db_session)

    assert (
        await service.require_eligible_vehicle_type(code, exact_capacity)
    ).code == code
    with pytest.raises(DomainValidationError, match="cannot accommodate"):
        await service.require_eligible_vehicle_type(code, ineligible_count)


@pytest.mark.asyncio
async def test_seven_passengers_returns_structured_no_eligible_result(
    db_session: AsyncSession,
) -> None:
    result = await vehicle_service(db_session).get_eligible_vehicle_types(7)

    assert result.state is VehicleEligibilityState.NO_ELIGIBLE_VEHICLE_TYPE
    assert result.passenger_count == 7
    assert result.eligible_vehicle_types == ()


@pytest.mark.asyncio
async def test_inactive_vehicle_is_excluded_and_cannot_be_selected(
    db_session: AsyncSession,
) -> None:
    await db_session.execute(
        update(VehicleType).where(VehicleType.code == "suv").values(active=False)
    )
    service = vehicle_service(db_session)

    result = await service.get_eligible_vehicle_types(5)
    assert result.state is VehicleEligibilityState.NO_ELIGIBLE_VEHICLE_TYPE
    with pytest.raises(DomainValidationError, match="inactive"):
        await service.require_eligible_vehicle_type("suv", 5)


@pytest.mark.asyncio
async def test_unknown_vehicle_code_is_rejected(db_session: AsyncSession) -> None:
    with pytest.raises(DomainValidationError, match="unknown"):
        await vehicle_service(db_session).require_eligible_vehicle_type("standard", 1)


@pytest.mark.asyncio
async def test_passenger_change_preserves_or_invalidates_selection_deterministically(
    db_session: AsyncSession,
) -> None:
    service = vehicle_service(db_session)
    context = RideContext(session_id="vehicle-test", caller_id=None)
    await service.select_vehicle_type(context, "auto")

    await service.update_passenger_count(
        context, 3, PassengerCountSource.USER_PROVIDED
    )
    assert context.selected_vehicle_type_code == "auto"

    context.user_confirmed = True
    await service.update_passenger_count(
        context, 4, PassengerCountSource.USER_PROVIDED
    )
    assert context.passenger_count == 4
    assert context.selected_vehicle_type_code is None
    assert context.user_confirmed is False
