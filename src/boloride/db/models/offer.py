from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from boloride.db.base import Base


class Offer(Base):
    __tablename__ = "offers"
    __table_args__ = (
        CheckConstraint("code ~ '^[A-Z][A-Z0-9_]*$'", name="ck_offers_code"),
        CheckConstraint("display_name !~ '^[[:space:]]*$'", name="ck_offers_name"),
        CheckConstraint("discount_type = 'percentage'", name="ck_offers_discount_type"),
        CheckConstraint("percentage > 0 AND percentage <= 100", name="ck_offers_percentage"),
        CheckConstraint("maximum_discount >= 0", name="ck_offers_maximum_discount"),
        CheckConstraint("currency = 'INR'", name="ck_offers_currency"),
        CheckConstraint("maximum_redemptions_per_customer > 0", name="ck_offers_redemption_limit"),
        CheckConstraint("eligibility_type = 'new_customer'", name="ck_offers_eligibility_type"),
        CheckConstraint("effective_until IS NULL OR effective_until > effective_from", name="ck_offers_effective_period"),
        CheckConstraint("version > 0", name="ck_offers_version"),
    )
    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    discount_type: Mapped[str] = mapped_column(String(32), nullable=False)
    percentage: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    maximum_discount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    maximum_redemptions_per_customer: Mapped[int] = mapped_column(Integer, nullable=False)
    eligibility_type: Mapped[str] = mapped_column(String(32), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
