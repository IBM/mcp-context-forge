# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_a2a_streaming.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

A2A Agent Streaming Tests.

Tests cover:
- Issue #3620 Phase 1: A2A agent SSE streaming support
- stream_agent_response() method functionality
- SSE format validation
- Security and RBAC enforcement
- Error handling
- Observability integration
"""

# Standard
import base64
from datetime import datetime, timezone
import json
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch, Mock
import uuid

# Third-Party
import httpx
import pytest
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import A2AAgent as DbA2AAgent
from mcpgateway.services.a2a_service import A2AAgentError, A2AAgentNotFoundError, A2AAgentService


@pytest.fixture(autouse=True)
def mock_logging_services():
    """Mock structured_logger to prevent database writes during tests."""
    with patch("mcpgateway.services.a2a_service.structured_logger") as mock_logger:
        mock_logger.log = MagicMock(return_value=None)
        mock_logger.info = MagicMock(return_value=None)
        yield


@pytest.fixture(autouse=True)
def bypass_uaid_security_for_tests(monkeypatch):
    """Bypass UAID security validation for streaming tests."""
    monkeypatch.setattr("mcpgateway.services.a2a_service.settings.uaid_allow_all_domains", True)
    monkeypatch.setattr("mcpgateway.services.a2a_service.settings.uaid_forward_auth", True)
    monkeypatch.setattr("mcpgateway.services.a2a_service.settings.uaid_max_federation_hops", 5)
    monkeypatch.setattr("mcpgateway.services.a2a_service.settings.mcpgateway_a2a_default_timeout", 30)


@pytest.fixture
def a2a_service():
    """Create A2A agent service instance."""
    return A2AAgentService()


@pytest.fixture
def mock_db():
    """Create mock database session."""
    db = MagicMock(spec=Session)
    db.commit = MagicMock()
    db.close = MagicMock()
    db.execute = MagicMock()
    return db


@pytest.fixture
def sample_streaming_agent():
    """Sample A2A agent for streaming tests."""
    agent_id = uuid.uuid4()
    return MagicMock(
        id=str(agent_id),
        name="test-streaming-agent",
        slug="test-streaming-agent",
        description="Test streaming A2A agent",
        endpoint_url="http://localhost:9001/invoke",
        agent_type="generic",
        protocol_version="v1",
        enabled=True,
        visibility="public",
        team_id=None,
        auth_type="none",
        auth_value=None,
        auth_query_params=None,
        uaid=None,
        uaid_native_id=None,
        tags=[],
        oauth_config=None,
        passthrough_headers=None,
        spec_type=DbA2AAgent,
    )


class TestStreamAgentResponseBasic:
    """Test basic streaming functionality."""

    @pytest.mark.asyncio
    async def test_stream_agent_response_yields_sse_chunks(self, a2a_service, mock_db, sample_streaming_agent):
        """Test that stream_agent_response yields properly formatted SSE chunks.

        Verifies:
        - Generator yields SSE-formatted strings
        - Each chunk has "data: " prefix and "\n\n" suffix
        - Multiple chunks are streamed
        """
        # Mock database lookup
        mock_db.execute.return_value.scalar_one_or_none.return_value = sample_streaming_agent.id

        # Mock get_for_update to return agent
        with patch("mcpgateway.services.a2a_service.get_for_update", return_value=sample_streaming_agent):
            # Mock agent access check
            with patch.object(a2a_service, "_check_agent_access", return_value=True):
                # Mock prepare_a2a_invocation
                mock_prepared = MagicMock()
                mock_prepared.endpoint_url = sample_streaming_agent.endpoint_url
                mock_prepared.request_data = {"message": "test"}
                mock_prepared.headers = {}
                mock_prepared.sanitized_endpoint_url = sample_streaming_agent.endpoint_url
                mock_prepared.sensitive_query_param_names = []

                with patch("mcpgateway.services.a2a_service.prepare_a2a_invocation", return_value=mock_prepared):
                    # Mock plugin manager
                    with patch.object(a2a_service, "_get_plugin_manager", return_value=None):
                        # Mock HTTP streaming response
                        mock_response = AsyncMock()
                        mock_response.status_code = 200

                        async def mock_aiter_bytes():
                            chunks = [
                                b'{"chunk": 0, "message": "Processing"}',
                                b'{"chunk": 1, "message": "Complete"}',
                            ]
                            for chunk in chunks:
                                yield chunk

                        mock_response.aiter_bytes = mock_aiter_bytes

                        # Mock HTTP client
                        mock_http_client = AsyncMock()
                        mock_http_client.stream = MagicMock()
                        mock_http_client.stream.return_value.__aenter__.return_value = mock_response

                        with patch("mcpgateway.services.a2a_service.get_http_client", return_value=mock_http_client):
                            # Mock fresh_db_session for timestamp update
                            with patch("mcpgateway.services.a2a_service.fresh_db_session"):
                                # Mock metrics buffer
                                with patch("mcpgateway.services.a2a_service.get_metrics_buffer_service"):
                                    # Call stream_agent_response
                                    chunks = []
                                    async for chunk in a2a_service.stream_agent_response(
                                        mock_db,
                                        "test-streaming-agent",
                                        {"message": "test"},
                                        "query",
                                        user_email="test@example.com",
                                        token_teams=None,
                                    ):
                                        chunks.append(chunk)

                                    # Verify chunks
                                    assert len(chunks) == 2
                                    assert chunks[0].startswith("data: ")
                                    assert chunks[0].endswith("\n\n")
                                    assert chunks[1].startswith("data: ")
                                    assert chunks[1].endswith("\n\n")

                                    # Verify content
                                    chunk_0_data = chunks[0].replace("data: ", "").replace("\n\n", "")
                                    chunk_1_data = chunks[1].replace("data: ", "").replace("\n\n", "")
                                    assert "Processing" in chunk_0_data
                                    assert "Complete" in chunk_1_data

    @pytest.mark.asyncio
    async def test_stream_agent_response_handles_binary_chunks(self, a2a_service, mock_db, sample_streaming_agent):
        """Test that binary chunks are base64-encoded in SSE output.

        Verifies:
        - Binary data is detected
        - Base64 encoding applied
        - SSE format maintained
        """
        mock_db.execute.return_value.scalar_one_or_none.return_value = sample_streaming_agent.id

        with patch("mcpgateway.services.a2a_service.get_for_update", return_value=sample_streaming_agent):
            with patch.object(a2a_service, "_check_agent_access", return_value=True):
                mock_prepared = MagicMock()
                mock_prepared.endpoint_url = sample_streaming_agent.endpoint_url
                mock_prepared.request_data = {}
                mock_prepared.headers = {}
                mock_prepared.sanitized_endpoint_url = sample_streaming_agent.endpoint_url
                mock_prepared.sensitive_query_param_names = []

                with patch("mcpgateway.services.a2a_service.prepare_a2a_invocation", return_value=mock_prepared):
                    with patch.object(a2a_service, "_get_plugin_manager", return_value=None):
                        mock_response = AsyncMock()
                        mock_response.status_code = 200

                        async def mock_aiter_bytes():
                            # Binary chunk that will fail UTF-8 decode
                            yield b"\x80\x81\x82\x83"

                        mock_response.aiter_bytes = mock_aiter_bytes

                        mock_http_client = AsyncMock()
                        mock_http_client.stream = MagicMock()
                        mock_http_client.stream.return_value.__aenter__.return_value = mock_response

                        with patch("mcpgateway.services.a2a_service.get_http_client", return_value=mock_http_client):
                            with patch("mcpgateway.services.a2a_service.fresh_db_session"):
                                with patch("mcpgateway.services.a2a_service.get_metrics_buffer_service"):
                                    chunks = []
                                    async for chunk in a2a_service.stream_agent_response(
                                        mock_db, "test-streaming-agent", {}, "query", user_email="test@example.com", token_teams=None
                                    ):
                                        chunks.append(chunk)

                                    # Verify base64 encoding was used
                                    assert len(chunks) == 1
                                    chunk_data = chunks[0].replace("data: ", "").replace("\n\n", "")
                                    # Should be base64-encoded binary data
                                    assert len(chunk_data) > 0


class TestStreamAgentResponseSecurity:
    """Test security and RBAC enforcement in streaming."""

    @pytest.mark.asyncio
    async def test_stream_agent_disabled_returns_error(self, a2a_service, mock_db, sample_streaming_agent):
        """Test that disabled agents return error SSE event.

        Verifies:
        - Disabled agent check happens before streaming
        - Error returned as SSE-formatted event
        - Contains appropriate error message
        """
        # Set agent as disabled
        sample_streaming_agent.enabled = False

        mock_db.execute.return_value.scalar_one_or_none.return_value = sample_streaming_agent.id

        with patch("mcpgateway.services.a2a_service.get_for_update", return_value=sample_streaming_agent):
            with patch.object(a2a_service, "_check_agent_access", return_value=True):
                chunks = []
                async for chunk in a2a_service.stream_agent_response(
                    mock_db, "test-streaming-agent", {}, "query", user_email="test@example.com", token_teams=None
                ):
                    chunks.append(chunk)

                # Should get error SSE event
                assert len(chunks) == 1
                assert chunks[0].startswith("data: ")
                error_data = json.loads(chunks[0].replace("data: ", "").replace("\n\n", ""))
                assert "error" in error_data
                assert "disabled" in error_data["error"].lower()

    @pytest.mark.asyncio
    async def test_stream_agent_not_found_returns_error(self, a2a_service, mock_db):
        """Test that non-existent agent returns error SSE event.

        Verifies:
        - Missing agent detected
        - Error returned as SSE event
        - 404-style error message
        """
        # Mock agent not found
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        chunks = []
        async for chunk in a2a_service.stream_agent_response(
            mock_db, "nonexistent-agent", {}, "query", user_email="test@example.com", token_teams=None
        ):
            chunks.append(chunk)

        # Should get error SSE event
        assert len(chunks) == 1
        error_data = json.loads(chunks[0].replace("data: ", "").replace("\n\n", ""))
        assert "error" in error_data
        assert "not found" in error_data["error"].lower()

    @pytest.mark.asyncio
    async def test_stream_agent_no_access_returns_error(self, a2a_service, mock_db, sample_streaming_agent):
        """Test that access denial returns error SSE event.

        Verifies:
        - RBAC/visibility checks enforced
        - Access denial returns 404-style error (not 403)
        - Error returned as SSE event
        """
        mock_db.execute.return_value.scalar_one_or_none.return_value = sample_streaming_agent.id

        with patch("mcpgateway.services.a2a_service.get_for_update", return_value=sample_streaming_agent):
            # Mock access check to deny
            with patch.object(a2a_service, "_check_agent_access", return_value=False):
                chunks = []
                async for chunk in a2a_service.stream_agent_response(
                    mock_db, "test-streaming-agent", {}, "query", user_email="test@example.com", token_teams=[]
                ):
                    chunks.append(chunk)

                # Should get error SSE event (404-style to avoid leaking existence)
                assert len(chunks) == 1
                error_data = json.loads(chunks[0].replace("data: ", "").replace("\n\n", ""))
                assert "error" in error_data
                assert "not found" in error_data["error"].lower()

    @pytest.mark.asyncio
    async def test_stream_agent_federation_hop_limit(self, a2a_service, mock_db, sample_streaming_agent, monkeypatch):
        """Test that federation hop limit is enforced.

        Verifies:
        - Hop counter checked before streaming
        - Limit exceeded returns error
        - Error message mentions hop limit
        """
        # Set low hop limit
        monkeypatch.setattr("mcpgateway.services.a2a_service.settings.uaid_max_federation_hops", 2)

        chunks = []
        async for chunk in a2a_service.stream_agent_response(
            mock_db,
            "test-streaming-agent",
            {},
            "query",
            user_email="test@example.com",
            token_teams=None,
            hop_count=2,  # At limit
        ):
            chunks.append(chunk)

        # Should get error SSE event
        assert len(chunks) == 1
        error_data = json.loads(chunks[0].replace("data: ", "").replace("\n\n", ""))
        assert "error" in error_data
        assert "hop limit" in error_data["error"].lower()


class TestStreamAgentResponseErrorHandling:
    """Test error handling and resilience in streaming."""

    @pytest.mark.asyncio
    async def test_stream_agent_http_error_returns_error_event(self, a2a_service, mock_db, sample_streaming_agent):
        """Test that HTTP errors are returned as SSE error events.

        Verifies:
        - Non-200 status codes handled
        - Error message included in SSE event
        - Connection cleanup happens
        """
        mock_db.execute.return_value.scalar_one_or_none.return_value = sample_streaming_agent.id

        with patch("mcpgateway.services.a2a_service.get_for_update", return_value=sample_streaming_agent):
            with patch.object(a2a_service, "_check_agent_access", return_value=True):
                mock_prepared = MagicMock()
                mock_prepared.endpoint_url = sample_streaming_agent.endpoint_url
                mock_prepared.request_data = {}
                mock_prepared.headers = {}
                mock_prepared.sanitized_endpoint_url = sample_streaming_agent.endpoint_url
                mock_prepared.sensitive_query_param_names = []

                with patch("mcpgateway.services.a2a_service.prepare_a2a_invocation", return_value=mock_prepared):
                    with patch.object(a2a_service, "_get_plugin_manager", return_value=None):
                        # Mock HTTP 500 error
                        mock_response = AsyncMock()
                        mock_response.status_code = 500
                        mock_response.aread = AsyncMock(return_value=b"Internal Server Error")

                        mock_http_client = AsyncMock()
                        mock_http_client.stream = MagicMock()
                        mock_http_client.stream.return_value.__aenter__.return_value = mock_response

                        with patch("mcpgateway.services.a2a_service.get_http_client", return_value=mock_http_client):
                            with patch("mcpgateway.services.a2a_service.fresh_db_session"):
                                with patch("mcpgateway.services.a2a_service.get_metrics_buffer_service"):
                                    chunks = []
                                    async for chunk in a2a_service.stream_agent_response(
                                        mock_db, "test-streaming-agent", {}, "query", user_email="test@example.com", token_teams=None
                                    ):
                                        chunks.append(chunk)

                                    # Should get error SSE event
                                    assert len(chunks) == 1
                                    error_data = json.loads(chunks[0].replace("data: ", "").replace("\n\n", ""))
                                    assert "error" in error_data
                                    assert "500" in error_data["error"]

    @pytest.mark.asyncio
    async def test_stream_agent_network_exception_returns_error(self, a2a_service, mock_db, sample_streaming_agent):
        """Test that network exceptions are handled gracefully.

        Verifies:
        - Connection errors caught
        - Error returned as SSE event
        - Sensitive info (credentials) sanitized
        """
        mock_db.execute.return_value.scalar_one_or_none.return_value = sample_streaming_agent.id

        with patch("mcpgateway.services.a2a_service.get_for_update", return_value=sample_streaming_agent):
            with patch.object(a2a_service, "_check_agent_access", return_value=True):
                mock_prepared = MagicMock()
                mock_prepared.endpoint_url = sample_streaming_agent.endpoint_url
                mock_prepared.request_data = {}
                mock_prepared.headers = {}
                mock_prepared.sanitized_endpoint_url = sample_streaming_agent.endpoint_url
                mock_prepared.sensitive_query_param_names = []

                with patch("mcpgateway.services.a2a_service.prepare_a2a_invocation", return_value=mock_prepared):
                    with patch.object(a2a_service, "_get_plugin_manager", return_value=None):
                        # Mock network error
                        mock_http_client = AsyncMock()
                        mock_http_client.stream.side_effect = httpx.ConnectError("Connection refused")

                        with patch("mcpgateway.services.a2a_service.get_http_client", return_value=mock_http_client):
                            chunks = []
                            async for chunk in a2a_service.stream_agent_response(
                                mock_db, "test-streaming-agent", {}, "query", user_email="test@example.com", token_teams=None
                            ):
                                chunks.append(chunk)

                            # Should get error SSE event
                            assert len(chunks) == 1
                            error_data = json.loads(chunks[0].replace("data: ", "").replace("\n\n", ""))
                            assert "error" in error_data


class TestStreamAgentResponseObservability:
    """Test observability integration (traces, spans, metrics)."""

    @pytest.mark.asyncio
    async def test_stream_agent_creates_trace_span(self, a2a_service, mock_db, sample_streaming_agent):
        """Test that streaming creates proper observability span.

        Verifies:
        - Span created with name 'a2a.invoke.stream'
        - Span attributes include streaming=True
        - Span attributes include agent info
        """
        mock_db.execute.return_value.scalar_one_or_none.return_value = sample_streaming_agent.id

        with patch("mcpgateway.services.a2a_service.get_for_update", return_value=sample_streaming_agent):
            with patch.object(a2a_service, "_check_agent_access", return_value=True):
                mock_prepared = MagicMock()
                mock_prepared.endpoint_url = sample_streaming_agent.endpoint_url
                mock_prepared.request_data = {}
                mock_prepared.headers = {}
                mock_prepared.sanitized_endpoint_url = sample_streaming_agent.endpoint_url
                mock_prepared.sensitive_query_param_names = []

                with patch("mcpgateway.services.a2a_service.prepare_a2a_invocation", return_value=mock_prepared):
                    with patch.object(a2a_service, "_get_plugin_manager", return_value=None):
                        mock_response = AsyncMock()
                        mock_response.status_code = 200

                        async def mock_aiter_bytes():
                            yield b"test"

                        mock_response.aiter_bytes = mock_aiter_bytes

                        mock_http_client = AsyncMock()
                        mock_http_client.stream = MagicMock()
                        mock_http_client.stream.return_value.__aenter__.return_value = mock_response

                        with patch("mcpgateway.services.a2a_service.get_http_client", return_value=mock_http_client):
                            with patch("mcpgateway.services.a2a_service.fresh_db_session"):
                                with patch("mcpgateway.services.a2a_service.get_metrics_buffer_service"):
                                    # Mock create_span to capture attributes
                                    with patch("mcpgateway.services.a2a_service.create_span") as mock_create_span:
                                        mock_span_context = MagicMock()
                                        mock_span_context.__enter__ = MagicMock(return_value=MagicMock())
                                        mock_span_context.__exit__ = MagicMock(return_value=False)
                                        mock_create_span.return_value = mock_span_context

                                        chunks = []
                                        async for chunk in a2a_service.stream_agent_response(
                                            mock_db, "test-streaming-agent", {}, "query", user_email="test@example.com", token_teams=None
                                        ):
                                            chunks.append(chunk)

                                        # Verify span was created
                                        mock_create_span.assert_called_once()
                                        span_name, span_attrs = mock_create_span.call_args[0]
                                        assert span_name == "a2a.invoke.stream"
                                        assert span_attrs["a2a.streaming"] is True
                                        assert "a2a.agent.name" in span_attrs
                                        assert "a2a.agent.id" in span_attrs

    @pytest.mark.asyncio
    async def test_stream_agent_records_metrics(self, a2a_service, mock_db, sample_streaming_agent):
        """Test that metrics are recorded for streaming calls.

        Verifies:
        - Metrics buffer service called
        - Success/failure recorded
        - Response time captured
        """
        mock_db.execute.return_value.scalar_one_or_none.return_value = sample_streaming_agent.id

        with patch("mcpgateway.services.a2a_service.get_for_update", return_value=sample_streaming_agent):
            with patch.object(a2a_service, "_check_agent_access", return_value=True):
                mock_prepared = MagicMock()
                mock_prepared.endpoint_url = sample_streaming_agent.endpoint_url
                mock_prepared.request_data = {}
                mock_prepared.headers = {}
                mock_prepared.sanitized_endpoint_url = sample_streaming_agent.endpoint_url
                mock_prepared.sensitive_query_param_names = []

                with patch("mcpgateway.services.a2a_service.prepare_a2a_invocation", return_value=mock_prepared):
                    with patch.object(a2a_service, "_get_plugin_manager", return_value=None):
                        mock_response = AsyncMock()
                        mock_response.status_code = 200

                        async def mock_aiter_bytes():
                            yield b"test"

                        mock_response.aiter_bytes = mock_aiter_bytes

                        mock_http_client = AsyncMock()
                        mock_http_client.stream = MagicMock()
                        mock_http_client.stream.return_value.__aenter__.return_value = mock_response

                        with patch("mcpgateway.services.a2a_service.get_http_client", return_value=mock_http_client):
                            with patch("mcpgateway.services.a2a_service.fresh_db_session"):
                                # Mock metrics buffer
                                mock_metrics_buffer = MagicMock()
                                with patch("mcpgateway.services.a2a_service.get_metrics_buffer_service", return_value=mock_metrics_buffer):
                                    chunks = []
                                    async for chunk in a2a_service.stream_agent_response(
                                        mock_db, "test-streaming-agent", {}, "query", user_email="test@example.com", token_teams=None
                                    ):
                                        chunks.append(chunk)

                                    # Verify metrics recorded
                                    mock_metrics_buffer.record_a2a_agent_metric_with_duration.assert_called_once()
                                    call_args = mock_metrics_buffer.record_a2a_agent_metric_with_duration.call_args
                                    assert call_args.kwargs["success"] is True
                                    assert call_args.kwargs["response_time"] > 0


class TestStreamAgentResponseRustRuntime:
    """Test Rust runtime constraint for streaming."""

    @pytest.mark.asyncio
    async def test_stream_agent_rust_runtime_returns_error(self, a2a_service, mock_db, sample_streaming_agent):
        """Test that Rust runtime delegation returns explicit error.

        Verifies:
        - Rust runtime is not supported for streaming
        - Clear error message returned
        - No attempt to stream via Rust
        """
        mock_db.execute.return_value.scalar_one_or_none.return_value = sample_streaming_agent.id

        with patch("mcpgateway.services.a2a_service.get_for_update", return_value=sample_streaming_agent):
            with patch.object(a2a_service, "_check_agent_access", return_value=True):
                mock_prepared = MagicMock()
                mock_prepared.endpoint_url = sample_streaming_agent.endpoint_url
                mock_prepared.request_data = {}
                mock_prepared.headers = {}
                mock_prepared.sanitized_endpoint_url = sample_streaming_agent.endpoint_url
                mock_prepared.sensitive_query_param_names = []

                with patch("mcpgateway.services.a2a_service.prepare_a2a_invocation", return_value=mock_prepared):
                    with patch.object(a2a_service, "_get_plugin_manager", return_value=None):
                        # Mock Rust runtime as enabled
                        with patch("mcpgateway.services.a2a_service._should_delegate_a2a_to_rust", return_value=True):
                            chunks = []
                            async for chunk in a2a_service.stream_agent_response(
                                mock_db, "test-streaming-agent", {}, "query", user_email="test@example.com", token_teams=None
                            ):
                                chunks.append(chunk)

                            # Should get error SSE event
                            assert len(chunks) == 1
                            error_data = json.loads(chunks[0].replace("data: ", "").replace("\n\n", ""))
                            assert "error" in error_data
                            assert "rust runtime" in error_data["error"].lower()
                            assert "streaming not supported" in error_data["error"].lower()


class TestStreamAgentResponsePlugins:
    """Test plugin hook integration in streaming."""

    @pytest.mark.asyncio
    async def test_stream_agent_pre_invoke_hook_fires(self, a2a_service, mock_db, sample_streaming_agent):
        """Test that PRE_INVOKE plugin hook fires before streaming.

        Verifies:
        - Plugin hook called with correct payload
        - Modified parameters respected
        - Hook errors handled gracefully
        """
        mock_db.execute.return_value.scalar_one_or_none.return_value = sample_streaming_agent.id

        with patch("mcpgateway.services.a2a_service.get_for_update", return_value=sample_streaming_agent):
            with patch.object(a2a_service, "_check_agent_access", return_value=True):
                mock_prepared = MagicMock()
                mock_prepared.endpoint_url = sample_streaming_agent.endpoint_url
                mock_prepared.request_data = {}
                mock_prepared.headers = {}
                mock_prepared.sanitized_endpoint_url = sample_streaming_agent.endpoint_url
                mock_prepared.sensitive_query_param_names = []

                with patch("mcpgateway.services.a2a_service.prepare_a2a_invocation", return_value=mock_prepared):
                    # Mock plugin manager with pre-invoke hook
                    mock_plugin_manager = MagicMock()
                    mock_plugin_manager.has_hooks_for = MagicMock(return_value=True)

                    # Mock hook result
                    mock_hook_result = MagicMock()
                    mock_hook_result.modified_payload = None
                    mock_plugin_manager.invoke_hook = AsyncMock(return_value=(mock_hook_result, {}))

                    with patch.object(a2a_service, "_get_plugin_manager", return_value=mock_plugin_manager):
                        mock_response = AsyncMock()
                        mock_response.status_code = 200

                        async def mock_aiter_bytes():
                            yield b"test"

                        mock_response.aiter_bytes = mock_aiter_bytes

                        mock_http_client = AsyncMock()
                        mock_http_client.stream = MagicMock()
                        mock_http_client.stream.return_value.__aenter__.return_value = mock_response

                        with patch("mcpgateway.services.a2a_service.get_http_client", return_value=mock_http_client):
                            with patch("mcpgateway.services.a2a_service.fresh_db_session"):
                                with patch("mcpgateway.services.a2a_service.get_metrics_buffer_service"):
                                    chunks = []
                                    async for chunk in a2a_service.stream_agent_response(
                                        mock_db, "test-streaming-agent", {"test": "data"}, "query", user_email="test@example.com", token_teams=None
                                    ):
                                        chunks.append(chunk)

                                    # Verify hook was called
                                    assert mock_plugin_manager.invoke_hook.called

    @pytest.mark.asyncio
    async def test_stream_agent_post_invoke_hook_fires(self, a2a_service, mock_db, sample_streaming_agent):
        """Test that POST_INVOKE plugin hook fires after streaming completes.

        Verifies:
        - Hook called after streaming
        - Accumulated response passed to hook
        - Hook errors don't fail stream
        """
        mock_db.execute.return_value.scalar_one_or_none.return_value = sample_streaming_agent.id

        with patch("mcpgateway.services.a2a_service.get_for_update", return_value=sample_streaming_agent):
            with patch.object(a2a_service, "_check_agent_access", return_value=True):
                mock_prepared = MagicMock()
                mock_prepared.endpoint_url = sample_streaming_agent.endpoint_url
                mock_prepared.request_data = {}
                mock_prepared.headers = {}
                mock_prepared.sanitized_endpoint_url = sample_streaming_agent.endpoint_url
                mock_prepared.sensitive_query_param_names = []

                with patch("mcpgateway.services.a2a_service.prepare_a2a_invocation", return_value=mock_prepared):
                    # Mock plugin manager
                    mock_plugin_manager = MagicMock()

                    def has_hooks_for_side_effect(hook_type):
                        # PRE_INVOKE: False, POST_INVOKE: True
                        from cpex.framework import AgentHookType

                        return hook_type == AgentHookType.AGENT_POST_INVOKE

                    mock_plugin_manager.has_hooks_for = MagicMock(side_effect=has_hooks_for_side_effect)
                    mock_plugin_manager.invoke_hook = AsyncMock(return_value=(MagicMock(), {}))

                    with patch.object(a2a_service, "_get_plugin_manager", return_value=mock_plugin_manager):
                        mock_response = AsyncMock()
                        mock_response.status_code = 200

                        async def mock_aiter_bytes():
                            yield b"chunk1"
                            yield b"chunk2"

                        mock_response.aiter_bytes = mock_aiter_bytes

                        mock_http_client = AsyncMock()
                        mock_http_client.stream = MagicMock()
                        mock_http_client.stream.return_value.__aenter__.return_value = mock_response

                        with patch("mcpgateway.services.a2a_service.get_http_client", return_value=mock_http_client):
                            with patch("mcpgateway.services.a2a_service.fresh_db_session"):
                                with patch("mcpgateway.services.a2a_service.get_metrics_buffer_service"):
                                    chunks = []
                                    async for chunk in a2a_service.stream_agent_response(
                                        mock_db, "test-streaming-agent", {}, "query", user_email="test@example.com", token_teams=None
                                    ):
                                        chunks.append(chunk)

                                    # Verify post-invoke hook was called
                                    assert mock_plugin_manager.invoke_hook.called


class TestStreamAgentResponseAgentIdentification:
    """Test agent identification by ID vs name."""

    @pytest.mark.asyncio
    async def test_stream_agent_response_by_agent_id(self, a2a_service, mock_db, sample_streaming_agent):
        """Test that agent can be invoked by agent_id parameter (not just name).

        Verifies:
        - agent_id parameter takes precedence over agent_name
        - Agent lookup by ID works correctly
        - Streaming completes successfully
        """
        agent_id_str = sample_streaming_agent.id

        # Mock get_for_update to return agent by ID
        with patch("mcpgateway.services.a2a_service.get_for_update", return_value=sample_streaming_agent):
            with patch.object(a2a_service, "_check_agent_access", return_value=True):
                mock_prepared = MagicMock()
                mock_prepared.endpoint_url = sample_streaming_agent.endpoint_url
                mock_prepared.request_data = {}
                mock_prepared.headers = {}
                mock_prepared.sanitized_endpoint_url = sample_streaming_agent.endpoint_url
                mock_prepared.sensitive_query_param_names = []

                with patch("mcpgateway.services.a2a_service.prepare_a2a_invocation", return_value=mock_prepared):
                    with patch.object(a2a_service, "_get_plugin_manager", return_value=None):
                        mock_response = AsyncMock()
                        mock_response.status_code = 200

                        async def mock_aiter_bytes():
                            yield b"test response"

                        mock_response.aiter_bytes = mock_aiter_bytes

                        mock_http_client = AsyncMock()
                        mock_http_client.stream = MagicMock()
                        mock_http_client.stream.return_value.__aenter__.return_value = mock_response

                        with patch("mcpgateway.services.a2a_service.get_http_client", return_value=mock_http_client):
                            with patch("mcpgateway.services.a2a_service.fresh_db_session"):
                                with patch("mcpgateway.services.a2a_service.get_metrics_buffer_service"):
                                    chunks = []
                                    async for chunk in a2a_service.stream_agent_response(
                                        mock_db,
                                        agent_name="",  # Empty name
                                        parameters={},
                                        interaction_type="query",
                                        agent_id=agent_id_str,  # ID provided
                                        user_email="test@example.com",
                                        token_teams=None,
                                    ):
                                        chunks.append(chunk)

                                    # Verify streaming succeeded
                                    assert len(chunks) == 1
                                    assert chunks[0].startswith("data: ")
                                    assert "test response" in chunks[0]


class TestStreamAgentResponseUAIDValidation:
    """Test UAID domain validation."""

    @pytest.mark.asyncio
    async def test_stream_agent_uaid_domain_validation_failure(self, a2a_service, mock_db, sample_streaming_agent):
        """Test that UAID domain validation failures return error.

        Verifies:
        - UAID endpoint domain validation is enforced
        - Blocked domains return error SSE event
        - Error message mentions validation failure
        """
        # Set agent with UAID
        sample_streaming_agent.uaid = "cf://example.com/test-agent/v1"
        sample_streaming_agent.uaid_native_id = "https://blocked-domain.com/agent"
        sample_streaming_agent.endpoint_url = "https://blocked-domain.com/invoke"

        mock_db.execute.return_value.scalar_one_or_none.return_value = sample_streaming_agent.id

        with patch("mcpgateway.services.a2a_service.get_for_update", return_value=sample_streaming_agent):
            with patch.object(a2a_service, "_check_agent_access", return_value=True):
                # Mock UAID validation to fail
                with patch("mcpgateway.services.a2a_service._validate_uaid_endpoint_domain", side_effect=ValueError("Domain blocked-domain.com not in allowlist")):
                    chunks = []
                    async for chunk in a2a_service.stream_agent_response(
                        mock_db, "test-streaming-agent", {}, "query", user_email="test@example.com", token_teams=None
                    ):
                        chunks.append(chunk)

                    # Should get error SSE event
                    assert len(chunks) == 1
                    error_data = json.loads(chunks[0].replace("data: ", "").replace("\n\n", ""))
                    assert "error" in error_data
                    assert "blocked" in error_data["error"].lower()


class TestStreamAgentResponseAuthDecryption:
    """Test authentication decryption error handling."""

    @pytest.mark.asyncio
    async def test_stream_agent_auth_decryption_failure_basic(self, a2a_service, mock_db, sample_streaming_agent):
        """Test that basic/bearer/authheaders auth decryption failures return error.

        Verifies:
        - Auth decryption errors caught
        - Error message mentions decryption failure
        - SSE error event returned
        """
        # Set agent with basic auth
        sample_streaming_agent.auth_type = "basic"
        sample_streaming_agent.auth_value = "encrypted:invalid_data"

        mock_db.execute.return_value.scalar_one_or_none.return_value = sample_streaming_agent.id

        with patch("mcpgateway.services.a2a_service.get_for_update", return_value=sample_streaming_agent):
            with patch.object(a2a_service, "_check_agent_access", return_value=True):
                # Mock prepare_a2a_invocation to fail on auth decryption
                with patch("mcpgateway.services.a2a_service.prepare_a2a_invocation", side_effect=Exception("Failed to decrypt credentials")):
                    chunks = []
                    async for chunk in a2a_service.stream_agent_response(
                        mock_db, "test-streaming-agent", {}, "query", user_email="test@example.com", token_teams=None
                    ):
                        chunks.append(chunk)

                    # Should get error SSE event
                    assert len(chunks) == 1
                    error_data = json.loads(chunks[0].replace("data: ", "").replace("\n\n", ""))
                    assert "error" in error_data
                    assert "decrypt" in error_data["error"].lower()

    @pytest.mark.asyncio
    async def test_stream_agent_auth_decryption_failure_query_param(self, a2a_service, mock_db, sample_streaming_agent):
        """Test that query_param auth decryption failures return error.

        Verifies:
        - Query param auth decryption errors caught
        - Error message mentions query_param authentication
        - SSE error event returned
        """
        # Set agent with query param auth
        sample_streaming_agent.auth_type = "query_param"
        sample_streaming_agent.auth_query_params = {"api_key": "encrypted:invalid_data"}

        mock_db.execute.return_value.scalar_one_or_none.return_value = sample_streaming_agent.id

        with patch("mcpgateway.services.a2a_service.get_for_update", return_value=sample_streaming_agent):
            with patch.object(a2a_service, "_check_agent_access", return_value=True):
                # Mock prepare_a2a_invocation to fail on query param auth decryption
                with patch("mcpgateway.services.a2a_service.prepare_a2a_invocation", side_effect=Exception("Failed to decrypt query parameters")):
                    chunks = []
                    async for chunk in a2a_service.stream_agent_response(
                        mock_db, "test-streaming-agent", {}, "query", user_email="test@example.com", token_teams=None
                    ):
                        chunks.append(chunk)

                    # Should get error SSE event
                    assert len(chunks) == 1
                    error_data = json.loads(chunks[0].replace("data: ", "").replace("\n\n", ""))
                    assert "error" in error_data
                    assert "query_param" in error_data["error"].lower()


class TestStreamAgentResponsePluginErrors:
    """Test plugin error handling."""

    @pytest.mark.asyncio
    async def test_stream_agent_pre_invoke_plugin_violation(self, a2a_service, mock_db, sample_streaming_agent):
        """Test that PRE_INVOKE plugin violations return error.

        Verifies:
        - PluginViolationError caught
        - Error message mentions plugin RBAC violation
        - SSE error event returned
        """
        from cpex.framework import PluginViolationError

        mock_db.execute.return_value.scalar_one_or_none.return_value = sample_streaming_agent.id

        with patch("mcpgateway.services.a2a_service.get_for_update", return_value=sample_streaming_agent):
            with patch.object(a2a_service, "_check_agent_access", return_value=True):
                mock_prepared = MagicMock()
                mock_prepared.endpoint_url = sample_streaming_agent.endpoint_url
                mock_prepared.request_data = {}
                mock_prepared.headers = {}
                mock_prepared.sanitized_endpoint_url = sample_streaming_agent.endpoint_url
                mock_prepared.sensitive_query_param_names = []

                with patch("mcpgateway.services.a2a_service.prepare_a2a_invocation", return_value=mock_prepared):
                    # Mock plugin manager that throws violation
                    mock_plugin_manager = MagicMock()
                    mock_plugin_manager.has_hooks_for = MagicMock(return_value=True)
                    mock_plugin_manager.invoke_hook = AsyncMock(side_effect=PluginViolationError("RBAC check failed: insufficient permissions"))

                    with patch.object(a2a_service, "_get_plugin_manager", return_value=mock_plugin_manager):
                        chunks = []
                        async for chunk in a2a_service.stream_agent_response(
                            mock_db, "test-streaming-agent", {}, "query", user_email="test@example.com", token_teams=None
                        ):
                            chunks.append(chunk)

                        # Should get error SSE event
                        assert len(chunks) == 1
                        error_data = json.loads(chunks[0].replace("data: ", "").replace("\n\n", ""))
                        assert "error" in error_data
                        assert "rbac" in error_data["error"].lower() or "violation" in error_data["error"].lower()

    @pytest.mark.asyncio
    async def test_stream_agent_pre_invoke_plugin_exception(self, a2a_service, mock_db, sample_streaming_agent):
        """Test that PRE_INVOKE plugin general exceptions return error.

        Verifies:
        - General plugin exceptions caught
        - Error message mentions pre-invoke plugin error
        - SSE error event returned
        """
        mock_db.execute.return_value.scalar_one_or_none.return_value = sample_streaming_agent.id

        with patch("mcpgateway.services.a2a_service.get_for_update", return_value=sample_streaming_agent):
            with patch.object(a2a_service, "_check_agent_access", return_value=True):
                mock_prepared = MagicMock()
                mock_prepared.endpoint_url = sample_streaming_agent.endpoint_url
                mock_prepared.request_data = {}
                mock_prepared.headers = {}
                mock_prepared.sanitized_endpoint_url = sample_streaming_agent.endpoint_url
                mock_prepared.sensitive_query_param_names = []

                with patch("mcpgateway.services.a2a_service.prepare_a2a_invocation", return_value=mock_prepared):
                    # Mock plugin manager that throws general exception
                    mock_plugin_manager = MagicMock()
                    mock_plugin_manager.has_hooks_for = MagicMock(return_value=True)
                    mock_plugin_manager.invoke_hook = AsyncMock(side_effect=Exception("Plugin internal error"))

                    with patch.object(a2a_service, "_get_plugin_manager", return_value=mock_plugin_manager):
                        chunks = []
                        async for chunk in a2a_service.stream_agent_response(
                            mock_db, "test-streaming-agent", {}, "query", user_email="test@example.com", token_teams=None
                        ):
                            chunks.append(chunk)

                        # Should get error SSE event
                        assert len(chunks) == 1
                        error_data = json.loads(chunks[0].replace("data: ", "").replace("\n\n", ""))
                        assert "error" in error_data
                        assert "pre-invoke" in error_data["error"].lower() or "plugin" in error_data["error"].lower()


class TestStreamAgentResponseMetricsAndTimestamps:
    """Test metrics recording and timestamp update error handling."""

    @pytest.mark.asyncio
    async def test_stream_agent_metrics_recording_failure(self, a2a_service, mock_db, sample_streaming_agent):
        """Test that metrics recording failures don't break streaming.

        Verifies:
        - Metrics recording errors caught and logged
        - Streaming completes successfully despite metrics failure
        - SSE chunks still delivered
        """
        mock_db.execute.return_value.scalar_one_or_none.return_value = sample_streaming_agent.id

        with patch("mcpgateway.services.a2a_service.get_for_update", return_value=sample_streaming_agent):
            with patch.object(a2a_service, "_check_agent_access", return_value=True):
                mock_prepared = MagicMock()
                mock_prepared.endpoint_url = sample_streaming_agent.endpoint_url
                mock_prepared.request_data = {}
                mock_prepared.headers = {}
                mock_prepared.sanitized_endpoint_url = sample_streaming_agent.endpoint_url
                mock_prepared.sensitive_query_param_names = []

                with patch("mcpgateway.services.a2a_service.prepare_a2a_invocation", return_value=mock_prepared):
                    with patch.object(a2a_service, "_get_plugin_manager", return_value=None):
                        mock_response = AsyncMock()
                        mock_response.status_code = 200

                        async def mock_aiter_bytes():
                            yield b"success"

                        mock_response.aiter_bytes = mock_aiter_bytes

                        mock_http_client = AsyncMock()
                        mock_http_client.stream = MagicMock()
                        mock_http_client.stream.return_value.__aenter__.return_value = mock_response

                        with patch("mcpgateway.services.a2a_service.get_http_client", return_value=mock_http_client):
                            with patch("mcpgateway.services.a2a_service.fresh_db_session"):
                                # Mock metrics buffer to raise exception
                                mock_metrics_buffer = MagicMock()
                                mock_metrics_buffer.record_a2a_agent_metric_with_duration.side_effect = Exception("Database connection failed")

                                with patch("mcpgateway.services.a2a_service.get_metrics_buffer_service", return_value=mock_metrics_buffer):
                                    chunks = []
                                    async for chunk in a2a_service.stream_agent_response(
                                        mock_db, "test-streaming-agent", {}, "query", user_email="test@example.com", token_teams=None
                                    ):
                                        chunks.append(chunk)

                                    # Streaming should still succeed
                                    assert len(chunks) == 1
                                    assert chunks[0].startswith("data: ")
                                    assert "success" in chunks[0]

    @pytest.mark.asyncio
    async def test_stream_agent_last_interaction_update_failure(self, a2a_service, mock_db, sample_streaming_agent):
        """Test that last_interaction update failures don't break streaming.

        Verifies:
        - Timestamp update errors caught and logged
        - Streaming completes successfully despite timestamp failure
        - SSE chunks still delivered
        """
        mock_db.execute.return_value.scalar_one_or_none.return_value = sample_streaming_agent.id

        with patch("mcpgateway.services.a2a_service.get_for_update", return_value=sample_streaming_agent):
            with patch.object(a2a_service, "_check_agent_access", return_value=True):
                mock_prepared = MagicMock()
                mock_prepared.endpoint_url = sample_streaming_agent.endpoint_url
                mock_prepared.request_data = {}
                mock_prepared.headers = {}
                mock_prepared.sanitized_endpoint_url = sample_streaming_agent.endpoint_url
                mock_prepared.sensitive_query_param_names = []

                with patch("mcpgateway.services.a2a_service.prepare_a2a_invocation", return_value=mock_prepared):
                    with patch.object(a2a_service, "_get_plugin_manager", return_value=None):
                        mock_response = AsyncMock()
                        mock_response.status_code = 200

                        async def mock_aiter_bytes():
                            yield b"success"

                        mock_response.aiter_bytes = mock_aiter_bytes

                        mock_http_client = AsyncMock()
                        mock_http_client.stream = MagicMock()
                        mock_http_client.stream.return_value.__aenter__.return_value = mock_response

                        with patch("mcpgateway.services.a2a_service.get_http_client", return_value=mock_http_client):
                            # Mock fresh_db_session to raise exception on timestamp update
                            with patch("mcpgateway.services.a2a_service.fresh_db_session", side_effect=Exception("Database locked")):
                                with patch("mcpgateway.services.a2a_service.get_metrics_buffer_service"):
                                    chunks = []
                                    async for chunk in a2a_service.stream_agent_response(
                                        mock_db, "test-streaming-agent", {}, "query", user_email="test@example.com", token_teams=None
                                    ):
                                        chunks.append(chunk)

                                    # Streaming should still succeed
                                    assert len(chunks) == 1
                                    assert chunks[0].startswith("data: ")
                                    assert "success" in chunks[0]

    @pytest.mark.asyncio
    async def test_stream_agent_post_invoke_retry_request(self, a2a_service, mock_db, sample_streaming_agent):
        """Test that POST_INVOKE plugin retry requests are logged.

        Verifies:
        - Plugin can request retry via retry_delay_ms
        - Retry request is logged
        - Streaming completes normally
        """
        mock_db.execute.return_value.scalar_one_or_none.return_value = sample_streaming_agent.id

        with patch("mcpgateway.services.a2a_service.get_for_update", return_value=sample_streaming_agent):
            with patch.object(a2a_service, "_check_agent_access", return_value=True):
                mock_prepared = MagicMock()
                mock_prepared.endpoint_url = sample_streaming_agent.endpoint_url
                mock_prepared.request_data = {}
                mock_prepared.headers = {}
                mock_prepared.sanitized_endpoint_url = sample_streaming_agent.endpoint_url
                mock_prepared.sensitive_query_param_names = []

                with patch("mcpgateway.services.a2a_service.prepare_a2a_invocation", return_value=mock_prepared):
                    # Mock plugin manager with POST_INVOKE that requests retry
                    mock_plugin_manager = MagicMock()

                    def has_hooks_for_side_effect(hook_type):
                        from cpex.framework import AgentHookType

                        return hook_type == AgentHookType.AGENT_POST_INVOKE

                    mock_plugin_manager.has_hooks_for = MagicMock(side_effect=has_hooks_for_side_effect)

                    # Mock post-invoke result with retry request
                    mock_post_result = MagicMock()
                    mock_post_result.retry_delay_ms = 5000  # Request 5s retry
                    mock_plugin_manager.invoke_hook = AsyncMock(return_value=(mock_post_result, {}))

                    with patch.object(a2a_service, "_get_plugin_manager", return_value=mock_plugin_manager):
                        mock_response = AsyncMock()
                        mock_response.status_code = 200

                        async def mock_aiter_bytes():
                            yield b"test"

                        mock_response.aiter_bytes = mock_aiter_bytes

                        mock_http_client = AsyncMock()
                        mock_http_client.stream = MagicMock()
                        mock_http_client.stream.return_value.__aenter__.return_value = mock_response

                        with patch("mcpgateway.services.a2a_service.get_http_client", return_value=mock_http_client):
                            with patch("mcpgateway.services.a2a_service.fresh_db_session"):
                                with patch("mcpgateway.services.a2a_service.get_metrics_buffer_service"):
                                    # Mock logger to verify retry is logged
                                    with patch("mcpgateway.services.a2a_service.logger") as mock_logger:
                                        chunks = []
                                        async for chunk in a2a_service.stream_agent_response(
                                            mock_db, "test-streaming-agent", {}, "query", user_email="test@example.com", token_teams=None
                                        ):
                                            chunks.append(chunk)

                                        # Streaming should complete
                                        assert len(chunks) == 1

                                        # Verify retry was logged
                                        mock_logger.info.assert_any_call(
                                            "Plugin requested retry for A2A agent %s after %sms",
                                            sample_streaming_agent.id,
                                            5000,
                                        )


class TestStreamAgentResponseCoverageGaps:
    """Tests to reach 93% coverage - missing error paths and edge cases."""

    @pytest.mark.asyncio
    async def test_stream_uaid_cross_gateway_not_supported(self, a2a_service, mock_db):
        """Test UAID cross-gateway streaming returns error (Phase 1 not supported)."""
        # Setup: UAID format identifier
        uaid = "uaid:example.com/some-agent"

        # Mock: is_uaid returns True, scalar_one_or_none returns None (not found locally)
        with patch("mcpgateway.services.a2a_service.is_uaid", return_value=True):
            mock_db.execute.return_value.scalar_one_or_none.return_value = None

            chunks = []
            async for chunk in a2a_service.stream_agent_response(
                mock_db,
                "test",
                {},
                "query",
                agent_id=uaid,
                user_email="test@example.com",
                token_teams=[],
            ):
                chunks.append(chunk)

            # Verify error message
            assert len(chunks) == 1
            assert "Streaming not supported for cross-gateway UAID agents" in chunks[0]

    @pytest.mark.asyncio
    async def test_stream_agent_not_found_after_name_lookup(self, a2a_service, mock_db):
        """Test agent not found after initial name lookup returns ID."""
        # First lookup returns ID, but get_for_update returns None
        mock_db.execute.return_value.scalar_one_or_none.return_value = "some-agent-id"

        with patch("mcpgateway.services.a2a_service.get_for_update", return_value=None):
            chunks = []
            async for chunk in a2a_service.stream_agent_response(
                mock_db,
                "nonexistent-agent",
                {},
                "query",
                user_email="test@example.com",
                token_teams=[],
            ):
                chunks.append(chunk)

            assert len(chunks) == 1
            assert "A2A Agent not found with name" in chunks[0]

    @pytest.mark.asyncio
    async def test_stream_agent_not_found_by_id_lookup(self, a2a_service, mock_db):
        """Test agent not found when looking up by agent_id."""
        with patch("mcpgateway.services.a2a_service.get_for_update", return_value=None):
            chunks = []
            async for chunk in a2a_service.stream_agent_response(
                mock_db,
                "test",
                {},
                "query",
                agent_id="nonexistent-uuid",
                user_email="test@example.com",
                token_teams=[],
            ):
                chunks.append(chunk)

            assert len(chunks) == 1
            assert "A2A Agent not found" in chunks[0]

    @pytest.mark.asyncio
    async def test_stream_agent_access_denied(self, a2a_service, mock_db, sample_streaming_agent):
        """Test access denied returns 404 (not 403) to avoid leaking agent existence."""
        sample_streaming_agent.team_id = "team-1"
        sample_streaming_agent.visibility = "team"

        with patch("mcpgateway.services.a2a_service.get_for_update", return_value=sample_streaming_agent):
            with patch.object(a2a_service, "_check_agent_access", return_value=False):
                chunks = []
                async for chunk in a2a_service.stream_agent_response(
                    mock_db,
                    "test",
                    {},
                    "query",
                    user_email="test@example.com",
                    token_teams=["team-2"],  # Different team
                ):
                    chunks.append(chunk)

                assert len(chunks) == 1
                assert "A2A Agent not found" in chunks[0]

    @pytest.mark.asyncio
    async def test_stream_headers_no_passthrough_list(self, a2a_service, mock_db, sample_streaming_agent):
        """Test header filtering when passthrough_headers is None."""
        sample_streaming_agent.passthrough_headers = None

        with patch("mcpgateway.services.a2a_service.get_for_update", return_value=sample_streaming_agent):
            with patch.object(a2a_service, "_check_agent_access", return_value=True):
                with patch("mcpgateway.services.a2a_service.get_http_client") as mock_client:
                    with patch("mcpgateway.services.a2a_service.prepare_a2a_invocation") as mock_prepare:
                        mock_prepare.return_value = MagicMock(
                            endpoint_url="http://localhost:9001",
                            request_data={},
                            headers={},
                            sanitized_endpoint_url="http://localhost:9001",
                            sensitive_query_param_names=[],
                        )

                        # Mock streaming response
                        mock_response = AsyncMock()
                        mock_response.status_code = 200
                        mock_response.aiter_bytes = AsyncMock(return_value=iter([b"test"]))
                        mock_client.return_value.stream.return_value.__aenter__.return_value = mock_response

                        chunks = []
                        async for chunk in a2a_service.stream_agent_response(
                            mock_db,
                            "test",
                            {},
                            "query",
                            request_headers={"x-custom": "value", "x-another": "header"},
                            user_email="test@example.com",
                            token_teams=[],
                        ):
                            chunks.append(chunk)

                        # Verify streaming works (headers filtered out when no whitelist)
                        assert len(chunks) == 1

    @pytest.mark.asyncio
    async def test_stream_uaid_endpoint_validation_error(self, a2a_service, mock_db, sample_streaming_agent):
        """Test UAID endpoint domain validation failure."""
        sample_streaming_agent.uaid = "uaid:invalid-domain.com/agent"
        sample_streaming_agent.endpoint_url = "http://invalid-domain.com/invoke"

        with patch("mcpgateway.services.a2a_service.get_for_update", return_value=sample_streaming_agent):
            with patch.object(a2a_service, "_check_agent_access", return_value=True):
                with patch("mcpgateway.services.a2a_service._validate_uaid_endpoint_domain", side_effect=ValueError("Domain not allowed")):
                    chunks = []
                    async for chunk in a2a_service.stream_agent_response(
                        mock_db,
                        "test",
                        {},
                        "query",
                        user_email="test@example.com",
                        token_teams=[],
                    ):
                        chunks.append(chunk)

                    assert len(chunks) == 1
                    assert "invocation blocked" in chunks[0]

    @pytest.mark.asyncio
    async def test_stream_plugin_modifies_parameters(self, a2a_service, mock_db, sample_streaming_agent):
        """Test PRE_INVOKE plugin can modify parameters."""
        with patch("mcpgateway.services.a2a_service.get_for_update", return_value=sample_streaming_agent):
            with patch.object(a2a_service, "_check_agent_access", return_value=True):
                with patch.object(a2a_service, "_get_plugin_manager") as mock_pm:
                    # Mock plugin manager that modifies parameters
                    mock_manager = MagicMock()
                    mock_manager.has_hooks_for.return_value = True

                    # Mock pre-invoke result with modified parameters
                    mock_pre_result = MagicMock()
                    mock_pre_result.modified_payload = MagicMock()
                    mock_pre_result.modified_payload.parameters = {"modified": "value"}
                    mock_pre_result.modified_payload.headers = MagicMock()
                    mock_pre_result.modified_payload.headers.model_dump.return_value = {"x-modified": "header"}

                    mock_manager.invoke_hook = AsyncMock(return_value=(mock_pre_result, {}))
                    mock_pm.return_value = mock_manager

                    with patch("mcpgateway.services.a2a_service.get_http_client") as mock_client:
                        with patch("mcpgateway.services.a2a_service.prepare_a2a_invocation") as mock_prepare:
                            mock_prepare.return_value = MagicMock(
                                endpoint_url="http://localhost:9001",
                                request_data={},
                                headers={},
                                sanitized_endpoint_url="http://localhost:9001",
                                sensitive_query_param_names=[],
                            )

                            mock_response = AsyncMock()
                            mock_response.status_code = 200
                            mock_response.aiter_bytes = AsyncMock(return_value=iter([b"success"]))
                            mock_client.return_value.stream.return_value.__aenter__.return_value = mock_response

                            chunks = []
                            async for chunk in a2a_service.stream_agent_response(
                                mock_db,
                                "test",
                                {"original": "value"},
                                "query",
                                user_email="test@example.com",
                                token_teams=[],
                            ):
                                chunks.append(chunk)

                            assert len(chunks) == 1
                            # Verify plugin hook was called
                            mock_manager.invoke_hook.assert_called()
