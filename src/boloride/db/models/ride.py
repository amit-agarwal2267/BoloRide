from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from boloride.db.base import Base
from boloride.domain.enums import RideStatus


class Ride(Base):
    __tablename__ = "rides"
    __table_args__ = (
        UniqueConstraint(
            "provider", "provider_booking_id", name="uq_rides_provider_booking"
        ),
        CheckConstraint("pickup_latitude BETWEEN -90 AND 90", name="ck_rides_pickup_latitude"),
        CheckConstraint("pickup_longitude BETWEEN -180 AND 180", name="ck_rides_pickup_longitude"),
        CheckConstraint("destination_latitude BETWEEN -90 AND 90", name="ck_rides_destination_latitude"),
        CheckConstraint("destination_longitude BETWEEN -180 AND 180", name="ck_rides_destination_longitude"),
        CheckConstraint(
            "pickup_latitude <> destination_latitude OR "
            "pickup_longitude <> destination_longitude",
            name="ck_rides_distinct_locations",
        ),
        CheckConstraint(
            "(fare_amount IS NULL AND fare_currency IS NULL) OR "
            "(fare_amount > 0 AND fare_currency ~ '^[A-Z]{3}$')",
            name="ck_rides_fare_pair",
        ),
        CheckConstraint(
            "confirmed_at IS NOT NULL AND provider IS NOT NULL "
            "AND provider_booking_id IS NOT NULL AND booked_at IS NOT NULL "
            "AND fare_amount IS NOT NULL AND fare_currency IS NOT NULL",
            name="ck_rides_status_fields",
        ),
        CheckConstraint(
            "final_customer_cost IS NULL OR final_customer_cost >= 0",
            name="ck_rides_final_customer_cost_nonnegative",
        ),
        CheckConstraint(
            "status <> 'cancelled' OR "
            "(final_customer_cost IS NOT NULL AND final_customer_cost = 0)",
            name="ck_rides_cancelled_zero_cost",
        ),
        Index(
            "uq_rides_one_active_per_customer",
            "user_id",
            unique=True,
            postgresql_where=text(
                "status IN ('booked', 'assigned', 'on_trip')"
            ),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    pickup_address: Mapped[str] = mapped_column(Text, nullable=False)
    pickup_display_name: Mapped[str | None] = mapped_column(String(255))
    pickup_latitude: Mapped[Decimal] = mapped_column(Numeric(9, 6), nullable=False)
    pickup_longitude: Mapped[Decimal] = mapped_column(Numeric(9, 6), nullable=False)
    pickup_provider: Mapped[str | None] = mapped_column(String(50))
    pickup_provider_place_id: Mapped[str | None] = mapped_column(String(255))
    destination_address: Mapped[str] = mapped_column(Text, nullable=False)
    destination_display_name: Mapped[str | None] = mapped_column(String(255))
    destination_latitude: Mapped[Decimal] = mapped_column(Numeric(9, 6), nullable=False)
    destination_longitude: Mapped[Decimal] = mapped_column(Numeric(9, 6), nullable=False)
    destination_provider: Mapped[str | None] = mapped_column(String(50))
    destination_provider_place_id: Mapped[str | None] = mapped_column(String(255))
    requested_ride_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[RideStatus] = mapped_column(
        Enum(
            RideStatus,
            values_callable=lambda statuses: [status.value for status in statuses],
            native_enum=False,
            create_constraint=True,
            name="ck_rides_status",
            length=32,
        ),
        nullable=False,
        default=RideStatus.BOOKED,
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider: Mapped[str | None] = mapped_column(String(50))
    provider_booking_id: Mapped[str | None] = mapped_column(String(255))
    booked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fare_amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    fare_currency: Mapped[str | None] = mapped_column(String(3))
    final_customer_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
