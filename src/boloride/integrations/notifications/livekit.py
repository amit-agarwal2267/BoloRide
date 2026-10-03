import json

from boloride.domain.models.notification import (
    NotificationDeliveryResult,
    NotificationDeliveryStatus,
    RideNotification,
)


class LiveKitDemoInboxProvider:
    """Deliver typed demo-inbox events over the already-connected LiveKit room."""

    def __init__(self, room) -> None:
        self._room = room

    async def deliver(
        self, notification: RideNotification
    ) -> NotificationDeliveryResult:
        await self._room.local_participant.publish_data(
            json.dumps(notification.as_json_dict()).encode("utf-8"),
            reliable=True,
            topic="boloride.notifications",
        )
        return NotificationDeliveryResult(status=NotificationDeliveryStatus.DELIVERED)
