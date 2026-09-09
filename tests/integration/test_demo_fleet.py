import re
from collections import Counter

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from boloride.db.models.driver import Driver
from boloride.db.models.vehicle import Vehicle
from boloride.db.models.vehicle_type import VehicleType
from boloride.domain.models.fleet import FLEET_SEED_VERSION, VEHICLE_COUNTS
from boloride.repositories.fleet_repository import FleetRepository
from boloride.services.fleet_seed_service import FleetSeedService


@pytest.mark.asyncio
async def test_demo_fleet_seed_counts_relationships_and_idempotency(
    db_session: AsyncSession,
) -> None:
    service = FleetSeedService(db_session, FleetRepository(db_session))
    assert await service.seed_demo_fleet() == VEHICLE_COUNTS
    assert await service.seed_demo_fleet() == VEHICLE_COUNTS

    drivers = list(
        await db_session.scalars(
            select(Driver).where(Driver.seed_version == FLEET_SEED_VERSION)
        )
    )
    vehicles = list(
        await db_session.scalars(
            select(Vehicle)
            .join(Driver, Driver.id == Vehicle.driver_id)
            .where(Driver.seed_version == FLEET_SEED_VERSION)
        )
    )
    assert len(drivers) == len(vehicles) == 1060
    assert Counter(vehicle.vehicle_type_code for vehicle in vehicles) == VEHICLE_COUNTS
    assert len({vehicle.driver_id for vehicle in vehicles}) == 1060
    assert len({vehicle.registration_number for vehicle in vehicles}) == 1060
    assert all(vehicle.active for vehicle in vehicles)

    valid_type_count = await db_session.scalar(
        select(func.count())
        .select_from(Vehicle)
        .join(VehicleType, VehicleType.code == Vehicle.vehicle_type_code)
        .join(Driver, Driver.id == Vehicle.driver_id)
        .where(Driver.seed_version == FLEET_SEED_VERSION)
    )
    assert valid_type_count == 1060


@pytest.mark.asyncio
async def test_seeded_registration_and_geography_are_valid(
    db_session: AsyncSession,
) -> None:
    await FleetSeedService(db_session, FleetRepository(db_session)).seed_demo_fleet()
    rows = (
        await db_session.execute(
            select(Driver.state, Driver.city, Vehicle.registration_number)
            .join(Vehicle, Vehicle.driver_id == Driver.id)
            .where(Driver.seed_version == FLEET_SEED_VERSION)
        )
    ).all()
    prefixes = {
        "Rajasthan": "RJ",
        "Uttar Pradesh": "UP",
        "Madhya Pradesh": "MP",
        "Punjab": "PB",
    }
    approved_cities = {
        "Rajasthan": {"Kota", "Jaipur", "Jodhpur", "Udaipur", "Ajmer"},
        "Uttar Pradesh": {"Lucknow", "Kanpur", "Agra", "Noida", "Prayagraj", "Varanasi"},
        "Madhya Pradesh": {"Indore", "Bhopal", "Gwalior", "Jabalpur", "Ujjain"},
        "Punjab": {"Ludhiana", "Amritsar", "Jalandhar", "Patiala", "Mohali"},
    }
    assert len(rows) == 1060
    for state, city, registration in rows:
        assert city in approved_cities[state]
        assert registration.startswith(prefixes[state])
        assert re.fullmatch(r"(?:RJ|UP|MP|PB)\d{2}[A-Z]{2}\d{4}", registration)
