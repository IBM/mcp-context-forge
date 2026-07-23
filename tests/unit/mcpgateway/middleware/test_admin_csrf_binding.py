# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/middleware/test_admin_csrf_binding.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Regression tests for issue #5739 — the Admin UI login handler bound the
CSRF token to ``EmailUser.id`` (the JWT ``sub`` claim) while ``CSRFMiddleware``
validates against ``EmailUser.email`` (``request.state.user.email``). The
mismatched HMAC binding meant every ``/llm/*`` write 403'd with
``CSRF_TOKEN_INVALID`` even with a syntactically-correct ``X-CSRF-Token``
header.

These tests prove the binding mismatch directly against ``CSRFService`` /
``CSRFMiddleware`` (the same pattern used by
``test_admin_random_csrf_token_fails_hmac_validation`` /
``test_admin_bound_csrf_token_from_page_load_passes_hmac_validation`` in
``test_csrf_middleware.py``), and additionally assert that ``admin.py``'s
login handler source binds ``csrf_user_id`` to the email, not the id/sub.
"""

# Standard
import inspect
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest
from starlette.requests import Request
from starlette.responses import Response

# First-Party
from mcpgateway.middleware.csrf_middleware import CSRFMiddleware
from mcpgateway.services.csrf_service import CSRFService

# A UUID primary key that deliberately differs from the user's email — the
# normal case for EmailUser, and the case that exposes the bug.
USER_ID = "3f9c9b8e-8a3a-4a4a-9d3c-1b2c3d4e5f60"
USER_EMAIL = "admin@example.com"
SESSION_ID = "session-jti-1"


@pytest.mark.asyncio
async def test_csrf_token_bound_to_user_id_fails_middleware_validation():
    """Reproduces the bug: a token bound to EmailUser.id (the old admin.py
    behavior) does NOT validate against CSRFMiddleware, which derives its
    user_id from request.state.user.email.
    """
    csrf_service = CSRFService(secret="test-csrf-secret", expiry=3600)  # pragma: allowlist secret

    # Token generation bound to the JWT `sub` claim (EmailUser.id) — the bug.
    csrf_token = csrf_service.generate_csrf_token(USER_ID, SESSION_ID)

    middleware = CSRFMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok", status_code=200))

    request = MagicMock(spec=Request)
    request.method = "POST"
    request.url.path = "/llm/providers"
    request.headers = {"X-CSRF-Token": csrf_token, "origin": "http://localhost:4444"}
    request.state = MagicMock()
    request.state.user = MagicMock(email=USER_EMAIL)  # CSRFMiddleware uses .email
    request.state.jti = SESSION_ID
    request.cookies = {"jwt_token": "admin-session-jwt", "mcpgateway_csrf_token": csrf_token}

    with (
        patch("mcpgateway.middleware.csrf_middleware.settings") as mock_settings,
        patch("mcpgateway.middleware.csrf_middleware.get_csrf_service", return_value=csrf_service),
    ):
        mock_settings.csrf_enabled = True
        mock_settings.auth_required = True
        mock_settings.csrf_exempt_paths = []
        mock_settings.csrf_token_name = "X-CSRF-Token"
        mock_settings.csrf_cookie_name = "mcpgateway_csrf_token"
        mock_settings.csrf_check_referer = False

        response = await middleware.dispatch(request, call_next)

    assert response.status_code == 403
    assert b"CSRF_TOKEN_INVALID" in response.body
    call_next.assert_not_awaited()


@pytest.mark.asyncio
async def test_csrf_token_bound_to_email_passes_middleware_validation():
    """Proves the fix: a token bound to EmailUser.email (the corrected
    admin.py behavior) validates successfully against CSRFMiddleware.
    """
    csrf_service = CSRFService(secret="test-csrf-secret", expiry=3600)  # pragma: allowlist secret

    # Token generation bound to the email — matches routers/auth.py,
    # routers/email_auth.py, and the fixed admin.py.
    csrf_token = csrf_service.generate_csrf_token(USER_EMAIL, SESSION_ID)

    middleware = CSRFMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok", status_code=200))

    request = MagicMock(spec=Request)
    request.method = "POST"
    request.url.path = "/llm/providers"
    request.headers = {"X-CSRF-Token": csrf_token, "origin": "http://localhost:4444"}
    request.state = MagicMock()
    request.state.user = MagicMock(email=USER_EMAIL)
    request.state.jti = SESSION_ID
    request.cookies = {"jwt_token": "admin-session-jwt", "mcpgateway_csrf_token": csrf_token}

    with (
        patch("mcpgateway.middleware.csrf_middleware.settings") as mock_settings,
        patch("mcpgateway.middleware.csrf_middleware.get_csrf_service", return_value=csrf_service),
    ):
        mock_settings.csrf_enabled = True
        mock_settings.auth_required = True
        mock_settings.csrf_exempt_paths = []
        mock_settings.csrf_token_name = "X-CSRF-Token"
        mock_settings.csrf_cookie_name = "mcpgateway_csrf_token"
        mock_settings.csrf_check_referer = False

        response = await middleware.dispatch(request, call_next)

    assert response.status_code == 200
    call_next.assert_awaited_once_with(request)


def test_validate_csrf_token_id_vs_email_binding_differ():
    """Focused unit check on CSRFService: binding to .id and binding to
    .email produce tokens that validate against different user_id values —
    the crux of the #5739 mismatch (CSRFMiddleware always validates against
    .email, never .id).
    """
    csrf_service = CSRFService(secret="test-csrf-secret-2", expiry=3600)  # pragma: allowlist secret

    token_bound_to_id = csrf_service.generate_csrf_token(USER_ID, SESSION_ID)
    token_bound_to_email = csrf_service.generate_csrf_token(USER_EMAIL, SESSION_ID)

    # The id-bound token only validates against the id, never the email that
    # CSRFMiddleware actually uses.
    assert csrf_service.validate_csrf_token(token_bound_to_id, USER_ID, SESSION_ID) is True
    assert csrf_service.validate_csrf_token(token_bound_to_id, USER_EMAIL, SESSION_ID) is False

    # The email-bound token validates against the email CSRFMiddleware uses.
    assert csrf_service.validate_csrf_token(token_bound_to_email, USER_EMAIL, SESSION_ID) is True
    assert csrf_service.validate_csrf_token(token_bound_to_email, USER_ID, SESSION_ID) is False


def test_admin_login_binds_csrf_to_email_not_sub_claim():
    """Source-level regression guard: the Admin UI login handler must set
    csrf_user_id from the user's email, not from the JWT `sub` claim
    (EmailUser.id). A regression back to `str(payload["sub"])` would
    reintroduce #5739 even if the CSRFMiddleware tests above still pass
    against a hand-built token.
    """
    # First-Party
    from mcpgateway import admin

    source = inspect.getsource(admin)
    assert 'csrf_user_id = admin_email' in source, "csrf_user_id must bind to the admin's email (CSRFMiddleware's identity), not the JWT sub claim"
    assert 'csrf_user_id = str(payload["sub"])' not in source, "csrf_user_id must not bind to the JWT sub claim (EmailUser.id) — CSRFMiddleware validates against .email"
