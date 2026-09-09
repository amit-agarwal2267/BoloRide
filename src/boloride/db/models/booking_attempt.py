from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from boloride.db.base import Base


class BookingAttempt(Base):
    __tablename__ = "booking_attempts"
    __table_args__ = (
        UniqueConstraint("quote_id", name="uq_booking_attempts_quote"),
        UniqueConstraint("provider_idempotency_key", name="uq_booking_attempts_idempotency_key"),
        UniqueConstraint("ride_id", name="uq_booking_attempts_ride"),
        UniqueConstraint("provider", "provider_booking_id", name="uq_booking_attempts_provider_booking"),
        CheckConstraint(
            "state IN ('ready','provider_calling','provider_confirmed','finalized',"
            "'definitively_failed','outcome_unknown','requote_required')",
            name="ck_booking_attempts_state",
        ),
        CheckConstraint("snapshot_version = 1", name="ck_booking_attempts_snapshot_version"),
        CheckConstraint(
            "NOT capacity_reserved OR offer_id IS NOT NULL",
            name="ck_booking_attempts_capacity_offer",
        ),
        CheckConstraint(
            "(provider_booking_id IS NULL AND provider_result_snapshot IS NULL) OR "
            "(provider_booking_id IS NOT NULL AND provider_result_snapshot IS NOT NULL)",
            name="ck_booking_attempts_provider_result",
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    quote_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    customer_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    provider_idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    snapshot_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    authorized_quote_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    provider_call_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider_booking_id: Mapped[str | None] = mapped_column(String(255))
    provider_result_snapshot: Mapped[dict | None] = mapped_column(JSON)
    failure_category: Mapped[str | None] = mapped_column(String(64))
    offer_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True), ForeignKey("offers.id", ondelete="RESTRICT"))
    capacity_reserved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ride_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True), ForeignKey("rides.id", ondelete="RESTRICT"))
    reconciliation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_reconciled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
