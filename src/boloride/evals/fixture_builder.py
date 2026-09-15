from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from boloride.agents.context import RideContext
from boloride.domain.enums import RideStatus
from boloride.domain.models.location import ResolvedLocation, RouteResult, TollStatus
from boloride.domain.models.offer import OfferDetails
from boloride.domain.models.quote import Quote
from boloride.domain.models.scheduling import RideTimingIntent
from boloride.domain.models.vehicle import PassengerCountSource
from boloride.domain.policies import CustomerIdentityState
from boloride.evals.schemas import EvaluationCase, LocationFixture
from boloride.repositories.offer_repository import OfferRepository
from boloride.repositories.pricing_rule_repository import PricingRuleRepository
from boloride.repositories.ride_repository import RideRepository
from boloride.repositories.user_repository import UserRepository
from boloride.services.offer_service import OfferService
from boloride.services.pricing_service import PricingService
from boloride.services.quote_service import QuoteService
from boloride.services.user_service import UserService
from boloride.services.vehicle_service import VehicleService
from boloride.repositories.vehicle_type_repository import VehicleTypeRepository


@dataclass(slots=True)
class FixtureRuntime:
    context: RideContext
    customer_id: UUID | None = None
    quote: Quote | None = None
    ride_id: UUID | None = None
    offer: OfferDetails | None = None
    location_search_results: tuple[ResolvedLocation, ...] = ()
    booking_provider_outcome: str | None = None
    provider_booking_id: str | None = None
    references: dict[str, UUID] = field(default_factory=dict)


class _UnusedLocationService:
    async def get_route(self, *_args, **_kwargs):
        raise AssertionError("fixture route must be declared in the dataset")


class EvaluationFixtureBuilder:
    """Translate declared evaluation fixtures through real repositories/services."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def build(self, case: EvaluationCase) -> FixtureRuntime:
        fixture = case.fixture
        if fixture is None:
            raise ValueError("integrated case requires an explicit fixture profile")

        context = RideContext(
            session_id=f"eval-{case.case_id.casefold()}-{uuid4().hex}",
            caller_id=None,
            session_active=fixture.session_active,
        )
        runtime = FixtureRuntime(context=context)
        runtime.location_search_results = tuple(
            _location(item) for item in fixture.location_search_results
        )
        if fixture.booking_provider:
            runtime.booking_provider_outcome = fixture.booking_provider.outcome
            runtime.provider_booking_id = fixture.booking_provider.provider_booking_id

        if fixture.customer is not None:
            identity = await UserService(UserRepository(self._session)).onboard_customer(
                fixture.customer.phone_number,
                fixture.customer.name,
                fixture.customer.age,
            )
            if identity.customer_id is None:
                raise ValueError(f"fixture customer could not be created for {case.case_id}")
            runtime.customer_id = identity.customer_id
            if fixture.customer.verified:
                context.establish_identity(
                    CustomerIdentityState.ONBOARDED_NEW_CUSTOMER,
                    identity.customer_id,
                )

        if fixture.pickup_geography_city:
            context.remember_endpoint_geography(
                "pickup", fixture.pickup_geography_city, None
            )
        if fixture.pickup:
            context.update_pickup(_location(fixture.pickup))
        if fixture.pickup_instruction_handled:
            if fixture.pickup_instructions is None:
                context.decline_pickup_instructions()
            else:
                context.set_pickup_instructions(fixture.pickup_instructions)
        if fixture.destination:
            context.update_destination(_location(fixture.destination))
        if fixture.scheduled_time:
            scheduled = datetime.fromisoformat(fixture.scheduled_time)
            context.update_ride_timing(RideTimingIntent.SCHEDULED, scheduled)
        if fixture.passenger_count is not None:
            await VehicleService(
                VehicleTypeRepository(self._session)
            ).update_passenger_count(
                context,
                fixture.passenger_count,
                PassengerCountSource.USER_PROVIDED,
            )
        if fixture.vehicle_code:
            await VehicleService(
                VehicleTypeRepository(self._session)
            ).select_vehicle_type(context, fixture.vehicle_code)
        if fixture.route:
            context.set_route(
                RouteResult(
                    fixture.route.distance_meters,
                    fixture.route.duration_seconds,
                    fixture.route.provider,
                    TollStatus(fixture.route.toll_status),
                )
            )

        quote_service = QuoteService(
            PricingService(PricingRuleRepository(self._session)),
            _UnusedLocationService(),  # type: ignore[arg-type]
        )
        if fixture.quote:
            quote = await quote_service.create_quote(context)
            if quote.pricing.estimated_total != Decimal(
                fixture.quote.expected_estimated_total
            ):
                raise ValueError(
                    f"fixture quote total mismatch for {case.case_id}: "
                    f"{quote.pricing.estimated_total}"
                )
            runtime.quote = quote
            runtime.references[fixture.quote.quote_ref] = quote.id
            if fixture.quote.confirmed:
                quote_service.confirm_quote(context, quote.id)

        if fixture.offer:
            if runtime.customer_id is None or runtime.quote is None:
                raise ValueError("offer fixture requires a customer and quote")
            eligible = await OfferService(
                OfferRepository(self._session), quote_service
            ).get_eligible_offers(
                runtime.customer_id, runtime.quote.pricing.currency
            )
            runtime.offer = next(
                (offer for offer in eligible if offer.code == fixture.offer.code),
                None,
            )
            if runtime.offer is None:
                raise ValueError(f"declared offer is not eligible for {case.case_id}")

        if fixture.ride:
            if runtime.customer_id is None or runtime.quote is None:
                raise ValueError("ride fixture requires a customer and quote")
            ride_id = uuid4()
            ride = await RideRepository(self._session).create_booked(
                ride_id,
                runtime.customer_id,
                context.pickup,  # type: ignore[arg-type]
                context.destination,  # type: ignore[arg-type]
                context.ride_time,  # type: ignore[arg-type]
                provider=fixture.ride.provider,
                provider_booking_id=fixture.ride.provider_booking_id,
                accepted_quote=runtime.quote,
            )
            requested_status = RideStatus(fixture.ride.status)
            if requested_status is not RideStatus.BOOKED:
                changed = await RideRepository(self._session).transition_internal(
                    ride.id,
                    expected_status=RideStatus.BOOKED,
                    requested_status=requested_status,
                )
                if not changed:
                    raise ValueError(f"could not establish ride state for {case.case_id}")
            runtime.ride_id = ride.id
            runtime.references[fixture.ride.ride_ref] = ride.id

        return runtime


def _location(fixture: LocationFixture) -> ResolvedLocation:
    return ResolvedLocation(
        address=fixture.address,
        latitude=Decimal(fixture.latitude),
        longitude=Decimal(fixture.longitude),
        display_name=fixture.display_name,
        provider=fixture.provider,
        provider_place_id=fixture.provider_place_id,
        place_types=fixture.place_types,
        country=fixture.country,
        city=fixture.city,
        state=fixture.state,
    )
