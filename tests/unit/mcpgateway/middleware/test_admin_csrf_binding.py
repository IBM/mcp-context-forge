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
import datetime
from datetime import timezone
import inspect
import os
from typing import Generator
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest
from fastapi import Depends, status
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.requests import Request
from starlette.responses import Response

# First-Party
import mcpgateway.db
from mcpgateway.config import settings as settings_wrapper
from mcpgateway.db import Base, EmailUser, get_db
from mcpgateway.middleware.csrf_middleware import CSRFMiddleware
from mcpgateway.services.csrf_service import CSRFService

# A UUID primary key that deliberately differs from the user's email — the
# normal case for EmailUser, and the case that exposes the bug.
USER_ID = "3f9c9b8e-8a3a-4a4a-9d3c-1b2c3d4e5f60"
USER_EMAIL = "admin@example.com"
SESSION_ID = "session-jti-1"
SESSION_ID_2 = "session-jti-2"


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


# ---------------------------------------------------------------------------
# End-to-end regression: real /admin/login -> real /llm/providers write
# ---------------------------------------------------------------------------

ADMIN_PASSWORD = "AdminPass123!"  # pragma: allowlist secret


@pytest.fixture
def _e2e_db_engine():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture(scope="session")
def _main_app_with_llm_routes(main_app_with_admin_api):
    """Dynamically mount llm_config_router/llm_admin_router if missing.

    Mirrors ``main_app_with_admin_api`` (tests/conftest.py): the session
    bootstrap force-disables ``LLMCHAT_ENABLED`` for import speed, so
    ``/llm/providers`` (llm_config_router) isn't mounted on a plain
    ``mcpgateway.main.app`` import. Unlike the admin router, no existing
    fixture re-mounts the LLM routers, so this does it the same way.

    Also mounts ``llm_admin_router`` a second time under ``/v1/admin/llm``,
    mirroring the real production assembly in
    ``mcpgateway/api/v1/__init__.py::_assemble_routers`` (Group E), which
    includes the same router instance into both the versioned (``/v1``) and
    legacy (unprefixed) target routers. This lets tests pin findings 13/14:
    unlike ``/admin/llm/*``, the ``/v1/admin/llm/*`` mount is NOT covered by
    ``CSRFMiddleware``'s ``/admin`` exempt-path prefix match (the prefix
    match is on the raw ``/admin`` string, which does not survive the
    leading ``/v1``), so it is validated by both ``CSRFMiddleware`` and
    ``enforce_admin_csrf``.
    """
    app = main_app_with_admin_api
    existing = [r for r in app.routes if getattr(r, "path", "") == "/llm/providers"]
    if not existing:
        # First-Party
        from mcpgateway.config import get_settings
        from mcpgateway.config import settings as settings_wrapper

        os.environ["LLMCHAT_ENABLED"] = "true"
        settings_wrapper.__dict__.pop("llmchat_enabled", None)
        get_settings.cache_clear()

        from mcpgateway.admin import enforce_admin_csrf
        from mcpgateway.routers.llm_admin_router import llm_admin_router
        from mcpgateway.routers.llm_config_router import llm_config_router

        app.include_router(llm_config_router, prefix="/llm", tags=["LLM Configuration"])
        app.include_router(llm_admin_router, prefix="/admin/llm", tags=["LLM Admin"], dependencies=[Depends(enforce_admin_csrf)])

    existing_v1 = [r for r in app.routes if getattr(r, "path", "") == "/v1/admin/llm/providers/{provider_id}/state"]
    if not existing_v1:
        # First-Party
        from mcpgateway.admin import enforce_admin_csrf
        from mcpgateway.routers.llm_admin_router import llm_admin_router

        app.include_router(llm_admin_router, prefix="/v1/admin/llm", tags=["LLM Admin (v1)"], dependencies=[Depends(enforce_admin_csrf)])

    yield app


@pytest.fixture
def e2e_client(_main_app_with_llm_routes, _e2e_db_engine) -> Generator:
    """A TestClient wired to the real app/middleware stack with an isolated in-memory DB.

    Depends on ``main_app_with_admin_api`` (tests/conftest.py) because the session
    bootstrap force-disables ``MCPGATEWAY_ADMIN_API_ENABLED`` for import speed, which
    means ``admin_router`` (and therefore ``/admin/login``) isn't mounted on a plain
    ``mcpgateway.main.app`` import.
    """
    # Third-Party
    from mcpgateway.services.argon2_service import Argon2PasswordService

    # First-Party
    from mcpgateway.middleware import rbac as rbac_module

    app = _main_app_with_llm_routes
    TestSessionLocal = sessionmaker(bind=_e2e_db_engine)

    def override_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    original_session_local = mcpgateway.db.SessionLocal
    original_engine = mcpgateway.db.engine
    mcpgateway.db.SessionLocal = TestSessionLocal
    mcpgateway.db.engine = _e2e_db_engine
    app.dependency_overrides[get_db] = override_get_db
    # llm_admin_router.py depends on the deprecated `rbac.get_db` (not
    # `mcpgateway.db.get_db`), which module-level-imported `SessionLocal`
    # from mcpgateway.db at *its own* import time — a separate binding that
    # the reassignment above does not reach. Without this second override,
    # every /admin/llm/* write would silently hit whatever real SessionLocal
    # existed when rbac.py was first imported instead of this isolated
    # in-memory DB (surfacing as "no such table: llm_providers" once a
    # request actually reaches a query, since that other engine was never
    # bootstrapped with Base.metadata.create_all here).
    app.dependency_overrides[rbac_module.get_db] = override_get_db

    # settings.secure_cookies defaults to True (config.py), so jwt_token/CSRF
    # cookies are set with the Secure flag unless a local .env overrides it —
    # which CI's checkout doesn't have. httpx's TestClient models real browser
    # cookie-jar semantics: a Secure cookie set over this plain-http base_url
    # is silently dropped on the very next request, breaking the whole session
    # (dashboard load 302s back to /admin/login instead of rendering) with no
    # exception raised anywhere to explain why. Pin it False for this
    # non-TLS test transport, matching what .env.example ships for real
    # non-TLS deployments.
    _secure_cookies_was_shadowed = "secure_cookies" in settings_wrapper.__dict__
    _original_secure_cookies = settings_wrapper.__dict__.get("secure_cookies")
    settings_wrapper.__dict__["secure_cookies"] = False

    argon2 = Argon2PasswordService()
    db = TestSessionLocal()
    db.add(
        EmailUser(
            email=USER_EMAIL,
            password_hash=argon2.hash_password(ADMIN_PASSWORD),
            full_name="Admin E2E Test",
            is_admin=True,
            is_active=True,
            auth_provider="local",
            email_verified_at=datetime.datetime.now(timezone.utc),
        )
    )
    db.commit()
    db.close()

    # base_url must match settings.app_domain (default http://localhost:4444) so
    # Origin/Referer checks in CSRFMiddleware and the RBAC same-origin-referer
    # check both see a host they actually allow (TestClient's default
    # "testserver" host matches neither).
    yield TestClient(app, base_url="http://localhost:4444")

    app.dependency_overrides.clear()
    mcpgateway.db.SessionLocal = original_session_local
    mcpgateway.db.engine = original_engine
    if _secure_cookies_was_shadowed:
        settings_wrapper.__dict__["secure_cookies"] = _original_secure_cookies
    else:
        settings_wrapper.__dict__.pop("secure_cookies", None)


def test_admin_login_csrf_token_validates_llm_provider_write(e2e_client):
    """End-to-end regression for #5739: a real /admin/login must produce a CSRF
    cookie that a subsequent /llm/providers write actually validates against.

    This exercises the full stack (real login handler, real CSRFMiddleware,
    real RBAC) rather than hand-built Request mocks, so a regression in how the
    login handler binds `csrf_user_id` (or in how CSRFMiddleware derives its
    own identity) would be caught here even if the more targeted unit tests
    above still pass.
    """
    login_resp = e2e_client.post(
        "/admin/login",
        data={"email": USER_EMAIL, "password": ADMIN_PASSWORD},
        follow_redirects=False,
    )
    assert login_resp.status_code == 303, login_resp.text
    assert "jwt_token" in e2e_client.cookies

    # A real browser auto-follows the 303 to GET /admin/. That first dashboard
    # load is what actually rotates the CSRF cookie to the HMAC-bound value
    # (see admin_ui()'s csrf_user_id/csrf_session_id binding in admin.py) —
    # the login handler itself only sets an opaque, non-HMAC placeholder.
    dashboard_resp = e2e_client.get("/admin/", headers={"origin": "http://localhost:4444", "accept": "text/html"})
    assert dashboard_resp.status_code == 200, dashboard_resp.text
    csrf_token = e2e_client.cookies.get("mcpgateway_csrf_token")
    assert csrf_token, "dashboard load must set the mcpgateway_csrf_token cookie"

    create_resp = e2e_client.post(
        "/llm/providers",
        json={"name": "e2e-test-provider", "provider_type": "openai"},
        headers={"X-CSRF-Token": csrf_token, "referer": "http://localhost:4444/admin/"},
    )

    assert create_resp.status_code != 403, create_resp.text
    assert "CSRF_TOKEN_INVALID" not in create_resp.text
    assert create_resp.status_code == status.HTTP_201_CREATED, create_resp.text


def test_csrf_middleware_runs_after_auth_context_middleware():
    """Regression guard for the middleware registration-order bug fixed
    alongside #5739: ``CSRFMiddleware`` must be registered *before*
    ``AuthContextMiddleware`` in ``main.py`` so that, per Starlette's
    reverse-registration-order execution, it actually runs *after*
    ``AuthContextMiddleware`` has populated ``request.state.user``.

    Getting this backwards makes CSRFMiddleware silently fall back to
    resolving identity from the raw JWT `sub` claim (EmailUser.id) instead
    of the email admin.py binds CSRF tokens to — reintroducing #5739 even
    though the HMAC-binding fix itself is correct.
    """
    # First-Party
    from mcpgateway.main import app
    from mcpgateway.middleware.auth_middleware import AuthContextMiddleware
    from mcpgateway.middleware.csrf_middleware import CSRFMiddleware

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


def test_admin_login_csrf_token_rejected_without_header(e2e_client):
    """Sanity check for the harness itself: the same write without the CSRF
    header must still 403, proving the positive-path test above isn't passing
    because CSRF enforcement is silently disabled in this test setup.
    """
    login_resp = e2e_client.post(
        "/admin/login",
        data={"email": USER_EMAIL, "password": ADMIN_PASSWORD},
        follow_redirects=False,
    )
    assert login_resp.status_code == 303, login_resp.text

    create_resp = e2e_client.post(
        "/llm/providers",
        json={"name": "e2e-test-provider-2", "provider_type": "openai"},
        headers={"origin": "http://localhost:4444"},
    )

    assert create_resp.status_code == 403
    assert "CSRF_TOKEN_INVALID" in create_resp.text


# ---------------------------------------------------------------------------
# End-to-end regression: enforce_admin_csrf path (/admin/llm/* and
# /v1/admin/llm/*), as opposed to the CSRFMiddleware path exercised above.
#
# `enforce_admin_csrf` (admin.py:1803) is a distinct implementation from
# CSRFMiddleware: hardcoded cookie/header names, a plain double-submit
# comparison (no HMAC), and its own three-way error surface. Nothing outside
# this file issues a real request against it, so these tests pin its actual
# deny/allow behavior rather than only asserting it is present as a FastAPI
# dependency (see tests/unit/mcpgateway/test_api_versioning_parity.py).
# ---------------------------------------------------------------------------

LLM_ADMIN_STATE_PATH = "/admin/llm/providers/e2e-nonexistent-provider/state"
LLM_ADMIN_STATE_PATH_V1 = "/v1/admin/llm/providers/e2e-nonexistent-provider/state"


def _login_and_prime_admin_session(client: TestClient) -> str:
    """Perform a real ``/admin/login`` then the dashboard GET that rotates the
    CSRF cookie to its HMAC-bound value.

    Mirrors the login+dashboard sequence in
    ``test_admin_login_csrf_token_validates_llm_provider_write`` above:
    ``admin_login_handler`` (admin.py) itself only sets an opaque,
    non-HMAC-bound CSRF cookie via ``_set_admin_csrf_cookie(request,
    response)``; it is the *dashboard* load (``admin_ui()``, which supplies
    ``user_id``/``session_id``) that rotates the cookie to its real HMAC
    value. Every ``enforce_admin_csrf`` case below runs against this fully
    primed session — both to match real browser behavior and to avoid the
    vacuous-pass hazard where ``enforce_admin_csrf`` no-ops entirely without
    a ``jwt_token`` cookie (admin.py:1818-1822).

    Args:
        client: The e2e TestClient to authenticate.

    Returns:
        The CSRF token value now held in the client's cookie jar.
    """
    login_resp = client.post(
        "/admin/login",
        data={"email": USER_EMAIL, "password": ADMIN_PASSWORD},
        follow_redirects=False,
    )
    assert login_resp.status_code == 303, login_resp.text
    assert "jwt_token" in client.cookies

    dashboard_resp = client.get("/admin/", headers={"origin": "http://localhost:4444", "accept": "text/html"})
    assert dashboard_resp.status_code == 200, dashboard_resp.text

    csrf_token = client.cookies.get("mcpgateway_csrf_token")
    assert csrf_token, "dashboard load must set the mcpgateway_csrf_token cookie"
    return csrf_token


def test_enforce_admin_csrf_allows_matching_header_and_cookie(e2e_client):
    """Happy path: session cookie + matching X-CSRF-Token header + good
    Origin must not 403 against the enforce_admin_csrf-only /admin/llm/*
    mount. The write 404s (provider does not exist) rather than 2xx,
    proving the request reached the handler without depending on
    provider/service state — the outcome under test is the CSRF verdict,
    not the business result.
    """
    csrf_token = _login_and_prime_admin_session(e2e_client)

    resp = e2e_client.post(
        LLM_ADMIN_STATE_PATH,
        headers={"x-csrf-token": csrf_token, "origin": "http://localhost:4444", "accept": "text/html"},
    )

    assert resp.status_code != 403, resp.text
    assert resp.status_code == status.HTTP_404_NOT_FOUND, resp.text


def test_enforce_admin_csrf_rejects_missing_header(e2e_client):
    """Header missing entirely -> 403 'CSRF token validation failed'."""
    _login_and_prime_admin_session(e2e_client)

    resp = e2e_client.post(
        LLM_ADMIN_STATE_PATH,
        headers={"origin": "http://localhost:4444"},
    )

    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == "CSRF token validation failed"


def test_enforce_admin_csrf_rejects_header_not_matching_cookie(e2e_client):
    """Header present but != cookie -> 403 'CSRF token validation failed'."""
    _login_and_prime_admin_session(e2e_client)

    resp = e2e_client.post(
        LLM_ADMIN_STATE_PATH,
        headers={"x-csrf-token": "attacker-supplied-token-does-not-match", "origin": "http://localhost:4444"},
    )

    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == "CSRF token validation failed"


def test_enforce_admin_csrf_rejects_missing_cookie(e2e_client):
    """CSRF cookie absent (header present) -> 403 'CSRF token cookie missing'.

    The header carries a syntactically valid (previously real) token, but
    the cookie half of the double-submit pair has been stripped from the
    client's cookie jar — simulating a cookie that expired, was cleared, or
    was never set for this origin.
    """
    csrf_token = _login_and_prime_admin_session(e2e_client)
    del e2e_client.cookies["mcpgateway_csrf_token"]

    resp = e2e_client.post(
        LLM_ADMIN_STATE_PATH,
        headers={"x-csrf-token": csrf_token, "origin": "http://localhost:4444"},
    )

    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == "CSRF token cookie missing"


def test_enforce_admin_csrf_rejects_bad_origin(e2e_client):
    """Missing Origin/Referer -> 403 'CSRF origin validation failed'.

    enforce_admin_csrf checks origin before either CSRF-token check, so this
    fails even though the header/cookie pair below is fully valid.
    """
    csrf_token = _login_and_prime_admin_session(e2e_client)

    resp = e2e_client.post(
        LLM_ADMIN_STATE_PATH,
        headers={"x-csrf-token": csrf_token},
    )

    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == "CSRF origin validation failed"


def test_enforce_admin_csrf_allows_form_encoded_csrf_token_field(e2e_client):
    """Form-encoded body with a csrf_token field, no header -> not 403.

    enforce_admin_csrf falls back to reading ``csrf_token`` out of an
    ``application/x-www-form-urlencoded`` body when the header is absent
    (admin.py:1832-1841) — the classic HTML-form (non-JS) submission shape.
    """
    csrf_token = _login_and_prime_admin_session(e2e_client)

    resp = e2e_client.post(
        LLM_ADMIN_STATE_PATH,
        data={"csrf_token": csrf_token},
        headers={"origin": "http://localhost:4444", "accept": "text/html"},
    )

    assert resp.status_code != 403, resp.text
    assert resp.status_code == status.HTTP_404_NOT_FOUND, resp.text


def test_enforce_admin_csrf_bypassed_for_bearer_token_without_session_cookie(e2e_client):
    """A Bearer-token API call with no jwt_token session cookie is not
    subject to enforce_admin_csrf at all (admin.py:1818-1822: 'CSRF is
    relevant only for browser cookie auth').

    No login, no CSRF header, no CSRF cookie, no Origin — every ingredient
    enforce_admin_csrf would otherwise demand is absent, and the request
    still is not blocked at the CSRF layer, because there is no jwt_token
    cookie to make CSRF relevant in the first place. The 404 (rather than a
    403) proves the request reached the handler.
    """
    # Standard
    import asyncio

    # First-Party
    import mcpgateway.db as db_mod
    from mcpgateway.routers.email_auth import create_access_token

    with db_mod.SessionLocal() as db:
        user = db.query(EmailUser).filter_by(email=USER_EMAIL).first()
        assert user is not None
        bearer_token, _ = asyncio.run(create_access_token(user))

    assert "jwt_token" not in e2e_client.cookies

    resp = e2e_client.post(
        LLM_ADMIN_STATE_PATH,
        headers={"authorization": f"Bearer {bearer_token}"},
    )

    assert resp.status_code != 403, resp.text
    assert resp.status_code == status.HTTP_404_NOT_FOUND, resp.text


def test_admin_llm_write_agrees_across_legacy_and_v1_mounts_after_dashboard_rotation(e2e_client):
    """Pin findings 13/14 (positive case): once a session has visited the
    dashboard (so the CSRF cookie has been rotated to its real HMAC-bound
    value), an identical write against the legacy ``/admin/llm/*`` mount
    (enforce_admin_csrf only, per finding 13 — exempt from CSRFMiddleware
    via the ``/admin`` prefix match) and the versioned ``/v1/admin/llm/*``
    mount (enforce_admin_csrf AND CSRFMiddleware, since ``/v1/admin`` does
    not match the ``/admin`` exempt-path prefix) agree: neither 403s.

    This is the steady-state a real browser session reaches after the first
    dashboard load, so it is the common case. See
    ``test_admin_llm_write_diverges_between_mounts_immediately_after_login``
    below for the narrower window, right after login and before any
    dashboard visit, where finding 14 shows the two mounts do NOT agree.
    """
    csrf_token = _login_and_prime_admin_session(e2e_client)
    headers = {"x-csrf-token": csrf_token, "origin": "http://localhost:4444", "referer": "http://localhost:4444/admin/"}

    legacy_resp = e2e_client.post(LLM_ADMIN_STATE_PATH, headers=headers)
    v1_resp = e2e_client.post(LLM_ADMIN_STATE_PATH_V1, headers=headers)

    assert legacy_resp.status_code != 403, legacy_resp.text
    assert v1_resp.status_code != 403, v1_resp.text
    assert legacy_resp.status_code == status.HTTP_404_NOT_FOUND, legacy_resp.text
    assert v1_resp.status_code == status.HTTP_404_NOT_FOUND, v1_resp.text


def test_admin_llm_write_diverges_between_mounts_immediately_after_login(e2e_client):
    """Pins finding 14: the fallback-token divergence is real and reachable
    in a normal session, in the window between login and the first
    dashboard load.

    ``admin_login_handler`` (admin.py:4634) sets the CSRF cookie via
    ``_set_admin_csrf_cookie(request, response)`` with NO ``user_id``/
    ``session_id`` — the opaque ``secrets.token_urlsafe(32)`` fallback
    (admin.py:1766-1770), not an HMAC token. It is only the *dashboard* GET
    (``admin_ui()``, admin.py:4371) that supplies ``user_id``/``session_id``
    and rotates the cookie to its HMAC-bound value.

    A client that writes to ``/admin/llm/*`` right after login — before
    ever loading the dashboard — presents this opaque cookie. That is
    sufficient for ``enforce_admin_csrf``'s plain
    ``secrets.compare_digest(header, cookie)`` double-submit check (which
    has no concept of HMAC), so the legacy mount accepts the write. But the
    identical write to ``/v1/admin/llm/*`` also traverses
    ``CSRFMiddleware``, whose ``CSRFService.validate_csrf_token()`` check
    requires the cookie to be a real HMAC token for the caller's
    (email, jti) — an opaque token is not, so it 403s with
    ``CSRF_TOKEN_INVALID``.

    Net effect: the exact same session, same cookie, same header, same
    origin — accepted at ``/admin/llm/*``, rejected at
    ``/v1/admin/llm/*``. This is not a hypothetical; it is what actually
    happens below. This is a real behavioral gap worth a follow-up fix; this
    test pins the current (divergent) behavior rather than asserting the two
    mounts agree, so a fix — or a further regression — shows up here.
    """
    login_resp = e2e_client.post(
        "/admin/login",
        data={"email": USER_EMAIL, "password": ADMIN_PASSWORD},
        follow_redirects=False,
    )
    assert login_resp.status_code == 303, login_resp.text

    csrf_token = e2e_client.cookies.get("mcpgateway_csrf_token")
    assert csrf_token, "admin_login_handler must set an (opaque, pre-rotation) CSRF cookie"

    headers = {"x-csrf-token": csrf_token, "origin": "http://localhost:4444", "referer": "http://localhost:4444/admin/"}

    legacy_resp = e2e_client.post(LLM_ADMIN_STATE_PATH, headers=headers)
    v1_resp = e2e_client.post(LLM_ADMIN_STATE_PATH_V1, headers=headers)

    # Legacy mount: enforce_admin_csrf only, plain double-submit -> accepted.
    assert legacy_resp.status_code != 403, legacy_resp.text
    assert legacy_resp.status_code == status.HTTP_404_NOT_FOUND, legacy_resp.text

    # Versioned mount: enforce_admin_csrf passes the same way, but
    # CSRFMiddleware's HMAC check on the opaque token fails -> 403.
    assert v1_resp.status_code == 403, v1_resp.text
    assert "CSRF_TOKEN_INVALID" in v1_resp.text
