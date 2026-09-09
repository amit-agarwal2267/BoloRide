from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from boloride.db.base import Base


class Vehicle(Base):
    __tablename__ = "vehicles"
    __table_args__ = (
        CheckConstraint(
            "registration_number ~ '^(RJ|UP|MP|PB)[0-9]{2}[A-Z]{2}[0-9]{4}$'",
            name="ck_vehicles_synthetic_registration_format",
        ),
        UniqueConstraint("id", "driver_id", name="uq_vehicles_id_driver_id"),
        Index("ix_vehicles_vehicle_type_code", "vehicle_type_code"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    driver_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("drivers.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    vehicle_type_code: Mapped[str] = mapped_column(
        String(32), ForeignKey("vehicle_types.code", ondelete="RESTRICT"), nullable=False
    )
    registration_number: Mapped[str] = mapped_column(String(16), nullable=False, unique=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
