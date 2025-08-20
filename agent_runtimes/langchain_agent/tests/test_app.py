# -*- coding: utf-8 -*-
"""Tests for the FastAPI application."""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import Mock, patch

from agent_runtimes.langchain_agent import app


@pytest.fixture
def client():
    """Create a test client for the FastAPI app."""
    return TestClient(app)


class TestHealthEndpoints:
    """Test health and readiness endpoints."""

    def test_health_endpoint(self, client):
        """Test the health check endpoint."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "timestamp" in data

    def test_ready_endpoint(self, client):
        """Test the readiness check endpoint."""
        response = client.get("/ready")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "agent_initialized" in data

    def test_list_tools_endpoint(self, client):
        """Test the list tools endpoint."""
        response = client.get("/list_tools")
        assert response.status_code == 200
        data = response.json()
        assert "tools" in data
        assert isinstance(data["tools"], list)


class TestChatCompletions:
    """Test chat completion endpoints."""

    @patch("agent_runtimes.langchain_agent.app.agent")
    def test_chat_completions_basic(self, mock_agent, client):
        """Test basic chat completion."""
        # Mock agent response
        mock_agent.invoke.return_value = {
            "output": "Hello! I'm a test response."
        }

        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4o-mini",
                "messages": [
                    {"role": "user", "content": "Hello!"}
                ]
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert "choices" in data
        assert len(data["choices"]) > 0

    @patch("agent_runtimes.langchain_agent.app.agent")
    def test_chat_completions_with_tools(self, mock_agent, client):
        """Test chat completion with tool usage."""
        # Mock agent response with tool usage
        mock_agent.invoke.return_value = {
            "output": "I used a tool to get this information.",
            "intermediate_steps": [
                ("tool_call", "result")
            ]
        }

        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4o-mini",
                "messages": [
                    {"role": "user", "content": "Use a tool to help me"}
                ]
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert "choices" in data


class TestA2AEndpoint:
    """Test A2A JSON-RPC endpoint."""

    @patch("agent_runtimes.langchain_agent.app.agent")
    def test_a2a_list_tools(self, mock_agent, client):
        """Test A2A list_tools method."""
        response = client.post(
            "/a2a",
            json={
                "jsonrpc": "2.0",
                "id": "1",
                "method": "list_tools",
                "params": {}
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert "jsonrpc" in data
        assert data["id"] == "1"

    @patch("agent_runtimes.langchain_agent.app.agent")
    def test_a2a_invoke_tool(self, mock_agent, client):
        """Test A2A tool invocation."""
        mock_agent.invoke.return_value = {
            "output": "Tool result"
        }

        response = client.post(
            "/a2a",
            json={
                "jsonrpc": "2.0",
                "id": "1",
                "method": "invoke",
                "params": {
                    "tool": "test_tool",
                    "args": {"param": "value"}
                }
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert "result" in data

    def test_a2a_invalid_method(self, client):
        """Test A2A with invalid method."""
        response = client.post(
            "/a2a",
            json={
                "jsonrpc": "2.0",
                "id": "1",
                "method": "invalid_method",
                "params": {}
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert "error" in data
