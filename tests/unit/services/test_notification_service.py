from uuid import uuid4
from datetime import UTC, datetime

import pytest

from boloride.domain.models.notification import (
    DEMO_NOTIFICATION_SENDER,
    RideNotification,
    RideNotificationType,
)
from boloride.services.notification_service import NotificationService
from boloride.integrations.notifications.livekit import LiveKitDemoInboxProvider
from types import SimpleNamespace
from unittest.mock import AsyncMock


def notification() -> RideNotification:
    return RideNotification(
        uuid4(), RideNotificationType.RIDE_BOOKED, DEMO_NOTIFICATION_SENDER,
        uuid4(), datetime.now(UTC), {"source": "Home"},
    )


@pytest.mark.asyncio
async def test_notification_delivery_is_typed_and_exactly_once() -> None:
    delivered = []

    class Provider:
        async def deliver(self, value):
            delivered.append(value)

    item = notification()
    await NotificationService(Provider()).deliver(item)
    assert delivered == [item]
    assert item.as_json_dict()["sender"] == "BR24IC42"


@pytest.mark.asyncio
async def test_notification_failure_never_escapes() -> None:
    class Provider:
        async def deliver(self, value):
            raise RuntimeError("delivery unavailable")

    await NotificationService(Provider()).deliver(notification())


@pytest.mark.asyncio
async def test_livekit_demo_delivery_awaits_publish_data() -> None:
    publish_data = AsyncMock()
    provider = LiveKitDemoInboxProvider(
        SimpleNamespace(local_participant=SimpleNamespace(publish_data=publish_data))
    )

    await provider.deliver(notification())

    publish_data.assert_awaited_once()
    assert publish_data.await_args.kwargs == {
        "reliable": True,
        "topic": "boloride.notifications",
    }
