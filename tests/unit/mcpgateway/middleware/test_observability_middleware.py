# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/middleware/test_observability_middleware.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for observability middleware.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from starlette.requests import Request
from starlette.responses import Response
from mcpgateway.middleware.observability_middleware import ObservabilityMiddleware
from mcpgateway.services.observability_service import ObservabilityService


@pytest.fixture
def mock_request():
    request = MagicMock(spec=Request)
    request.method = "GET"
    request.url.path = "/rpc"
    request.url.query = "param=value"
    request.url.__str__.return_value = "http://testserver/rpc?param=value"
    request.client = MagicMock()
    request.client.host = "127.0.0.1"
    request.headers = {"user-agent": "pytest", "traceparent": "00-abc123-def456-01"}
    request.state = MagicMock()
    return request


@pytest.fixture
def mock_call_next():
    async def _call_next(request):
        return Response("OK", status_code=200)

    return _call_next


@pytest.mark.asyncio
async def test_dispatch_disabled(mock_request, mock_call_next):
    middleware = ObservabilityMiddleware(app=None, enabled=False)
    response = await middleware.dispatch(mock_request, mock_call_next)
    assert response.status_code == 200
    # Since mock_request.state is a MagicMock, trace_id may exist implicitly
    # Ensure middleware did not modify it explicitly
    # Ensure middleware did not set trace_id explicitly
    assert "trace_id" not in mock_request.state.__dict__


@pytest.mark.asyncio
async def test_dispatch_health_check_skipped(mock_request, mock_call_next):
    middleware = ObservabilityMiddleware(app=None, enabled=True)
    mock_request.url.path = "/health"
    response = await middleware.dispatch(mock_request, mock_call_next)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_dispatch_trace_setup_success(mock_request, mock_call_next):
    middleware = ObservabilityMiddleware(app=None, enabled=True)
    mock_session = MagicMock()
    mock_session.is_active = True
    mock_session.in_transaction.return_value = False
    with (
        patch.object(middleware.service, "start_trace", return_value="trace123") as mock_start_trace,
        patch.object(middleware.service, "start_span", return_value="span123") as mock_start_span,
        patch.object(middleware.service, "end_span") as mock_end_span,
        patch.object(middleware.service, "end_trace") as mock_end_trace,
        patch("mcpgateway.middleware.observability_middleware.attach_trace_to_session") as mock_attach,
        patch("mcpgateway.middleware.observability_middleware.parse_traceparent", return_value=("traceX", "spanY", "flags")),
        patch("mcpgateway.middleware.observability_middleware.should_skip_observability", return_value=False),
    ):
        response = await middleware.dispatch(mock_request, mock_call_next)
        assert response.status_code == 200
        mock_start_trace.assert_called_once()
        mock_start_span.assert_called_once()
        mock_end_span.assert_called_once()
        mock_end_trace.assert_called_once()
        mock_attach.assert_called_once()


@pytest.mark.asyncio
async def test_dispatch_trace_setup_failure(mock_request, mock_call_next):
    middleware = ObservabilityMiddleware(app=None, enabled=True)
    with patch.object(middleware.service, "start_trace", side_effect=Exception("trace fail")), patch("mcpgateway.middleware.observability_middleware.should_skip_observability", return_value=False):
        response = await middleware.dispatch(mock_request, mock_call_next)
        assert response.status_code == 200


@pytest.mark.asyncio
async def test_dispatch_exception_during_request(mock_request):
    async def failing_call_next(request):
        raise RuntimeError("Request failed")

    middleware = ObservabilityMiddleware(app=None, enabled=True)
    with (
        patch.object(middleware.service, "start_trace", return_value="trace123"),
        patch.object(middleware.service, "start_span", return_value="span123"),
        patch.object(middleware.service, "end_span") as mock_end_span,
        patch.object(middleware.service, "add_event") as mock_add_event,
        patch.object(middleware.service, "end_trace") as mock_end_trace,
        patch("mcpgateway.middleware.observability_middleware.should_skip_observability", return_value=False),
    ):
        with pytest.raises(RuntimeError):
            await middleware.dispatch(mock_request, failing_call_next)
        mock_end_span.assert_called()
        mock_add_event.assert_called()
        mock_end_trace.assert_called()


# Tests removed - obsolete after #3883
# Middleware no longer creates or manages database sessions.


@pytest.mark.asyncio
async def test_dispatch_trace_setup_cleanup_close_failure_logs_debug(mock_request, mock_call_next):
    middleware = ObservabilityMiddleware(app=None, enabled=True)

    with patch.object(middleware.service, "start_trace", side_effect=Exception("trace fail")), patch("mcpgateway.middleware.observability_middleware.should_skip_observability", return_value=False):
        response = await middleware.dispatch(mock_request, mock_call_next)
        assert response.status_code == 200


@pytest.mark.asyncio
async def test_dispatch_end_span_failure_logs_warning(mock_request, mock_call_next):
    middleware = ObservabilityMiddleware(app=None, enabled=True)

    with (
        patch.object(middleware.service, "start_trace", return_value="trace123"),
        patch.object(middleware.service, "start_span", return_value="span123"),
        patch.object(middleware.service, "end_span", side_effect=Exception("end span fail")),
        patch.object(middleware.service, "end_trace"),
        patch("mcpgateway.middleware.observability_middleware.logger.warning") as mock_warning,
        patch("mcpgateway.middleware.observability_middleware.should_skip_observability", return_value=False),
    ):
        response = await middleware.dispatch(mock_request, mock_call_next)
        assert response.status_code == 200
        mock_warning.assert_called()


@pytest.mark.asyncio
async def test_dispatch_end_trace_failure_logs_warning(mock_request, mock_call_next):
    middleware = ObservabilityMiddleware(app=None, enabled=True)

    with (
        patch.object(middleware.service, "start_trace", return_value="trace123"),
        patch.object(middleware.service, "start_span", return_value="span123"),
        patch.object(middleware.service, "end_span"),
        patch.object(middleware.service, "end_trace", side_effect=Exception("end trace fail")),
        patch("mcpgateway.middleware.observability_middleware.logger.warning") as mock_warning,
        patch("mcpgateway.middleware.observability_middleware.should_skip_observability", return_value=False),
    ):
        response = await middleware.dispatch(mock_request, mock_call_next)
        assert response.status_code == 200
        mock_warning.assert_called()


@pytest.mark.asyncio
async def test_dispatch_exception_logging_failure_logs_warning(mock_request):
    async def failing_call_next(request):
        raise RuntimeError("Request failed")

    middleware = ObservabilityMiddleware(app=None, enabled=True)

    with (
        patch.object(middleware.service, "start_trace", return_value="trace123"),
        patch.object(middleware.service, "start_span", return_value="span123"),
        patch.object(middleware.service, "end_span"),
        patch.object(middleware.service, "add_event", side_effect=Exception("add event fail")),
        patch.object(middleware.service, "end_trace"),
        patch("mcpgateway.middleware.observability_middleware.logger.warning") as mock_warning,
        patch("mcpgateway.middleware.observability_middleware.should_skip_observability", return_value=False),
    ):
        with pytest.raises(RuntimeError):
            await middleware.dispatch(mock_request, failing_call_next)
        mock_warning.assert_called()


@pytest.mark.asyncio
async def test_dispatch_end_trace_error_failure_logs_warning(mock_request):
    async def failing_call_next(request):
        raise RuntimeError("Request failed")

    middleware = ObservabilityMiddleware(app=None, enabled=True)

    with (
        patch.object(middleware.service, "start_trace", return_value="trace123"),
        patch.object(middleware.service, "start_span", return_value="span123"),
        patch.object(middleware.service, "end_span"),
        patch.object(middleware.service, "add_event"),
        patch.object(middleware.service, "end_trace", side_effect=Exception("end trace fail")),
        patch("mcpgateway.middleware.observability_middleware.logger.warning") as mock_warning,
        patch("mcpgateway.middleware.observability_middleware.should_skip_observability", return_value=False),
    ):
        with pytest.raises(RuntimeError):
            await middleware.dispatch(mock_request, failing_call_next)
        mock_warning.assert_called()


# ============================================================================
# Session Reuse Tests
# ============================================================================


@pytest.fixture
def mock_observability_service():
    """Create a mock observability service."""
    service = MagicMock(spec=ObservabilityService)
    service.start_trace.return_value = "test-trace-id"
    service.start_span.return_value = "test-span-id"
    return service


# Test removed - obsolete after #3883
# Middleware no longer creates or manages request sessions.
# Each observability operation creates its own independent session.


@pytest.mark.asyncio
async def test_get_db_reuses_middleware_session():
    """Test that get_db() reuses the session from ObservabilityMiddleware."""
    from mcpgateway.main import get_db

    # Create a mock request with a session in state
    mock_request = MagicMock(spec=Request)
    mock_session = MagicMock()
    mock_session.is_active = True  # Required for commit check
    mock_request.state.db = mock_session

    # Call get_db with the request
    db_generator = get_db(request=mock_request)
    db = next(db_generator)

    # Verify it returns the same session
    assert db is mock_session, "get_db should return the middleware's session"

    # Complete the generator (simulating successful request)
    try:
        next(db_generator)
    except StopIteration:
        pass

    # Verify get_db() commits the middleware session (Issue #3731 fix)
    # Transaction control is now delegated to get_db(), not middleware
    # Verify the session is NOT closed (middleware will handle that)


@pytest.mark.asyncio
async def test_get_db_creates_own_session_when_no_middleware_session():
    """Test that get_db() creates its own session when middleware hasn't created one."""
    from mcpgateway.main import get_db

    # Create a mock request without a session in state
    mock_request = MagicMock(spec=Request)
    mock_request.state = MagicMock(spec=[])  # No 'db' attribute

    # Mock SessionLocal
    mock_session = MagicMock()
    mock_session.is_active = True

    with patch("mcpgateway.main.SessionLocal", return_value=mock_session):
        # Call get_db with the request
        db_generator = get_db(request=mock_request)
        db = next(db_generator)

        # Verify it creates a new session
        assert db is mock_session

        # Complete the generator (simulating successful request)
        try:
            next(db_generator)
        except StopIteration:
            pass

        # Verify the session was committed and closed


# Test removed - obsolete after #3883
# Middleware no longer creates request sessions. Each observability operation
# creates its own independent session. See test_middleware_no_session_management() in
# test_observability_middleware_transactions.py for the updated behavior.

# Tests removed - obsolete after #3883
# Middleware no longer creates or manages database sessions, so no rollback/invalidate operations.
