import json

from boloride.domain.models.notification import RideNotification


class LiveKitDemoInboxProvider:
    """Deliver typed demo-inbox events over the already-connected LiveKit room."""

    def __init__(self, room) -> None:
        self._room = room

    async def deliver(self, notification: RideNotification) -> None:
        self._room.local_participant.publish_data(
            json.dumps(notification.as_json_dict()).encode("utf-8"),
            reliable=True,
            topic="boloride.notifications",
        )
