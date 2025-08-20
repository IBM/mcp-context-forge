# -*- coding: utf-8 -*-
"""Pytest configuration and fixtures for MCP LangChain Agent tests."""

import os
import pytest
from unittest.mock import Mock, AsyncMock
from fastapi.testclient import TestClient

# Set test environment variables before any imports
os.environ["OPENAI_API_KEY"] = "test-key"
os.environ["MCPGATEWAY_BEARER_TOKEN"] = "test-token"
os.environ["DEBUG_MODE"] = "true"


@pytest.fixture(scope="session")
def test_env():
    """Set up test environment variables."""
    env_vars = {
        "OPENAI_API_KEY": "test-key",
        "MCPGATEWAY_BEARER_TOKEN": "test-token",
        "MCP_GATEWAY_URL": "http://localhost:4444",
        "DEFAULT_MODEL": "gpt-4o-mini",
        "TEMPERATURE": "0.7",
        "MAX_ITERATIONS": "5",
        "DEBUG_MODE": "true",
    }

    # Store original values
    original_values = {}
    for key, value in env_vars.items():
        original_values[key] = os.environ.get(key)
        os.environ[key] = value

    yield env_vars

    # Restore original values
    for key, original_value in original_values.items():
        if original_value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = original_value


@pytest.fixture
def mock_agent():
    """Create a mock LangChain agent."""
    agent = Mock()
    agent.invoke = AsyncMock()
    agent.tools = []
    return agent


@pytest.fixture
def mock_mcp_client():
    """Create a mock MCP client."""
    client = Mock()
    client.get_tools = AsyncMock()
    client.invoke_tool = AsyncMock()
    client.is_healthy = Mock(return_value=True)
    return client


@pytest.fixture
def sample_tools():
    """Sample tools data for testing."""
    return [
        {
            "id": "test-tool-1",
            "name": "test_tool",
            "description": "A test tool",
            "input_schema": {
                "type": "object",
                "properties": {
                    "param": {"type": "string"}
                }
            }
        },
        {
            "id": "test-tool-2",
            "name": "another_tool",
            "description": "Another test tool",
            "input_schema": {
                "type": "object",
                "properties": {
                    "value": {"type": "number"}
                }
            }
        }
    ]


@pytest.fixture
def sample_chat_request():
    """Sample chat completion request."""
    return {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "user", "content": "Hello, how are you?"}
        ],
        "temperature": 0.7,
        "max_tokens": 150
    }


@pytest.fixture
def sample_a2a_request():
    """Sample A2A JSON-RPC request."""
    return {
        "jsonrpc": "2.0",
        "id": "test-id",
        "method": "invoke",
        "params": {
            "tool": "test_tool",
            "args": {"param": "test_value"}
        }
    }
