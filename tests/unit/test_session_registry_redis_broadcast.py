import json

import pytest

from mcpgateway.cache.session_registry import SessionRegistry


@pytest.mark.asyncio
async def test_redis_broadcast_single_encode() -> None:
    """Verify that Redis broadcast encodes payload once as a JSON string.

    The registry should call Redis.publish(channel, payload) where payload
    is a JSON string containing keys: type, message, timestamp.
    """
    reg = SessionRegistry(backend="memory")
    # Force redis mode but avoid real Redis by injecting a dummy client
    reg._backend = "redis"

    captured: list[tuple[str, str]] = []

    class DummyRedis:
        async def publish(self, channel: str, payload: str) -> None:  # pragma: no cover - dummy
            captured.append((channel, payload))

    reg._redis = DummyRedis()

    message = {"method": "ping", "id": 1}
    await reg.broadcast("session-1", message)

    assert captured, "Redis.publish was not called"
    channel, payload = captured[0]
    assert channel == "session-1"
    assert isinstance(payload, str)

    data = json.loads(payload)
    assert data.get("type") == "message"
    assert data.get("message") == message
