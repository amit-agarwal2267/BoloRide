from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, func, text
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from boloride.db.base import Base


class PricingRule(Base):
    __tablename__ = "pricing_rules"
    __table_args__ = (
        CheckConstraint("base_fare >= 0", name="ck_pricing_rules_base_fare"),
        CheckConstraint("per_km_rate >= 0", name="ck_pricing_rules_per_km_rate"),
        CheckConstraint("night_charge >= 0", name="ck_pricing_rules_night_charge"),
        CheckConstraint("airport_fee >= 0", name="ck_pricing_rules_airport_fee"),
        CheckConstraint(
            "currency ~ '^[A-Z]{3}$'", name="ck_pricing_rules_currency"
        ),
        Index(
            "uq_pricing_rules_active_vehicle",
            "vehicle_type_code",
            unique=True,
            postgresql_where=text("active"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    vehicle_type_code: Mapped[str] = mapped_column(
        String(32), ForeignKey("vehicle_types.code", ondelete="RESTRICT"), nullable=False
    )
    base_fare: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    per_km_rate: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    night_charge: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    airport_fee: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
