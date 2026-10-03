from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from boloride.domain.models.notification import (
    DEMO_NOTIFICATION_SENDER,
    NotificationDeliveryResult,
    NotificationDeliveryStatus,
    RideNotification,
    RideNotificationType,
)
from boloride.integrations.notifications.livekit import LiveKitDemoInboxProvider
from boloride.services.notification_service import NotificationService


def notification() -> RideNotification:
    return RideNotification(
        uuid4(),
        RideNotificationType.RIDE_BOOKED,
        DEMO_NOTIFICATION_SENDER,
        uuid4(),
        datetime.now(UTC),
        {"source": "Home"},
    )


@pytest.mark.asyncio
async def test_notification_delivery_is_typed_and_exactly_once() -> None:
    delivered = []

    class Provider:
        async def deliver(self, value):
            delivered.append(value)
            return NotificationDeliveryResult(
                status=NotificationDeliveryStatus.DELIVERED
            )

    item = notification()
    result = await NotificationService(Provider()).deliver(item)
    assert result == NotificationDeliveryResult(
        status=NotificationDeliveryStatus.DELIVERED
    )
    assert delivered == [item]
    assert item.as_json_dict()["sender"] == "BR24IC42"

    noop_result = await NotificationService().deliver(item)
    assert noop_result == NotificationDeliveryResult(
        status=NotificationDeliveryStatus.SKIPPED
    )


@pytest.mark.asyncio
async def test_notification_failure_never_escapes() -> None:
    class Provider:
        async def deliver(self, value):
            raise RuntimeError("delivery unavailable")

    result = await NotificationService(Provider()).deliver(notification())
    assert result == NotificationDeliveryResult(
        status=NotificationDeliveryStatus.FAILED
    )


@pytest.mark.asyncio
async def test_livekit_demo_delivery_awaits_publish_data() -> None:
    publish_data = AsyncMock()
    provider = LiveKitDemoInboxProvider(
        SimpleNamespace(local_participant=SimpleNamespace(publish_data=publish_data))
    )

    result = await provider.deliver(notification())

    assert result == NotificationDeliveryResult(
        status=NotificationDeliveryStatus.DELIVERED
    )
    publish_data.assert_awaited_once()
    assert publish_data.await_args.kwargs == {
        "reliable": True,
        "topic": "boloride.notifications",
    }
