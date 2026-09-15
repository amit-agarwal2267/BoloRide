import logging
from typing import Protocol

from boloride.domain.models.notification import RideNotification


logger = logging.getLogger(__name__)


class NotificationProvider(Protocol):
    async def deliver(self, notification: RideNotification) -> None: ...


class NoOpNotificationProvider:
    async def deliver(self, notification: RideNotification) -> None:
        return None


class NotificationService:
    """Best-effort side effects after the authoritative ride transaction commits."""

    def __init__(self, provider: NotificationProvider | None = None) -> None:
        self._provider = provider or NoOpNotificationProvider()

    async def deliver(self, notification: RideNotification) -> None:
        try:
            await self._provider.deliver(notification)
        except Exception as exc:
            logger.warning(
                "ride_notification_delivery_failed",
                extra={
                    "event": "ride_notification_delivery_failed",
                    "notification_type": notification.type.value,
                    "error_type": type(exc).__name__,
                },
            )
