from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from boloride.db.base import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("phone_number", name="uq_users_phone_number"),
        CheckConstraint(
            "phone_number ~ '^\\+[1-9][0-9]{7,14}$'",
            name="ck_users_phone_number_e164",
        ),
        CheckConstraint(
            "name !~ '^[[:space:]]*$'", name="ck_users_name_nonempty"
        ),
        CheckConstraint(
            "normalized_name <> '' AND "
            "normalized_name = lower(regexp_replace(btrim(normalized_name), "
            "'[[:space:]]+', ' ', 'g'))",
            name="ck_users_normalized_name_canonical",
        ),
        CheckConstraint("age BETWEEN 1 AND 120", name="ck_users_age_range"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    phone_number: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_name: Mapped[str] = mapped_column(Text, nullable=False)
    age: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
