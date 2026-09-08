from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from boloride.agents.context import RideContext
from boloride.domain.exceptions import DomainValidationError
from boloride.domain.models.quote import Quote, request_fingerprint
from boloride.services.location_service import LocationService
from boloride.services.pricing_service import PricingService

QUOTE_VALIDITY = timedelta(minutes=20)


class QuoteService:
    def __init__(self, pricing: PricingService, locations: LocationService) -> None:
        self._pricing = pricing
        self._locations = locations

    async def create_quote(self, context: RideContext, *, now: datetime | None = None) -> Quote:
        pickup, destination, ride_at, vehicle = self._require_inputs(context)
        route = await self._locations.get_route(pickup, destination)
        pricing = await self._pricing.calculate(vehicle, pickup, destination, ride_at, route)
        quoted_at = now or datetime.now(UTC)
        if quoted_at.tzinfo is None:
            raise DomainValidationError("quote creation time must be timezone-aware")
        quote = Quote(
            uuid4(), context.session_id,
            request_fingerprint(pickup, destination, ride_at, context.passenger_count, vehicle),
            pricing, quoted_at, quoted_at + QUOTE_VALIDITY,
        )
        context.set_quote(quote)
        return quote

    async def require_bookable_quote(self, context: RideContext, *, now: datetime | None = None) -> Quote:
        if not context.session_active:
            raise DomainValidationError("quote is not valid for this active session")
        quote = context.current_quote
        if quote is None:
            raise DomainValidationError("a current fare quote is required before booking")
        if quote.session_id != context.session_id:
            raise DomainValidationError("quote is not valid for this active session")
        check_time = now or datetime.now(UTC)
        if not quote.is_time_valid(check_time):
            raise DomainValidationError("fare quote has expired")
        pickup, destination, ride_at, vehicle = self._require_inputs(context)
        fingerprint = request_fingerprint(pickup, destination, ride_at, context.passenger_count, vehicle)
        if fingerprint != quote.request_fingerprint:
            raise DomainValidationError("fare quote no longer matches the ride request")
        if not await self._pricing.is_rule_active(quote.pricing.pricing_rule_id):
            raise DomainValidationError("fare quote pricing rule is no longer active")
        if context.confirmed_quote_id != quote.id:
            raise DomainValidationError("explicit confirmation for the current quote is required")
        return quote

    @staticmethod
    def _require_inputs(context: RideContext):
        if context.pickup is None or context.destination is None:
            raise DomainValidationError("pickup and destination are required for a quote")
        if context.ride_time is None:
            raise DomainValidationError("ride time is required for a quote")
        if context.ride_time.tzinfo is None:
            raise DomainValidationError("ride time must be timezone-aware")
        if context.selected_vehicle_type_code is None:
            raise DomainValidationError("vehicle type is required for a quote")
        return context.pickup, context.destination, context.ride_time, context.selected_vehicle_type_code

    @staticmethod
    def confirm_quote(context: RideContext, quote_id: UUID) -> None:
        context.confirm_quote(quote_id)

    @staticmethod
    def disconnect(context: RideContext) -> None:
        context.disconnect()
