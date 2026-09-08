from sqlalchemy import Boolean, CheckConstraint, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from boloride.db.base import Base


class VehicleType(Base):
    __tablename__ = "vehicle_types"
    __table_args__ = (
        CheckConstraint(
            "code ~ '^[a-z][a-z0-9_]*$'", name="ck_vehicle_types_code_format"
        ),
        CheckConstraint(
            "display_name !~ '^[[:space:]]*$'",
            name="ck_vehicle_types_display_name_nonempty",
        ),
        CheckConstraint(
            "passenger_capacity > 0",
            name="ck_vehicle_types_passenger_capacity_positive",
        ),
    )

    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    passenger_capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
