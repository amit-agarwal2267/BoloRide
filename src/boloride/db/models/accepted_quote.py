from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from boloride.db.base import Base


class AcceptedQuote(Base):
    __tablename__ = "accepted_quotes"
    __table_args__ = (
        UniqueConstraint("ride_id", name="uq_accepted_quotes_ride_id"),
        CheckConstraint("route_distance_meters >= 0", name="ck_accepted_quotes_distance"),
        CheckConstraint(
            "route_duration_seconds IS NULL OR route_duration_seconds >= 0",
            name="ck_accepted_quotes_duration",
        ),
        CheckConstraint(
            "base_fare >= 0 AND distance_fare >= 0 AND night_charge >= 0 "
            "AND airport_fee >= 0 AND estimated_total >= 0",
            name="ck_accepted_quotes_amounts",
        ),
        CheckConstraint(
            "(toll_estimate IS NULL) OR toll_estimate >= 0",
            name="ck_accepted_quotes_toll",
        ),
        CheckConstraint(
            "toll_status IN ('estimate_available', 'may_apply', 'no_toll', 'unknown')",
            name="ck_accepted_quotes_toll_status",
        ),
        CheckConstraint(
            "(toll_status = 'estimate_available') = (toll_estimate IS NOT NULL)",
            name="ck_accepted_quotes_toll_pair",
        ),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_accepted_quotes_currency"),
        CheckConstraint(
            "request_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_accepted_quotes_fingerprint",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    ride_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("rides.id", ondelete="RESTRICT"),
        nullable=False,
    )
    pricing_rule_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    vehicle_type_code: Mapped[str] = mapped_column(String(32), nullable=False)
    session_id: Mapped[str] = mapped_column(String(255), nullable=False)
    route_provider: Mapped[str] = mapped_column(String(50), nullable=False)
    route_distance_meters: Mapped[int] = mapped_column(Integer, nullable=False)
    route_duration_seconds: Mapped[int | None] = mapped_column(Integer)
    base_fare: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    distance_fare: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    night_charge: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    airport_fee: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    toll_estimate: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    toll_status: Mapped[str] = mapped_column(String(32), nullable=False)
    estimated_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    quoted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
