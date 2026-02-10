# -*- coding: utf-8 -*-
"""Extra tests for MCP chat service helpers."""

# Standard
from types import SimpleNamespace

# Third-Party
import pytest

# First-Party
from mcpgateway.services.mcp_client_chat_service import (
    ChatHistoryManager,
    GatewayConfig,
    LLMConfig,
    LLMProviderFactory,
    MCPServerConfig,
)


@pytest.mark.asyncio
async def test_chat_history_manager_in_memory():
    manager = ChatHistoryManager(redis_client=None, max_messages=2)

    await manager.append_message("u1", "user", "hello")
    await manager.append_message("u1", "assistant", "hi")
    await manager.append_message("u1", "user", "third")

    history = await manager.get_history("u1")
    assert len(history) == 2
    assert history[0]["content"] == "hi"

    await manager.clear_history("u1")
    assert await manager.get_history("u1") == []


def test_mcp_server_config_validators():
    config = MCPServerConfig(url="http://example.com", transport="streamable_http", auth_token="token")
    assert config.headers["Authorization"] == "Bearer token"

    MCPServerConfig(url=None, transport="streamable_http")
    MCPServerConfig(command=None, transport="stdio")


def test_llm_provider_factory_gateway():
    llm_config = LLMConfig(provider="gateway", config=GatewayConfig(model="gpt"))
    provider = LLMProviderFactory.create(llm_config)
    assert provider.get_model_name() == "gpt"
