import os

import pytest

from boloride.config import Settings
from boloride.integrations.langfuse.client import LangfuseClient


@pytest.mark.skipif(
    os.getenv("RUN_LANGFUSE_INTEGRATION_TESTS") != "true",
    reason="requires the self-hosted Langfuse stack",
)
def test_langfuse_authentication_against_docker_stack() -> None:
    client = LangfuseClient(Settings())
    try:
        assert client.is_available()
    finally:
        client.shutdown()
