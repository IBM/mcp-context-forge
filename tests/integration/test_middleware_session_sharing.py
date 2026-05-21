# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_middleware_session_sharing.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Integration tests for middleware session sharing (Issue #3622).

These tests verify that only 1 database session is created per request
across all middleware layers (observability, auth, RBAC) and route handlers.
"""

import pytest
from unittest.mock import patch, MagicMock


def _make_mock_session():
    """Create a MagicMock with standard SQLAlchemy session attributes."""
    session = MagicMock()
    session.close = MagicMock()
    session.commit = MagicMock()
    session.rollback = MagicMock()
    session.invalidate = MagicMock()
    session.is_active = True
    session.in_transaction = MagicMock(return_value=True)
    return session


@pytest.mark.asyncio
async def test_auth_middleware_does_not_create_session_when_observability_provides_one():
    """When ObservabilityMiddleware creates a session, auth middleware must reuse it.

    This is the core behavior fix from issue #3622.  We patch SessionLocal
    per-module to track which module actually creates a session.
    """
    from mcpgateway.middleware.auth_middleware import _get_or_create_session
    from starlette.requests import Request

    # Simulate ObservabilityMiddleware having stored a session
    existing_session = _make_mock_session()
    mock_request = MagicMock(spec=Request)
    mock_request.state.db = existing_session

    db, owned = _get_or_create_session(mock_request)

    assert db is existing_session, "Auth should reuse ObservabilityMiddleware session"
    assert owned is False, "Auth does not own the session"


@pytest.mark.asyncio
async def test_auth_middleware_creates_temporary_session_when_no_middleware_session():
    """When no middleware session exists, auth middleware creates a temporary one
    that is NOT stored in request.state.db (to prevent stale reference after close).
    """
    from mcpgateway.middleware.auth_middleware import _get_or_create_session
    from starlette.requests import Request

    mock_request = MagicMock(spec=Request)
    mock_request.state = MagicMock()
    mock_request.state.db = None

    with patch("mcpgateway.middleware.auth_middleware.SessionLocal") as mock_sl:
        new_session = _make_mock_session()
        mock_sl.return_value = new_session

        db, owned = _get_or_create_session(mock_request)

    assert db is new_session, "Auth should create a new session"
    assert owned is True, "Auth owns the session"
    # Must NOT be stored in request.state.db
    assert mock_request.state.db is None, "Owned session must not be stored in request.state.db " "to prevent downstream use of a closed session"


@pytest.mark.asyncio
async def test_rbac_get_db_reuses_middleware_session():
    """RBAC's deprecated get_db() reuses request.state.db when available."""
    import warnings
    from mcpgateway.middleware.rbac import get_db
    from starlette.requests import Request

    existing_session = _make_mock_session()
    mock_request = MagicMock(spec=Request)
    mock_request.state.db = existing_session

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        gen = get_db(request=mock_request)
        db = next(gen)

    assert db is existing_session, "RBAC get_db() should reuse middleware session"
    # Should NOT close it (not owned)
    existing_session.close.assert_not_called()
    gen.close()
    existing_session.close.assert_not_called()


@pytest.mark.asyncio
async def test_rbac_get_db_creates_own_session_when_none_available():
    """RBAC's deprecated get_db() creates its own session when no middleware session exists."""
    import warnings
    from mcpgateway.middleware.rbac import get_db

    mock_session = _make_mock_session()

    with warnings.catch_warnings(), patch("mcpgateway.middleware.rbac.SessionLocal", return_value=mock_session):
        warnings.simplefilter("ignore", DeprecationWarning)
        gen = get_db(request=None)
        db = next(gen)

    assert db is mock_session, "RBAC get_db() should create a new session"
    gen.close()
    # Should close its own session
    mock_session.close.assert_called_once()


@pytest.mark.asyncio
async def test_shared_session_rollback_on_auth_logging_failure():
    """When auth logging fails on a shared session, rollback must prevent PendingRollbackError.

    This test validates that the auth middleware properly cleans up the shared
    session when security logging raises an exception, so that downstream
    call_next()/get_db() does not inherit a broken session.
    """
    from mcpgateway.middleware.auth_middleware import AuthContextMiddleware
    from starlette.responses import Response

    middleware = AuthContextMiddleware(app=MagicMock())
    call_next = MagicMock(return_value=Response("ok"))

    # Make call_next a coroutine
    async def async_call_next(req):
        return Response("ok")

    request = MagicMock()
    request.url.path = "/servers"
    request.cookies = {"jwt_token": "valid_token"}
    request.headers = {}
    request.client = MagicMock()
    request.client.host = "127.0.0.1"

    mock_user = MagicMock()
    mock_user.email = "user@example.com"

    # Shared session simulating ObservabilityMiddleware
    shared_session = _make_mock_session()
    request.state.db = shared_session

    mock_security_logger = MagicMock()
    mock_security_logger.log_authentication_attempt.side_effect = RuntimeError("connection error")

    with (
        patch("mcpgateway.middleware.auth_middleware._should_log_auth_success", return_value=True),
        patch("mcpgateway.middleware.auth_middleware.get_current_user", return_value=mock_user),
        patch("mcpgateway.middleware.auth_middleware.security_logger", mock_security_logger),
    ):
        response = await middleware.dispatch(request, async_call_next)

    assert response.status_code == 200
    # Critical: shared session must be rolled back
    shared_session.rollback.assert_called_once()
    # Must NOT be closed (owned by ObservabilityMiddleware)
    shared_session.close.assert_not_called()


@pytest.mark.asyncio
async def test_session_count_with_full_middleware_stack():
    """Verify that the full middleware chain creates at most 1 session per request.

    Uses the real app but patches SessionLocal at all entry points.
    Targets /health (which skips auth) to count only ObservabilityMiddleware sessions.
    """
    from mcpgateway.main import app
    from fastapi.testclient import TestClient

    session_count = 0

    def counting_session_local():
        nonlocal session_count
        session_count += 1
        return _make_mock_session()

    with (
        patch("mcpgateway.middleware.observability_middleware.SessionLocal", counting_session_local),
        patch("mcpgateway.middleware.auth_middleware.SessionLocal", counting_session_local),
        patch("mcpgateway.middleware.rbac.SessionLocal", counting_session_local),
        patch("mcpgateway.main.SessionLocal", counting_session_local),
    ):

        client = TestClient(app)
        session_count = 0  # Reset after TestClient setup
        response = client.get("/health")

    # /health skips auth middleware, so we expect at most 1 session
    # (from ObservabilityMiddleware, if enabled)
    assert session_count <= 1, f"Expected at most 1 session for /health, got {session_count}"
