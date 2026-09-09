from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Enum, Index, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from boloride.db.base import Base
from boloride.domain.models.fleet import DriverAvailability


class Driver(Base):
    __tablename__ = "drivers"
    __table_args__ = (
        CheckConstraint("name !~ '^[[:space:]]*$'", name="ck_drivers_name_nonempty"),
        CheckConstraint("latitude BETWEEN -90 AND 90", name="ck_drivers_latitude"),
        CheckConstraint("longitude BETWEEN -180 AND 180", name="ck_drivers_longitude"),
        CheckConstraint("city !~ '^[[:space:]]*$'", name="ck_drivers_city_nonempty"),
        CheckConstraint("state !~ '^[[:space:]]*$'", name="ck_drivers_state_nonempty"),
        Index("ix_drivers_dispatch_area", "availability", "state", "city"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    availability: Mapped[DriverAvailability] = mapped_column(
        Enum(
            DriverAvailability,
            values_callable=lambda states: [state.value for state in states],
            native_enum=False,
            create_constraint=True,
            name="driver_availability",
        ),
        nullable=False,
        default=DriverAvailability.AVAILABLE,
    )
    latitude: Mapped[Decimal] = mapped_column(Numeric(9, 6), nullable=False)
    longitude: Mapped[Decimal] = mapped_column(Numeric(9, 6), nullable=False)
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    state: Mapped[str] = mapped_column(String(100), nullable=False)
    seed_version: Mapped[str | None] = mapped_column(String(64))
    seed_key: Mapped[str | None] = mapped_column(String(96), unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
