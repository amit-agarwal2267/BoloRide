from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from boloride.db.base import Base


class OfferRedemption(Base):
    __tablename__ = "offer_redemptions"
    __table_args__ = (
        UniqueConstraint("ride_id", name="uq_offer_redemptions_ride"),
        UniqueConstraint("accepted_quote_id", name="uq_offer_redemptions_quote"),
        CheckConstraint("status IN ('pending', 'consumed', 'cancelled')", name="ck_offer_redemptions_status"),
        CheckConstraint("(status = 'consumed') = (consumed_at IS NOT NULL)", name="ck_offer_redemptions_consumed_at"),
    )
    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    offer_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), ForeignKey("offers.id", ondelete="RESTRICT"), nullable=False)
    customer_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    ride_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), ForeignKey("rides.id", ondelete="RESTRICT"), nullable=False)
    accepted_quote_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), ForeignKey("accepted_quotes.id", ondelete="RESTRICT"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
