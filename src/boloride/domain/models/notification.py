from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

DEMO_NOTIFICATION_SENDER = "BR24IC42"


class NotificationDeliveryStatus(StrEnum):
    DELIVERED = "delivered"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True)
class NotificationDeliveryResult:
    status: NotificationDeliveryStatus


class RideNotificationType(StrEnum):
    RIDE_BOOKED = "ride_booked"
    RIDE_CANCELLED = "ride_cancelled"


@dataclass(frozen=True, slots=True)
class RideNotification:
    notification_id: UUID
    type: RideNotificationType
    sender: str
    ride_id: UUID
    timestamp: datetime
    payload: dict[str, str]

    def as_json_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["notification_id"] = str(self.notification_id)
        value["ride_id"] = str(self.ride_id)
        value["type"] = self.type.value
        value["timestamp"] = self.timestamp.isoformat()
        return value
