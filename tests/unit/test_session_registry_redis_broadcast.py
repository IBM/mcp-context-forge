# -*- coding: utf-8 -*-
"""Unit test: Redis broadcast single-encoding

Location: ./tests/unit/test_session_registry_redis_broadcast.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

This unit test verifies that `SessionRegistry.broadcast()` when using the
Redis backend publishes a single JSON-encoded payload (not double-encoded).
The test injects a dummy Redis client to assert the published payload shape.
"""

import orjson
import pytest

from mcpgateway.cache.session_registry import SessionRegistry


@pytest.mark.asyncio
async def test_redis_broadcast_single_encode() -> None:
    """Verify that Redis broadcast encodes payload once as JSON bytes.

    The registry should call Redis.publish(channel, payload) where payload
    is JSON bytes containing keys: type, message, timestamp.
    """
    reg = SessionRegistry(backend="memory")
    # Force redis mode but avoid real Redis by injecting a dummy client
    reg._backend = "redis"

    captured: list[tuple[str, bytes]] = []

    class DummyRedis:
        async def publish(self, channel: str, payload: bytes) -> None:  # pragma: no cover - dummy
            captured.append((channel, payload))

    reg._redis = DummyRedis()

    message = {"method": "ping", "id": 1}
    await reg.broadcast("session-1", message)

    assert captured, "Redis.publish was not called"
    channel, payload = captured[0]
    assert channel == "session-1"
    assert isinstance(payload, bytes)

    data = orjson.loads(payload)
    assert data.get("type") == "message"
    assert data.get("message") == message
