from datetime import UTC, datetime
from uuid import UUID

from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from boloride.db.models.ride import Ride
from boloride.db.models.accepted_quote import AcceptedQuote
from boloride.db.models.driver import Driver
from boloride.db.models.ride_assignment import RideAssignment
from boloride.db.models.vehicle import Vehicle
from boloride.db.models.vehicle_type import VehicleType
from boloride.domain.enums import RideStatus
from boloride.domain.exceptions import DomainValidationError
from boloride.domain.models.location import ResolvedLocation
from boloride.domain.models.cancellation import RideStatusDetails
from boloride.domain.models.ride import CANCELLABLE_RIDE_STATUSES
from boloride.domain.models.ride import validate_ride_transition
from boloride.domain.models.quote import FareComponentType, Quote


class RideRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_booked(
        self,
        ride_id: UUID,
        user_id: UUID,
        pickup: ResolvedLocation,
        destination: ResolvedLocation,
        requested_ride_at: datetime,
        *,
        provider: str,
        provider_booking_id: str,
        accepted_quote: Quote,
    ) -> Ride:
        if pickup.latitude == destination.latitude and pickup.longitude == destination.longitude:
            raise DomainValidationError("pickup and destination must differ")
        if requested_ride_at.tzinfo is None:
            raise DomainValidationError("requested ride time must be timezone-aware")

        normalized_provider = provider.strip().casefold()
        normalized_booking_id = provider_booking_id.strip()
        normalized_currency = accepted_quote.pricing.currency.strip().upper()
        if not normalized_provider or not normalized_booking_id:
            raise DomainValidationError("provider booking details cannot be blank")
        if accepted_quote.pricing.estimated_total <= 0:
            raise DomainValidationError("fare amount must be positive")
        if len(normalized_currency) != 3 or not normalized_currency.isalpha():
            raise DomainValidationError("fare currency must be a three-letter code")

        now = datetime.now(UTC)
        ride = Ride(
            id=ride_id,
            user_id=user_id,
            pickup_address=pickup.address,
            pickup_display_name=pickup.display_name,
            pickup_latitude=pickup.latitude,
            pickup_longitude=pickup.longitude,
            pickup_provider=pickup.provider,
            pickup_provider_place_id=pickup.provider_place_id,
            destination_address=destination.address,
            destination_display_name=destination.display_name,
            destination_latitude=destination.latitude,
            destination_longitude=destination.longitude,
            destination_provider=destination.provider,
            destination_provider_place_id=destination.provider_place_id,
            requested_ride_at=requested_ride_at,
            status=RideStatus.BOOKED,
            confirmed_at=now,
            provider=normalized_provider,
            provider_booking_id=normalized_booking_id,
            booked_at=now,
            fare_amount=accepted_quote.pricing.estimated_total,
            fare_currency=normalized_currency,
        )
        self._session.add(ride)
        await self._session.flush()
        pricing = accepted_quote.pricing
        toll = next(
            (item.amount for item in pricing.components if item.component_type is FareComponentType.TOLL_ESTIMATE),
            None,
        )
        snapshot = AcceptedQuote(
                ride_id=ride.id,
                pricing_rule_id=pricing.pricing_rule_id,
                vehicle_type_code=pricing.vehicle_type_code,
                session_id=accepted_quote.session_id,
                route_provider=pricing.route_provider,
                route_distance_meters=pricing.route_distance_meters,
                route_duration_seconds=pricing.route_duration_seconds,
                base_fare=pricing.component(FareComponentType.BASE_FARE),
                distance_fare=pricing.component(FareComponentType.DISTANCE_FARE),
                night_charge=pricing.component(FareComponentType.NIGHT_CHARGE),
                airport_fee=pricing.component(FareComponentType.AIRPORT_FEE),
                toll_estimate=toll,
                toll_status=pricing.toll_status.value,
                estimated_total=pricing.estimated_total,
                currency=normalized_currency,
                quoted_at=accepted_quote.quoted_at,
                request_fingerprint=accepted_quote.request_fingerprint,
                pre_discount_estimated_total=pricing.pre_discount_estimated_total or pricing.estimated_total,
                offer_id=pricing.applied_offer.offer_id if pricing.applied_offer else None,
                offer_code=pricing.applied_offer.code if pricing.applied_offer else None,
                offer_display_name=pricing.applied_offer.display_name if pricing.applied_offer else None,
                offer_discount_type=pricing.applied_offer.discount_type.value if pricing.applied_offer else None,
                offer_percentage=pricing.applied_offer.percentage if pricing.applied_offer else None,
                offer_maximum_discount=pricing.applied_offer.maximum_discount if pricing.applied_offer else None,
                offer_discount_amount=pricing.applied_offer.discount_amount if pricing.applied_offer else None,
                offer_currency=pricing.applied_offer.currency if pricing.applied_offer else None,
                offer_version=pricing.applied_offer.version if pricing.applied_offer else None,
        )
        self._session.add(snapshot)
        await self._session.flush()
        return ride

    async def get_by_id_internal(
        self, ride_id: UUID, *, for_update: bool = False
    ) -> Ride | None:
        """Internal lookup; caller-facing services must use customer-scoped APIs."""
        statement = select(Ride).where(Ride.id == ride_id)
        if for_update:
            statement = statement.with_for_update()
        return await self._session.scalar(statement)

    async def get_for_customer(
        self, customer_id: UUID, ride_id: UUID, *, for_update: bool = False
    ) -> Ride | None:
        statement = select(Ride).where(
            Ride.id == ride_id, Ride.user_id == customer_id
        )
        if for_update:
            statement = statement.with_for_update()
        return await self._session.scalar(statement)

    async def get_status_for_customer(
        self, customer_id: UUID, ride_id: UUID
    ) -> RideStatusDetails | None:
        row = (
            await self._session.execute(
                select(Ride, AcceptedQuote)
                .outerjoin(AcceptedQuote, AcceptedQuote.ride_id == Ride.id)
                .where(Ride.id == ride_id, Ride.user_id == customer_id)
            )
        ).one_or_none()
        if row is None:
            return None
        ride, quote = row
        assignment_details = None
        if ride.status in {RideStatus.ASSIGNED, RideStatus.ON_TRIP}:
            assignment_details = (
                await self._session.execute(
                    select(Driver.name, Vehicle.registration_number, VehicleType.display_name)
                    .join(Vehicle, Vehicle.driver_id == Driver.id)
                    .join(VehicleType, VehicleType.code == Vehicle.vehicle_type_code)
                    .join(RideAssignment, RideAssignment.vehicle_id == Vehicle.id)
                    .where(
                        RideAssignment.ride_id == ride.id,
                        RideAssignment.released_at.is_(None),
                    )
                )
            ).one_or_none()
        return RideStatusDetails(
            ride_id=ride.id,
            status=ride.status,
            pickup=ride.pickup_display_name or ride.pickup_address,
            destination=ride.destination_display_name or ride.destination_address,
            requested_ride_at=ride.requested_ride_at,
            vehicle_type_code=quote.vehicle_type_code if quote else None,
            estimated_fare=quote.estimated_total if quote else ride.fare_amount,
            currency=quote.currency if quote else ride.fare_currency,
            final_customer_cost=ride.final_customer_cost,
            driver_display_name=assignment_details[0] if assignment_details else None,
            vehicle_registration=assignment_details[1] if assignment_details else None,
            vehicle_display_name=assignment_details[2] if assignment_details else None,
        )

    async def get_active_status_for_customer(
        self, customer_id: UUID
    ) -> RideStatusDetails | None:
        ride_id = await self._session.scalar(
            select(Ride.id)
            .where(
                Ride.user_id == customer_id,
                Ride.status.in_(
                    (RideStatus.BOOKED, RideStatus.ASSIGNED, RideStatus.ON_TRIP)
                ),
            )
            .order_by(Ride.created_at.desc())
            .limit(1)
        )
        if ride_id is None:
            return None
        return await self.get_status_for_customer(customer_id, ride_id)

    async def list_status_for_customer(
        self, customer_id: UUID, *, limit: int = 5
    ) -> list[RideStatusDetails]:
        rows = (
            await self._session.execute(
                select(Ride, AcceptedQuote)
                .outerjoin(AcceptedQuote, AcceptedQuote.ride_id == Ride.id)
                .where(Ride.user_id == customer_id)
                .order_by(Ride.requested_ride_at.desc(), Ride.created_at.desc())
                .limit(limit)
            )
        ).all()
        return [
            RideStatusDetails(
                ride_id=ride.id,
                status=ride.status,
                pickup=ride.pickup_display_name or ride.pickup_address,
                destination=ride.destination_display_name
                or ride.destination_address,
                requested_ride_at=ride.requested_ride_at,
                vehicle_type_code=quote.vehicle_type_code if quote else None,
                estimated_fare=quote.estimated_total if quote else ride.fare_amount,
                currency=quote.currency if quote else ride.fare_currency,
                final_customer_cost=ride.final_customer_cost,
            )
            for ride, quote in rows
        ]

    async def cancel_for_customer(
        self, customer_id: UUID, ride_id: UUID, *, expected_status: RideStatus
    ) -> Ride | None:
        if expected_status not in CANCELLABLE_RIDE_STATUSES:
            raise DomainValidationError("only a pre-trip ride can be cancelled")
        result = await self._session.execute(
            update(Ride)
            .where(
                Ride.id == ride_id,
                Ride.user_id == customer_id,
                Ride.status == expected_status,
            )
            .values(status=RideStatus.CANCELLED, final_customer_cost=Decimal("0.00"))
            .returning(Ride)
        )
        return result.scalar_one_or_none()

    async def list_for_customer(
        self, customer_id: UUID, *, limit: int = 5
    ) -> list[Ride]:
        result = await self._session.scalars(
            select(Ride)
            .where(Ride.user_id == customer_id)
            .order_by(Ride.created_at.desc())
            .limit(limit)
        )
        return list(result)

    async def transition_internal(
        self,
        ride_id: UUID,
        *,
        expected_status: RideStatus,
        requested_status: RideStatus,
    ) -> Ride | None:
        return await self._transition(
            ride_id,
            expected_status=expected_status,
            requested_status=requested_status,
        )

    async def transition_for_customer(
        self,
        customer_id: UUID,
        ride_id: UUID,
        *,
        expected_status: RideStatus,
        requested_status: RideStatus,
    ) -> Ride | None:
        return await self._transition(
            ride_id,
            customer_id=customer_id,
            expected_status=expected_status,
            requested_status=requested_status,
        )

    async def _transition(
        self,
        ride_id: UUID,
        *,
        expected_status: RideStatus,
        requested_status: RideStatus,
        customer_id: UUID | None = None,
    ) -> Ride | None:
        validate_ride_transition(expected_status, requested_status)
        conditions = [Ride.id == ride_id, Ride.status == expected_status]
        if customer_id is not None:
            conditions.append(Ride.user_id == customer_id)
        result = await self._session.execute(
            update(Ride)
            .where(*conditions)
            .values(status=requested_status)
            .returning(Ride)
        )
        return result.scalar_one_or_none()
