from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from boloride.db.models.pricing_rule import PricingRule


class PricingRuleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_active_for_vehicle(self, vehicle_type_code: str) -> PricingRule | None:
        return await self._session.scalar(
            select(PricingRule).where(
                PricingRule.vehicle_type_code == vehicle_type_code,
                PricingRule.active.is_(True),
            )
        )

    async def is_active(self, pricing_rule_id: UUID) -> bool:
        return (
            await self._session.scalar(
                select(PricingRule.active).where(PricingRule.id == pricing_rule_id)
            )
            is True
        )
