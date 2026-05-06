# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/middleware/test_observability_middleware_transactions.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for observability middleware transaction control.

Tests verify that transaction control (commit/rollback) is correctly
delegated to get_db() while middleware only manages session lifecycle
(create/close). This addresses the transaction management violation
described in issue #3731.
"""

# Standard
from unittest.mock import MagicMock, patch

# Third-Party
import pytest
from starlette.requests import Request
from starlette.responses import Response

# First-Party
from mcpgateway.middleware.observability_middleware import ObservabilityMiddleware


def create_mock_request():
    """Create a mock request for testing."""
    request = MagicMock(spec=Request)
    request.method = "GET"
    request.url.path = "/api/v1/servers"
    request.url.query = ""
    request.url.__str__.return_value = "http://testserver/api/v1/servers"
    request.client = MagicMock()
    request.client.host = "127.0.0.1"
    request.headers = {"user-agent": "pytest"}
    request.state = MagicMock()
    return request


# Test removed - obsolete after #3883
# Middleware no longer creates or manages request sessions.
# Observability operations create their own independent sessions.


@pytest.mark.asyncio
async def test_get_db_commits_middleware_session_on_success():
    """
    Test 2: Verify get_db() commits middleware session on successful completion.

    When get_db() reuses a middleware session, it must commit on success
    to maintain the transaction control contract. This ensures route
    handlers have predictable transaction semantics.
    """
    # First-Party
    from mcpgateway.main import get_db

    mock_request = MagicMock(spec=Request)
    mock_session = MagicMock()
    mock_session.is_active = True
    mock_request.state.db = mock_session

    # Simulate successful route handler
    gen = get_db(request=mock_request)
    db = next(gen)

    assert db is mock_session  # Verify we got the middleware session

    # Simulate successful completion (no exception)
    try:
        next(gen)
    except StopIteration:
        pass

    # CRITICAL: Verify get_db() called commit
    mock_session.commit.assert_called_once()
    # Verify get_db() did NOT call close (middleware owns lifecycle)
    mock_session.close.assert_not_called()


@pytest.mark.asyncio
async def test_get_db_rollsback_middleware_session_on_error():
    """
    Test 3: Verify get_db() rolls back middleware session on exception.

    When a route handler raises an exception, get_db() must rollback
    the session to prevent partial commits of invalid data. This is
    the core fix for issue #3731.
    """
    # First-Party
    from mcpgateway.main import get_db

    mock_request = MagicMock(spec=Request)
    mock_session = MagicMock()
    mock_session.is_active = True
    mock_request.state.db = mock_session

    # Simulate route handler that raises exception
    gen = get_db(request=mock_request)
    db = next(gen)

    assert db is mock_session

    # Simulate exception in route handler
    with pytest.raises(ValueError):
        gen.throw(ValueError("Validation failed"))

    # CRITICAL: Verify get_db() called rollback
    mock_session.rollback.assert_called_once()
    # Verify get_db() did NOT call commit
    mock_session.commit.assert_not_called()
    # Verify get_db() did NOT call close
    mock_session.close.assert_not_called()


@pytest.mark.asyncio
async def test_get_db_invalidates_broken_connection_middleware_session():
    """
    Test 4: Verify get_db() invalidates broken connections on rollback failure.

    When a connection is broken (e.g., PgBouncer timeout), the rollback
    itself may fail. In this case, get_db() must invalidate the session
    to ensure the broken connection is removed from the pool.
    """
    # First-Party
    from mcpgateway.main import get_db

    mock_request = MagicMock(spec=Request)
    mock_session = MagicMock()
    mock_session.is_active = True
    mock_request.state.db = mock_session

    # Simulate broken connection (rollback fails)
    mock_session.rollback.side_effect = Exception("Connection broken")

    gen = get_db(request=mock_request)
    next(gen)

    # Simulate exception in route handler
    with pytest.raises(ValueError):
        gen.throw(ValueError("Validation failed"))

    # Verify rollback was attempted
    mock_session.rollback.assert_called_once()
    # Verify invalidate was called due to rollback failure
    mock_session.invalidate.assert_called_once()


# Test removed - obsolete after #3883
# Middleware no longer creates request sessions. Each observability operation
# creates its own independent session. See test_middleware_no_session_management() instead.


@pytest.mark.asyncio
async def test_observability_data_persists_on_error_separate_session():
    """
    Test 6: Verify that observability data persists on error (Option 2 behavior).

    With separate observability sessions (issue #3883), observability data
    commits independently of main transaction failures. This provides
    visibility into partial failures at the cost of atomicity.

    This is a BREAKING BEHAVIOR CHANGE from the previous implementation
    where observability data was rolled back with main transaction.
    """
    # First-Party
    from mcpgateway.main import get_db
    from mcpgateway.middleware.observability_middleware import ObservabilityMiddleware

    middleware = ObservabilityMiddleware(app=None, enabled=True)
    mock_request = create_mock_request()

    with (
        patch("mcpgateway.middleware.observability_middleware.should_skip_observability", return_value=False),
        patch.object(middleware.service, "start_trace", return_value="trace123") as mock_start_trace,
        patch.object(middleware.service, "start_span", return_value="span123") as mock_start_span,
        patch.object(middleware.service, "end_span") as mock_end_span,
        patch.object(middleware.service, "end_trace") as mock_end_trace,
        patch("mcpgateway.middleware.observability_middleware.attach_trace_to_session"),
    ):

        async def failing_call_next(request):
            # Simulate route handler using get_db()
            gen = get_db(request=request)
            next(gen)
            # Simulate failure
            try:
                gen.throw(ValueError("Validation failed"))
            except ValueError:
                # The exception propagates up from get_db()
                raise
            return Response("OK", status_code=200)

        with pytest.raises(ValueError):
            await middleware.dispatch(mock_request, failing_call_next)

        # CRITICAL: Verify observability methods were called (they create their own sessions)
        mock_start_trace.assert_called_once()
        mock_start_span.assert_called_once()
        mock_end_span.assert_called_once()  # Called with error status
        mock_end_trace.assert_called_once()  # Called with error status

        # Verify end_span was called with error status
        end_span_call = mock_end_span.call_args
        assert end_span_call is not None
        # Check that status="error" was passed
        assert end_span_call.kwargs.get("status") == "error" or (len(end_span_call.args) > 1 and end_span_call.args[1] == "error")

        # Verify end_trace was called with error status
        end_trace_call = mock_end_trace.call_args
        assert end_trace_call is not None
        assert end_trace_call.kwargs.get("status") == "error" or (len(end_trace_call.args) > 1 and end_trace_call.args[1] == "error")


@pytest.mark.asyncio
async def test_get_db_invalidates_broken_connection_double_failure():
    """
    Test 7: Verify get_db() handles case where both rollback AND invalidate fail.

    In extreme cases (e.g., complete database crash), both rollback() and
    invalidate() may fail. The code should handle this gracefully and still
    re-raise the original exception.
    """
    # First-Party
    from mcpgateway.main import get_db

    mock_request = MagicMock(spec=Request)
    mock_session = MagicMock()
    mock_session.is_active = True
    mock_request.state.db = mock_session

    # Simulate both rollback AND invalidate failing
    mock_session.rollback.side_effect = Exception("Rollback failed")
    mock_session.invalidate.side_effect = Exception("Invalidate also failed")

    gen = get_db(request=mock_request)
    next(gen)

    # Simulate exception in route handler
    with pytest.raises(ValueError):
        gen.throw(ValueError("Validation failed"))

    # Verify both were attempted
    mock_session.rollback.assert_called_once()
    mock_session.invalidate.assert_called_once()


@pytest.mark.asyncio
async def test_get_db_inactive_session_skips_commit():
    """
    Test 8: Verify get_db() skips commit if session becomes inactive.

    In some cases (e.g., CancelledError during async cleanup), the session
    may become inactive before get_db() attempts to commit. This is handled
    gracefully by checking is_active before committing.
    """
    # First-Party
    from mcpgateway.main import get_db

    mock_request = MagicMock(spec=Request)
    mock_session = MagicMock()
    mock_session.is_active = False  # Session became inactive
    mock_request.state.db = mock_session

    # Simulate successful route handler
    gen = get_db(request=mock_request)
    db = next(gen)

    assert db is mock_session

    # Simulate successful completion (no exception)
    try:
        next(gen)
    except StopIteration:
        pass

    # Verify commit was NOT called (session inactive)
    mock_session.commit.assert_not_called()
    # Verify get_db() did NOT call close
    mock_session.close.assert_not_called()


# =============================================================================
# New tests for separate observability session pattern (issue #3883)
# =============================================================================


def test_observability_uses_independent_sessions():
    """Verify observability write operations use independent sessions."""
    # First-Party
    from mcpgateway.services.observability_service import ObservabilityService

    service = ObservabilityService()

    with patch("mcpgateway.services.observability_service.SessionLocal") as mock_factory:
        mock_session = MagicMock()
        mock_factory.return_value = mock_session

        trace_id = service.start_trace(name="test_trace")

        # Verify: New session created
        mock_factory.assert_called_once()
        # Verify: Session committed
        mock_session.commit.assert_called_once()
        # Verify: Session closed
        mock_session.close.assert_called_once()
        # Verify: trace_id returned
        assert trace_id is not None


def test_context_manager_reuses_session():
    """Verify context managers use a single session for start/end."""
    # Standard
    from datetime import datetime, timezone

    # First-Party
    from mcpgateway.services.observability_service import ObservabilityService

    service = ObservabilityService()

    with patch("mcpgateway.services.observability_service.SessionLocal") as mock_factory:
        mock_session = MagicMock()
        mock_factory.return_value = mock_session

        # Mock the query chain for end_span
        mock_span = MagicMock()
        mock_span.start_time = datetime.now(timezone.utc)
        mock_span.attributes = {}
        mock_session.query.return_value.filter_by.return_value.first.return_value = mock_span

        with service.trace_span(trace_id="test123", name="test_span"):
            pass

        # Verify: Only ONE session created (not two for start_span + end_span)
        mock_factory.assert_called_once()
        # Verify: Single commit at end
        mock_session.commit.assert_called_once()
        # Verify: Session closed
        mock_session.close.assert_called_once()


def test_add_event_bug_fix():
    """Verify add_event doesn't call refresh after commit failure."""
    # Third-Party
    from sqlalchemy.exc import SQLAlchemyError

    # First-Party
    from mcpgateway.services.observability_service import ObservabilityService

    service = ObservabilityService()

    with patch("mcpgateway.services.observability_service.SessionLocal") as mock_factory:
        mock_session = MagicMock()
        mock_session.commit.side_effect = SQLAlchemyError("commit failed")
        mock_factory.return_value = mock_session

        event_id = service.add_event(span_id="test", name="test_event", severity="info", message="test")

        # Verify: Returns 0 on commit failure
        assert event_id == 0
        # Verify: refresh NOT called after commit failure (bug fix)
        mock_session.refresh.assert_not_called()
        # Verify: rollback was called
        mock_session.rollback.assert_called_once()
        # Verify: session still closed
        mock_session.close.assert_called_once()


def test_record_metric_returns_zero_on_failure():
    """Verify record_metric returns 0 when commit fails."""
    # Third-Party
    from sqlalchemy.exc import SQLAlchemyError

    # First-Party
    from mcpgateway.services.observability_service import ObservabilityService

    service = ObservabilityService()

    with patch("mcpgateway.services.observability_service.SessionLocal") as mock_factory:
        mock_session = MagicMock()
        mock_session.commit.side_effect = SQLAlchemyError("commit failed")
        mock_factory.return_value = mock_session

        metric_id = service.record_metric(name="test.metric", value=42.0, metric_type="gauge")

        # Verify: Returns 0 on commit failure
        assert metric_id == 0
        # Verify: refresh NOT called after commit failure
        mock_session.refresh.assert_not_called()
        # Verify: rollback was called
        mock_session.rollback.assert_called_once()
        # Verify: session still closed
        mock_session.close.assert_called_once()


@pytest.mark.asyncio
async def test_middleware_no_session_management():
    """Verify middleware doesn't create or manage request sessions anymore."""
    # First-Party
    from mcpgateway.middleware.observability_middleware import ObservabilityMiddleware

    middleware = ObservabilityMiddleware(app=None, enabled=True)
    # Create a fresh mock request without any preset attributes
    mock_request = MagicMock(spec=Request)
    mock_request.method = "GET"
    mock_request.url.path = "/api/v1/servers"
    mock_request.url.query = ""
    mock_request.url.__str__.return_value = "http://testserver/api/v1/servers"
    mock_request.client = MagicMock()
    mock_request.client.host = "127.0.0.1"
    mock_request.headers = {"user-agent": "pytest"}
    # Create a clean state object without db attribute
    mock_request.state = MagicMock()
    del mock_request.state.db  # Explicitly remove db attribute if it exists

    db_was_set = False

    with (
        patch("mcpgateway.middleware.observability_middleware.should_skip_observability", return_value=False),
        patch.object(middleware.service, "start_trace", return_value="trace123"),
        patch.object(middleware.service, "start_span", return_value="span123"),
        patch.object(middleware.service, "end_span"),
        patch.object(middleware.service, "end_trace"),
        patch("mcpgateway.middleware.observability_middleware.attach_trace_to_session"),
    ):

        async def mock_call_next(request):
            # Verify: No session in request.state created by middleware
            nonlocal db_was_set
            db_was_set = hasattr(request.state, "db") and request.state.db is not None
            return Response("OK", status_code=200)

        response = await middleware.dispatch(mock_request, mock_call_next)

        assert response.status_code == 200
        # CRITICAL: Verify middleware did NOT set request.state.db
        assert not db_was_set, "Middleware should not create request.state.db"
        # Verify: trace_id was set in request state
        assert hasattr(mock_request.state, "trace_id")
        assert mock_request.state.trace_id == "trace123"
