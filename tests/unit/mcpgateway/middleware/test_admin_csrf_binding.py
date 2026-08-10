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
``test_csrf_middleware.py``), assert that ``admin.py``'s login handler source
binds ``csrf_user_id`` to the email, pin the middleware registration order
via ``mcpgateway.middleware.auth_context_stack.register_auth_context_middleware``, and unit-test
``enforce_admin_csrf`` by direct call.

This file intentionally contains no full-stack tests. Earlier revisions drove
real ``/admin/login`` -> dashboard -> ``/llm/*`` flows through a TestClient
wired to the shared ``mcpgateway.main.app`` singleton; those passed in
isolation but failed under the full suite because middleware registration is
import-time and settings-dependent (``AuthContextMiddleware`` is absent when
``MCPGATEWAY_ADMIN_API_ENABLED=false`` at first import, and xdist workers
import ``mcpgateway.main`` during collection). End-to-end CSRF coverage lives
in the Playwright suite (``tests/playwright/security/``), where a real
assembled gateway exists.
"""

# Standard
import contextlib
import inspect
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest
from fastapi import HTTPException
from starlette.datastructures import URL
from starlette.requests import Request
from starlette.responses import Response

# First-Party
from mcpgateway.config import settings as settings_wrapper
from mcpgateway.middleware.csrf_middleware import CSRFMiddleware
from mcpgateway.services.csrf_service import CSRFService

# A UUID primary key that deliberately differs from the user's email — the
# normal case for EmailUser, and the case that exposes the bug.
USER_ID = "3f9c9b8e-8a3a-4a4a-9d3c-1b2c3d4e5f60"
USER_EMAIL = "admin@example.com"
SESSION_ID = "session-jti-1"
SESSION_ID_2 = "session-jti-2"


@contextlib.contextmanager
def _shadow_settings(**overrides):
    """Temporarily shadow LazySettingsWrapper attributes via instance ``__dict__``.

    ``monkeypatch.setattr`` is unreliable on ``LazySettingsWrapper``: because
    ``__getattr__`` resolves every key, monkeypatch records a pre-existing
    value and restores it via ``setattr`` at teardown, permanently shadowing
    the wrapper. Direct ``__dict__`` manipulation with explicit restore
    avoids that leak.

    Args:
        **overrides: Setting names and the values to shadow them with.
    """
    sentinel = object()
    saved = {key: settings_wrapper.__dict__.get(key, sentinel) for key in overrides}
    settings_wrapper.__dict__.update(overrides)
    try:
        yield
    finally:
        for key, value in saved.items():
            if value is sentinel:
                settings_wrapper.__dict__.pop(key, None)
            else:
                settings_wrapper.__dict__[key] = value


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

    assert response.status_code == 403, response.body
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

    assert response.status_code == 200, response.body
    call_next.assert_awaited_once_with(request)


@pytest.mark.asyncio
async def test_csrf_token_bound_to_wrong_session_id_fails_validation():
    """Proves CSRF validation fails when the session_id does not match: a token
    bound to the correct email but a different `jti` (session_id) does NOT
    validate against CSRFMiddleware, which derives session_id from
    request.state.jti.
    """
    csrf_service = CSRFService(secret="test-csrf-secret", expiry=3600)  # pragma: allowlist secret

    # Token generation bound to the correct email but SESSION_ID.
    csrf_token = csrf_service.generate_csrf_token(USER_EMAIL, SESSION_ID)

    middleware = CSRFMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok", status_code=200))

    request = MagicMock(spec=Request)
    request.method = "POST"
    request.url.path = "/llm/providers"
    request.headers = {"X-CSRF-Token": csrf_token, "origin": "http://localhost:4444"}
    request.state = MagicMock()
    request.state.user = MagicMock(email=USER_EMAIL)  # CSRFMiddleware uses .email
    request.state.jti = SESSION_ID_2  # But the session_id is different — the bug
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

    assert response.status_code == 403, response.body
    assert b"CSRF_TOKEN_INVALID" in response.body
    call_next.assert_not_awaited()


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


def test_validate_csrf_token_session_id_binding_differs():
    """Focused unit check on CSRFService: a token bound to one session_id
    does NOT validate against a different session_id — ensuring the
    session_id is part of the HMAC binding.
    """
    csrf_service = CSRFService(secret="test-csrf-secret-3", expiry=3600)  # pragma: allowlist secret

    token_bound_to_session_1 = csrf_service.generate_csrf_token(USER_EMAIL, SESSION_ID)
    token_bound_to_session_2 = csrf_service.generate_csrf_token(USER_EMAIL, SESSION_ID_2)

    # The session-1 bound token only validates against session-1, never
    # against session-2.
    assert csrf_service.validate_csrf_token(token_bound_to_session_1, USER_EMAIL, SESSION_ID) is True
    assert csrf_service.validate_csrf_token(token_bound_to_session_1, USER_EMAIL, SESSION_ID_2) is False

    # The session-2 bound token validates only against session-2.
    assert csrf_service.validate_csrf_token(token_bound_to_session_2, USER_EMAIL, SESSION_ID_2) is True
    assert csrf_service.validate_csrf_token(token_bound_to_session_2, USER_EMAIL, SESSION_ID) is False


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


def test_main_calls_register_auth_context_middleware_before_router_mounting():
    """Source-level regression guard for issue #6025: mcpgateway/main.py must
    call ``register_auth_context_middleware(app)`` and that call must appear
    *before* the first ``app.include_router(`` so middleware is registered on
    the application before any routes are mounted.

    The existing tests in this file exercise the helper against a bare
    FastAPI app; they would continue to pass even if the call were silently
    removed from main.py.  This guard closes that gap by reading the actual
    production source.
    """
    # Standard
    from importlib import resources

    source = resources.files("mcpgateway").joinpath("main.py").read_text(encoding="utf-8")

    call_token = "register_auth_context_middleware(app)"
    router_token = "app.include_router("

    assert call_token in source, (
        "register_auth_context_middleware(app) not found in mcpgateway/main.py — "
        "the production middleware registration has been removed (issue #6025)"
    )
    assert router_token in source, (
        "app.include_router( not found in mcpgateway/main.py — "
        "cannot verify middleware-before-router ordering"
    )

    call_pos = source.index(call_token)
    router_pos = source.index(router_token)

    assert call_pos < router_pos, (
        f"register_auth_context_middleware(app) (offset {call_pos}) must appear "
        f"before the first app.include_router( (offset {router_pos}) in "
        "mcpgateway/main.py — middleware must be registered before routes are mounted"
    )


# ---------------------------------------------------------------------------
# Middleware registration order (issue #5739 companion fix)
#
# These tests exercise ``mcpgateway.middleware.auth_context_stack``'s
# against a bare FastAPI app. They replace a previous guard that inspected
# the shared ``mcpgateway.main.app`` singleton: that version was hostage to
# which settings were in effect when some other module first imported
# ``mcpgateway.main`` (middleware registration is import-time), so it failed
# under the full xdist suite while passing in isolation.
# ---------------------------------------------------------------------------


def test_csrf_middleware_runs_after_auth_context_middleware():
    """Regression guard for the middleware registration-order bug fixed
    alongside #5739: ``CSRFMiddleware`` must be registered *before*
    ``AuthContextMiddleware`` so that, per Starlette's
    reverse-registration-order execution, it actually runs *after*
    ``AuthContextMiddleware`` has populated ``request.state.user``.

    Getting this backwards makes CSRFMiddleware silently fall back to
    resolving identity from the raw JWT `sub` claim (EmailUser.id) instead
    of the email admin.py binds CSRF tokens to — reintroducing #5739 even
    though the HMAC-binding fix itself is correct.
    """
    # Third-Party
    from fastapi import FastAPI

    # First-Party
    from mcpgateway.middleware.auth_context_stack import register_auth_context_middleware
    from mcpgateway.middleware.auth_middleware import AuthContextMiddleware

    with _shadow_settings(
        csrf_enabled=True,
        mcpgateway_admin_api_enabled=True,
        security_logging_enabled=False,
        siem_export_enabled=False,
        password_change_enforcement_enabled=False,
    ):
        app = FastAPI()
        register_auth_context_middleware(app)

    middleware_classes = [m.cls for m in app.user_middleware]
    assert AuthContextMiddleware in middleware_classes, "AuthContextMiddleware must be registered for this regression guard to be meaningful"
    assert CSRFMiddleware in middleware_classes, "CSRFMiddleware must be registered for this regression guard to be meaningful"

    auth_index = middleware_classes.index(AuthContextMiddleware)
    csrf_index = middleware_classes.index(CSRFMiddleware)

    # Starlette executes app.user_middleware in list order on the way in, so
    # a lower index runs FIRST. AuthContextMiddleware must run before
    # CSRFMiddleware so request.state.user is populated by the time
    # CSRFMiddleware reads it.
    assert auth_index < csrf_index, f"AuthContextMiddleware (index {auth_index}) must run before CSRFMiddleware (index {csrf_index}) so request.state.user is populated for CSRF identity resolution"


def test_password_change_enforcement_runs_between_auth_context_and_csrf():
    """With password-change enforcement enabled, the execution order must be
    AuthContextMiddleware -> PasswordChangeEnforcementMiddleware ->
    CSRFMiddleware: enforcement needs ``request.state.user`` from
    AuthContextMiddleware, and CSRF validation stays innermost.
    """
    # Third-Party
    from fastapi import FastAPI

    # First-Party
    from mcpgateway.middleware.auth_context_stack import register_auth_context_middleware
    from mcpgateway.middleware.auth_middleware import AuthContextMiddleware
    from mcpgateway.middleware.password_change_enforcement import PasswordChangeEnforcementMiddleware

    with _shadow_settings(
        csrf_enabled=True,
        mcpgateway_admin_api_enabled=False,
        security_logging_enabled=False,
        siem_export_enabled=False,
        password_change_enforcement_enabled=True,
    ):
        app = FastAPI()
        register_auth_context_middleware(app)

    middleware_classes = [m.cls for m in app.user_middleware]
    auth_index = middleware_classes.index(AuthContextMiddleware)
    pce_index = middleware_classes.index(PasswordChangeEnforcementMiddleware)
    csrf_index = middleware_classes.index(CSRFMiddleware)

    assert auth_index < pce_index < csrf_index, f"Execution order must be AuthContext ({auth_index}) -> PasswordChangeEnforcement ({pce_index}) -> CSRF ({csrf_index})"


def test_auth_context_middleware_registration_is_conditional():
    """Pins the conditional-registration behavior that made the old
    app-singleton tests order-dependent: with the session bootstrap's minimal
    feature flags (admin API disabled, security logging off, no SIEM auth
    source, no password enforcement), the assembled app legitimately has NO
    AuthContextMiddleware — so any test that needs ``request.state.user``
    populated must not rely on the shared ``mcpgateway.main.app``.
    """
    # Third-Party
    from fastapi import FastAPI

    # First-Party
    from mcpgateway.middleware.auth_context_stack import register_auth_context_middleware
    from mcpgateway.middleware.auth_middleware import AuthContextMiddleware

    with _shadow_settings(
        csrf_enabled=True,
        mcpgateway_admin_api_enabled=False,
        security_logging_enabled=False,
        siem_export_enabled=False,
        password_change_enforcement_enabled=False,
    ):
        app = FastAPI()
        register_auth_context_middleware(app)

    middleware_classes = [m.cls for m in app.user_middleware]
    assert AuthContextMiddleware not in middleware_classes
    assert CSRFMiddleware in middleware_classes


@pytest.mark.asyncio
async def test_csrf_fallback_preserves_existing_user_id():
    """Regression guard: when ``request.state.user`` already resolved
    ``user_id`` from the email but ``request.state.jti`` is unset (e.g. a
    local/session login where no JWT `jti` is minted), the JWT-decode
    fallback must fill in ONLY the missing ``session_id`` — it must NOT
    also re-resolve ``user_id`` from the JWT `sub` claim (EmailUser.id) and
    clobber the already-correct email.

    Before the fix, the fallback unconditionally overwrote both fields
    whenever either was missing, so this exact case (user_id present,
    session_id absent) would have silently rebound the CSRF identity to
    EmailUser.id and failed validation even with everything else correct.
    """
    csrf_service = CSRFService(secret="test-csrf-secret-3", expiry=3600)  # pragma: allowlist secret

    # Token bound to the email + session id that request.state should end up
    # resolving to.
    csrf_token = csrf_service.generate_csrf_token(USER_EMAIL, SESSION_ID)

    # A JWT whose `sub` is the (different) user id — if the fallback
    # incorrectly overwrote user_id, it would pick this up instead of the
    # already-resolved email and the token would fail validation.
    jwt_payload = {"sub": USER_ID, "email": USER_EMAIL, "jti": SESSION_ID}

    middleware = CSRFMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok", status_code=200))

    request = MagicMock(spec=Request)
    request.method = "POST"
    request.url.path = "/llm/providers"
    request.headers = {"X-CSRF-Token": csrf_token, "origin": "http://localhost:4444"}
    request.state = MagicMock()
    request.state.user = MagicMock(email=USER_EMAIL)  # user_id already resolvable from here
    request.state.jti = None  # session_id NOT resolvable from request.state — must fall back
    request.cookies = {"jwt_token": "admin-session-jwt", "mcpgateway_csrf_token": csrf_token}

    with (
        patch("mcpgateway.middleware.csrf_middleware.settings") as mock_settings,
        patch("mcpgateway.middleware.csrf_middleware.get_csrf_service", return_value=csrf_service),
        patch("mcpgateway.middleware.csrf_middleware.verify_jwt_token_cached", AsyncMock(return_value=jwt_payload)),
    ):
        mock_settings.csrf_enabled = True
        mock_settings.auth_required = True
        mock_settings.csrf_exempt_paths = []
        mock_settings.csrf_token_name = "X-CSRF-Token"
        mock_settings.csrf_cookie_name = "mcpgateway_csrf_token"
        mock_settings.csrf_check_referer = False

        response = await middleware.dispatch(request, call_next)

    assert response.status_code == 200, response.body
    call_next.assert_awaited_once_with(request)


# ---------------------------------------------------------------------------
# enforce_admin_csrf (admin.py) — direct-call unit tests
#
# ``enforce_admin_csrf`` is a distinct implementation from CSRFMiddleware:
# hardcoded cookie/header names, a plain double-submit comparison (no HMAC),
# and its own three-way error surface. These tests call the dependency
# function directly with a mocked Request, replacing earlier full-stack
# versions that needed the assembled app (and were therefore hostage to
# import-order pollution of the shared ``mcpgateway.main.app`` singleton).
# ---------------------------------------------------------------------------

CSRF_COOKIE = "mcpgateway_csrf_token"  # ADMIN_CSRF_COOKIE_NAME (admin.py)
CSRF_HEADER = "x-csrf-token"  # ADMIN_CSRF_HEADER_NAME (admin.py)
ADMIN_URL = "http://localhost:4444/admin/llm/providers/e2e-nonexistent-provider/state"
DOUBLE_SUBMIT_TOKEN = "double-submit-token-value-0123456789"  # pragma: allowlist secret


def _make_admin_request(*, method="POST", cookies=None, headers=None, form=None):
    """Build a mocked Request for direct ``enforce_admin_csrf`` calls.

    Args:
        method: HTTP method (safe methods short-circuit the check).
        cookies: Cookie dict; ``jwt_token`` presence is what makes CSRF
            relevant at all.
        headers: Header dict; origin/referer/host feed
            ``_request_origin_matches``.
        form: When provided, ``request.form()`` returns this dict (for the
            form-encoded token fallback).

    Returns:
        A ``MagicMock(spec=Request)`` with a real ``URL`` so scheme/netloc
        comparisons in ``_request_origin_matches`` behave realistically.
    """
    request = MagicMock(spec=Request)
    request.method = method
    request.cookies = dict(cookies or {})
    request.headers = dict(headers or {})
    request.url = URL(ADMIN_URL)
    if form is not None:
        request.form = AsyncMock(return_value=form)
    return request


def _primed_cookies():
    """Cookies for a fully primed admin session: JWT session + CSRF cookie."""
    return {"jwt_token": "admin-session-jwt", CSRF_COOKIE: DOUBLE_SUBMIT_TOKEN}


def _good_headers():
    """Headers that pass origin validation and double-submit comparison."""
    return {CSRF_HEADER: DOUBLE_SUBMIT_TOKEN, "origin": "http://localhost:4444", "host": "localhost:4444"}


@pytest.mark.asyncio
async def test_enforce_admin_csrf_allows_matching_header_and_cookie():
    """Happy path: session cookie + matching X-CSRF-Token header + good
    Origin must pass without raising."""
    # First-Party
    from mcpgateway.admin import enforce_admin_csrf

    request = _make_admin_request(cookies=_primed_cookies(), headers=_good_headers())

    await enforce_admin_csrf(request)  # must not raise


@pytest.mark.asyncio
async def test_enforce_admin_csrf_rejects_missing_header():
    """Header missing entirely -> 403 'CSRF token validation failed'."""
    # First-Party
    from mcpgateway.admin import enforce_admin_csrf

    headers = _good_headers()
    del headers[CSRF_HEADER]
    request = _make_admin_request(cookies=_primed_cookies(), headers=headers)

    with pytest.raises(HTTPException) as exc_info:
        await enforce_admin_csrf(request)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "CSRF token validation failed"


@pytest.mark.asyncio
async def test_enforce_admin_csrf_rejects_header_not_matching_cookie():
    """Header present but != cookie -> 403 'CSRF token validation failed'."""
    # First-Party
    from mcpgateway.admin import enforce_admin_csrf

    headers = _good_headers()
    headers[CSRF_HEADER] = "attacker-supplied-token-does-not-match"
    request = _make_admin_request(cookies=_primed_cookies(), headers=headers)

    with pytest.raises(HTTPException) as exc_info:
        await enforce_admin_csrf(request)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "CSRF token validation failed"


@pytest.mark.asyncio
async def test_enforce_admin_csrf_rejects_missing_cookie():
    """CSRF cookie absent (header present) -> 403 'CSRF token cookie missing'.

    The header carries a syntactically valid token, but the cookie half of
    the double-submit pair is gone — simulating a cookie that expired, was
    cleared, or was never set for this origin.
    """
    # First-Party
    from mcpgateway.admin import enforce_admin_csrf

    cookies = _primed_cookies()
    del cookies[CSRF_COOKIE]
    request = _make_admin_request(cookies=cookies, headers=_good_headers())

    with pytest.raises(HTTPException) as exc_info:
        await enforce_admin_csrf(request)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "CSRF token cookie missing"


@pytest.mark.asyncio
async def test_enforce_admin_csrf_rejects_missing_origin():
    """Missing Origin/Referer -> 403 'CSRF origin validation failed'.

    enforce_admin_csrf checks origin before either CSRF-token check, so this
    fails even though the header/cookie pair below is fully valid.
    """
    # First-Party
    from mcpgateway.admin import enforce_admin_csrf

    headers = _good_headers()
    del headers["origin"]
    request = _make_admin_request(cookies=_primed_cookies(), headers=headers)

    with pytest.raises(HTTPException) as exc_info:
        await enforce_admin_csrf(request)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "CSRF origin validation failed"


@pytest.mark.asyncio
async def test_enforce_admin_csrf_rejects_wrong_origin():
    """Present but non-matching Origin -> 403 'CSRF origin validation failed'.

    A present-but-wrong Origin exercises the ``settings.allowed_origins``
    fallback branch of ``_request_origin_matches`` (admin.py): the
    exact-same-origin comparison against the request's host fails, and the
    candidate origin is absent from ``allowed_origins``, so the request is
    rejected via different code than the missing-header case.
    """
    # First-Party
    from mcpgateway.admin import enforce_admin_csrf

    headers = _good_headers()
    headers["origin"] = "https://evil.example"
    request = _make_admin_request(cookies=_primed_cookies(), headers=headers)

    with _shadow_settings(allowed_origins=[]):
        with pytest.raises(HTTPException) as exc_info:
            await enforce_admin_csrf(request)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "CSRF origin validation failed"


@pytest.mark.asyncio
async def test_enforce_admin_csrf_allows_form_encoded_csrf_token_field():
    """Form-encoded body with a csrf_token field, no header -> passes.

    enforce_admin_csrf falls back to reading ``csrf_token`` out of an
    ``application/x-www-form-urlencoded`` body when the header is absent
    (admin.py) — the classic HTML-form (non-JS) submission shape.
    """
    # First-Party
    from mcpgateway.admin import enforce_admin_csrf

    headers = {"origin": "http://localhost:4444", "host": "localhost:4444", "content-type": "application/x-www-form-urlencoded"}
    request = _make_admin_request(cookies=_primed_cookies(), headers=headers, form={"csrf_token": DOUBLE_SUBMIT_TOKEN})

    await enforce_admin_csrf(request)  # must not raise


@pytest.mark.asyncio
async def test_enforce_admin_csrf_bypassed_without_session_cookie():
    """A request with no jwt_token session cookie is not subject to
    enforce_admin_csrf at all (admin.py: 'CSRF is relevant only for browser
    cookie auth').

    No login, no CSRF header, no CSRF cookie, no Origin — every ingredient
    enforce_admin_csrf would otherwise demand is absent, and the call still
    is not blocked, because there is no jwt_token cookie to make CSRF
    relevant in the first place.
    """
    # First-Party
    from mcpgateway.admin import enforce_admin_csrf

    request = _make_admin_request(cookies={}, headers={})

    await enforce_admin_csrf(request)  # must not raise


@pytest.mark.asyncio
async def test_enforce_admin_csrf_skips_safe_methods():
    """Safe methods (GET/HEAD/OPTIONS/TRACE) short-circuit before any check,
    even with a session cookie present and no CSRF token anywhere."""
    # First-Party
    from mcpgateway.admin import enforce_admin_csrf

    request = _make_admin_request(method="GET", cookies=_primed_cookies(), headers={})

    await enforce_admin_csrf(request)  # must not raise
