from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from boloride.db.base import Base


class DemoPhoneLease(Base):
    __tablename__ = "demo_phone_leases"
    __table_args__ = (
        UniqueConstraint("phone_number", name="uq_demo_phone_leases_phone"),
        CheckConstraint(
            "phone_number ~ '^\\+91[6-9][0-9]{9}$'",
            name="ck_demo_phone_leases_indian_mobile",
        ),
        CheckConstraint(
            "(active_call_id IS NULL AND active_call_expires_at IS NULL) OR "
            "(active_call_id IS NOT NULL AND active_call_expires_at IS NOT NULL)",
            name="ck_demo_phone_leases_call_pair",
        ),
    )

    auth_user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, nullable=False
    )
    phone_number: Mapped[str] = mapped_column(String(16), nullable=False)
    active_call_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=True
    )
    active_call_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
