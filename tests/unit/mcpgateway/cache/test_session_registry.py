# -*- coding: utf-8 -*-
"""Memory-backend unit tests for ``session_registry.py``.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

This suite exercises the in-memory implementation of
:pyfile:`mcpgateway/cache/session_registry.py`.

Covered behaviours
------------------
* add_session / get_session / get_session_sync / remove_session
* broadcast -> respond for **dict**, **list**, **str** payloads
* generate_response branches:
  - initialize (result + notifications)
  - ping
  - tools/list (with stubbed service + DB)
* handle_initialize_logic success, and both error branches


Includes comprehensive backend testing, error scenarios, and cleanup tasks.
"""

# Future
from __future__ import annotations

# Standard
import asyncio
import json
import re
from typing import Any, Dict, List
from unittest.mock import AsyncMock, Mock, patch

# Third-Party
from fastapi import HTTPException
import pytest

# First-Party
from mcpgateway.cache.session_registry import SessionRegistry
from mcpgateway.config import settings


# --------------------------------------------------------------------------- #
# Minimal SSE transport stub                                                  #
# --------------------------------------------------------------------------- #
class FakeSSETransport:
    """Stub implementing just the subset of the API used by SessionRegistry."""

    def __init__(self, session_id: str, connected: bool = True):
        self.session_id = session_id
        self._connected = connected
        self.sent: List[Any] = []
        self.disconnect_called = False

    async def disconnect(self) -> None:  # noqa: D401
        self._connected = False
        self.disconnect_called = True

    async def is_connected(self) -> bool:  # noqa: D401
        return self._connected

    async def send_message(self, msg) -> None:  # noqa: D401
        if not self._connected:
            raise ConnectionError("Transport disconnected")
        # Deep-copy through JSON round-trip for realism
        self.sent.append(json.loads(json.dumps(msg)))

    def make_disconnected(self):
        """Helper to simulate disconnection."""
        self._connected = False


class MockRedis:
    """Mock Redis client for testing Redis backend."""

    def __init__(self):
        self.data = {}
        self.published = []
        self.should_fail = False

    @classmethod
    def from_url(cls, url):
        return cls()

    async def setex(self, key, ttl, value):
        if self.should_fail:
            raise Exception("Redis connection failed")
        self.data[key] = {"value": value, "ttl": ttl}

    async def exists(self, key):
        if self.should_fail:
            raise Exception("Redis connection failed")
        return key in self.data

    async def delete(self, key):
        if self.should_fail:
            raise Exception("Redis connection failed")
        self.data.pop(key, None)

    async def expire(self, key, ttl):
        if self.should_fail:
            raise Exception("Redis connection failed")
        if key in self.data:
            self.data[key]["ttl"] = ttl

    async def publish(self, channel, message):
        if self.should_fail:
            raise Exception("Redis connection failed")
        self.published.append({"channel": channel, "message": message})

    def pubsub(self):
        return MockPubSub()

    def close(self):
        pass


class MockPubSub:
    """Mock Redis PubSub."""

    def __init__(self):
        self.subscribed_channels = set()

    def subscribe(self, channel):
        self.subscribed_channels.add(channel)

    async def subscribe(self, channel):
        self.subscribed_channels.add(channel)

    async def unsubscribe(self, channel):
        self.subscribed_channels.discard(channel)

    async def listen(self):
        # Simulate empty message stream
        if False:  # Never yield anything
            yield {}

    def close(self):
        pass


# --------------------------------------------------------------------------- #
# Event-loop fixture (pytest default loop is function-scoped)                 #
# --------------------------------------------------------------------------- #
@pytest.fixture(name="event_loop")
def _event_loop_fixture():
    """Provide a fresh asyncio loop for these async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# --------------------------------------------------------------------------- #
# SessionRegistry fixture (memory backend)                                    #
# --------------------------------------------------------------------------- #
@pytest.fixture()
async def registry() -> SessionRegistry:
    """Initialise an in-memory SessionRegistry and tear it down after tests."""
    reg = SessionRegistry(backend="memory")
    await reg.initialize()
    yield reg
    await reg.shutdown()


# --------------------------------------------------------------------------- #
# Core CRUD behaviour                                                         #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_add_get_remove(registry: SessionRegistry):
    """Add ➜ get (async & sync) ➜ remove and verify cache/state."""
    tr = FakeSSETransport("A")
    await registry.add_session("A", tr)

    assert await registry.get_session("A") is tr
    assert registry.get_session_sync("A") is tr
    assert await registry.get_session("missing") is None

    # Remove twice - second call must be harmless
    await registry.remove_session("A")
    await registry.remove_session("A")

    assert not await tr.is_connected()
    assert registry.get_session_sync("A") is None


# --------------------------------------------------------------------------- #
# broadcast ➜ respond with different payload types                            #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"method": "ping", "id": 1, "params": {}},  # dict
        ["x", "y", 42],  # list
        "plain-string",  # str
    ],
)
async def test_broadcast_and_respond(payload, monkeypatch, registry: SessionRegistry):
    """broadcast stores the payload; respond routes it to generate_response."""
    tr = FakeSSETransport("B")
    await registry.add_session("B", tr)

    captured: Dict[str, Any] = {}

    # Patch generate_response so we can verify it's called with our payload:
    async def fake_generate_response(*, message, transport, **kwargs):  # noqa: D401
        captured["message"] = message
        captured["transport"] = transport
        captured["kwargs"] = kwargs

    monkeypatch.setattr(registry, "generate_response", fake_generate_response)

    await registry.broadcast("B", payload)
    await registry.respond(server_id=None, user={}, session_id="B", base_url="http://localhost")

    assert captured["transport"] is tr
    assert captured["message"] == payload


# --------------------------------------------------------------------------- #
# Fixtures to stub get_db and the three *Service objects                      #
# --------------------------------------------------------------------------- #
@pytest.fixture()
def stub_db(monkeypatch):
    """Patch ``get_db`` to return a synchronous dummy iterator."""

    def _dummy_iter():
        yield None

    monkeypatch.setattr(
        "mcpgateway.cache.session_registry.get_db",
        lambda: _dummy_iter(),
        raising=False,
    )


@pytest.fixture()
def stub_services(monkeypatch):
    """Replace list_* service methods so they return predictable data."""

    class _Item:
        def model_dump(self, *_, **__) -> Dict[str, str]:  # noqa: D401
            return {"name": "demo"}

    async def _return_items(*args, **kwargs):  # noqa: D401
        return [_Item()]

    mod = "mcpgateway.cache.session_registry"
    monkeypatch.setattr(f"{mod}.tool_service.list_tools", _return_items, raising=False)
    monkeypatch.setattr(f"{mod}.tool_service.list_server_tools", _return_items, raising=False)
    monkeypatch.setattr(f"{mod}.prompt_service.list_prompts", _return_items, raising=False)
    monkeypatch.setattr(f"{mod}.prompt_service.list_server_prompts", _return_items, raising=False)
    monkeypatch.setattr(f"{mod}.resource_service.list_resources", _return_items, raising=False)
    monkeypatch.setattr(f"{mod}.resource_service.list_server_resources", _return_items, raising=False)


# --------------------------------------------------------------------------- #
# generate_response branches                                                  #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_generate_response_initialize(registry: SessionRegistry):
    """The *initialize* branch sends result + notifications (>= 5 messages)."""
    tr = FakeSSETransport("init")
    await registry.add_session("init", tr)

    msg = {
        "method": "initialize",
        "id": 101,
        "params": {"protocol_version": settings.protocol_version},
    }
    await registry.generate_response(
        message=msg,
        transport=tr,
        server_id=None,
        user={},
        base_url="http://host",
    )

    # Implementation may emit 5 or 6 messages (roots/list_changed optional)
    assert len(tr.sent) >= 5

    first = tr.sent[0]
    assert first["id"] == 101
    assert first["result"]["protocolVersion"] == settings.protocol_version
    assert re.match(r"notifications/initialized$", tr.sent[1]["method"])


@pytest.mark.asyncio
async def test_generate_response_ping(registry: SessionRegistry):
    """The *ping* branch should echo an empty result."""
    tr = FakeSSETransport("ping")
    await registry.add_session("ping", tr)

    msg = {"method": "ping", "id": 77, "params": {}}
    await registry.generate_response(
        message=msg,
        transport=tr,
        server_id=None,
        user={},
        base_url="http://host",
    )

    assert tr.sent[-1] == {"jsonrpc": "2.0", "result": {}, "id": 77}


@pytest.mark.asyncio
async def test_generate_response_tools_list(registry: SessionRegistry, stub_db, stub_services):
    """*tools/list* responds with the stubbed ToolService payload."""
    tr = FakeSSETransport("tools")
    await registry.add_session("tools", tr)

    msg = {"method": "tools/list", "id": 42, "params": {}}
    await registry.generate_response(
        message=msg,
        transport=tr,
        server_id=None,
        user={},
        base_url="http://host",
    )

    reply = tr.sent[-1]
    assert reply["id"] == 42
    assert reply["result"]["tools"] == [{"name": "demo"}]


@pytest.mark.asyncio
async def test_generate_response_resources_list(registry: SessionRegistry, stub_db, stub_services):
    """*resources/list* responds with the stubbed ResourceService payload."""
    tr = FakeSSETransport("resources")
    await registry.add_session("resources", tr)

    msg = {"method": "resources/list", "id": 43, "params": {}}
    await registry.generate_response(
        message=msg,
        transport=tr,
        server_id=None,
        user={},
        base_url="http://host",
    )

    reply = tr.sent[-1]
    assert reply["id"] == 43
    assert reply["result"]["resources"] == [{"name": "demo"}]


@pytest.mark.asyncio
async def test_generate_response_prompts_list(registry: SessionRegistry, stub_db, stub_services):
    """*prompts/list* responds with the stubbed PromptService payload."""
    tr = FakeSSETransport("prompts")
    await registry.add_session("prompts", tr)

    msg = {"method": "prompts/list", "id": 44, "params": {}}
    await registry.generate_response(
        message=msg,
        transport=tr,
        server_id=None,
        user={},
        base_url="http://host",
    )

    reply = tr.sent[-1]
    assert reply["id"] == 44
    assert reply["result"]["prompts"] == [{"name": "demo"}]


@pytest.mark.asyncio
async def test_generate_response_tools_call(registry: SessionRegistry, stub_db, stub_services):
    """*tools/call* makes HTTP request and returns response."""
    tr = FakeSSETransport("tools_call")
    await registry.add_session("tools_call", tr)

    # Mock httpx.AsyncClient properly as an async context manager
    mock_response = Mock()
    mock_response.json.return_value = {"result": "tool_executed"}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    # Create a proper async context manager mock
    class MockAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return mock_client

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            return None

    with patch("mcpgateway.cache.session_registry.httpx.AsyncClient", MockAsyncClient):
        msg = {"method": "tools/call", "id": 45, "params": {"name": "test_tool", "arguments": {"arg1": "value1"}}}
        await registry.generate_response(
            message=msg,
            transport=tr,
            server_id=None,
            user={"token": "test_token"},
            base_url="http://host",
        )

    reply = tr.sent[-1]
    assert reply["id"] == 45
    assert reply["result"]["result"] == "tool_executed"


@pytest.mark.asyncio
async def test_generate_response_server_specific_tools_list(registry: SessionRegistry, stub_db, stub_services):
    """*tools/list* with server_id calls server-specific method."""
    tr = FakeSSETransport("server_tools")
    await registry.add_session("server_tools", tr)

    msg = {"method": "tools/list", "id": 46, "params": {}}
    await registry.generate_response(
        message=msg,
        transport=tr,
        server_id="server123",
        user={},
        base_url="http://host",
    )

    reply = tr.sent[-1]
    assert reply["id"] == 46
    assert reply["result"]["tools"] == [{"name": "demo"}]


@pytest.mark.asyncio
async def test_generate_response_unknown_method(registry: SessionRegistry, stub_db):
    """Unknown method returns empty result."""
    tr = FakeSSETransport("unknown")
    await registry.add_session("unknown", tr)

    msg = {"method": "unknown_method", "id": 47, "params": {}}
    await registry.generate_response(
        message=msg,
        transport=tr,
        server_id=None,
        user={},
        base_url="http://host",
    )

    reply = tr.sent[-1]
    assert reply["id"] == 47
    assert reply["result"] == {}


@pytest.mark.asyncio
async def test_generate_response_no_method_or_id(registry: SessionRegistry):
    """Message without method or id is ignored."""
    tr = FakeSSETransport("no_method")
    await registry.add_session("no_method", tr)

    msg = {"some": "data"}
    await registry.generate_response(
        message=msg,
        transport=tr,
        server_id=None,
        user={},
        base_url="http://host",
    )

    # Should not send any response
    assert len(tr.sent) == 0


# --------------------------------------------------------------------------- #
# handle_initialize_logic success & errors                                    #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_handle_initialize_success(registry: SessionRegistry):
    body = {"protocol_version": settings.protocol_version}
    res = await registry.handle_initialize_logic(body)
    assert res.protocol_version == settings.protocol_version


@pytest.mark.asyncio
async def test_handle_initialize_missing_version_error(registry: SessionRegistry):
    with pytest.raises(HTTPException) as exc:
        await registry.handle_initialize_logic({})
    assert exc.value.headers["MCP-Error-Code"] == "-32002"


@pytest.mark.asyncio
async def test_handle_initialize_unsupported_version_error(registry: SessionRegistry):
    body = {"protocol_version": "999"}
    with pytest.raises(HTTPException) as exc:
        await registry.handle_initialize_logic(body)
    assert exc.value.headers["MCP-Error-Code"] == "-32003"


# --------------------------------------------------------------------------- #
# Backend initialization tests                                                #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_none_backend():
    """Test 'none' backend does no-op for all operations."""
    registry = SessionRegistry(backend="none")
    await registry.initialize()

    try:
        tr = FakeSSETransport("none_test")

        # All operations should be no-ops
        await registry.add_session("none_test", tr)
        assert registry.get_session_sync("none_test") is None
        assert await registry.get_session("none_test") is None

        await registry.remove_session("none_test")
        assert not tr.disconnect_called

        await registry.broadcast("none_test", {"test": "message"})
        await registry.respond(server_id=None, user={"token": "test"}, session_id="none_test", base_url="http://localhost")

        assert len(tr.sent) == 0
    finally:
        await registry.shutdown()


@pytest.mark.asyncio
async def test_redis_backend_init_no_redis_available(monkeypatch):
    """Test Redis backend when Redis not available."""
    monkeypatch.setattr("mcpgateway.cache.session_registry.REDIS_AVAILABLE", False)

    with pytest.raises(ValueError, match="Redis backend requested but redis package not installed"):
        SessionRegistry(backend="redis", redis_url="redis://localhost:6379")


@pytest.mark.asyncio
async def test_redis_backend_init_no_url(monkeypatch):
    """Test Redis backend without URL."""
    monkeypatch.setattr("mcpgateway.cache.session_registry.REDIS_AVAILABLE", True)

    with pytest.raises(ValueError, match="Redis backend requires redis_url"):
        SessionRegistry(backend="redis")


@pytest.mark.asyncio
async def test_database_backend_init_no_sqlalchemy_available(monkeypatch):
    """Test database backend when SQLAlchemy not available."""
    monkeypatch.setattr("mcpgateway.cache.session_registry.SQLALCHEMY_AVAILABLE", False)

    with pytest.raises(ValueError, match="Database backend requested but SQLAlchemy not installed"):
        SessionRegistry(backend="database", database_url="sqlite:///test.db")


@pytest.mark.asyncio
async def test_database_backend_init_no_url(monkeypatch):
    """Test database backend without URL."""
    monkeypatch.setattr("mcpgateway.cache.session_registry.SQLALCHEMY_AVAILABLE", True)

    with pytest.raises(ValueError, match="Database backend requires database_url"):
        SessionRegistry(backend="database")


@pytest.mark.asyncio
async def test_invalid_backend():
    """Test initialization with invalid backend."""
    with pytest.raises(ValueError, match="Invalid backend: invalid"):
        SessionRegistry(backend="invalid")


# --------------------------------------------------------------------------- #
# Redis backend session operations                                            #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_redis_session_operations(monkeypatch):
    """Test Redis backend session operations."""
    mock_redis = MockRedis()

    # Patch Redis imports before creating the registry
    monkeypatch.setattr("mcpgateway.cache.session_registry.REDIS_AVAILABLE", True)

    # Create a mock Redis class that returns our specific mock instance
    class MockRedisClass:
        @classmethod
        def from_url(cls, url):
            return mock_redis

    # Patch the Redis class import
    with patch("mcpgateway.cache.session_registry.Redis", MockRedisClass):
        registry = SessionRegistry(backend="redis", redis_url="redis://localhost:6379")
        await registry.initialize()

        try:
            tr = FakeSSETransport("redis_session")

            # Add session
            await registry.add_session("redis_session", tr)
            assert registry.get_session_sync("redis_session") is tr
            assert "mcp:session:redis_session" in mock_redis.data
            assert len(mock_redis.published) == 1

            # Get session from local cache
            result = await registry.get_session("redis_session")
            assert result is tr

            # Remove session
            await registry.remove_session("redis_session")
            assert registry.get_session_sync("redis_session") is None
            assert tr.disconnect_called

            # Test broadcast
            message = {"method": "test", "params": {}}
            await registry.broadcast("test_session", message)
            assert len(mock_redis.published) >= 2

        finally:
            await registry.shutdown()


@pytest.mark.asyncio
async def test_redis_error_handling(monkeypatch):
    """Test Redis backend error handling."""
    mock_redis = MockRedis()
    mock_redis.should_fail = True

    monkeypatch.setattr("mcpgateway.cache.session_registry.REDIS_AVAILABLE", True)

    # Create a mock Redis class that returns our specific mock instance
    class MockRedisClass:
        @classmethod
        def from_url(cls, url):
            return mock_redis

    with patch("mcpgateway.cache.session_registry.Redis", MockRedis):
        registry = SessionRegistry(backend="redis", redis_url="redis://localhost:6379")
        await registry.initialize()

        try:
            tr = FakeSSETransport("redis_error")

            # Operations should not raise exceptions despite Redis failures
            await registry.add_session("redis_error", tr)
            await registry.get_session("redis_error")
            await registry.remove_session("redis_error")
            await registry.broadcast("redis_error", {"test": "message"})

        finally:
            await registry.shutdown()


# --------------------------------------------------------------------------- #
# Database backend session operations                                         #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_database_session_operations(monkeypatch):
    """Test database backend session operations."""
    mock_db_session = Mock()
    mock_db_session.query.return_value.filter.return_value.first.return_value = None
    mock_db_session.query.return_value.filter.return_value.delete.return_value = 0

    async def immediate_execution(func):
        return func()

    monkeypatch.setattr("mcpgateway.cache.session_registry.SQLALCHEMY_AVAILABLE", True)
    monkeypatch.setattr("mcpgateway.cache.session_registry.get_db", lambda: iter([mock_db_session]))
    monkeypatch.setattr("mcpgateway.cache.session_registry.asyncio.to_thread", immediate_execution)

    registry = SessionRegistry(backend="database", database_url="sqlite:///test.db")
    await registry.initialize()

    try:
        tr = FakeSSETransport("db_session")

        # Add session
        await registry.add_session("db_session", tr)
        assert registry.get_session_sync("db_session") is tr

        # Get session (should return None since not in DB)
        result = await registry.get_session("db_session")
        assert result is tr  # Found in local cache

        # Remove session
        await registry.remove_session("db_session")
        assert registry.get_session_sync("db_session") is None
        assert tr.disconnect_called

        # Test broadcast
        message = {"method": "test", "params": {}}
        await registry.broadcast("test_session", message)

    finally:
        await registry.shutdown()


# --------------------------------------------------------------------------- #
# Cleanup and error scenarios                                                 #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_transport_disconnect_error(registry: SessionRegistry):
    """Test handling transport disconnect errors."""
    tr = FakeSSETransport("error_test")

    # Mock disconnect to raise exception
    async def failing_disconnect():
        raise Exception("Disconnect failed")

    tr.disconnect = failing_disconnect

    await registry.add_session("error_test", tr)

    # Should not raise exception
    await registry.remove_session("error_test")


@pytest.mark.asyncio
async def test_concurrent_session_operations():
    """Test concurrent session operations."""
    registry = SessionRegistry(backend="memory")
    await registry.initialize()

    try:

        async def add_remove_session(session_id):
            transport = FakeSSETransport(session_id)
            await registry.add_session(session_id, transport)
            await asyncio.sleep(0.001)  # Small delay
            await registry.remove_session(session_id)

        # Run multiple concurrent operations
        tasks = [add_remove_session(f"session_{i}") for i in range(5)]
        await asyncio.gather(*tasks)

        # All sessions should be cleaned up
        assert len(registry._sessions) == 0

    finally:
        await registry.shutdown()


@pytest.mark.asyncio
async def test_memory_cleanup_task():
    """Test memory cleanup task removes disconnected sessions."""
    registry = SessionRegistry(backend="memory")
    await registry.initialize()

    try:
        tr = FakeSSETransport("cleanup_test")
        await registry.add_session("cleanup_test", tr)

        # Simulate disconnection
        tr.make_disconnected()

        # Manually trigger cleanup logic
        async with registry._lock:
            local_transports = registry._sessions.copy()

        for session_id, transport in local_transports.items():
            if not await transport.is_connected():
                await registry.remove_session(session_id)

        assert registry.get_session_sync("cleanup_test") is None

    finally:
        await registry.shutdown()


@pytest.mark.asyncio
async def test_shutdown_with_redis_error(monkeypatch):
    """shutdown() should swallow Redis / PubSub aclose() errors."""

    # Tell the registry that the Redis extras are present
    monkeypatch.setattr("mcpgateway.cache.session_registry.REDIS_AVAILABLE", True)

    # ── fake PubSub object ────────────────────────────────────────────────
    mock_pubsub = AsyncMock(name="MockPubSub")
    mock_pubsub.aclose = AsyncMock(side_effect=Exception("PubSub close error"))

    # ── fake Redis client ────────────────────────────────────────────────
    mock_redis = AsyncMock(name="MockRedis")
    mock_redis.aclose = AsyncMock(side_effect=Exception("Redis close error"))
    # pubsub() is **not** awaited in prod code, so a plain Mock is fine
    mock_redis.pubsub = Mock(return_value=mock_pubsub)

    # ── patch the Redis class the module imported ────────────────────────
    with patch("mcpgateway.cache.session_registry.Redis") as MockRedis:
        MockRedis.from_url.return_value = mock_redis

        registry = SessionRegistry(
            backend="redis",
            redis_url="redis://localhost:6379",
        )
        await registry.initialize()  # calls mock_redis.pubsub()

        # must swallow both aclose() exceptions
        await registry.shutdown()


@pytest.mark.asyncio
async def test_full_memory_workflow(stub_db, stub_services):
    """Test complete workflow with memory backend."""
    registry = SessionRegistry(backend="memory")
    await registry.initialize()

    try:
        # Add session
        transport = FakeSSETransport("workflow_test")
        await registry.add_session("workflow_test", transport)

        # Broadcast message
        init_message = {"method": "initialize", "id": 1, "params": {"protocol_version": settings.protocol_version}}
        await registry.broadcast("workflow_test", init_message)

        # Respond to message
        await registry.respond(server_id=None, user={"token": "test"}, session_id="workflow_test", base_url="http://localhost")

        # Should have received initialize response + notifications
        assert len(transport.sent) >= 5

        # Verify initialize response
        init_response = transport.sent[0]
        assert init_response["id"] == 1
        assert "protocolVersion" in init_response["result"]

        # Clean up
        await registry.remove_session("workflow_test")
        assert transport.disconnect_called

    finally:
        await registry.shutdown()


if __name__ == "__main__":
    # Allow running tests directly
    pytest.main([__file__, "-v"])
