import logging
from typing import Protocol

from boloride.domain.models.notification import (
    NotificationDeliveryResult,
    NotificationDeliveryStatus,
    RideNotification,
)

logger = logging.getLogger(__name__)


class NotificationProvider(Protocol):
    async def deliver(
        self, notification: RideNotification
    ) -> NotificationDeliveryResult: ...


class NoOpNotificationProvider:
    async def deliver(
        self, notification: RideNotification
    ) -> NotificationDeliveryResult:
        return NotificationDeliveryResult(status=NotificationDeliveryStatus.SKIPPED)


class NotificationService:
    """Best-effort side effects after the authoritative ride transaction commits."""

    def __init__(self, provider: NotificationProvider | None = None) -> None:
        self._provider = provider or NoOpNotificationProvider()

    async def deliver(
        self, notification: RideNotification
    ) -> NotificationDeliveryResult:
        try:
            return await self._provider.deliver(notification)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "ride_notification_delivery_failed",
                extra={
                    "event": "ride_notification_delivery_failed",
                    "notification_type": notification.type.value,
                    "error_type": type(exc).__name__,
                },
            )
            return NotificationDeliveryResult(status=NotificationDeliveryStatus.FAILED)
