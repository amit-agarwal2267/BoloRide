import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from boloride.agents.context import RideContext
from boloride.db.models.offer import Offer
from boloride.domain.exceptions import DomainValidationError
from boloride.domain.models.offer import (
    AppliedOfferSnapshot, DiscountType, OfferDetails, OfferEligibilityType,
    RedemptionStatus, calculate_discount,
)
from boloride.domain.models.quote import PricingResult, Quote
from boloride.repositories.offer_repository import OfferRepository
from boloride.services.quote_service import QuoteService

logger = logging.getLogger(__name__)


class OfferService:
    def __init__(self, offers: OfferRepository, quotes: QuoteService | None = None) -> None:
        self._offers = offers
        self._quotes = quotes

    @staticmethod
    def _details(row: Offer) -> OfferDetails:
        return OfferDetails(
            row.id, row.code, row.display_name, DiscountType(row.discount_type),
            row.percentage, row.maximum_discount, row.currency,
            row.maximum_redemptions_per_customer,
            OfferEligibilityType(row.eligibility_type), row.active,
            row.effective_from, row.effective_until, row.version,
        )

    async def get_eligible_offers(self, customer_id: UUID, currency: str, *, now: datetime | None = None) -> tuple[OfferDetails, ...]:
        checked_at = now or datetime.now(UTC)
        eligible = []
        for row in await self._offers.list_effective(checked_at):
            details = self._details(row)
            pending, consumed = await self._offers.usage_counts(customer_id, row.id)
            if details.currency == currency and pending + consumed < details.maximum_redemptions_per_customer:
                eligible.append(details)
        logger.info("offer_eligibility_evaluated", extra={"event": "offer_eligibility_evaluated", "eligible_offer_count": len(eligible)})
        return tuple(eligible)

    async def apply_offer(self, customer_id: UUID, context: RideContext, code: str, *, now: datetime | None = None) -> Quote:
        current = await self._quotes.require_current_quote(context, now=now) if self._quotes else context.current_quote
        if current is None:
            raise DomainValidationError("a current fare quote is required before applying an offer")
        if current.pricing.applied_offer is not None:
            raise DomainValidationError("only one offer may be applied to a quote")
        offer = await self._require_eligible(customer_id, code, current.pricing.currency, now=now)
        discount, total = calculate_discount(current.pricing.estimated_total, offer)
        snapshot = AppliedOfferSnapshot(
            offer.id, offer.code, offer.display_name, offer.discount_type,
            offer.percentage, offer.maximum_discount, discount, offer.currency, offer.version,
        )
        pricing = PricingResult(
            current.pricing.pricing_rule_id, current.pricing.vehicle_type_code,
            current.pricing.route_distance_meters, current.pricing.route_duration_seconds,
            current.pricing.route_provider, current.pricing.components,
            current.pricing.toll_status, total, current.pricing.currency,
            pre_discount_estimated_total=current.pricing.estimated_total,
            applied_offer=snapshot,
        )
        created = now or datetime.now(UTC)
        quote = Quote(uuid4(), context.session_id, current.request_fingerprint, pricing, created, created + timedelta(minutes=20))
        context.set_quote(quote)
        logger.info("offer_application_succeeded", extra={"event": "offer_application_succeeded", "offer_code": offer.code, "quote_id": str(quote.id)})
        return quote

    async def remove_offer(self, context: RideContext, *, now: datetime | None = None) -> Quote:
        current = await self._quotes.require_current_quote(context, now=now) if self._quotes else context.current_quote
        if current is None or current.pricing.applied_offer is None or current.pricing.pre_discount_estimated_total is None:
            raise DomainValidationError("current quote has no applied offer")
        pricing = PricingResult(
            current.pricing.pricing_rule_id, current.pricing.vehicle_type_code,
            current.pricing.route_distance_meters, current.pricing.route_duration_seconds,
            current.pricing.route_provider, current.pricing.components,
            current.pricing.toll_status, current.pricing.pre_discount_estimated_total,
            current.pricing.currency,
        )
        created = now or datetime.now(UTC)
        quote = Quote(uuid4(), context.session_id, current.request_fingerprint, pricing, created, created + timedelta(minutes=20))
        context.set_quote(quote)
        logger.info("offer_removed_before_booking", extra={"event": "offer_removed_before_booking", "quote_id": str(quote.id)})
        return quote

    async def revalidate_quote(self, customer_id: UUID, quote: Quote, *, now: datetime | None = None) -> Offer | None:
        snapshot = quote.pricing.applied_offer
        if snapshot is None:
            return None
        row = await self._offers.get_by_id(snapshot.offer_id)
        if row is None:
            raise DomainValidationError("applied offer no longer exists")
        details = self._details(row)
        checked_at = now or datetime.now(UTC)
        pending, consumed = await self._offers.usage_counts(customer_id, row.id)
        if not details.is_effective(checked_at) or details.currency != quote.pricing.currency or details.version != snapshot.version or pending + consumed >= details.maximum_redemptions_per_customer:
            raise DomainValidationError("applied offer is stale or no longer eligible")
        expected_discount, expected_total = calculate_discount(quote.pricing.pre_discount_estimated_total or Decimal("0"), details)
        if expected_discount != snapshot.discount_amount or expected_total != quote.pricing.estimated_total:
            raise DomainValidationError("applied offer snapshot does not match current offer")
        logger.info("offer_booking_revalidation_succeeded", extra={"event": "offer_booking_revalidation_succeeded", "offer_code": details.code})
        return row

    async def create_pending_redemption(self, customer_id: UUID, offer: Offer, ride_id: UUID) -> None:
        try:
            await self._offers.create_pending(customer_id, offer, ride_id)
        except DomainValidationError:
            logger.info("offer_redemption_limit_rejected", extra={"event": "offer_redemption_limit_rejected", "offer_code": offer.code})
            raise
        logger.info("offer_redemption_pending", extra={"event": "offer_redemption_pending", "offer_code": offer.code, "ride_id": str(ride_id)})

    async def finalize_redemption(self, customer_id: UUID, ride_id: UUID, ride_status) -> None:
        if ride_status.value == "completed":
            _, changed = await self._offers.finalize_for_ride(customer_id, ride_id, RedemptionStatus.CONSUMED)
            if changed:
                logger.info("offer_redemption_consumed", extra={"event": "offer_redemption_consumed", "ride_id": str(ride_id)})
        elif ride_status.value == "cancelled":
            _, changed = await self._offers.finalize_for_ride(customer_id, ride_id, RedemptionStatus.CANCELLED)
            if changed:
                logger.info("offer_redemption_cancelled", extra={"event": "offer_redemption_cancelled", "ride_id": str(ride_id)})

    async def _require_eligible(self, customer_id: UUID, code: str, currency: str, *, now: datetime | None = None) -> OfferDetails:
        row = await self._offers.get_by_code(code)
        if row is None:
            raise DomainValidationError("offer does not exist")
        details = self._details(row)
        checked_at = now or datetime.now(UTC)
        pending, consumed = await self._offers.usage_counts(customer_id, row.id)
        if not details.is_effective(checked_at) or details.currency != currency or pending + consumed >= details.maximum_redemptions_per_customer:
            raise DomainValidationError("offer is not eligible")
        return details

    async def create_offer(self, **values) -> Offer:
        self._details(Offer(**values))
        return await self._offers.create(**values)

    async def list_offers(self) -> list[Offer]:
        return await self._offers.list_all()

    async def update_offer(self, code: str, **values) -> Offer:
        row = await self._offers.get_by_code(code)
        if row is None:
            raise DomainValidationError("offer does not exist")
        candidate = {key: getattr(row, key) for key in ("id", "code", "display_name", "discount_type", "percentage", "maximum_discount", "currency", "maximum_redemptions_per_customer", "eligibility_type", "active", "effective_from", "effective_until", "version")}
        candidate.update(values); candidate["version"] = row.version + 1
        self._details(OfferDetails(**candidate))
        return await self._offers.update(row, **values)

    async def deactivate_offer(self, code: str) -> Offer:
        row = await self._offers.get_by_code(code)
        if row is None:
            raise DomainValidationError("offer does not exist")
        return await self._offers.deactivate(row)
