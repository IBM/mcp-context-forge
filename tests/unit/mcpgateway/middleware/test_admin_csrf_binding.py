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
from mcpgateway.db import Base, EmailUser, get_db
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
