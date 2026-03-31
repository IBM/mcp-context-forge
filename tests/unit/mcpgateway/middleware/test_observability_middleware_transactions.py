# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/middleware/test_observability_middleware_transactions.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

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


@pytest.mark.asyncio
async def test_middleware_does_not_commit_shared_session():
    """
    Test 1: Verify middleware does not commit the shared session.

    The middleware should only manage session lifecycle (create/close),
    not transactions (commit/rollback). Transaction control is delegated
    to get_db() to maintain predictable semantics for route handlers.
    """
    middleware = ObservabilityMiddleware(app=None, enabled=True)
    mock_request = create_mock_request()
    mock_session = MagicMock()
    mock_session.is_active = True
    mock_session.in_transaction.return_value = False

    with (
        patch("mcpgateway.middleware.observability_middleware.SessionLocal", return_value=mock_session),
        patch("mcpgateway.middleware.observability_middleware.should_skip_observability", return_value=False),
        patch.object(middleware.service, "start_trace", return_value="trace123"),
        patch.object(middleware.service, "start_span", return_value="span123"),
        patch.object(middleware.service, "end_span"),
        patch.object(middleware.service, "end_trace"),
        patch("mcpgateway.middleware.observability_middleware.attach_trace_to_session"),
    ):

        async def mock_call_next(request):
            return Response("OK", status_code=200)

        response = await middleware.dispatch(mock_request, mock_call_next)

        assert response.status_code == 200
        # CRITICAL: Verify middleware did NOT call commit
        mock_session.commit.assert_not_called()
        # Verify middleware DID call close (lifecycle management)
        mock_session.close.assert_called_once()


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


@pytest.mark.asyncio
async def test_full_request_flow_with_observability():
    """
    Test 5: Integration test - Full request flow with observability enabled.

    Verifies the complete flow: middleware creates session, route handler
    uses get_db(), get_db() commits, middleware closes. This confirms the
    separation of concerns between lifecycle (middleware) and transactions
    (get_db()).
    """
    # First-Party
    from mcpgateway.main import get_db
    from mcpgateway.middleware.observability_middleware import ObservabilityMiddleware

    middleware = ObservabilityMiddleware(app=None, enabled=True)
    mock_request = create_mock_request()
    mock_session = MagicMock()
    mock_session.is_active = True
    mock_session.in_transaction.return_value = False

    with (
        patch("mcpgateway.middleware.observability_middleware.SessionLocal", return_value=mock_session),
        patch("mcpgateway.middleware.observability_middleware.should_skip_observability", return_value=False),
        patch.object(middleware.service, "start_trace", return_value="trace123"),
        patch.object(middleware.service, "start_span", return_value="span123"),
        patch.object(middleware.service, "end_span"),
        patch.object(middleware.service, "end_trace"),
        patch("mcpgateway.middleware.observability_middleware.attach_trace_to_session"),
    ):

        async def mock_call_next(request):
            # Simulate route handler using get_db()
            gen = get_db(request=request)
            next(gen)
            # Do some work...
            # Complete successfully
            try:
                next(gen)
            except StopIteration:
                pass
            return Response("OK", status_code=200)

        response = await middleware.dispatch(mock_request, mock_call_next)

        assert response.status_code == 200
        # Verify commit was called exactly once (by get_db())
        mock_session.commit.assert_called_once()
        # Verify session was closed exactly once (by middleware)
        mock_session.close.assert_called_once()


@pytest.mark.asyncio
async def test_observability_data_lost_on_error_is_acceptable():
    """
    Test 6: Verify that observability data is rolled back on error.

    This is EXPECTED and ACCEPTABLE behavior - observability is best-effort.
    When a route handler fails, get_db() rolls back the entire transaction,
    including any observability traces/spans that were written. This is an
    acceptable trade-off to maintain data integrity.
    """
    # First-Party
    from mcpgateway.main import get_db
    from mcpgateway.middleware.observability_middleware import ObservabilityMiddleware

    middleware = ObservabilityMiddleware(app=None, enabled=True)
    mock_request = create_mock_request()
    mock_session = MagicMock()
    mock_session.is_active = True
    mock_session.in_transaction.return_value = False

    with (
        patch("mcpgateway.middleware.observability_middleware.SessionLocal", return_value=mock_session),
        patch("mcpgateway.middleware.observability_middleware.should_skip_observability", return_value=False),
        patch.object(middleware.service, "start_trace", return_value="trace123") as mock_start,
        patch.object(middleware.service, "start_span", return_value="span123"),
        patch.object(middleware.service, "end_span"),
        patch.object(middleware.service, "end_trace"),
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

        # Observability trace/span were created
        mock_start.assert_called_once()
        # Session was rolled back by middleware (observability data lost - ACCEPTABLE)
        mock_session.rollback.assert_called()
        # Session was closed
        mock_session.close.assert_called_once()


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
