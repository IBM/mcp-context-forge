# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_a2a_client_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Tests for A2A Client Service functionality.
"""

# Standard
import json
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import httpx
import pytest

# First-Party
from mcpgateway.services.a2a_client_service import A2AClientService


@pytest.fixture(autouse=True)
def mock_logging():
    """Mock logging to prevent side effects."""
    with (
        patch("mcpgateway.services.a2a_client_service.structured_logger") as mock_slog,
        patch("mcpgateway.services.a2a_client_service.logger") as mock_log,
    ):
        mock_slog.log = MagicMock(return_value=None)
        mock_log.error = MagicMock(return_value=None)
        yield


class TestSendJsonrpc:
    """Tests for A2AClientService.send_jsonrpc (non-streaming)."""

    @pytest.fixture
    def service(self):
        return A2AClientService()

    @pytest.fixture
    def sample_body(self):
        return {
            "jsonrpc": "2.0",
            "method": "message/send",
            "params": {"message": {"role": "user", "parts": [{"kind": "text", "text": "Hello"}]}},
            "id": 1,
        }

    @pytest.mark.asyncio
    async def test_successful_request(self, service, sample_body):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "jsonrpc": "2.0",
            "result": {"id": "task-123", "status": {"state": "completed"}},
            "id": 1,
        }

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock, return_value=mock_client):
            result = await service.send_jsonrpc(
                endpoint_url="https://agent.example.com/a2a",
                auth_headers={"Authorization": "Bearer token"},
                body=sample_body,
                agent_slug="echo",
            )

        assert result["jsonrpc"] == "2.0"
        assert result["result"]["id"] == "task-123"

    @pytest.mark.asyncio
    async def test_http_error_response(self, service, sample_body):
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock, return_value=mock_client):
            result = await service.send_jsonrpc(
                endpoint_url="https://agent.example.com/a2a",
                auth_headers={},
                body=sample_body,
                agent_slug="echo",
            )

        assert "error" in result
        assert result["error"]["code"] == -32603

    @pytest.mark.asyncio
    async def test_timeout_returns_error(self, service, sample_body):
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.TimeoutException("Connection timed out")

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock, return_value=mock_client):
            result = await service.send_jsonrpc(
                endpoint_url="https://agent.example.com/a2a",
                auth_headers={},
                body=sample_body,
                agent_slug="echo",
            )

        assert "error" in result
        assert "timed out" in result["error"]["message"].lower()

    @pytest.mark.asyncio
    async def test_generic_exception_returns_error(self, service, sample_body):
        mock_client = AsyncMock()
        mock_client.post.side_effect = ConnectionError("Connection refused")

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock, return_value=mock_client):
            result = await service.send_jsonrpc(
                endpoint_url="https://agent.example.com/a2a",
                auth_headers={},
                body=sample_body,
                agent_slug="echo",
            )

        assert "error" in result
        assert result["error"]["code"] == -32603

    @pytest.mark.asyncio
    async def test_correlation_id_forwarded(self, service, sample_body):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"jsonrpc": "2.0", "result": {}, "id": 1}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        with (
            patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock, return_value=mock_client),
            patch("mcpgateway.services.a2a_client_service.get_correlation_id", return_value="corr-123"),
        ):
            await service.send_jsonrpc(
                endpoint_url="https://agent.example.com/a2a",
                auth_headers={},
                body=sample_body,
            )

        # Check that correlation ID was included in headers
        call_kwargs = mock_client.post.call_args
        headers = call_kwargs.kwargs.get("headers", call_kwargs[1].get("headers", {}))
        assert headers.get("X-Correlation-ID") == "corr-123"


class TestStreamJsonrpc:
    """Tests for A2AClientService.stream_jsonrpc (SSE streaming)."""

    @pytest.fixture
    def service(self):
        return A2AClientService()

    @pytest.fixture
    def sample_body(self):
        return {
            "jsonrpc": "2.0",
            "method": "message/stream",
            "params": {"message": {"role": "user", "parts": [{"kind": "text", "text": "Hello"}]}},
            "id": 1,
        }

    @pytest.mark.asyncio
    async def test_stream_timeout_yields_error(self, service, sample_body):
        """Timeout during streaming should yield a JSON-RPC error event."""

        async def mock_aconnect_sse(*args, **kwargs):
            raise httpx.TimeoutException("Stream timed out")

        with patch("mcpgateway.services.a2a_client_service.httpx_sse.aconnect_sse", side_effect=mock_aconnect_sse):
            events = []
            async for event in service.stream_jsonrpc(
                endpoint_url="https://agent.example.com/a2a",
                auth_headers={},
                body=sample_body,
                agent_slug="echo",
            ):
                events.append(event)

        # Should have yielded at least one error event
        assert len(events) >= 1
        error_data = json.loads(events[-1].replace("data: ", "").strip())
        assert "error" in error_data

    @pytest.mark.asyncio
    async def test_stream_exception_yields_error(self, service, sample_body):
        """Generic exception during streaming should yield a JSON-RPC error event."""

        async def mock_aconnect_sse(*args, **kwargs):
            raise ConnectionError("Connection lost")

        with patch("mcpgateway.services.a2a_client_service.httpx_sse.aconnect_sse", side_effect=mock_aconnect_sse):
            events = []
            async for event in service.stream_jsonrpc(
                endpoint_url="https://agent.example.com/a2a",
                auth_headers={},
                body=sample_body,
                agent_slug="echo",
            ):
                events.append(event)

        assert len(events) >= 1
        error_data = json.loads(events[-1].replace("data: ", "").strip())
        assert error_data["error"]["code"] == -32603
