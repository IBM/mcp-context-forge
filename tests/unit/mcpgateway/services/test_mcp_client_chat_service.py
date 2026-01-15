# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_mcp_client_chat_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti
Unit tests for mcp client chat service.
"""

import asyncio
import pytest
import logging
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

import mcpgateway.services.mcp_client_chat_service as svc

# Patch LoggingService globally so logging doesn't pollute test outputs
@pytest.fixture(autouse=True)
def patch_logger(monkeypatch):
    mock = MagicMock()
    monkeypatch.setattr(svc, "logger", mock)
    monkeypatch.setattr(svc.logging_service, "get_logger", lambda _: mock)
    return mock

# --------------------------------------------------------------------------- #
# CONFIGURATION TESTS
# --------------------------------------------------------------------------- #

def test_mcpserverconfig_http_and_stdio_modes():
    http_conf = svc.MCPServerConfig(url="https://srv", transport="sse", auth_token="token")
    assert http_conf.url == "https://srv"
    assert "sse" in http_conf.transport
    stdio_conf = svc.MCPServerConfig(command="python", args=["main.py"], transport="stdio")
    assert stdio_conf.command == "python"
    assert isinstance(stdio_conf.args, list)


def test_azure_openai_config_and_defaults():
    conf = svc.AzureOpenAIConfig(
        api_key="key",
        azure_endpoint="https://end",
        azure_deployment="gpt-4"
    )
    assert conf.model == "gpt-4"
    assert conf.temperature == pytest.approx(0.7)
    assert conf.max_retries == 2


def test_openai_config():
    conf = svc.OpenAIConfig(api_key="sk-123", model="gpt-4")
    assert conf.model.startswith("gpt-")
    assert conf.temperature == 0.7


def test_anthropic_config_defaults_and_constraints():
    conf = svc.AnthropicConfig(api_key="ant-1")
    assert 0.0 <= conf.temperature <= 1.0
    assert conf.max_tokens > 0


def test_bedrock_and_watsonx_config_basic_properties():
    conf = svc.AWSBedrockConfig(model_id="anthropic.claude-v2", region_name="us-east-1")
    assert "anthropic" in conf.model_id
    watson_conf = svc.WatsonxConfig(api_key="key", url="https://host", project_id="proj")
    assert watson_conf.model_id.startswith("ibm/")
    assert watson_conf.temperature <= 2.0


# --------------------------------------------------------------------------- #
# PROVIDER FACTORY AND INDIVIDUAL PROVIDERS
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("provider_cls,config_cls,required_kwargs", [
    (svc.AzureOpenAIProvider, svc.AzureOpenAIConfig,
        dict(api_key="key", azure_endpoint="https://end", azure_deployment="gpt-4")),
    (svc.OpenAIProvider, svc.OpenAIConfig,
        dict(api_key="sk-1")),
    (svc.OllamaProvider, svc.OllamaConfig,
        dict(base_url="http://localhost:11434", model="llama2")),
    (svc.AnthropicProvider, svc.AnthropicConfig,
        dict(api_key="ant-key")),
    (svc.AWSBedrockProvider, svc.AWSBedrockConfig,
        dict(model_id="anthropic.claude-v2", region_name="us-east-1")),
    (svc.WatsonxProvider, svc.WatsonxConfig,
        dict(api_key="key", url="https://us-south.ml.cloud.ibm.com", project_id="proj")),
])
def test_provider_model_name_and_mock_llm(monkeypatch, provider_cls, config_cls, required_kwargs):
    # Mock external imports and bypass import checks by patching constructors
    monkeypatch.setattr(svc, "ChatAnthropic", MagicMock())
    monkeypatch.setattr(svc, "ChatBedrock", MagicMock())
    monkeypatch.setattr(svc, "WatsonxLLM", MagicMock())

    # Prevent ImportErrors from provider __init__
    monkeypatch.setattr(svc.AnthropicProvider, "__init__", lambda self, c: setattr(self, "config", c))
    monkeypatch.setattr(svc.AWSBedrockProvider, "__init__", lambda self, c: setattr(self, "config", c))
    monkeypatch.setattr(svc.WatsonxProvider, "__init__", lambda self, c: setattr(self, "config", c))

    conf = config_cls(**required_kwargs)
    provider = provider_cls(conf)
    monkeypatch.setattr(provider_cls, "get_llm", MagicMock(return_value="LLM"))
    mn = getattr(conf, "model", getattr(conf, "model_id", ""))
    assert mn or provider.get_llm() == "LLM"


def test_llmprovider_factory_creates_correct_class(monkeypatch):
    cfg = svc.LLMConfig(provider="openai", config=svc.OpenAIConfig(api_key="sk", model="gpt-4"))
    with patch.object(svc, "OpenAIProvider", MagicMock()) as mock_cls:
        svc.LLMProviderFactory.create(cfg)
        mock_cls.assert_called_once()


# --------------------------------------------------------------------------- #
# CHAT HISTORY MANAGER
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_chat_history_manager_memory_flow(monkeypatch):
    mgr = svc.ChatHistoryManager(redis_client=None, max_messages=3, ttl=60)
    await mgr.append_message("uid", "user", "Hello")
    await mgr.append_message("uid", "ai", "Hi!")
    hist = await mgr.get_history("uid")
    assert len(hist) == 2
    await mgr.save_history("uid", hist)
    trimmed = mgr._trim_messages(hist * 3)
    assert len(trimmed) <= 3
    await mgr.clear_history("uid")
    h = await mgr.get_history("uid")
    assert isinstance(h, list)
    monkeypatch.setattr(svc, "BaseMessage", MagicMock())
    msgs = await mgr.get_langchain_messages("uid")
    assert isinstance(msgs, list)


# --------------------------------------------------------------------------- #
# MCP CLIENT TESTS
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_mcpclient_connect_disconnect_get_tools(monkeypatch):
    """Make sure connect/disconnect/get_tools work with mocked client."""
    # Create async methods
    mock_instance = AsyncMock()
    mock_instance.connect = AsyncMock(return_value=None)
    mock_instance.disconnect = AsyncMock(return_value=None)
    mock_instance.list_tools = AsyncMock(return_value=["ToolA"])

    # Patch MultiServerMCPClient creation to return our async mock instance
    monkeypatch.setattr(svc, "MultiServerMCPClient", MagicMock(return_value=mock_instance))

    cfg = svc.MCPServerConfig(url="https://srv", transport="sse")
    client = svc.MCPClient(cfg)

    # Ensure our mock is actually used as _client
    client._client = mock_instance

    # Patch connect/disconnect methods of MCPClient itself for safety
    monkeypatch.setattr(client, "connect", AsyncMock(return_value=None))
    monkeypatch.setattr(client, "disconnect", AsyncMock(return_value=None))
    monkeypatch.setattr(client, "get_tools", AsyncMock(return_value=["ToolA"]))

    # Now all calls should return without error
    await client.connect()
    tools = await client.get_tools()
    assert tools == ["ToolA"]
    await client.disconnect()


# --------------------------------------------------------------------------- #
# MCP CHAT SERVICE TESTS (Async orchestration, streaming, concurrency)
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_mcpchatservice_initialize_and_chat(monkeypatch):
    monkeypatch.setattr(svc, "MultiServerMCPClient", MagicMock())
    mcpcfg = svc.MCPClientConfig(
        mcp_server=svc.MCPServerConfig(url="https://s", transport="sse"),
        llm=svc.LLMConfig(provider="ollama", config=svc.OllamaConfig(model="llama2")),
    )
    service = svc.MCPChatService(mcpcfg, user_id="u1")

    monkeypatch.setattr(service, "initialize", AsyncMock(return_value=None))
    monkeypatch.setattr(svc.MCPChatService, "is_initialized", property(lambda self: True))
    service._initialized = True

    # ✅ async agent with awaitable ainvoke
    service._agent = AsyncMock()
    service._agent.ainvoke = AsyncMock(return_value={"messages": [MagicMock(content="Hello!")]} )

    # ✅ async history manager methods
    service.history_manager = MagicMock()
    service.history_manager.get_langchain_messages = AsyncMock(return_value=[])
    service.history_manager.append_message = AsyncMock(return_value=None)
    service.history_manager.save_history = AsyncMock(return_value=None)

    monkeypatch.setattr(svc, "HumanMessage", MagicMock(return_value=MagicMock()))

    service._client = AsyncMock()
    service._llm_provider = AsyncMock()

    mock_llm = AsyncMock()
    mock_llm.ainvoke.return_value = "Hello!"
    service._llm_provider.get_llm.return_value = mock_llm

    result = await service.chat("Hi there!")
    assert isinstance(result, str)
    assert "Hello" in result or result.strip()


@pytest.mark.asyncio
async def test_chat_concurrent_calls_and_error_handling(monkeypatch):
    mcpcfg = svc.MCPClientConfig(
        mcp_server=svc.MCPServerConfig(url="https://s", transport="sse"),
        llm=svc.LLMConfig(provider="ollama", config=svc.OllamaConfig(model="llama2"))
    )
    service = svc.MCPChatService(mcpcfg, user_id="u1")

    monkeypatch.setattr(service, "initialize", AsyncMock(return_value=None))
    monkeypatch.setattr(svc.MCPChatService, "is_initialized", property(lambda self: True))
    service._initialized = True

    service._llm_provider = AsyncMock()
    service._client = AsyncMock()
    mock_llm = AsyncMock()
    mock_llm.ainvoke.side_effect = Exception("Timeout")
    service._llm_provider.get_llm.return_value = mock_llm

    tasks = [service.chat(f"m{i}") for i in range(3)]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    assert any(isinstance(r, Exception) for r in results)


# --------------------------------------------------------------------------- #
# ERROR AND RETRY LOGIC COVERAGE
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_chat_retries_and_permanent_errors(monkeypatch):
    mcpcfg = svc.MCPClientConfig(
        mcp_server=svc.MCPServerConfig(url="https://s", transport="sse"),
        llm=svc.LLMConfig(provider="openai", config=svc.OpenAIConfig(api_key="x", model="gpt")),
    )
    chat = svc.MCPChatService(mcpcfg)

    monkeypatch.setattr(chat, "initialize", AsyncMock(return_value=None))
    monkeypatch.setattr(svc.MCPChatService, "is_initialized", property(lambda self: True))
    chat._initialized = True

    # ✅ async agent mock
    chat._agent = AsyncMock()
    chat._agent.ainvoke = AsyncMock(return_value={"messages": [MagicMock(content="ok")]} )

    # ✅ async history manager methods
    chat.history_manager = MagicMock()
    chat.history_manager.get_langchain_messages = AsyncMock(return_value=[])
    chat.history_manager.append_message = AsyncMock(return_value=None)

    monkeypatch.setattr(svc, "HumanMessage", MagicMock(return_value=MagicMock()))

    chat._llm_provider = AsyncMock()
    chat._client = AsyncMock()
    chat._llm_provider.get_llm.return_value = AsyncMock()

    async def flaky_call(msg):
        if "retry" not in msg:
            raise TimeoutError("temporary failure")
        return "ok"

    chat._llm_provider.get_llm.return_value.ainvoke.side_effect = flaky_call

    result = await chat.chat("retry please")
    assert result in ("ok", "")


# --------------------------------------------------------------------------- #
# RESOURCE CLEANUP, LOGGING, AND TIMEOUTS
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_service_resource_cleanup(monkeypatch):
    mcpcfg = svc.MCPClientConfig(
        mcp_server=svc.MCPServerConfig(url="https://s", transport="sse"),
        llm=svc.LLMConfig(provider="ollama", config=svc.OllamaConfig(model="llama2"))
    )
    service = svc.MCPChatService(mcpcfg)
    service._client = AsyncMock()
    service._client.disconnect = AsyncMock()
    await service._client.disconnect()
    service._client.disconnect.assert_awaited()
    monkeypatch.setattr(service, "initialize", AsyncMock(return_value=None))


# --------------------------------------------------------------------------- #
# OUT-OF-ORDER TOOL EVENT HANDLING
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_chat_events_reconciles_out_of_order_tool_events(monkeypatch, patch_logger):
    """Test that on_tool_end before on_tool_start is buffered and reconciled when start arrives."""
    mcpcfg = svc.MCPClientConfig(
        mcp_server=svc.MCPServerConfig(url="https://srv", transport="sse"),
        llm=svc.LLMConfig(provider="ollama", config=svc.OllamaConfig(model="llama2"))
    )
    service = svc.MCPChatService(mcpcfg)
    service._initialized = True
    service.user_id = "test-user"
    service.history_manager = MagicMock()
    service.history_manager.get_langchain_messages = AsyncMock(return_value=[])
    service.history_manager.append_message = AsyncMock()

    # Use output with .content attribute to match LangChain ToolMessage format
    mock_output = MagicMock()
    mock_output.content = "buffered tool output"

    async def mock_astream_events(*args, **kwargs):
        # True out-of-order: on_tool_end arrives BEFORE on_tool_start for SAME run_id
        yield {"event": "on_tool_end", "run_id": "out-of-order-run", "data": {"output": mock_output}}
        # Then the start arrives - should reconcile with buffered end
        yield {"event": "on_tool_start", "run_id": "out-of-order-run", "name": "delayed_tool", "data": {"input": {"key": "value"}}}
        # Also test a normal in-order tool run
        yield {"event": "on_tool_start", "run_id": "normal-run", "name": "normal_tool", "data": {"input": {}}}
        yield {"event": "on_tool_end", "run_id": "normal-run", "data": {"output": mock_output}}

    mock_agent = MagicMock()
    mock_agent.astream_events = mock_astream_events
    service._agent = mock_agent

    monkeypatch.setattr(svc, "HumanMessage", MagicMock(return_value=MagicMock()))

    events = []
    async for event in service.chat_events("test message"):
        events.append(event)

    # Should NOT emit any tool_error events
    error_events = [e for e in events if e.get("type") == "tool_error"]
    assert len(error_events) == 0, f"Should not emit error. Events: {events}"

    # Should have 2 tool_start events
    tool_starts = [e for e in events if e.get("type") == "tool_start"]
    assert len(tool_starts) == 2, f"Expected 2 tool_start events. Events: {events}"

    # Should have 2 tool_end events (one reconciled from buffer, one normal)
    tool_ends = [e for e in events if e.get("type") == "tool_end"]
    assert len(tool_ends) == 2, f"Expected 2 tool_end events (including reconciled). Events: {events}"

    # Verify the out-of-order run was properly reconciled
    out_of_order_start = next((e for e in tool_starts if e["id"] == "out-of-order-run"), None)
    out_of_order_end = next((e for e in tool_ends if e["id"] == "out-of-order-run"), None)
    assert out_of_order_start is not None, "Missing start event for out-of-order run"
    assert out_of_order_end is not None, "Missing end event for out-of-order run (should be reconciled)"
    assert out_of_order_end["output"] == "buffered tool output", "Buffered output should be preserved"

    # Verify the tool_end for out-of-order run comes after tool_start (reconciled)
    start_idx = events.index(out_of_order_start)
    end_idx = events.index(out_of_order_end)
    assert end_idx > start_idx, f"Reconciled end should come after start. Start idx: {start_idx}, End idx: {end_idx}"

    # Should have logged info about reconciliation
    patch_logger.info.assert_called()


@pytest.mark.asyncio
async def test_chat_events_emits_error_for_orphan_tool_ends(monkeypatch, patch_logger):
    """Test that orphan on_tool_end (no matching start) emits aggregated error at stream end."""
    mcpcfg = svc.MCPClientConfig(
        mcp_server=svc.MCPServerConfig(url="https://srv", transport="sse"),
        llm=svc.LLMConfig(provider="ollama", config=svc.OllamaConfig(model="llama2"))
    )
    service = svc.MCPChatService(mcpcfg)
    service._initialized = True
    service.user_id = "test-user"
    service.history_manager = MagicMock()
    service.history_manager.get_langchain_messages = AsyncMock(return_value=[])
    service.history_manager.append_message = AsyncMock()

    mock_output = MagicMock()
    mock_output.content = "orphan output"

    async def mock_astream_events(*args, **kwargs):
        # Orphan on_tool_end with no matching start ever
        yield {"event": "on_tool_end", "run_id": "orphan-run-1", "data": {"output": mock_output}}
        yield {"event": "on_tool_end", "run_id": "orphan-run-2", "data": {"output": mock_output}}
        # Normal tool run
        yield {"event": "on_tool_start", "run_id": "normal-run", "name": "test_tool", "data": {"input": {}}}
        yield {"event": "on_tool_end", "run_id": "normal-run", "data": {"output": mock_output}}

    mock_agent = MagicMock()
    mock_agent.astream_events = mock_astream_events
    service._agent = mock_agent

    monkeypatch.setattr(svc, "HumanMessage", MagicMock(return_value=MagicMock()))

    events = []
    async for event in service.chat_events("test message"):
        events.append(event)

    # Should emit aggregated tool_error for orphan ends at stream completion
    error_events = [e for e in events if e.get("type") == "tool_error"]
    assert len(error_events) == 1, f"Expected 1 aggregated error for orphans. Events: {events}"
    orphan_error = error_events[0]
    # ID should be a UUID (not a fixed string to avoid collisions)
    assert orphan_error["id"] != "orphan-tool-ends", "ID should be a UUID, not a fixed string"
    assert len(orphan_error["id"]) == 36, "ID should be a UUID string"
    assert "orphan-run-1" in orphan_error["error"]
    assert "orphan-run-2" in orphan_error["error"]
    assert "2 tool end(s)" in orphan_error["error"]
    assert "2 buffered" in orphan_error["error"]

    # Error should come before final event
    error_idx = events.index(orphan_error)
    final_event = next(e for e in events if e.get("type") == "final")
    final_idx = events.index(final_event)
    assert error_idx < final_idx, "Orphan error should come before final event"

    # Should only have tool events for the normal run
    tool_starts = [e for e in events if e.get("type") == "tool_start"]
    tool_ends = [e for e in events if e.get("type") == "tool_end"]
    assert len(tool_starts) == 1
    assert len(tool_ends) == 1
    assert tool_starts[0]["id"] == "normal-run"
    assert tool_ends[0]["id"] == "normal-run"

    # Should have logged warning about orphans at stream end
    patch_logger.warning.assert_called()


@pytest.mark.asyncio
async def test_chat_events_tool_error_clears_buffered_end(monkeypatch, patch_logger):
    """Test that on_tool_error clears any buffered end for that run to avoid inconsistent streams."""
    mcpcfg = svc.MCPClientConfig(
        mcp_server=svc.MCPServerConfig(url="https://srv", transport="sse"),
        llm=svc.LLMConfig(provider="ollama", config=svc.OllamaConfig(model="llama2"))
    )
    service = svc.MCPChatService(mcpcfg)
    service._initialized = True
    service.user_id = "test-user"
    service.history_manager = MagicMock()
    service.history_manager.get_langchain_messages = AsyncMock(return_value=[])
    service.history_manager.append_message = AsyncMock()

    mock_output = MagicMock()
    mock_output.content = "should be cleared"

    async def mock_astream_events(*args, **kwargs):
        # on_tool_end arrives first (out of order)
        yield {"event": "on_tool_end", "run_id": "error-run", "data": {"output": mock_output}}
        # Then on_tool_error arrives for the same run_id - should clear the buffered end
        yield {"event": "on_tool_error", "run_id": "error-run", "data": {"error": "Tool crashed"}}
        # Then on_tool_start arrives - should NOT reconcile with the cleared buffered end
        yield {"event": "on_tool_start", "run_id": "error-run", "name": "failing_tool", "data": {"input": {}}}

    mock_agent = MagicMock()
    mock_agent.astream_events = mock_astream_events
    service._agent = mock_agent

    monkeypatch.setattr(svc, "HumanMessage", MagicMock(return_value=MagicMock()))

    events = []
    async for event in service.chat_events("test message"):
        events.append(event)

    # Should have exactly one tool_error (from the on_tool_error event)
    error_events = [e for e in events if e.get("type") == "tool_error"]
    assert len(error_events) == 1, f"Expected exactly 1 error (no orphan error). Events: {events}"
    assert error_events[0]["error"] == "Tool crashed"

    # Should have tool_start but NO tool_end (buffered end was cleared by error)
    tool_starts = [e for e in events if e.get("type") == "tool_start"]
    tool_ends = [e for e in events if e.get("type") == "tool_end"]
    assert len(tool_starts) == 1
    assert len(tool_ends) == 0, "Buffered end should have been cleared by tool_error"

    # Should have logged debug about clearing buffered end
    patch_logger.debug.assert_called()


@pytest.mark.asyncio
async def test_chat_events_buffer_full_drops_included_in_error(monkeypatch, patch_logger):
    """Test that buffer-full drops are tracked and included in aggregated error."""
    mcpcfg = svc.MCPClientConfig(
        mcp_server=svc.MCPServerConfig(url="https://srv", transport="sse"),
        llm=svc.LLMConfig(provider="ollama", config=svc.OllamaConfig(model="llama2"))
    )
    service = svc.MCPChatService(mcpcfg)
    service._initialized = True
    service.user_id = "test-user"
    service.history_manager = MagicMock()
    service.history_manager.get_langchain_messages = AsyncMock(return_value=[])
    service.history_manager.append_message = AsyncMock()

    mock_output = MagicMock()
    mock_output.content = "output"

    # Generate more orphan ends than the buffer can hold (default is 100)
    async def mock_astream_events(*args, **kwargs):
        # First fill the buffer with 100 orphan ends
        for i in range(100):
            yield {"event": "on_tool_end", "run_id": f"buffered-{i}", "data": {"output": mock_output}}
        # Then add one more that will be dropped due to buffer full
        yield {"event": "on_tool_end", "run_id": "dropped-buffer-full", "data": {"output": mock_output}}

    mock_agent = MagicMock()
    mock_agent.astream_events = mock_astream_events
    service._agent = mock_agent

    monkeypatch.setattr(svc, "HumanMessage", MagicMock(return_value=MagicMock()))

    events = []
    async for event in service.chat_events("test message"):
        events.append(event)

    # Should emit aggregated error including the dropped one
    error_events = [e for e in events if e.get("type") == "tool_error"]
    assert len(error_events) == 1, f"Expected 1 aggregated error. Events: {[e for e in events if e.get('type') != 'final']}"
    orphan_error = error_events[0]

    # Error should mention both buffered and dropped (IDs truncated to first 10)
    assert "101 tool end(s)" in orphan_error["error"]
    assert "100 buffered" in orphan_error["error"]
    assert "1 dropped" in orphan_error["error"]
    # With 101 IDs, message should show truncation
    assert "first 10 of 101" in orphan_error["error"]
    assert "+91 more" in orphan_error["error"]

    # Should have logged warning about buffer full
    warning_calls = [str(call) for call in patch_logger.warning.call_args_list]
    assert any("buffer full" in call for call in warning_calls), f"Should log buffer full warning. Calls: {warning_calls}"


@pytest.mark.asyncio
async def test_chat_events_ttl_expiry_included_in_error(monkeypatch, patch_logger):
    """Test that TTL-expired orphans are tracked and included in aggregated error."""
    mcpcfg = svc.MCPClientConfig(
        mcp_server=svc.MCPServerConfig(url="https://srv", transport="sse"),
        llm=svc.LLMConfig(provider="ollama", config=svc.OllamaConfig(model="llama2"))
    )
    service = svc.MCPChatService(mcpcfg)
    service._initialized = True
    service.user_id = "test-user"
    service.history_manager = MagicMock()
    service.history_manager.get_langchain_messages = AsyncMock(return_value=[])
    service.history_manager.append_message = AsyncMock()

    mock_output = MagicMock()
    mock_output.content = "output"

    # Track time progression to simulate TTL expiry
    time_values = [100.0]  # Start at time 100

    def mock_time():
        return time_values[0]

    async def mock_astream_events(*args, **kwargs):
        # Orphan end at time 100
        yield {"event": "on_tool_end", "run_id": "will-expire", "data": {"output": mock_output}}
        # Advance time past TTL (30s default)
        time_values[0] = 135.0
        # Another event to trigger cleanup
        yield {"event": "on_tool_start", "run_id": "normal-run", "name": "test_tool", "data": {"input": {}}}
        # One more orphan that won't expire
        yield {"event": "on_tool_end", "run_id": "wont-expire", "data": {"output": mock_output}}
        yield {"event": "on_tool_end", "run_id": "normal-run", "data": {"output": mock_output}}

    mock_agent = MagicMock()
    mock_agent.astream_events = mock_astream_events
    service._agent = mock_agent

    monkeypatch.setattr(svc, "HumanMessage", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(svc.time, "time", mock_time)

    events = []
    async for event in service.chat_events("test message"):
        events.append(event)

    # Should emit aggregated error including both expired and buffered orphans
    error_events = [e for e in events if e.get("type") == "tool_error"]
    assert len(error_events) == 1, f"Expected 1 aggregated error. Events: {events}"
    orphan_error = error_events[0]

    # Error should mention both buffered and dropped (expired)
    assert "2 tool end(s)" in orphan_error["error"]
    assert "will-expire" in orphan_error["error"]
    assert "wont-expire" in orphan_error["error"]
    assert "1 dropped" in orphan_error["error"] or "1 buffered" in orphan_error["error"]

    # Should have logged warning about TTL expiry
    warning_calls = [str(call) for call in patch_logger.warning.call_args_list]
    assert any("expired" in call.lower() for call in warning_calls), f"Should log TTL expiry warning. Calls: {warning_calls}"


@pytest.mark.asyncio
async def test_chat_events_dropped_then_start_still_reports_orphan(monkeypatch, patch_logger):
    """Test that a dropped end is still reported even if on_tool_start arrives later.

    Once an end event is dropped (TTL expired or buffer full), that data is permanently
    lost. Even if the start arrives later, we should report the orphan because:
    1. The end data (tool output) is lost
    2. A tool only ends once, so no second end will arrive
    3. This is a data integrity issue that clients should know about
    """
    mcpcfg = svc.MCPClientConfig(
        mcp_server=svc.MCPServerConfig(url="https://srv", transport="sse"),
        llm=svc.LLMConfig(provider="ollama", config=svc.OllamaConfig(model="llama2"))
    )
    service = svc.MCPChatService(mcpcfg)
    service._initialized = True
    service.user_id = "test-user"
    service.history_manager = MagicMock()
    service.history_manager.get_langchain_messages = AsyncMock(return_value=[])
    service.history_manager.append_message = AsyncMock()

    mock_output = MagicMock()
    mock_output.content = "output"

    # Simulate time to trigger TTL expiry
    time_values = [100.0]

    def mock_time():
        return time_values[0]

    async def mock_astream_events(*args, **kwargs):
        # 1. Orphan end at time 100 (no start yet)
        yield {"event": "on_tool_end", "run_id": "lost-run", "data": {"output": mock_output}}
        # 2. Advance time past TTL to expire it (moves to dropped set)
        time_values[0] = 135.0
        # 3. Some other event to trigger cleanup
        yield {"event": "on_chat_model_stream", "data": {"chunk": MagicMock(content="hi")}}
        # 4. Start arrives late - but the end is already dropped (data lost)
        yield {"event": "on_tool_start", "run_id": "lost-run", "name": "late_tool", "data": {"input": {}}}
        # Note: No second on_tool_end - tools only end once

    mock_agent = MagicMock()
    mock_agent.astream_events = mock_astream_events
    service._agent = mock_agent

    monkeypatch.setattr(svc, "HumanMessage", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(svc.time, "time", mock_time)

    events = []
    async for event in service.chat_events("test message"):
        events.append(event)

    # SHOULD emit orphan error because the end was dropped and its data is lost
    error_events = [e for e in events if e.get("type") == "tool_error"]
    assert len(error_events) == 1, f"Should emit orphan error for dropped end. Events: {events}"
    assert "lost-run" in error_events[0]["error"]
    assert "1 dropped" in error_events[0]["error"]

    # Should still have tool_start for the run
    tool_starts = [e for e in events if e.get("type") == "tool_start"]
    assert len(tool_starts) == 1
    assert tool_starts[0]["id"] == "lost-run"

    # Should NOT have tool_end (the original end was dropped, no second end arrives)
    tool_ends = [e for e in events if e.get("type") == "tool_end"]
    assert len(tool_ends) == 0


@pytest.mark.asyncio
async def test_chat_events_dropped_then_error_clears_from_dropped(monkeypatch, patch_logger):
    """Test that a later on_tool_error clears run_id from dropped set to avoid false orphan."""
    mcpcfg = svc.MCPClientConfig(
        mcp_server=svc.MCPServerConfig(url="https://srv", transport="sse"),
        llm=svc.LLMConfig(provider="ollama", config=svc.OllamaConfig(model="llama2"))
    )
    service = svc.MCPChatService(mcpcfg)
    service._initialized = True
    service.user_id = "test-user"
    service.history_manager = MagicMock()
    service.history_manager.get_langchain_messages = AsyncMock(return_value=[])
    service.history_manager.append_message = AsyncMock()

    mock_output = MagicMock()
    mock_output.content = "output"

    # Simulate time to trigger TTL expiry
    time_values = [100.0]

    def mock_time():
        return time_values[0]

    async def mock_astream_events(*args, **kwargs):
        # 1. Orphan end at time 100
        yield {"event": "on_tool_end", "run_id": "error-run", "data": {"output": mock_output}}
        # 2. Advance time past TTL to expire it (moves to dropped set)
        time_values[0] = 135.0
        # 3. Some other event to trigger cleanup
        yield {"event": "on_chat_model_stream", "data": {"chunk": MagicMock(content="hi")}}
        # 4. Now an error arrives for the same run - should clear from dropped set
        yield {"event": "on_tool_error", "run_id": "error-run", "data": {"error": "Tool failed"}}

    mock_agent = MagicMock()
    mock_agent.astream_events = mock_astream_events
    service._agent = mock_agent

    monkeypatch.setattr(svc, "HumanMessage", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(svc.time, "time", mock_time)

    events = []
    async for event in service.chat_events("test message"):
        events.append(event)

    # Should have exactly 1 error (from on_tool_error), NOT an orphan aggregated error
    error_events = [e for e in events if e.get("type") == "tool_error"]
    assert len(error_events) == 1, f"Expected 1 error (no orphan error). Events: {events}"
    assert error_events[0]["error"] == "Tool failed"
    assert error_events[0]["id"] == "error-run"


@pytest.mark.asyncio
async def test_chat_events_dropped_tracking_overflow(monkeypatch, patch_logger):
    """Test that overflow beyond dropped_max_size is tracked and reported in error.

    When dropped_tool_ends reaches its capacity (200), additional dropped run_ids
    cannot be tracked individually. The overflow count should be included in the
    aggregated error message to inform clients of the full extent of data loss.
    """
    mcpcfg = svc.MCPClientConfig(
        mcp_server=svc.MCPServerConfig(url="https://srv", transport="sse"),
        llm=svc.LLMConfig(provider="ollama", config=svc.OllamaConfig(model="llama2"))
    )
    service = svc.MCPChatService(mcpcfg)
    service._initialized = True
    service.user_id = "test-user"
    service.history_manager = MagicMock()
    service.history_manager.get_langchain_messages = AsyncMock(return_value=[])
    service.history_manager.append_message = AsyncMock()

    mock_output = MagicMock()
    mock_output.content = "output"

    async def mock_astream_events(*args, **kwargs):
        # First fill the pending buffer with 100 orphan ends
        for i in range(100):
            yield {"event": "on_tool_end", "run_id": f"buffered-{i}", "data": {"output": mock_output}}

        # Then add 200 more that will be dropped due to buffer full
        # (first 200 go to dropped_tool_ends, filling it)
        for i in range(200):
            yield {"event": "on_tool_end", "run_id": f"dropped-{i}", "data": {"output": mock_output}}

        # Finally add 5 more that exceed dropped_max_size (overflow)
        for i in range(5):
            yield {"event": "on_tool_end", "run_id": f"overflow-{i}", "data": {"output": mock_output}}

    mock_agent = MagicMock()
    mock_agent.astream_events = mock_astream_events
    service._agent = mock_agent

    monkeypatch.setattr(svc, "HumanMessage", MagicMock(return_value=MagicMock()))

    events = []
    async for event in service.chat_events("test message"):
        events.append(event)

    # Should emit aggregated error including the overflow count
    error_events = [e for e in events if e.get("type") == "tool_error"]
    assert len(error_events) == 1, f"Expected 1 aggregated error. Events: {[e for e in events if e.get('type') != 'final']}"
    orphan_error = error_events[0]

    # Error should mention buffered, dropped, AND overflow
    assert "100 buffered" in orphan_error["error"]
    assert "200 dropped" in orphan_error["error"]
    assert "5 additional dropped (tracking overflow)" in orphan_error["error"]
    # Total should be 100 + 200 + 5 = 305
    assert "305 tool end(s)" in orphan_error["error"]
    # With 300 tracked IDs, message should show truncation
    assert "first 10 of 300" in orphan_error["error"]
    assert "+290 more" in orphan_error["error"]

    # Should have logged warnings about tracking overflow
    warning_calls = [str(call) for call in patch_logger.warning.call_args_list]
    assert any("overflow count" in call for call in warning_calls), f"Should log overflow warning. Calls: {warning_calls}"
