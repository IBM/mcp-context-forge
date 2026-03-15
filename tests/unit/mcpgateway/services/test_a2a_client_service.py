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
                agent_id="echo",
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
                agent_id="echo",
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
                agent_id="echo",
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
                agent_id="echo",
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

    @pytest.mark.asyncio
    async def test_send_with_forwarded_headers(self, service, sample_body):
        """Line 80: Forwarded headers are included in send_jsonrpc."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"jsonrpc": "2.0", "result": {}, "id": 1}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock, return_value=mock_client):
            await service.send_jsonrpc(
                endpoint_url="https://agent.example.com/a2a",
                auth_headers={"Authorization": "Bearer token"},
                body=sample_body,
                agent_id="echo",
                forwarded_headers={"X-Custom-Header": "custom-value", "X-Request-ID": "req-789"},
            )

        # Check that forwarded headers were included
        call_kwargs = mock_client.post.call_args
        headers = call_kwargs.kwargs.get("headers", call_kwargs[1].get("headers", {}))
        assert headers.get("X-Custom-Header") == "custom-value"
        assert headers.get("X-Request-ID") == "req-789"
        # Content-Type should still be set
        assert headers.get("Content-Type") == "application/json"

    @pytest.mark.asyncio
    async def test_non_200_with_valid_jsonrpc_error_preserved(self, service, sample_body):
        """Line 160: Preserve downstream JSON-RPC error structure from non-200 response."""
        downstream_error_body = {
            "jsonrpc": "2.0",
            "error": {"code": -32001, "message": "Custom agent error", "data": {"details": "Agent-specific info"}},
            "id": 1,
        }

        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Bad Request"
        mock_response.json.return_value = downstream_error_body

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock, return_value=mock_client):
            result = await service.send_jsonrpc(
                endpoint_url="https://agent.example.com/a2a",
                auth_headers={},
                body=sample_body,
                agent_id="echo",
            )

        # Should preserve the downstream JSON-RPC error structure
        assert result == downstream_error_body
        assert result["error"]["code"] == -32001
        assert result["error"]["message"] == "Custom agent error"

    @pytest.mark.asyncio
    async def test_non_200_with_invalid_json_falls_back(self, service, sample_body):
        """Lines 161-162: Exception during JSON parsing falls back to generic error."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        # json() raises an exception (e.g., invalid JSON)
        mock_response.json.side_effect = json.JSONDecodeError("Invalid JSON", "", 0)

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock, return_value=mock_client):
            result = await service.send_jsonrpc(
                endpoint_url="https://agent.example.com/a2a",
                auth_headers={},
                body=sample_body,
                agent_id="echo",
            )

        # Should fall back to generic error since JSON parsing failed
        assert "error" in result
        assert result["error"]["code"] == -32603
        assert "Internal Server Error" in result["error"]["message"]


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
        """Lines 301-318: Timeout during streaming should yield a JSON-RPC error event."""

        class MockSSEContextManager:
            async def __aenter__(self):
                # Raise timeout exception when entering the context
                raise httpx.TimeoutException("Stream timed out")

            async def __aexit__(self, *args):
                pass

        def mock_aconnect_sse(*args, **kwargs):
            return MockSSEContextManager()

        with patch("mcpgateway.services.a2a_client_service.httpx_sse.aconnect_sse", side_effect=mock_aconnect_sse):
            events = []
            async for event in service.stream_jsonrpc(
                endpoint_url="https://agent.example.com/a2a",
                auth_headers={},
                body=sample_body,
                agent_id="echo",
            ):
                events.append(event)

        # Should have yielded exactly one error event (lines 317-318)
        assert len(events) == 1
        error_data = json.loads(events[0].replace("data: ", "").strip())
        assert "error" in error_data
        assert error_data["error"]["code"] == -32603
        assert "timed out" in error_data["error"]["message"].lower()

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
                agent_id="echo",
            ):
                events.append(event)

        assert len(events) >= 1
        error_data = json.loads(events[-1].replace("data: ", "").strip())
        assert error_data["error"]["code"] == -32603

    @pytest.mark.asyncio
    async def test_stream_with_forwarded_headers(self, service, sample_body):
        """Line 248: Forwarded headers are included in the downstream request."""

        class MockSSEEvent:
            def __init__(self, data, event="message"):
                self.data = data
                self.event = event

        class MockEventSource:
            def __init__(self):
                self.response = MagicMock()
                self.response.raise_for_status = MagicMock()
                self.events = [MockSSEEvent('{"jsonrpc": "2.0", "result": {"text": "Hello"}, "id": 1}')]

            async def aiter_sse(self):
                for event in self.events:
                    yield event

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

        class MockSSEContextManager:
            def __init__(self, headers):
                # Verify forwarded headers are present
                assert headers.get("X-Custom-Header") == "custom-value"
                assert headers.get("X-Request-ID") == "req-123"
                # Accept header should still be set for SSE
                assert headers.get("Accept") == "text/event-stream"

            async def __aenter__(self):
                return MockEventSource()

            async def __aexit__(self, *args):
                pass

        def mock_aconnect_sse(client, method, url, json, headers):
            return MockSSEContextManager(headers)

        with patch("mcpgateway.services.a2a_client_service.httpx_sse.aconnect_sse", side_effect=mock_aconnect_sse):
            events = []
            async for event in service.stream_jsonrpc(
                endpoint_url="https://agent.example.com/a2a",
                auth_headers={"Authorization": "Bearer token"},
                body=sample_body,
                agent_id="echo",
                forwarded_headers={"X-Custom-Header": "custom-value", "X-Request-ID": "req-123"},
            ):
                events.append(event)

        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_stream_with_correlation_id(self, service, sample_body):
        """Line 255: Correlation ID is included in downstream request headers."""

        class MockSSEEvent:
            def __init__(self, data, event="message"):
                self.data = data
                self.event = event

        class MockEventSource:
            def __init__(self):
                self.response = MagicMock()
                self.response.raise_for_status = MagicMock()
                self.events = [MockSSEEvent('{"jsonrpc": "2.0", "result": {"text": "Hello"}, "id": 1}')]

            async def aiter_sse(self):
                for event in self.events:
                    yield event

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

        class MockSSEContextManager:
            def __init__(self, headers):
                # Verify correlation ID is present
                assert headers.get("X-Correlation-ID") == "corr-456"

            async def __aenter__(self):
                return MockEventSource()

            async def __aexit__(self, *args):
                pass

        def mock_aconnect_sse(client, method, url, json, headers):
            return MockSSEContextManager(headers)

        with (
            patch("mcpgateway.services.a2a_client_service.httpx_sse.aconnect_sse", side_effect=mock_aconnect_sse),
            patch("mcpgateway.services.a2a_client_service.get_correlation_id", return_value="corr-456"),
        ):
            events = []
            async for event in service.stream_jsonrpc(
                endpoint_url="https://agent.example.com/a2a",
                auth_headers={},
                body=sample_body,
                agent_id="echo",
            ):
                events.append(event)

        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_stream_custom_event_types(self, service, sample_body):
        """Lines 287-298: SSE events with custom event types are formatted correctly."""

        class MockSSEEvent:
            def __init__(self, data, event="message"):
                self.data = data
                self.event = event

        class MockEventSource:
            def __init__(self):
                self.response = MagicMock()
                self.response.raise_for_status = MagicMock()
                # Mix of default "message" events and custom event types
                self.events = [
                    MockSSEEvent('{"type": "start"}', event="agent.start"),  # Custom event type
                    MockSSEEvent('{"text": "Hello"}', event="message"),  # Default event type
                    MockSSEEvent('{"type": "end"}', event="agent.end"),  # Custom event type
                ]

            async def aiter_sse(self):
                for event in self.events:
                    yield event

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

        class MockSSEContextManager:
            async def __aenter__(self):
                return MockEventSource()

            async def __aexit__(self, *args):
                pass

        def mock_aconnect_sse(client, method, url, json, headers):
            return MockSSEContextManager()

        with patch("mcpgateway.services.a2a_client_service.httpx_sse.aconnect_sse", side_effect=mock_aconnect_sse):
            events = []
            async for event in service.stream_jsonrpc(
                endpoint_url="https://agent.example.com/a2a",
                auth_headers={},
                body=sample_body,
                agent_id="echo",
            ):
                events.append(event)

        # Verify event formatting
        assert len(events) == 3

        # Custom event type should include "event: " prefix (line 296)
        assert events[0] == 'event: agent.start\ndata: {"type": "start"}\n\n'

        # Default "message" event should NOT include "event: " prefix (line 298)
        assert events[1] == 'data: {"text": "Hello"}\n\n'

        # Another custom event type
        assert events[2] == 'event: agent.end\ndata: {"type": "end"}\n\n'
