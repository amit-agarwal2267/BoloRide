import asyncio
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from boloride.db.models.driver import Driver
from boloride.db.models.accepted_quote import AcceptedQuote
from boloride.db.models.ride_assignment import RideAssignment
from boloride.db.models.vehicle import Vehicle
from boloride.db.models.vehicle_type import VehicleType
from boloride.domain.enums import RideStatus
from boloride.domain.models.dispatch import DispatchResultStatus
from boloride.domain.models.fleet import DriverAvailability
from boloride.repositories.assignment_repository import AssignmentRepository
from boloride.repositories.fleet_repository import FleetRepository
from boloride.repositories.ride_repository import RideRepository
from boloride.services.dispatch_service import DispatchService
from boloride.services.ride_service import RideService
from test_ride_cancellation import (
    confirm,
    create_customer,
    create_ride,
    verified_context,
)


async def add_candidate(
    session: AsyncSession,
    *,
    vehicle_type: str,
    latitude: str,
    longitude: str,
    available: DriverAvailability = DriverAvailability.AVAILABLE,
    active: bool = True,
    driver_id: UUID | None = None,
) -> tuple[Driver, Vehicle]:
    token = uuid4().int
    driver = Driver(
        id=driver_id or uuid4(), name="Synthetic Dispatch Driver",
        availability=available, latitude=Decimal(latitude), longitude=Decimal(longitude),
        city="Kota", state="Rajasthan", seed_version="dispatch-test", seed_key=f"dispatch:{uuid4()}",
    )
    vehicle = Vehicle(
        id=uuid4(), driver_id=driver.id, vehicle_type_code=vehicle_type,
        registration_number=(
            f"RJ{10 + token % 90:02d}"
            f"{chr(65 + token // 90 % 26)}{chr(65 + token // 2340 % 26)}"
            f"{1000 + token % 9000:04d}"
        ),
        active=active,
    )
    session.add_all([driver, vehicle])
    await session.flush()
    return driver, vehicle


def dispatch_service(session: AsyncSession) -> DispatchService:
    return DispatchService(
        session, RideRepository(session), FleetRepository(session), AssignmentRepository(session)
    )


async def set_test_category(session: AsyncSession, ride_id: UUID, label: str) -> str:
    code = f"{label}_{uuid4().hex[:8]}"
    session.add(VehicleType(code=code, display_name=f"{label} Test", passenger_capacity=4, active=True))
    snapshot = await session.scalar(
        select(AcceptedQuote).where(AcceptedQuote.ride_id == ride_id)
    )
    snapshot.vehicle_type_code = code
    await session.flush()
    return code


async def deactivate_category(session: AsyncSession, code: str) -> None:
    category = await session.get(VehicleType, code)
    category.active = False
    await session.commit()


@pytest.mark.asyncio
async def test_nearest_eligible_driver_is_assigned_deterministically(db_session: AsyncSession):
    user = await create_customer(db_session, "Dispatch Owner")
    ride = await create_ride(db_session, user.id, uuid4().hex)
    code = await set_test_category(db_session, ride.id, "nearest")
    first_id, second_id = sorted((uuid4(), uuid4()), key=str)
    await add_candidate(db_session, vehicle_type=code, latitude="25.180001", longitude="75.830001")
    near, _ = await add_candidate(
        db_session, vehicle_type=code, latitude="25.180000", longitude="75.830000",
        driver_id=first_id,
    )
    await add_candidate(
        db_session, vehicle_type=code, latitude="25.180000", longitude="75.830000",
        driver_id=second_id,
    )
    await add_candidate(db_session, vehicle_type="mini", latitude="25.180000", longitude="75.830000")
    await add_candidate(db_session, vehicle_type=code, latitude="25.180000", longitude="75.830000", active=False)
    await add_candidate(
        db_session, vehicle_type=code, latitude="25.180000", longitude="75.830000",
        available=DriverAvailability.ASSIGNED,
    )

    result = await dispatch_service(db_session).dispatch(user.id, ride.id)
    assignment = await AssignmentRepository(db_session).get_for_ride(ride.id)
    assert result.status is DispatchResultStatus.ASSIGNED
    assert assignment.driver_id == near.id
    assert (await RideRepository(db_session).get_for_customer(user.id, ride.id)).status is RideStatus.ASSIGNED
    assert (await FleetRepository(db_session).get_driver(near.id)).availability is DriverAvailability.ASSIGNED
    await deactivate_category(db_session, code)


@pytest.mark.asyncio
async def test_no_driver_keeps_ride_booked(db_session: AsyncSession):
    user = await create_customer(db_session, "No Driver Owner")
    ride = await create_ride(db_session, user.id, uuid4().hex)
    code = await set_test_category(db_session, ride.id, "empty")
    user_id, ride_id = user.id, ride.id
    await db_session.commit()

    result = await dispatch_service(db_session).dispatch(user_id, ride_id)
    assert result.status is DispatchResultStatus.NO_DRIVER_AVAILABLE
    assert (await RideRepository(db_session).get_for_customer(user_id, ride_id)).status is RideStatus.BOOKED
    await deactivate_category(db_session, code)


@pytest.mark.asyncio
async def test_trip_lifecycle_and_customer_safe_assignment_details(db_session: AsyncSession):
    user = await create_customer(db_session, "Trip Owner")
    ride = await create_ride(db_session, user.id, uuid4().hex)
    code = await set_test_category(db_session, ride.id, "trip")
    driver, vehicle = await add_candidate(
        db_session, vehicle_type=code, latitude="25.180000", longitude="75.830000"
    )
    service = dispatch_service(db_session)
    assert (await service.dispatch(user.id, ride.id)).status is DispatchResultStatus.ASSIGNED
    details = await RideRepository(db_session).get_status_for_customer(user.id, ride.id)
    assert details.driver_display_name == driver.name
    assert details.vehicle_registration == vehicle.registration_number
    assert not hasattr(details, "driver_id")
    assert (await service.start_trip(user.id, ride.id)).status is DispatchResultStatus.STARTED
    assert (await service.complete_trip(user.id, ride.id)).status is DispatchResultStatus.COMPLETED
    assert (await FleetRepository(db_session).get_driver(driver.id)).availability is DriverAvailability.AVAILABLE
    await deactivate_category(db_session, code)


@pytest.mark.asyncio
async def test_assigned_cancellation_uses_idempotent_real_release(db_session: AsyncSession):
    user = await create_customer(db_session, "Release Owner")
    ride = await create_ride(db_session, user.id, uuid4().hex)
    code = await set_test_category(db_session, ride.id, "release")
    driver, _ = await add_candidate(
        db_session, vehicle_type=code, latitude="25.180000", longitude="75.830000"
    )
    dispatch = dispatch_service(db_session)
    driver_id, ride_id, user_id = driver.id, ride.id, user.id
    await dispatch.dispatch(user_id, ride_id)
    context = verified_context(user_id)
    await confirm(context, ride_id)
    result = await RideService(db_session, RideRepository(db_session), driver_assignments=dispatch).cancel_customer_ride(user_id, ride_id, context)
    await dispatch.release_assignment_idempotently(ride_id)
    assignment = await AssignmentRepository(db_session).get_for_ride(ride_id)
    assert result.ride.status is RideStatus.CANCELLED
    assert result.ride.final_customer_cost == Decimal("0.00")
    assert assignment.release_reason == "cancelled"
    assert (await FleetRepository(db_session).get_driver(driver_id)).availability is DriverAvailability.AVAILABLE
    await deactivate_category(db_session, code)


@pytest.mark.asyncio
async def test_concurrent_rides_claim_distinct_drivers_when_next_candidate_exists(app):
    code = f"race_{uuid4().hex[:8]}"
    async with app.state.db_session_factory() as setup:
        first_user = await create_customer(setup, "Race One")
        second_user = await create_customer(setup, "Race Two")
        first_ride = await create_ride(setup, first_user.id, uuid4().hex)
        second_ride = await create_ride(setup, second_user.id, uuid4().hex)
        setup.add(VehicleType(code=code, display_name="Race Test", passenger_capacity=4, active=True))
        first_quote = await setup.scalar(select(AcceptedQuote).where(AcceptedQuote.ride_id == first_ride.id))
        second_quote = await setup.scalar(select(AcceptedQuote).where(AcceptedQuote.ride_id == second_ride.id))
        first_quote.vehicle_type_code = code
        second_quote.vehicle_type_code = code
        driver, _ = await add_candidate(
            setup, vehicle_type=code, latitude="25.180000", longitude="75.830000"
        )
        second_driver, _ = await add_candidate(
            setup, vehicle_type=code, latitude="25.180001", longitude="75.830001"
        )
        ids = first_user.id, second_user.id, first_ride.id, second_ride.id, driver.id, second_driver.id
        await setup.commit()

    async with app.state.db_session_factory() as one, app.state.db_session_factory() as two:
        results = await asyncio.gather(
            dispatch_service(one).dispatch(ids[0], ids[2]),
            dispatch_service(two).dispatch(ids[1], ids[3]),
        )
    assert [result.status for result in results] == [
        DispatchResultStatus.ASSIGNED, DispatchResultStatus.ASSIGNED
    ]
    async with app.state.db_session_factory() as verify:
        active_assignments = list(
            await verify.scalars(
                select(RideAssignment).where(
                    RideAssignment.ride_id.in_((ids[2], ids[3])),
                    RideAssignment.driver_id.in_((ids[4], ids[5])),
                    RideAssignment.released_at.is_(None),
                )
            )
        )
        assert len(active_assignments) == 2
        assert len({assignment.driver_id for assignment in active_assignments}) == 2
        await deactivate_category(verify, code)


@pytest.mark.asyncio
async def test_offer_is_consumed_only_when_trip_completes(db_session: AsyncSession):
    user = await create_customer(db_session, "Offer Trip Owner")
    ride = await create_ride(db_session, user.id, uuid4().hex)
    code = await set_test_category(db_session, ride.id, "offertrip")
    await add_candidate(db_session, vehicle_type=code, latitude="25.180000", longitude="75.830000")
    class RecordingOffers:
        def __init__(self):
            self.statuses = []

        async def finalize_redemption(self, customer_id, ride_id, status):
            self.statuses.append(status)

    offers = RecordingOffers()
    service = DispatchService(
        db_session, RideRepository(db_session), FleetRepository(db_session),
        AssignmentRepository(db_session), offers,
    )

    await service.dispatch(user.id, ride.id)
    assert offers.statuses == []
    await service.start_trip(user.id, ride.id)
    assert offers.statuses == []
    assert (await service.complete_trip(user.id, ride.id)).status is DispatchResultStatus.COMPLETED
    assert offers.statuses == [RideStatus.COMPLETED]
    assert (await service.complete_trip(user.id, ride.id)).status is DispatchResultStatus.INVALID_LIFECYCLE
    assert offers.statuses == [RideStatus.COMPLETED]
    await deactivate_category(db_session, code)


@pytest.mark.asyncio
async def test_invalid_booked_to_on_trip_mutates_nothing(db_session: AsyncSession):
    user = await create_customer(db_session, "Invalid Start Owner")
    ride = await create_ride(db_session, user.id, uuid4().hex)
    user_id, ride_id = user.id, ride.id
    await db_session.commit()
    result = await dispatch_service(db_session).start_trip(user_id, ride_id)
    assert result.status is DispatchResultStatus.INVALID_LIFECYCLE
    assert (await RideRepository(db_session).get_for_customer(user_id, ride_id)).status is RideStatus.BOOKED


@pytest.mark.asyncio
async def test_cancellation_and_trip_start_race_remains_consistent(app):
    async with app.state.db_session_factory() as setup:
        user = await create_customer(setup, "Lifecycle Race Owner")
        ride = await create_ride(setup, user.id, uuid4().hex)
        code = await set_test_category(setup, ride.id, "lifecyclerace")
        await add_candidate(setup, vehicle_type=code, latitude="25.180000", longitude="75.830000")
        await dispatch_service(setup).dispatch(user.id, ride.id)
        user_id, ride_id = user.id, ride.id

    async with app.state.db_session_factory() as cancel_session, app.state.db_session_factory() as start_session:
        cancel_dispatch = dispatch_service(cancel_session)
        context = verified_context(user_id)
        await confirm(context, ride_id)
        cancellation, start = await asyncio.gather(
            RideService(
                cancel_session, RideRepository(cancel_session), driver_assignments=cancel_dispatch
            ).cancel_customer_ride(user_id, ride_id, context),
            dispatch_service(start_session).start_trip(user_id, ride_id),
        )

    async with app.state.db_session_factory() as verify:
        ride = await RideRepository(verify).get_for_customer(user_id, ride_id)
        assignment = await AssignmentRepository(verify).get_for_ride(ride_id)
        driver = await FleetRepository(verify).get_driver(assignment.driver_id)
        if ride.status is RideStatus.CANCELLED:
            assert cancellation.status.value in {"success", "idempotent_success"}
            assert driver.availability is DriverAvailability.AVAILABLE
            assert assignment.release_reason == "cancelled"
        else:
            assert ride.status is RideStatus.ON_TRIP
            assert start.status is DispatchResultStatus.STARTED
            assert driver.availability is DriverAvailability.ON_TRIP
            assert assignment.released_at is None
        await deactivate_category(verify, code)
