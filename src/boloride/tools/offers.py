from uuid import UUID

from boloride.agents.context import RideContext
from boloride.services.offer_service import OfferService


async def get_eligible_offers(service: OfferService, customer_id: UUID, context: RideContext):
    currency = context.current_quote.pricing.currency if context.current_quote else "INR"
    return await service.get_eligible_offers(customer_id, currency)


async def apply_offer(service: OfferService, customer_id: UUID, context: RideContext, offer_code: str):
    return await service.apply_offer(customer_id, context, offer_code)


async def remove_offer(service: OfferService, context: RideContext):
    return await service.remove_offer(context)
