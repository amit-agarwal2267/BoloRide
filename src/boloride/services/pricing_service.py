from datetime import time
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo

from boloride.domain.exceptions import DomainValidationError
from boloride.domain.models.location import AirportClassification, ResolvedLocation, RouteResult, TollStatus
from boloride.domain.models.quote import FareComponent, FareComponentType, PricingResult, PricingRuleDetails
from boloride.repositories.pricing_rule_repository import PricingRuleRepository

MONEY = Decimal("0.01")
WHOLE_INR = Decimal("1")
INDIA_PRICING_TIMEZONE = ZoneInfo("Asia/Kolkata")


class PricingService:
    def __init__(self, rules: PricingRuleRepository) -> None:
        self._rules = rules

    async def calculate(
        self,
        vehicle_type_code: str,
        pickup: ResolvedLocation,
        destination: ResolvedLocation,
        requested_ride_at,
        route: RouteResult,
    ) -> PricingResult:
        if requested_ride_at.tzinfo is None:
            raise DomainValidationError("scheduled pickup time must be timezone-aware")
        self._require_supported_pickup(pickup)
        classifications = (pickup.airport_classification, destination.airport_classification)
        if AirportClassification.UNKNOWN in classifications:
            raise DomainValidationError("airport classification is required for pricing")
        rule_row = await self._rules.get_active_for_vehicle(vehicle_type_code)
        if rule_row is None:
            raise DomainValidationError("active pricing rule is required")
        rule = PricingRuleDetails(
            rule_row.id, rule_row.vehicle_type_code, rule_row.base_fare,
            rule_row.per_km_rate, rule_row.night_charge, rule_row.airport_fee,
            rule_row.currency, rule_row.active,
        )
        base = self._money(rule.base_fare)
        distance = self._money(Decimal(route.distance_meters) / Decimal(1000) * rule.per_km_rate)
        local_time = requested_ride_at.astimezone(INDIA_PRICING_TIMEZONE).time()
        night = self._money(rule.night_charge if local_time >= time(23) or local_time < time(5) else Decimal(0))
        airport = self._money(
            rule.airport_fee if AirportClassification.AIRPORT in classifications else Decimal(0)
        )
        toll: Decimal | None = None
        if route.toll_status is TollStatus.ESTIMATE_AVAILABLE:
            if route.toll_currency != rule.currency:
                raise DomainValidationError("route toll currency must match pricing currency")
            toll = self._money(route.toll_estimate or Decimal(0))
        components = [
            FareComponent(FareComponentType.BASE_FARE, base),
            FareComponent(FareComponentType.DISTANCE_FARE, distance),
            FareComponent(FareComponentType.NIGHT_CHARGE, night),
            FareComponent(FareComponentType.AIRPORT_FEE, airport),
        ]
        if toll is not None:
            components.append(FareComponent(FareComponentType.TOLL_ESTIMATE, toll))
        total = self._money(sum((item.amount for item in components), Decimal(0)).quantize(WHOLE_INR, rounding=ROUND_HALF_UP))
        return PricingResult(
            rule.id, rule.vehicle_type_code, route.distance_meters,
            route.duration_seconds, route.provider, tuple(components),
            route.toll_status, total, rule.currency,
        )

    async def is_rule_active(self, pricing_rule_id) -> bool:
        return await self._rules.is_active(pricing_rule_id)

    @staticmethod
    def _money(value: Decimal) -> Decimal:
        return value.quantize(MONEY, rounding=ROUND_HALF_UP)

    @staticmethod
    def _require_supported_pickup(pickup: ResolvedLocation) -> None:
        if pickup.country and pickup.country not in {"in", "india"}:
            raise DomainValidationError("Prototype v1 supports pickups in India only")
