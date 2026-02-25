# -*- coding: utf-8 -*-
"""Tests for LLM chat router helpers and endpoints."""

# Standard
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

# Third-Party
import pytest
from fastapi import HTTPException

# First-Party
from mcpgateway.routers import llmchat_router
from mcpgateway.routers.llmchat_router import ChatInput, ConnectInput, DisconnectInput, LLMInput, ServerInput


class DummyChatService:
    def __init__(self, config, user_id=None, redis_client=None):
        self.config = config
        self.user_id = user_id
        self.redis_client = redis_client
        self._tools = [SimpleNamespace(name="tool1")]
        self.is_initialized = True
        self.shutdown_called = False
        self.history_cleared = False

    async def initialize(self):
        return None

    async def clear_history(self):
        self.history_cleared = True

    async def shutdown(self):
        self.shutdown_called = True

    async def chat_with_metadata(self, message):
        return {
            "text": f"echo:{message}",
            "tool_used": False,
            "tools": [],
            "tool_invocations": 0,
            "elapsed_ms": 1,
        }


class StreamingChatService(DummyChatService):
    async def chat_events(self, message):
        yield {"type": "token", "content": "hi"}
        yield {"type": "final", "text": f"done:{message}", "metadata": {"elapsed_ms": 1}}


class FailingStreamChatService(DummyChatService):
    async def chat_events(self, message):
        raise RuntimeError("boom")
        if message:  # pragma: no cover - keep generator signature
            yield {"type": "token", "content": message}


@pytest.fixture(autouse=True)
def reset_state(monkeypatch: pytest.MonkeyPatch):
    llmchat_router.active_sessions.clear()
    llmchat_router.user_configs.clear()
    monkeypatch.setattr(llmchat_router, "redis_client", None)
    yield
    llmchat_router.active_sessions.clear()
    llmchat_router.user_configs.clear()


def test_build_llm_config_defaults():
    config = llmchat_router.build_llm_config(LLMInput(model="gpt-4"))
    assert config.provider == "gateway"
    assert config.config.temperature == 0.7


def test_build_config_defaults():
    config = llmchat_router.build_config(ConnectInput(user_id="u1", llm=LLMInput(model="gpt")))
    assert config.mcp_server.url.endswith("/mcp")
    assert config.mcp_server.transport == "streamable_http"


def test_resolve_user_id_mismatch():
    with pytest.raises(HTTPException) as excinfo:
        llmchat_router._resolve_user_id("other", {"id": "user"})
    assert excinfo.value.status_code == 403


def test_resolve_user_id_unknown():
    with pytest.raises(HTTPException) as excinfo:
        llmchat_router._resolve_user_id(None, {})
    assert excinfo.value.status_code == 401


def test_key_helpers():
    assert llmchat_router._cfg_key("u1") == "user_config:u1"
    assert llmchat_router._active_key("u1") == "active_session:u1"
    assert llmchat_router._lock_key("u1") == "session_lock:u1"


@pytest.mark.asyncio
async def test_set_get_delete_user_config_in_memory():
    config = llmchat_router.build_config(ConnectInput(user_id="u1", llm=LLMInput(model="gpt")))
    await llmchat_router.set_user_config("u1", config)
    assert await llmchat_router.get_user_config("u1") == config
    await llmchat_router.delete_user_config("u1")
    assert await llmchat_router.get_user_config("u1") is None


@pytest.mark.asyncio
async def test_get_user_config_in_memory_respects_ttl(monkeypatch: pytest.MonkeyPatch):
    config = llmchat_router.build_config(ConnectInput(user_id="u1", llm=LLMInput(model="gpt")))
    start = 1000.0
    monkeypatch.setattr(llmchat_router.time, "monotonic", lambda: start)
    await llmchat_router.set_user_config("u1", config)

    monkeypatch.setattr(llmchat_router.time, "monotonic", lambda: start + llmchat_router.USER_CONFIG_TTL + 1)
    assert await llmchat_router.get_user_config("u1") is None
    assert "u1" not in llmchat_router.user_configs


@pytest.mark.asyncio
async def test_set_get_delete_user_config_redis(monkeypatch: pytest.MonkeyPatch):
    config = llmchat_router.build_config(
        ConnectInput(
            user_id="u1",
            llm=LLMInput(model="gpt", config={"api_key": "llm-secret"}),
            server=ServerInput(url="https://api.example.com/mcp", auth_token="server-secret"),
        )
    )
    redis_mock = AsyncMock()
    monkeypatch.setattr(llmchat_router, "redis_client", redis_mock)

    await llmchat_router.set_user_config("u1", config)
    redis_mock.set.assert_awaited_once()
    set_args = redis_mock.set.await_args
    assert set_args.kwargs["ex"] == llmchat_router.USER_CONFIG_TTL
    serialized_payload = set_args.args[1]
    parsed_payload = llmchat_router.orjson.loads(serialized_payload)
    assert llmchat_router._ENCRYPTED_CONFIG_PAYLOAD_KEY in parsed_payload
    assert b"llm-secret" not in serialized_payload
    assert b"server-secret" not in serialized_payload

    redis_mock.get.return_value = serialized_payload
    assert await llmchat_router.get_user_config("u1") == config
    await llmchat_router.delete_user_config("u1")
    redis_mock.get.assert_awaited()
    redis_mock.delete.assert_awaited()


@pytest.mark.asyncio
async def test_get_user_config_redis_supports_legacy_plaintext(monkeypatch: pytest.MonkeyPatch):
    config = llmchat_router.build_config(ConnectInput(user_id="u1", llm=LLMInput(model="gpt")))
    redis_mock = AsyncMock()
    redis_mock.get.return_value = llmchat_router.orjson.dumps(config.model_dump())
    monkeypatch.setattr(llmchat_router, "redis_client", redis_mock)

    result = await llmchat_router.get_user_config("u1")
    assert result == config


def test_deserialize_user_config_rejects_invalid_payload(caplog: pytest.LogCaptureFixture):
    caplog.set_level("WARNING")
    assert llmchat_router._deserialize_user_config_from_storage(b"{not-json") is None
    assert "Failed to parse stored LLM chat config payload" in caplog.text


def test_deserialize_user_config_rejects_missing_or_invalid_encrypted_payload(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture):
    caplog.set_level("WARNING")

    missing_payload = llmchat_router.orjson.dumps(
        {llmchat_router._ENCRYPTED_CONFIG_PAYLOAD_KEY: ""}
    )
    assert llmchat_router._deserialize_user_config_from_storage(missing_payload) is None

    monkeypatch.setattr(llmchat_router, "decode_auth", lambda *_args, **_kwargs: ["invalid"])
    invalid_decoded = llmchat_router.orjson.dumps(
        {llmchat_router._ENCRYPTED_CONFIG_PAYLOAD_KEY: "ciphertext"}
    )
    assert llmchat_router._deserialize_user_config_from_storage(invalid_decoded) is None
    assert "Decoded encrypted LLM chat config is invalid" in caplog.text


def test_deserialize_user_config_rejects_non_dict_legacy_payload():
    legacy_non_dict = llmchat_router.orjson.dumps(["not-a-dict"])
    assert llmchat_router._deserialize_user_config_from_storage(legacy_non_dict) is None


@pytest.mark.asyncio
async def test_active_session_redis_set_and_delete(monkeypatch: pytest.MonkeyPatch):
    redis_mock = AsyncMock()
    monkeypatch.setattr(llmchat_router, "redis_client", redis_mock)

    session = DummyChatService(config=None, user_id="u1")
    await llmchat_router.set_active_session("u1", session)
    assert llmchat_router.active_sessions["u1"] is session

    await llmchat_router.delete_active_session("u1")
    redis_mock.set.assert_awaited()
    redis_mock.eval.assert_awaited()


@pytest.mark.asyncio
async def test_active_session_redis_delete_logs_warning(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture):
    redis_mock = AsyncMock()
    redis_mock.eval.side_effect = RuntimeError("boom")
    monkeypatch.setattr(llmchat_router, "redis_client", redis_mock)

    caplog.set_level("WARNING")
    session = DummyChatService(config=None, user_id="u1")
    await llmchat_router.set_active_session("u1", session)
    await llmchat_router.delete_active_session("u1")

    assert "Failed to delete active session" in caplog.text


@pytest.mark.asyncio
async def test_try_acquire_lock_paths(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(llmchat_router, "redis_client", None)
    assert await llmchat_router._try_acquire_lock("u1") is True

    redis_mock = AsyncMock()
    redis_mock.set.return_value = True
    monkeypatch.setattr(llmchat_router, "redis_client", redis_mock)
    assert await llmchat_router._try_acquire_lock("u1") is True
    redis_mock.set.assert_awaited()


@pytest.mark.asyncio
async def test_release_lock_safe_paths(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture):
    monkeypatch.setattr(llmchat_router, "redis_client", None)
    await llmchat_router._release_lock_safe("u1")

    redis_mock = AsyncMock()
    redis_mock.eval.side_effect = RuntimeError("boom")
    monkeypatch.setattr(llmchat_router, "redis_client", redis_mock)
    caplog.set_level("WARNING")
    await llmchat_router._release_lock_safe("u1")
    assert "Failed to release lock" in caplog.text


@pytest.mark.asyncio
async def test_create_local_session_from_config_success(monkeypatch: pytest.MonkeyPatch):
    config = llmchat_router.build_config(ConnectInput(user_id="u1", llm=LLMInput(model="gpt")))

    async def fake_get_user_config(_user_id):
        return config

    async def fake_set_active_session(_user_id, _session):
        return None

    monkeypatch.setattr(llmchat_router, "get_user_config", fake_get_user_config)
    monkeypatch.setattr(llmchat_router, "set_active_session", AsyncMock(side_effect=fake_set_active_session))
    monkeypatch.setattr(llmchat_router, "MCPChatService", DummyChatService)

    session = await llmchat_router._create_local_session_from_config("u1")
    assert isinstance(session, DummyChatService)


@pytest.mark.asyncio
async def test_create_local_session_from_config_failure(monkeypatch: pytest.MonkeyPatch):
    config = llmchat_router.build_config(ConnectInput(user_id="u1", llm=LLMInput(model="gpt")))

    async def fake_get_user_config(_user_id):
        return config

    class BadChatService(DummyChatService):
        async def initialize(self):
            raise RuntimeError("boom")

    delete_active = AsyncMock()

    monkeypatch.setattr(llmchat_router, "get_user_config", fake_get_user_config)
    monkeypatch.setattr(llmchat_router, "delete_active_session", delete_active)
    monkeypatch.setattr(llmchat_router, "MCPChatService", BadChatService)

    session = await llmchat_router._create_local_session_from_config("u1")
    assert session is None
    assert delete_active.await_count == 1


@pytest.mark.asyncio
async def test_get_active_session_no_redis():
    session = DummyChatService(config=None, user_id="u1")
    llmchat_router.active_sessions["u1"] = session
    assert await llmchat_router.get_active_session("u1") is session


@pytest.mark.asyncio
async def test_get_active_session_owner_local_refresh(monkeypatch: pytest.MonkeyPatch):
    redis_mock = AsyncMock()
    redis_mock.get.return_value = llmchat_router.WORKER_ID
    monkeypatch.setattr(llmchat_router, "redis_client", redis_mock)

    session = DummyChatService(config=None, user_id="u1")
    llmchat_router.active_sessions["u1"] = session
    result = await llmchat_router.get_active_session("u1")
    assert result is session
    redis_mock.expire.assert_awaited()


@pytest.mark.asyncio
async def test_get_active_session_owner_missing_recreate(monkeypatch: pytest.MonkeyPatch):
    redis_mock = AsyncMock()
    redis_mock.get.return_value = llmchat_router.WORKER_ID
    monkeypatch.setattr(llmchat_router, "redis_client", redis_mock)

    session = DummyChatService(config=None, user_id="u1")
    monkeypatch.setattr(llmchat_router, "_try_acquire_lock", AsyncMock(return_value=True))
    monkeypatch.setattr(llmchat_router, "_create_local_session_from_config", AsyncMock(return_value=session))
    release_lock = AsyncMock()
    monkeypatch.setattr(llmchat_router, "_release_lock_safe", release_lock)

    result = await llmchat_router.get_active_session("u1")
    assert result is session
    assert release_lock.await_count == 1


@pytest.mark.asyncio
async def test_get_active_session_no_owner_other_worker(monkeypatch: pytest.MonkeyPatch):
    redis_mock = AsyncMock()
    redis_mock.get.side_effect = [None, "other-worker"]
    monkeypatch.setattr(llmchat_router, "redis_client", redis_mock)
    monkeypatch.setattr(llmchat_router, "_try_acquire_lock", AsyncMock(return_value=False))
    monkeypatch.setattr(llmchat_router, "LOCK_RETRIES", 1)
    monkeypatch.setattr(llmchat_router.asyncio, "sleep", AsyncMock())

    assert await llmchat_router.get_active_session("u1") is None


@pytest.mark.asyncio
async def test_get_active_session_owned_by_other_worker(monkeypatch: pytest.MonkeyPatch):
    redis_mock = AsyncMock()
    redis_mock.get.return_value = "other-worker"
    monkeypatch.setattr(llmchat_router, "redis_client", redis_mock)

    assert await llmchat_router.get_active_session("u1") is None


@pytest.mark.asyncio
async def test_connect_success(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(llmchat_router, "MCPChatService", DummyChatService)

    request = MagicMock()
    request.cookies = {"jwt_token": "token"}
    request.headers = {}

    input_data = ConnectInput(user_id="user1", llm=LLMInput(model="gpt"), server=ServerInput(auth_token=""))

    result = await llmchat_router.connect(input_data, request, user={"id": "user1", "db": MagicMock()})

    assert result["status"] == "connected"
    assert result["tool_count"] == 1
    assert await llmchat_router.get_active_session("user1") is not None


@pytest.mark.asyncio
async def test_connect_rejects_ssrf_server_url(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(llmchat_router, "MCPChatService", DummyChatService)

    def _reject_url(_url: str, _field_name: str = "URL") -> str:
        raise ValueError("localhost is blocked")

    monkeypatch.setattr(llmchat_router.SecurityValidator, "validate_url", _reject_url)

    request = MagicMock()
    request.cookies = {}
    request.headers = {}

    input_data = ConnectInput(user_id="user1", llm=LLMInput(model="gpt"), server=ServerInput(url="http://127.0.0.1/mcp", auth_token="token"))

    with pytest.raises(HTTPException) as excinfo:
        await llmchat_router.connect(input_data, request, user={"id": "user1", "db": MagicMock()})

    assert excinfo.value.status_code == 400
    assert excinfo.value.detail == "Invalid server URL"


@pytest.mark.asyncio
async def test_connect_rejects_private_server_url_in_strict_ssrf_mode(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(llmchat_router, "MCPChatService", DummyChatService)

    class StrictSSRFSettings:
        ssrf_protection_enabled = True
        ssrf_allow_localhost = False
        ssrf_allow_private_networks = False
        ssrf_allowed_networks = []
        ssrf_blocked_networks = ["169.254.169.254/32"]
        ssrf_blocked_hosts = []
        ssrf_dns_fail_closed = False

    monkeypatch.setattr("mcpgateway.common.validators.settings", StrictSSRFSettings())

    request = MagicMock()
    request.cookies = {}
    request.headers = {}

    input_data = ConnectInput(user_id="user1", llm=LLMInput(model="gpt"), server=ServerInput(url="http://127.0.0.1/mcp", auth_token="token"))

    with pytest.raises(HTTPException) as excinfo:
        await llmchat_router.connect(input_data, request, user={"id": "user1", "db": MagicMock()})

    assert excinfo.value.status_code == 400
    assert excinfo.value.detail == "Invalid server URL"


@pytest.mark.asyncio
async def test_connect_validates_user_supplied_server_url(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(llmchat_router, "MCPChatService", DummyChatService)
    seen: dict[str, str] = {}

    def _accept_url(url: str, _field_name: str = "URL") -> str:
        seen["url"] = url
        return url

    monkeypatch.setattr(llmchat_router.SecurityValidator, "validate_url", _accept_url)

    request = MagicMock()
    request.cookies = {}
    request.headers = {}

    input_data = ConnectInput(user_id="user1", llm=LLMInput(model="gpt"), server=ServerInput(url="https://api.example.com/mcp", auth_token="token"))

    result = await llmchat_router.connect(input_data, request, user={"id": "user1", "db": MagicMock()})

    assert result["status"] == "connected"
    assert seen["url"] == "https://api.example.com/mcp"


@pytest.mark.asyncio
async def test_connect_invalid_resolved_user_id(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(llmchat_router, "_resolve_user_id", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(llmchat_router, "MCPChatService", DummyChatService)

    request = MagicMock()
    request.cookies = {}
    request.headers = {}

    input_data = ConnectInput(user_id="user1", llm=LLMInput(model="gpt"), server=ServerInput(auth_token="token"))

    with pytest.raises(HTTPException) as excinfo:
        await llmchat_router.connect(input_data, request, user={"id": "user1"})

    assert excinfo.value.status_code == 400


@pytest.mark.asyncio
async def test_connect_existing_session_shutdown_error(monkeypatch: pytest.MonkeyPatch):
    class ShutdownErrorChatService(DummyChatService):
        async def shutdown(self):
            raise RuntimeError("shutdown failed")

    monkeypatch.setattr(llmchat_router, "MCPChatService", DummyChatService)

    request = MagicMock()
    request.cookies = {}
    request.headers = {}

    llmchat_router.active_sessions["user1"] = ShutdownErrorChatService(config=None, user_id="user1")

    input_data = ConnectInput(user_id="user1", llm=LLMInput(model="gpt"), server=ServerInput(auth_token="token"))

    result = await llmchat_router.connect(input_data, request, user={"id": "user1", "db": MagicMock()})

    assert result["status"] == "connected"
    assert isinstance(llmchat_router.active_sessions["user1"], DummyChatService)


@pytest.mark.asyncio
async def test_connect_build_config_error(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(llmchat_router, "build_config", MagicMock(side_effect=ValueError("bad config")))

    request = MagicMock()
    request.cookies = {}
    request.headers = {}

    input_data = ConnectInput(user_id="user1", llm=LLMInput(model="gpt"), server=ServerInput(auth_token="token"))

    with pytest.raises(HTTPException) as excinfo:
        await llmchat_router.connect(input_data, request, user={"id": "user1"})

    assert excinfo.value.status_code == 400


@pytest.mark.asyncio
async def test_connect_chat_service_connection_error(monkeypatch: pytest.MonkeyPatch):
    class InitErrorChatService(DummyChatService):
        async def initialize(self):
            raise ConnectionError("nope")

    monkeypatch.setattr(llmchat_router, "MCPChatService", InitErrorChatService)
    delete_config = AsyncMock()
    monkeypatch.setattr(llmchat_router, "delete_user_config", delete_config)

    request = MagicMock()
    request.cookies = {}
    request.headers = {}

    input_data = ConnectInput(user_id="user1", llm=LLMInput(model="gpt"), server=ServerInput(auth_token="token"))

    with pytest.raises(HTTPException) as excinfo:
        await llmchat_router.connect(input_data, request, user={"id": "user1", "db": MagicMock()})

    assert excinfo.value.status_code == 503
    assert delete_config.await_count == 1


@pytest.mark.asyncio
async def test_connect_requires_auth_token(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(llmchat_router, "MCPChatService", DummyChatService)

    request = MagicMock()
    request.cookies = {}
    request.headers = {}

    input_data = ConnectInput(user_id="user1", llm=LLMInput(model="gpt"), server=ServerInput(auth_token=""))

    with pytest.raises(HTTPException) as excinfo:
        await llmchat_router.connect(input_data, request, user={"id": "user1", "db": MagicMock()})

    assert excinfo.value.status_code == 401


@pytest.mark.asyncio
async def test_chat_non_streaming_success(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(llmchat_router, "MCPChatService", DummyChatService)
    llmchat_router.active_sessions["user1"] = DummyChatService(config=None, user_id="user1")

    input_data = ChatInput(user_id="user1", message="hi", streaming=False)

    result = await llmchat_router.chat(input_data, user={"id": "user1"})

    assert result["response"] == "echo:hi"


@pytest.mark.asyncio
async def test_chat_streaming_returns_streaming_response(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(llmchat_router, "MCPChatService", StreamingChatService)
    llmchat_router.active_sessions["user1"] = StreamingChatService(config=None, user_id="user1")

    input_data = ChatInput(user_id="user1", message="hi", streaming=True)

    response = await llmchat_router.chat(input_data, user={"id": "user1"})

    assert response.media_type == "text/event-stream"


@pytest.mark.asyncio
async def test_chat_no_session():
    input_data = ChatInput(user_id="user1", message="hi", streaming=False)

    with pytest.raises(HTTPException) as excinfo:
        await llmchat_router.chat(input_data, user={"id": "user1"})

    assert excinfo.value.status_code == 400


@pytest.mark.asyncio
async def test_disconnect_clears_session(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(llmchat_router, "MCPChatService", DummyChatService)
    llmchat_router.active_sessions["user1"] = DummyChatService(config=None, user_id="user1")

    result = await llmchat_router.disconnect(DisconnectInput(user_id="user1"), user={"id": "user1"})

    assert result["status"] == "disconnected"
    assert await llmchat_router.get_active_session("user1") is None


@pytest.mark.asyncio
async def test_disconnect_no_active_session():
    result = await llmchat_router.disconnect(DisconnectInput(user_id="user1"), user={"id": "user1"})

    assert result["status"] == "no_active_session"


@pytest.mark.asyncio
async def test_disconnect_with_errors():
    class ErrorChatService(DummyChatService):
        async def clear_history(self):
            raise RuntimeError("fail")

    llmchat_router.active_sessions["user1"] = ErrorChatService(config=None, user_id="user1")

    result = await llmchat_router.disconnect(DisconnectInput(user_id="user1"), user={"id": "user1"})

    assert result["status"] == "disconnected_with_errors"
    assert "warning" in result


@pytest.mark.asyncio
async def test_status_connected(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(llmchat_router, "MCPChatService", DummyChatService)
    llmchat_router.active_sessions["user1"] = DummyChatService(config=None, user_id="user1")

    result = await llmchat_router.status("user1", user={"id": "user1"})

    assert result["connected"] is True


@pytest.mark.asyncio
async def test_get_config_sanitizes(monkeypatch: pytest.MonkeyPatch):
    config = llmchat_router.build_config(
        ConnectInput(
            user_id="u1",
            llm=LLMInput(model="gpt"),
            server=ServerInput(url="https://api.example.com/mcp", auth_token="server-token"),
        )
    )
    await llmchat_router.set_user_config("u1", config)

    result = await llmchat_router.get_config("u1", user={"id": "u1"})

    assert result["mcp_server"]["auth_token"] == llmchat_router.settings.masked_auth_value


def test_mask_sensitive_config_values_masks_nested_fields():
    data = {
        "api_key": "k",
        "nested": {"client_secret": "s"},
        "list": [{"password": "p"}],
        "plain": "value",
    }

    masked = llmchat_router._mask_sensitive_config_values(data)
    assert masked["api_key"] == llmchat_router.settings.masked_auth_value
    assert masked["nested"]["client_secret"] == llmchat_router.settings.masked_auth_value
    assert masked["list"][0]["password"] == llmchat_router.settings.masked_auth_value
    assert masked["plain"] == "value"


@pytest.mark.asyncio
async def test_get_config_missing():
    with pytest.raises(HTTPException) as excinfo:
        await llmchat_router.get_config("u1", user={"id": "u1"})

    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_token_streamer_emits_events():
    chat_service = StreamingChatService(config=None, user_id="user1")

    parts = []
    async for part in llmchat_router.token_streamer(chat_service, "hi", "user1"):
        parts.append(part.decode("utf-8"))

    joined = "".join(parts)
    assert "event: token" in joined
    assert "event: final" in joined


@pytest.mark.asyncio
async def test_token_streamer_handles_runtime_error():
    chat_service = FailingStreamChatService(config=None, user_id="user1")

    parts = []
    async for part in llmchat_router.token_streamer(chat_service, "hi", "user1"):
        parts.append(part.decode("utf-8"))

    joined = "".join(parts)
    assert "event: error" in joined


@pytest.mark.asyncio
async def test_get_gateway_models_success(monkeypatch: pytest.MonkeyPatch):
    class DummyModel:
        def model_dump(self):
            return {"id": "m1"}

    class DummyService:
        def get_gateway_models(self, _db):
            return [DummyModel()]

    class DummySession:
        def __enter__(self):
            return MagicMock()

        def __exit__(self, exc_type, exc, tb):
            return False

    import mcpgateway.db as db_module
    import mcpgateway.services.llm_provider_service as lps

    monkeypatch.setattr(db_module, "SessionLocal", lambda: DummySession())
    monkeypatch.setattr(lps, "LLMProviderService", DummyService)

    result = await llmchat_router.get_gateway_models(_user={"id": "user1"})

    assert result["count"] == 1
    assert result["models"][0]["id"] == "m1"


@pytest.mark.asyncio
async def test_get_gateway_models_failure(monkeypatch: pytest.MonkeyPatch):
    class DummyService:
        def get_gateway_models(self, _db):
            raise RuntimeError("boom")

    class DummySession:
        def __enter__(self):
            return MagicMock()

        def __exit__(self, exc_type, exc, tb):
            return False

    import mcpgateway.db as db_module
    import mcpgateway.services.llm_provider_service as lps

    monkeypatch.setattr(db_module, "SessionLocal", lambda: DummySession())
    monkeypatch.setattr(lps, "LLMProviderService", DummyService)

    with pytest.raises(HTTPException) as excinfo:
        await llmchat_router.get_gateway_models(_user={"id": "user1"})

    assert excinfo.value.status_code == 500


# ---------- Additional coverage tests ----------


@pytest.mark.asyncio
async def test_init_redis_with_redis_config(monkeypatch: pytest.MonkeyPatch):
    mock_redis = AsyncMock()
    monkeypatch.setattr(llmchat_router.settings, "cache_type", "redis")
    monkeypatch.setattr(llmchat_router.settings, "redis_url", "redis://localhost")
    monkeypatch.setattr(llmchat_router, "get_redis_client", AsyncMock(return_value=mock_redis))

    await llmchat_router.init_redis()

    assert llmchat_router.redis_client is mock_redis
    # Clean up
    llmchat_router.redis_client = None


@pytest.mark.asyncio
async def test_init_redis_client_returns_none(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(llmchat_router.settings, "cache_type", "redis")
    monkeypatch.setattr(llmchat_router.settings, "redis_url", "redis://localhost")
    monkeypatch.setattr(llmchat_router, "get_redis_client", AsyncMock(return_value=None))

    await llmchat_router.init_redis()

    assert llmchat_router.redis_client is None


@pytest.mark.asyncio
async def test_chat_session_not_initialized():
    svc = DummyChatService(config=None, user_id="user1")
    svc.is_initialized = False
    llmchat_router.active_sessions["user1"] = svc

    input_data = ChatInput(user_id="user1", message="hi", streaming=False)

    with pytest.raises(HTTPException) as excinfo:
        await llmchat_router.chat(input_data, user={"id": "user1"})

    assert excinfo.value.status_code == 503
    assert "not properly initialized" in excinfo.value.detail


@pytest.mark.asyncio
async def test_chat_runtime_error():
    class RuntimeErrorChat(DummyChatService):
        async def chat_with_metadata(self, message):
            raise RuntimeError("service error")

    llmchat_router.active_sessions["user1"] = RuntimeErrorChat(config=None, user_id="user1")
    input_data = ChatInput(user_id="user1", message="hi", streaming=False)

    with pytest.raises(HTTPException) as excinfo:
        await llmchat_router.chat(input_data, user={"id": "user1"})

    assert excinfo.value.status_code == 503


@pytest.mark.asyncio
async def test_chat_connection_error():
    class ConnectionErrorChat(DummyChatService):
        async def chat_with_metadata(self, message):
            raise ConnectionError("lost connection")

    llmchat_router.active_sessions["user1"] = ConnectionErrorChat(config=None, user_id="user1")
    input_data = ChatInput(user_id="user1", message="hi", streaming=False)

    with pytest.raises(HTTPException) as excinfo:
        await llmchat_router.chat(input_data, user={"id": "user1"})

    assert excinfo.value.status_code == 503


@pytest.mark.asyncio
async def test_chat_timeout_error():
    class TimeoutChat(DummyChatService):
        async def chat_with_metadata(self, message):
            raise TimeoutError("timed out")

    llmchat_router.active_sessions["user1"] = TimeoutChat(config=None, user_id="user1")
    input_data = ChatInput(user_id="user1", message="hi", streaming=False)

    with pytest.raises(HTTPException) as excinfo:
        await llmchat_router.chat(input_data, user={"id": "user1"})

    assert excinfo.value.status_code == 504


@pytest.mark.asyncio
async def test_chat_unexpected_error():
    class UnexpectedErrorChat(DummyChatService):
        async def chat_with_metadata(self, message):
            raise ValueError("unexpected")

    llmchat_router.active_sessions["user1"] = UnexpectedErrorChat(config=None, user_id="user1")
    input_data = ChatInput(user_id="user1", message="hi", streaming=False)

    with pytest.raises(HTTPException) as excinfo:
        await llmchat_router.chat(input_data, user={"id": "user1"})

    assert excinfo.value.status_code == 500


@pytest.mark.asyncio
async def test_chat_empty_message():
    llmchat_router.active_sessions["user1"] = DummyChatService(config=None, user_id="user1")
    input_data = ChatInput(user_id="user1", message="   ", streaming=False)

    with pytest.raises(HTTPException) as excinfo:
        await llmchat_router.chat(input_data, user={"id": "user1"})

    assert excinfo.value.status_code == 400
    assert "empty" in excinfo.value.detail


@pytest.mark.asyncio
async def test_token_streamer_connection_error():
    class ConnErrChat(DummyChatService):
        async def chat_events(self, message):
            raise ConnectionError("lost")
            if message:  # pragma: no cover
                yield {"type": "token", "content": message}

    svc = ConnErrChat(config=None, user_id="user1")
    parts = []
    async for part in llmchat_router.token_streamer(svc, "hi", "user1"):
        parts.append(part.decode("utf-8"))

    joined = "".join(parts)
    assert "event: error" in joined
    assert "Connection lost" in joined


@pytest.mark.asyncio
async def test_token_streamer_timeout_error():
    class TimeoutChat(DummyChatService):
        async def chat_events(self, message):
            raise TimeoutError()
            if message:  # pragma: no cover
                yield {"type": "token", "content": message}

    svc = TimeoutChat(config=None, user_id="user1")
    parts = []
    async for part in llmchat_router.token_streamer(svc, "hi", "user1"):
        parts.append(part.decode("utf-8"))

    joined = "".join(parts)
    assert "event: error" in joined
    assert "timed out" in joined


@pytest.mark.asyncio
async def test_token_streamer_generic_error():
    class GenericErrChat(DummyChatService):
        async def chat_events(self, message):
            raise ValueError("bad value")
            if message:  # pragma: no cover
                yield {"type": "token", "content": message}

    svc = GenericErrChat(config=None, user_id="user1")
    parts = []
    async for part in llmchat_router.token_streamer(svc, "hi", "user1"):
        parts.append(part.decode("utf-8"))

    joined = "".join(parts)
    assert "event: error" in joined
    assert "Unexpected error" in joined


@pytest.mark.asyncio
async def test_token_streamer_tool_events():
    class ToolChat(DummyChatService):
        async def chat_events(self, message):
            yield {"type": "tool_start", "tool": "search"}
            yield {"type": "tool_end", "tool": "search", "result": "ok"}
            yield {"type": "tool_error", "tool": "search", "error": "oops"}
            yield {"type": "final", "text": "done", "metadata": {}}

    svc = ToolChat(config=None, user_id="user1")
    parts = []
    async for part in llmchat_router.token_streamer(svc, "hi", "user1"):
        parts.append(part.decode("utf-8"))

    joined = "".join(parts)
    assert "event: tool_start" in joined
    assert "event: tool_end" in joined
    assert "event: tool_error" in joined
    assert "event: final" in joined


def test_get_user_id_from_context_non_dict():
    assert llmchat_router._get_user_id_from_context(None) == "unknown"
    assert llmchat_router._get_user_id_from_context("user123") == "user123"

    class UserObj:
        id = "obj-user"

    assert llmchat_router._get_user_id_from_context(UserObj()) == "obj-user"


def test_resolve_user_id_match():
    result = llmchat_router._resolve_user_id("user1", {"id": "user1"})
    assert result == "user1"


def test_resolve_user_id_none_input():
    result = llmchat_router._resolve_user_id(None, {"id": "user1"})
    assert result == "user1"


@pytest.mark.asyncio
async def test_connect_init_value_error(monkeypatch: pytest.MonkeyPatch):
    class InitValueErrorChatService(DummyChatService):
        async def initialize(self):
            raise ValueError("bad model")

    monkeypatch.setattr(llmchat_router, "MCPChatService", InitValueErrorChatService)
    delete_config = AsyncMock()
    monkeypatch.setattr(llmchat_router, "delete_user_config", delete_config)

    request = MagicMock()
    request.cookies = {}
    request.headers = {}

    input_data = ConnectInput(user_id="user1", llm=LLMInput(model="gpt"), server=ServerInput(auth_token="token"))

    with pytest.raises(HTTPException) as excinfo:
        await llmchat_router.connect(input_data, request, user={"id": "user1", "db": MagicMock()})

    assert excinfo.value.status_code == 400
    assert "Invalid LLM configuration" in excinfo.value.detail


@pytest.mark.asyncio
async def test_connect_init_generic_error(monkeypatch: pytest.MonkeyPatch):
    class InitGenericErrorChatService(DummyChatService):
        async def initialize(self):
            raise RuntimeError("init failed")

    monkeypatch.setattr(llmchat_router, "MCPChatService", InitGenericErrorChatService)
    delete_config = AsyncMock()
    monkeypatch.setattr(llmchat_router, "delete_user_config", delete_config)

    request = MagicMock()
    request.cookies = {}
    request.headers = {}

    input_data = ConnectInput(user_id="user1", llm=LLMInput(model="gpt"), server=ServerInput(auth_token="token"))

    with pytest.raises(HTTPException) as excinfo:
        await llmchat_router.connect(input_data, request, user={"id": "user1", "db": MagicMock()})

    assert excinfo.value.status_code == 500
    assert "Service initialization failed" in excinfo.value.detail


@pytest.mark.asyncio
async def test_connect_build_config_generic_error(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(llmchat_router, "build_config", MagicMock(side_effect=RuntimeError("config error")))

    request = MagicMock()
    request.cookies = {}
    request.headers = {}

    input_data = ConnectInput(user_id="user1", llm=LLMInput(model="gpt"), server=ServerInput(auth_token="token"))

    with pytest.raises(HTTPException) as excinfo:
        await llmchat_router.connect(input_data, request, user={"id": "user1"})

    assert excinfo.value.status_code == 400
    assert "Configuration error" in excinfo.value.detail


@pytest.mark.asyncio
async def test_connect_unexpected_error(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(llmchat_router, "MCPChatService", DummyChatService)
    monkeypatch.setattr(llmchat_router, "get_active_session", AsyncMock(side_effect=RuntimeError("unexpected")))

    request = MagicMock()
    request.cookies = {}
    request.headers = {}

    input_data = ConnectInput(user_id="user1", llm=LLMInput(model="gpt"), server=ServerInput(auth_token="token"))

    with pytest.raises(HTTPException) as excinfo:
        await llmchat_router.connect(input_data, request, user={"id": "user1"})

    assert excinfo.value.status_code == 500
    assert "Unexpected connection error" in excinfo.value.detail


@pytest.mark.asyncio
async def test_connect_no_server(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(llmchat_router, "MCPChatService", DummyChatService)

    request = MagicMock()
    request.cookies = {}
    request.headers = {}

    input_data = ConnectInput(user_id="user1", llm=LLMInput(model="gpt"), server=None)

    result = await llmchat_router.connect(input_data, request, user={"id": "user1", "db": MagicMock()})

    assert result["status"] == "connected"


@pytest.mark.asyncio
async def test_connect_tool_extraction_error(monkeypatch: pytest.MonkeyPatch):
    class BadToolChat:
        def __init__(self, config, user_id=None, redis_client=None):
            self.config = config
            self.user_id = user_id
            self.is_initialized = True

        async def initialize(self):
            pass

        async def clear_history(self):
            pass

        async def shutdown(self):
            pass

        @property
        def _tools(self):
            raise RuntimeError("tool error")

    monkeypatch.setattr(llmchat_router, "MCPChatService", BadToolChat)

    request = MagicMock()
    request.cookies = {}
    request.headers = {}

    input_data = ConnectInput(user_id="user1", llm=LLMInput(model="gpt"), server=ServerInput(auth_token="token"))

    result = await llmchat_router.connect(input_data, request, user={"id": "user1", "db": MagicMock()})

    assert result["status"] == "connected"
    assert result["tool_count"] == 0


@pytest.mark.asyncio
async def test_get_active_session_expire_failure(monkeypatch: pytest.MonkeyPatch):
    redis_mock = AsyncMock()
    redis_mock.get.return_value = llmchat_router.WORKER_ID
    redis_mock.expire.side_effect = RuntimeError("expire failed")
    monkeypatch.setattr(llmchat_router, "redis_client", redis_mock)

    session = DummyChatService(config=None, user_id="u1")
    llmchat_router.active_sessions["u1"] = session

    result = await llmchat_router.get_active_session("u1")
    assert result is session


@pytest.mark.asyncio
async def test_get_active_session_owner_missing_lock_failed(monkeypatch: pytest.MonkeyPatch):
    redis_mock = AsyncMock()
    redis_mock.get.return_value = llmchat_router.WORKER_ID
    monkeypatch.setattr(llmchat_router, "redis_client", redis_mock)

    # No local session
    monkeypatch.setattr(llmchat_router, "_try_acquire_lock", AsyncMock(return_value=False))
    monkeypatch.setattr(llmchat_router, "LOCK_RETRIES", 1)
    monkeypatch.setattr(llmchat_router.asyncio, "sleep", AsyncMock())

    result = await llmchat_router.get_active_session("u1")
    assert result is None


@pytest.mark.asyncio
async def test_get_active_session_no_owner_claim_success(monkeypatch: pytest.MonkeyPatch):
    redis_mock = AsyncMock()
    redis_mock.get.return_value = None
    monkeypatch.setattr(llmchat_router, "redis_client", redis_mock)

    session = DummyChatService(config=None, user_id="u1")
    monkeypatch.setattr(llmchat_router, "_try_acquire_lock", AsyncMock(return_value=True))
    monkeypatch.setattr(llmchat_router, "_create_local_session_from_config", AsyncMock(return_value=session))
    release_lock = AsyncMock()
    monkeypatch.setattr(llmchat_router, "_release_lock_safe", release_lock)

    result = await llmchat_router.get_active_session("u1")
    assert result is session
    assert release_lock.await_count == 1


@pytest.mark.asyncio
async def test_get_active_session_no_owner_retry_our_worker(monkeypatch: pytest.MonkeyPatch):
    redis_mock = AsyncMock()
    redis_mock.get.side_effect = [None, llmchat_router.WORKER_ID]
    monkeypatch.setattr(llmchat_router, "redis_client", redis_mock)

    session = DummyChatService(config=None, user_id="u1")
    # First lock fails, then gets session during retry
    monkeypatch.setattr(llmchat_router, "_try_acquire_lock", AsyncMock(return_value=False))
    monkeypatch.setattr(llmchat_router, "LOCK_RETRIES", 1)
    monkeypatch.setattr(llmchat_router.asyncio, "sleep", AsyncMock())
    llmchat_router.active_sessions["u1"] = session

    result = await llmchat_router.get_active_session("u1")
    assert result is session


@pytest.mark.asyncio
async def test_get_active_session_no_owner_final_acquire(monkeypatch: pytest.MonkeyPatch):
    redis_mock = AsyncMock()
    redis_mock.get.side_effect = [None, None]
    monkeypatch.setattr(llmchat_router, "redis_client", redis_mock)

    session = DummyChatService(config=None, user_id="u1")
    # First lock fails, retry loop finds no owner, final acquire succeeds
    lock_calls = [False, True]
    monkeypatch.setattr(llmchat_router, "_try_acquire_lock", AsyncMock(side_effect=lock_calls))
    monkeypatch.setattr(llmchat_router, "_create_local_session_from_config", AsyncMock(return_value=session))
    release_lock = AsyncMock()
    monkeypatch.setattr(llmchat_router, "_release_lock_safe", release_lock)
    monkeypatch.setattr(llmchat_router, "LOCK_RETRIES", 1)
    monkeypatch.setattr(llmchat_router.asyncio, "sleep", AsyncMock())

    result = await llmchat_router.get_active_session("u1")
    assert result is session


@pytest.mark.asyncio
async def test_get_active_session_no_owner_all_fail(monkeypatch: pytest.MonkeyPatch):
    redis_mock = AsyncMock()
    redis_mock.get.side_effect = [None, None]
    monkeypatch.setattr(llmchat_router, "redis_client", redis_mock)

    monkeypatch.setattr(llmchat_router, "_try_acquire_lock", AsyncMock(return_value=False))
    monkeypatch.setattr(llmchat_router, "LOCK_RETRIES", 1)
    monkeypatch.setattr(llmchat_router.asyncio, "sleep", AsyncMock())

    result = await llmchat_router.get_active_session("u1")
    assert result is None


@pytest.mark.asyncio
async def test_create_local_session_no_config(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(llmchat_router, "get_user_config", AsyncMock(return_value=None))

    result = await llmchat_router._create_local_session_from_config("u1")
    assert result is None


def test_build_llm_config_with_temperature():
    config = llmchat_router.build_llm_config(LLMInput(model="gpt-4", temperature=0.5, max_tokens=100))
    assert config.config.temperature == 0.5
    assert config.config.max_tokens == 100


def test_build_config_with_server():
    config = llmchat_router.build_config(ConnectInput(
        user_id="u1",
        llm=LLMInput(model="gpt"),
        server=ServerInput(url="http://custom/mcp", transport="sse", auth_token="token"),
        streaming=True,
    ))
    assert config.mcp_server.url == "http://custom/mcp"
    assert config.mcp_server.transport == "sse"
    assert config.mcp_server.auth_token == "token"
    assert config.enable_streaming is True


@pytest.mark.asyncio
async def test_get_user_config_redis_no_data(monkeypatch: pytest.MonkeyPatch):
    redis_mock = AsyncMock()
    redis_mock.get.return_value = None
    monkeypatch.setattr(llmchat_router, "redis_client", redis_mock)

    result = await llmchat_router.get_user_config("u1")
    assert result is None
