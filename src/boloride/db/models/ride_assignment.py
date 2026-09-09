from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Index, String, func, text
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from boloride.db.base import Base


class RideAssignment(Base):
    __tablename__ = "ride_assignments"
    __table_args__ = (
        CheckConstraint(
            "(released_at IS NULL AND release_reason IS NULL) OR "
            "(released_at IS NOT NULL AND release_reason IN ('cancelled', 'completed'))",
            name="ck_ride_assignments_release_pair",
        ),
        ForeignKeyConstraint(
            ["vehicle_id", "driver_id"],
            ["vehicles.id", "vehicles.driver_id"],
            name="fk_ride_assignments_vehicle_driver",
            ondelete="RESTRICT",
        ),
        Index(
            "uq_ride_assignments_active_driver",
            "driver_id",
            unique=True,
            postgresql_where=text("released_at IS NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    ride_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("rides.id", ondelete="RESTRICT"),
        nullable=False, unique=True,
    )
    driver_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("drivers.id", ondelete="RESTRICT"), nullable=False
    )
    vehicle_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    release_reason: Mapped[str | None] = mapped_column(String(16))
