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


@pytest.mark.asyncio
async def test_set_get_delete_user_config_in_memory():
    config = llmchat_router.build_config(ConnectInput(user_id="u1", llm=LLMInput(model="gpt")))
    await llmchat_router.set_user_config("u1", config)
    assert await llmchat_router.get_user_config("u1") == config
    await llmchat_router.delete_user_config("u1")
    assert await llmchat_router.get_user_config("u1") is None


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
async def test_status_connected(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(llmchat_router, "MCPChatService", DummyChatService)
    llmchat_router.active_sessions["user1"] = DummyChatService(config=None, user_id="user1")

    result = await llmchat_router.status("user1", user={"id": "user1"})

    assert result["connected"] is True


@pytest.mark.asyncio
async def test_get_config_sanitizes(monkeypatch: pytest.MonkeyPatch):
    config = llmchat_router.build_config(ConnectInput(user_id="u1", llm=LLMInput(model="gpt")))
    await llmchat_router.set_user_config("u1", config)

    result = await llmchat_router.get_config("u1", user={"id": "u1"})

    assert "api_key" not in result["llm"]["config"]
    assert "auth_token" not in result["llm"]["config"]
