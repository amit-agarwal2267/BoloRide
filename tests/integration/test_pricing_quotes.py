from decimal import Decimal

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from boloride.db.models.pricing_rule import PricingRule
from boloride.repositories.pricing_rule_repository import PricingRuleRepository


EXPECTED = {
    "auto": (Decimal("30.00"), Decimal("10.00"), Decimal("50.00")),
    "mini": (Decimal("40.00"), Decimal("12.00"), Decimal("100.00")),
    "sedan": (Decimal("50.00"), Decimal("14.00"), Decimal("150.00")),
    "suv": (Decimal("70.00"), Decimal("18.00"), Decimal("200.00")),
    "premium": (Decimal("90.00"), Decimal("22.00"), Decimal("250.00")),
}


@pytest.mark.asyncio
async def test_seeded_active_pricing_rules_are_authoritative(db_session: AsyncSession):
    repository = PricingRuleRepository(db_session)
    assert await db_session.scalar(select(func.count()).select_from(PricingRule)) == 5
    for code, expected in EXPECTED.items():
        rule = await repository.get_active_for_vehicle(code)
        assert rule is not None
        assert (rule.base_fare, rule.per_km_rate, rule.night_charge) == expected
        assert rule.airport_fee == Decimal("150.00")
        assert rule.currency == "INR"


@pytest.mark.asyncio
async def test_only_one_active_rule_per_vehicle_and_history_is_versionable(db_session: AsyncSession):
    current = await PricingRuleRepository(db_session).get_active_for_vehicle("auto")
    assert current is not None
    db_session.add(PricingRule(vehicle_type_code="auto", base_fare=Decimal("35"), per_km_rate=Decimal("11"), night_charge=Decimal("55"), airport_fee=Decimal("150"), currency="INR", active=True))
    with pytest.raises(IntegrityError):
        await db_session.flush()
