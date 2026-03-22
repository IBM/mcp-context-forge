# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/middleware/test_observability_middleware.py
Copyright 2025
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
    with patch("mcpgateway.middleware.observability_middleware.SessionLocal", return_value=mock_session), \
         patch.object(middleware.service, "start_trace", return_value="trace123") as mock_start_trace, \
         patch.object(middleware.service, "start_span", return_value="span123") as mock_start_span, \
         patch.object(middleware.service, "end_span") as mock_end_span, \
         patch.object(middleware.service, "end_trace") as mock_end_trace, \
         patch("mcpgateway.middleware.observability_middleware.attach_trace_to_session") as mock_attach, \
         patch("mcpgateway.middleware.observability_middleware.parse_traceparent", return_value=("traceX", "spanY", "flags")), \
         patch("mcpgateway.middleware.observability_middleware.should_skip_observability", return_value=False):
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
    with patch("mcpgateway.middleware.observability_middleware.SessionLocal", side_effect=Exception("DB fail")):
        response = await middleware.dispatch(mock_request, mock_call_next)
        assert response.status_code == 200


@pytest.mark.asyncio
async def test_dispatch_exception_during_request(mock_request):
    async def failing_call_next(request):
        raise RuntimeError("Request failed")

    middleware = ObservabilityMiddleware(app=None, enabled=True)
    db_mock = MagicMock()
    db_mock.is_active = True
    db_mock.in_transaction.return_value = False
    with patch("mcpgateway.middleware.observability_middleware.SessionLocal", return_value=db_mock), \
         patch.object(middleware.service, "start_trace", return_value="trace123"), \
         patch.object(middleware.service, "start_span", return_value="span123"), \
         patch.object(middleware.service, "end_span") as mock_end_span, \
         patch.object(middleware.service, "add_event") as mock_add_event, \
         patch.object(middleware.service, "end_trace") as mock_end_trace, \
         patch("mcpgateway.middleware.observability_middleware.should_skip_observability", return_value=False):
        with pytest.raises(RuntimeError):
            await middleware.dispatch(mock_request, failing_call_next)
        mock_end_span.assert_called()
        mock_add_event.assert_called()
        mock_end_trace.assert_called()


@pytest.mark.asyncio
async def test_dispatch_close_db_failure(mock_request, mock_call_next):
    middleware = ObservabilityMiddleware(app=None, enabled=True)
    db_mock = MagicMock()
    db_mock.is_active = True
    db_mock.in_transaction.return_value = False
    db_mock.close.side_effect = Exception("close fail")
    with patch("mcpgateway.middleware.observability_middleware.SessionLocal", return_value=db_mock), \
         patch.object(middleware.service, "start_trace", return_value="trace123"), \
         patch.object(middleware.service, "start_span", return_value="span123"), \
         patch.object(middleware.service, "end_span"), \
         patch.object(middleware.service, "end_trace"), \
         patch("mcpgateway.middleware.observability_middleware.should_skip_observability", return_value=False):
        response = await middleware.dispatch(mock_request, mock_call_next)
        assert response.status_code == 200


@pytest.mark.asyncio
async def test_dispatch_trace_setup_failure_rolls_back_and_closes_db(mock_request, mock_call_next):
    middleware = ObservabilityMiddleware(app=None, enabled=True)
    db_mock = MagicMock()

    with patch("mcpgateway.middleware.observability_middleware.SessionLocal", return_value=db_mock), \
         patch.object(middleware.service, "start_trace", side_effect=Exception("trace fail")), \
         patch("mcpgateway.middleware.observability_middleware.should_skip_observability", return_value=False):
        response = await middleware.dispatch(mock_request, mock_call_next)
        assert response.status_code == 200

    db_mock.rollback.assert_called()
    db_mock.close.assert_called()


@pytest.mark.asyncio
async def test_dispatch_trace_setup_cleanup_close_failure_logs_debug(mock_request, mock_call_next):
    middleware = ObservabilityMiddleware(app=None, enabled=True)
    db_mock = MagicMock()
    db_mock.close.side_effect = Exception("close fail")

    with patch("mcpgateway.middleware.observability_middleware.SessionLocal", return_value=db_mock), \
         patch.object(middleware.service, "start_trace", side_effect=Exception("trace fail")), \
         patch("mcpgateway.middleware.observability_middleware.logger.debug") as mock_debug, \
         patch("mcpgateway.middleware.observability_middleware.should_skip_observability", return_value=False):
        response = await middleware.dispatch(mock_request, mock_call_next)
        assert response.status_code == 200
        mock_debug.assert_called()


@pytest.mark.asyncio
async def test_dispatch_end_span_failure_logs_warning(mock_request, mock_call_next):
    middleware = ObservabilityMiddleware(app=None, enabled=True)
    db_mock = MagicMock()
    db_mock.is_active = True
    db_mock.in_transaction.return_value = False

    with patch("mcpgateway.middleware.observability_middleware.SessionLocal", return_value=db_mock), \
         patch.object(middleware.service, "start_trace", return_value="trace123"), \
         patch.object(middleware.service, "start_span", return_value="span123"), \
         patch.object(middleware.service, "end_span", side_effect=Exception("end span fail")), \
         patch.object(middleware.service, "end_trace"), \
         patch("mcpgateway.middleware.observability_middleware.logger.warning") as mock_warning, \
         patch("mcpgateway.middleware.observability_middleware.should_skip_observability", return_value=False):
        response = await middleware.dispatch(mock_request, mock_call_next)
        assert response.status_code == 200
        mock_warning.assert_called()


@pytest.mark.asyncio
async def test_dispatch_end_trace_failure_logs_warning(mock_request, mock_call_next):
    middleware = ObservabilityMiddleware(app=None, enabled=True)
    db_mock = MagicMock()
    db_mock.is_active = True
    db_mock.in_transaction.return_value = False

    with patch("mcpgateway.middleware.observability_middleware.SessionLocal", return_value=db_mock), \
         patch.object(middleware.service, "start_trace", return_value="trace123"), \
         patch.object(middleware.service, "start_span", return_value="span123"), \
         patch.object(middleware.service, "end_span"), \
         patch.object(middleware.service, "end_trace", side_effect=Exception("end trace fail")), \
         patch("mcpgateway.middleware.observability_middleware.logger.warning") as mock_warning, \
         patch("mcpgateway.middleware.observability_middleware.should_skip_observability", return_value=False):
        response = await middleware.dispatch(mock_request, mock_call_next)
        assert response.status_code == 200
        mock_warning.assert_called()


@pytest.mark.asyncio
async def test_dispatch_exception_logging_failure_logs_warning(mock_request):
    async def failing_call_next(request):
        raise RuntimeError("Request failed")

    middleware = ObservabilityMiddleware(app=None, enabled=True)
    db_mock = MagicMock()
    db_mock.is_active = True
    db_mock.in_transaction.return_value = False

    with patch("mcpgateway.middleware.observability_middleware.SessionLocal", return_value=db_mock), \
         patch.object(middleware.service, "start_trace", return_value="trace123"), \
         patch.object(middleware.service, "start_span", return_value="span123"), \
         patch.object(middleware.service, "end_span"), \
         patch.object(middleware.service, "add_event", side_effect=Exception("add event fail")), \
         patch.object(middleware.service, "end_trace"), \
         patch("mcpgateway.middleware.observability_middleware.logger.warning") as mock_warning, \
         patch("mcpgateway.middleware.observability_middleware.should_skip_observability", return_value=False):
        with pytest.raises(RuntimeError):
            await middleware.dispatch(mock_request, failing_call_next)
        mock_warning.assert_called()


@pytest.mark.asyncio
async def test_dispatch_end_trace_error_failure_logs_warning(mock_request):
    async def failing_call_next(request):
        raise RuntimeError("Request failed")

    middleware = ObservabilityMiddleware(app=None, enabled=True)
    db_mock = MagicMock()
    db_mock.is_active = True
    db_mock.in_transaction.return_value = False

    with patch("mcpgateway.middleware.observability_middleware.SessionLocal", return_value=db_mock), \
         patch.object(middleware.service, "start_trace", return_value="trace123"), \
         patch.object(middleware.service, "start_span", return_value="span123"), \
         patch.object(middleware.service, "end_span"), \
         patch.object(middleware.service, "add_event"), \
         patch.object(middleware.service, "end_trace", side_effect=Exception("end trace fail")), \
         patch("mcpgateway.middleware.observability_middleware.logger.warning") as mock_warning, \
         patch("mcpgateway.middleware.observability_middleware.should_skip_observability", return_value=False):
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


@pytest.mark.asyncio
async def test_observability_middleware_creates_request_scoped_session(mock_request, mock_observability_service):
    """Test that observability middleware creates a session and stores it in request.state.db."""

    # Use /rpc path which is in the observability include list
    mock_request.url.path = "/rpc"

    # Create middleware
    app = MagicMock()
    middleware = ObservabilityMiddleware(app, enabled=True, service=mock_observability_service)

    # Mock SessionLocal to track session creation
    session_instances = []

    def mock_session_local():
        session = MagicMock()
        session.is_active = True
        session.in_transaction.return_value = True  # Session has uncommitted changes
        session_instances.append(session)
        return session

    # Mock call_next to simulate route handler
    async def mock_call_next(request):
        # Verify session is stored in request.state.db
        assert hasattr(request.state, "db"), "Session should be stored in request.state.db"
        assert request.state.db is not None, "Session should not be None"
        return Response(content="OK", status_code=200)

    # Patch SessionLocal and should_skip_observability
    with patch("mcpgateway.middleware.observability_middleware.SessionLocal", side_effect=mock_session_local):
        with patch("mcpgateway.middleware.observability_middleware.should_skip_observability", return_value=False):
            response = await middleware.dispatch(mock_request, mock_call_next)

    # Verify only one session was created
    assert len(session_instances) == 1, f"Expected 1 session, but {len(session_instances)} were created"

    # Verify session was committed and closed
    session_instances[0].commit.assert_called_once()
    session_instances[0].close.assert_called_once()

    # Verify response
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_observability_middleware_cleans_up_on_error(mock_request, mock_observability_service):
    """Test that observability middleware properly cleans up session on error."""

    # Use /rpc path which is in the observability include list
    mock_request.url.path = "/rpc"

    # Create middleware
    app = MagicMock()
    middleware = ObservabilityMiddleware(app, enabled=True, service=mock_observability_service)

    # Mock SessionLocal
    session_instances = []

    def mock_session_local():
        session = MagicMock()
        session.is_active = True
        session.in_transaction.return_value = False
        session_instances.append(session)
        return session

    # Mock call_next to raise an exception
    async def mock_call_next(request):
        raise ValueError("Test error")

    # Patch SessionLocal and should_skip_observability
    with patch("mcpgateway.middleware.observability_middleware.SessionLocal", side_effect=mock_session_local):
        with patch("mcpgateway.middleware.observability_middleware.should_skip_observability", return_value=False):
            with pytest.raises(ValueError, match="Test error"):
                await middleware.dispatch(mock_request, mock_call_next)

    # Verify session was rolled back and closed
    assert len(session_instances) == 1, f"Expected 1 session, but {len(session_instances)} were created"
    session_instances[0].rollback.assert_called_once()
    session_instances[0].close.assert_called_once()


@pytest.mark.asyncio
async def test_get_db_reuses_middleware_session():
    """Test that get_db() reuses the session from ObservabilityMiddleware."""
    from mcpgateway.main import get_db

    # Create a mock request with a session in state
    mock_request = MagicMock(spec=Request)
    mock_session = MagicMock()
    mock_request.state.db = mock_session

    # Call get_db with the request
    db_generator = get_db(request=mock_request)
    db = next(db_generator)

    # Verify it returns the same session
    assert db is mock_session, "get_db should return the middleware's session"

    # Verify the session is NOT closed (middleware will handle that)
    try:
        next(db_generator)
    except StopIteration:
        pass

    mock_session.close.assert_not_called()
    mock_session.commit.assert_not_called()


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
        mock_session.commit.assert_called_once()
        mock_session.close.assert_called_once()


@pytest.mark.asyncio
async def test_single_session_per_request_integration():
    """Integration test: Verify only one session is created per request with observability enabled."""
    from mcpgateway.main import get_db

    # Track session creation
    session_instances = []

    def mock_session_local():
        session = MagicMock()
        session.is_active = True
        session.in_transaction.return_value = True  # Session has uncommitted changes
        session_instances.append(session)
        return session

    # Create mock request with /rpc path (traced by default)
    mock_request = MagicMock(spec=Request)
    mock_request.method = "GET"
    mock_request.url.path = "/rpc"
    mock_request.url.query = ""
    mock_request.url = MagicMock()
    mock_request.url.__str__ = MagicMock(return_value="http://test.com/rpc")
    mock_request.client = MagicMock()
    mock_request.client.host = "127.0.0.1"
    mock_request.headers = {"user-agent": "test-agent"}
    mock_request.state = MagicMock()

    # Create middleware
    app = MagicMock()
    mock_service = MagicMock(spec=ObservabilityService)
    mock_service.start_trace.return_value = "test-trace-id"
    mock_service.start_span.return_value = "test-span-id"
    middleware = ObservabilityMiddleware(app, enabled=True, service=mock_service)

    # Simulate route handler that uses get_db
    async def mock_call_next(request):
        # This simulates what happens in a real route handler
        db_generator = get_db(request=request)
        db = next(db_generator)

        # Verify we got a session
        assert db is not None

        # Complete the generator
        try:
            next(db_generator)
        except StopIteration:
            pass

        return Response(content="OK", status_code=200)

    # Patch SessionLocal in both modules and should_skip_observability
    with patch("mcpgateway.middleware.observability_middleware.SessionLocal", side_effect=mock_session_local):
        with patch("mcpgateway.main.SessionLocal", side_effect=mock_session_local):
            with patch("mcpgateway.middleware.observability_middleware.should_skip_observability", return_value=False):
                response = await middleware.dispatch(mock_request, mock_call_next)

    # CRITICAL ASSERTION: Only ONE session should be created
    assert len(session_instances) == 1, f"Expected 1 session, but {len(session_instances)} were created"

    # Verify the single session was properly managed
    session_instances[0].commit.assert_called_once()
    session_instances[0].close.assert_called_once()

    # Verify response
    assert response.status_code == 200

@pytest.mark.asyncio
async def test_dispatch_trace_setup_rollback_and_invalidate_failure():
    """Test that trace setup handles both rollback and invalidate failures gracefully."""
    middleware = ObservabilityMiddleware(app=None, enabled=True)

    mock_request = MagicMock(spec=Request)
    mock_request.url.path = "/rpc"
    mock_request.url.query = ""
    mock_request.url = MagicMock()
    mock_request.url.__str__ = MagicMock(return_value="http://test.com/rpc")
    mock_request.client = MagicMock()
    mock_request.client.host = "127.0.0.1"
    mock_request.headers = {"user-agent": "test-agent"}
    mock_request.state = MagicMock()

    # Mock SessionLocal to return a session that fails on both rollback and invalidate
    db_mock = MagicMock()
    db_mock.rollback.side_effect = Exception("rollback failed")
    db_mock.invalidate.side_effect = Exception("invalidate failed")
    db_mock.close.return_value = None

    async def mock_call_next(request):
        return Response(content="OK", status_code=200)

    with patch("mcpgateway.middleware.observability_middleware.SessionLocal", return_value=db_mock), \
         patch.object(middleware.service, "start_trace", side_effect=Exception("trace setup failed")), \
         patch("mcpgateway.middleware.observability_middleware.logger.debug") as mock_debug, \
         patch("mcpgateway.middleware.observability_middleware.should_skip_observability", return_value=False):
        response = await middleware.dispatch(mock_request, mock_call_next)

        # Verify rollback was attempted
        db_mock.rollback.assert_called_once()

        # Verify invalidate was attempted (even though it failed)
        db_mock.invalidate.assert_called_once()

        # Verify debug log was called for rollback failure
        mock_debug.assert_any_call("Failed to rollback during cleanup: rollback failed")

        # Verify response is still returned (graceful degradation)
        assert response.status_code == 200


@pytest.mark.asyncio
async def test_dispatch_exception_handler_invalidate_failure():
    """Test that main exception handler handles invalidate failure gracefully."""
    async def failing_call_next(request):
        raise RuntimeError("Request failed")

    middleware = ObservabilityMiddleware(app=None, enabled=True)

    mock_request = MagicMock(spec=Request)
    mock_request.url.path = "/rpc"
    mock_request.url.query = ""
    mock_request.url = MagicMock()
    mock_request.url.__str__ = MagicMock(return_value="http://test.com/rpc")
    mock_request.client = MagicMock()
    mock_request.client.host = "127.0.0.1"
    mock_request.headers = {"user-agent": "test-agent"}
    mock_request.state = MagicMock()

    # Mock SessionLocal to return a session that fails on both rollback and invalidate
    db_mock = MagicMock()
    db_mock.is_active = True
    db_mock.rollback.side_effect = Exception("rollback failed")
    db_mock.invalidate.side_effect = Exception("invalidate failed")

    with patch("mcpgateway.middleware.observability_middleware.SessionLocal", return_value=db_mock), \
         patch.object(middleware.service, "start_trace", return_value="trace123"), \
         patch.object(middleware.service, "start_span", return_value="span123"), \
         patch.object(middleware.service, "end_span"), \
         patch.object(middleware.service, "add_event"), \
         patch.object(middleware.service, "end_trace"), \
         patch("mcpgateway.middleware.observability_middleware.logger.warning") as mock_warning, \
         patch("mcpgateway.middleware.observability_middleware.should_skip_observability", return_value=False):
        with pytest.raises(RuntimeError, match="Request failed"):
            await middleware.dispatch(mock_request, failing_call_next)

        # Verify rollback was attempted
        db_mock.rollback.assert_called_once()

        # Verify invalidate was attempted (even though it failed)
        db_mock.invalidate.assert_called_once()

        # Verify warning log was called for rollback failure
        mock_warning.assert_any_call("Failed to rollback database session: rollback failed")



@pytest.mark.asyncio
async def test_dispatch_rollback_failure_logs_warning(mock_request):
    """Test that rollback failure during exception handling logs a warning."""
    async def failing_call_next(request):
        raise RuntimeError("Request failed")

    middleware = ObservabilityMiddleware(app=None, enabled=True)
    db_mock = MagicMock()
    db_mock.is_active = True
    db_mock.rollback.side_effect = Exception("rollback fail")  # Simulate rollback failure

    with patch("mcpgateway.middleware.observability_middleware.SessionLocal", return_value=db_mock), \
         patch.object(middleware.service, "start_trace", return_value="trace123"), \
         patch.object(middleware.service, "start_span", return_value="span123"), \
         patch.object(middleware.service, "end_span"), \
         patch.object(middleware.service, "add_event"), \
         patch.object(middleware.service, "end_trace"), \
         patch("mcpgateway.middleware.observability_middleware.logger.warning") as mock_warning, \
         patch("mcpgateway.middleware.observability_middleware.should_skip_observability", return_value=False):
        with pytest.raises(RuntimeError):
            await middleware.dispatch(mock_request, failing_call_next)
        # Verify that the rollback failure was logged
        mock_warning.assert_any_call("Failed to rollback database session: rollback fail")
