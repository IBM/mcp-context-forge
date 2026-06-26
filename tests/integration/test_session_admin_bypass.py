# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_session_admin_bypass.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Integration tests for session token admin bypass (PR #5232, issue #5232).

Exercises the real auth pipeline end-to-end: session login via /auth/email/login
followed by requests that trigger get_rpc_filter_context. Catches regressions
where auth.py stops setting request.state.token_use, which unit-level tests
(which mock request.state directly) would not catch.
"""

# Standard
from datetime import datetime, timezone

# Third-Party
import jwt
import pytest
from fastapi import Depends, Request as FastAPIRequest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# First-Party
import mcpgateway.db as db_mod
import mcpgateway.main as main_mod
from mcpgateway.auth import get_current_user
from mcpgateway.auth_context import get_rpc_filter_context
from mcpgateway.config import settings
from mcpgateway.db import Base, EmailUser
from mcpgateway.middleware.rbac import get_current_user_with_permissions


@pytest.fixture
def app_and_client():
    """Set up FastAPI app with temp SQLite DB, admin user, and TestClient.

    Uses the real auth pipeline (require_auth, get_current_user) but overrides
    get_current_user_with_permissions to bypass complex RBAC while preserving
    request.state setup from the real auth chain.

    The app registers a synthetic admin bypass check endpoint
    (_test_session_admin_bypass_check) that returns get_rpc_filter_context
    results and can look up a private tool by ID.
    """
    from _pytest.monkeypatch import MonkeyPatch

    mp = MonkeyPatch()
    import os
    import tempfile

    fd, path = tempfile.mkstemp(suffix=".db")
    url = f"sqlite:///{path}"

    # Patch settings
    mp.setattr(settings, "database_url", url, raising=False)

    engine = create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    # Patch SessionLocal in all modules that import it directly
    mp.setattr(db_mod, "engine", engine, raising=False)
    mp.setattr(db_mod, "SessionLocal", TestSessionLocal, raising=False)
    mp.setattr(main_mod, "SessionLocal", TestSessionLocal, raising=False)

    import mcpgateway.middleware.auth_middleware as auth_middleware_mod
    import mcpgateway.services.security_logger as sec_logger_mod
    import mcpgateway.services.structured_logger as struct_logger_mod
    import mcpgateway.services.audit_trail_service as audit_trail_mod
    import mcpgateway.services.log_aggregator as log_aggregator_mod

    mp.setattr(auth_middleware_mod, "SessionLocal", TestSessionLocal, raising=False)
    mp.setattr(sec_logger_mod, "SessionLocal", TestSessionLocal, raising=False)
    mp.setattr(struct_logger_mod, "SessionLocal", TestSessionLocal, raising=False)
    mp.setattr(audit_trail_mod, "SessionLocal", TestSessionLocal, raising=False)
    mp.setattr(log_aggregator_mod, "SessionLocal", TestSessionLocal, raising=False)

    # Create schema
    Base.metadata.create_all(bind=engine)

    # Override get_db for all routers that use it
    def override_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    from mcpgateway.db import get_db as mcpgateway_get_db
    from mcpgateway.routers.auth import get_db as auth_get_db
    from mcpgateway.middleware.rbac import get_db as rbac_get_db

    main_mod.app.dependency_overrides[mcpgateway_get_db] = override_get_db
    main_mod.app.dependency_overrides[auth_get_db] = override_get_db
    main_mod.app.dependency_overrides[rbac_get_db] = override_get_db

    # Override get_current_user_with_permissions to bypass RBAC complexity
    # while preserving the real auth pipeline (get_current_user sets up
    # request.state.token_use, request.state.token_teams, etc.)
    async def mock_user_with_permissions(request: FastAPIRequest, user=Depends(get_current_user)):
        return {
            "email": user.email,
            "full_name": user.full_name,
            "is_admin": user.is_admin,
            "ip_address": "127.0.0.1",
            "user_agent": "test-client",
        }

    main_mod.app.dependency_overrides[get_current_user_with_permissions] = mock_user_with_permissions

    # Seed users and a private tool
    import uuid

    from mcpgateway.services.argon2_service import Argon2PasswordService

    argon2 = Argon2PasswordService()
    db = TestSessionLocal()

    # Admin user
    admin_user = EmailUser(
        id=str(uuid.uuid4()),
        email="admin-bypass@example.com",
        password_hash=argon2.hash_password("TestPass123!"),  # pragma: allowlist secret
        full_name="Admin Bypass Test",
        is_admin=True,
        is_active=True,
        auth_provider="local",
        email_verified_at=datetime.now(timezone.utc),
    )
    db.add(admin_user)

    # Non-admin user (negative control)
    non_admin_user = EmailUser(
        id=str(uuid.uuid4()),
        email="nonadmin@example.com",
        password_hash=argon2.hash_password("NonAdminPass1!"),  # pragma: allowlist secret
        full_name="Non Admin User",
        is_admin=False,
        is_active=True,
        auth_provider="local",
        email_verified_at=datetime.now(timezone.utc),
    )
    db.add(non_admin_user)
    db.commit()

    # Seed a private tool owned by the admin
    tool_id = uuid.uuid4().hex
    admin_tool = db_mod.Tool(
        id=tool_id,
        original_name="admin-private-tool",
        url="http://example.com/tool",
        owner_email=admin_user.email,
        visibility="private",
        integration_type="REST",
        request_type="GET",
        input_schema={},
        output_schema={},
        enabled=True,
        deprecated=False,
        created_by=admin_user.email,
        tags=[],
    )
    db.add(admin_tool)
    db.commit()

    # Capture emails before session closes (objects become detached)
    admin_email = admin_user.email
    non_admin_email = non_admin_user.email
    db.close()

    # Register synthetic check endpoint
    from fastapi import APIRouter

    _test_router = APIRouter()

    @_test_router.get("/_test_session_admin_bypass_check/{tool_id}")
    @_test_router.get("/_test_session_admin_bypass_check")  # no tool_id = probe only
    async def _bypass_check(
        request: FastAPIRequest,
        tool_id: str = "",
        db: db_mod.Session = Depends(override_get_db),  # noqa: B008
        user=Depends(get_current_user_with_permissions),
    ):
        user_email, token_teams, is_admin = get_rpc_filter_context(request, user)
        result = {
            "user_email": user_email,
            "token_teams": token_teams,
            "is_admin": is_admin,
            "token_use": getattr(request.state, "token_use", None),
        }
        if tool_id:
            from mcpgateway.utils.admin_check import is_user_admin

            tool = db.get(db_mod.Tool, tool_id)
            result["tool_found"] = tool is not None
            if tool:
                result["tool_owner"] = tool.owner_email
                result["is_user_admin_db"] = is_user_admin(db, user_email)
        return result

    main_mod.app.include_router(_test_router)

    client = TestClient(main_mod.app)
    yield {
        "client": client,
        "tool_id": tool_id,
        "admin_email": admin_email,
        "non_admin_email": non_admin_email,
    }

    # Teardown
    main_mod.app.dependency_overrides.clear()
    mp.undo()
    engine.dispose()
    os.close(fd)
    os.unlink(path)


class TestSessionAdminBypassRealPipeline:
    """Exercises the real auth pipeline for session token admin bypass."""

    def _login(self, client, email, password):
        resp = client.post(
            "/auth/login",
            json={"email": email, "password": password},
        )
        assert resp.status_code == 200, f"Login failed for {email}: {resp.text}"
        return resp.json()["access_token"]

    def test_admin_bypass_via_real_session_login(self, app_and_client):
        """Full pipeline: real login -> admin bypass fires -> non-admin denied.

        This catches regressions where auth.py stops setting
        request.state.token_use, which unit tests (mocking request.state
        directly) would silently pass.
        """
        ctx = app_and_client
        client = ctx["client"]
        tool_id = ctx["tool_id"]

        # Step 1: Admin login - get a real session JWT
        admin_token = self._login(
            client,
            "admin-bypass@example.com",
            "TestPass123!",  # pragma: allowlist secret
        )

        # Step 2: Verify the token is a session token (no is_admin claim)
        payload = jwt.decode(
            admin_token,
            settings.jwt_secret_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
            options={"verify_signature": False},
        )
        assert payload.get("token_use") == "session", "Expected session token"
        # Session JWTs intentionally omit is_admin — DB is the authority
        assert payload.get("is_admin") is None, "Session JWT should not carry is_admin"

        # Step 3: Probe the bypass check endpoint (no tool_id) to verify
        # get_rpc_filter_context returns admin bypass for session admin
        headers = {"Authorization": f"Bearer {admin_token}"}
        resp = client.get("/_test_session_admin_bypass_check", headers=headers)
        assert resp.status_code == 200, f"Bypass probe failed: {resp.text}"
        data = resp.json()
        assert data["is_admin"] is True, f"Admin should get is_admin=True, got: {data}"
        assert data["token_use"] == "session"
        assert data["token_teams"] is None, f"Admin bypass requires token_teams=None, got: {data}"

        # Step 4: Admin fetches their own private tool via the bypass check endpoint
        resp = client.get(f"/_test_session_admin_bypass_check/{tool_id}", headers=headers)
        assert resp.status_code == 200, f"Admin tool fetch failed: {resp.text}"
        data = resp.json()
        assert data["tool_found"] is True
        assert data["tool_owner"] == "admin-bypass@example.com"
        assert data["is_admin"] is True
        assert data["is_user_admin_db"] is True

        # Step 5: Non-admin login and attempt the same
        non_admin_token = self._login(
            client,
            "nonadmin@example.com",
            "NonAdminPass1!",  # pragma: allowlist secret
        )
        non_admin_headers = {"Authorization": f"Bearer {non_admin_token}"}
        resp = client.get(f"/_test_session_admin_bypass_check/{tool_id}", headers=non_admin_headers)
        assert resp.status_code == 200, f"Non-admin probe failed: {resp.text}"
        data = resp.json()
        assert data["is_admin"] is False
        assert data["is_user_admin_db"] is False
        # Non-admin should still see the tool exists (the check endpoint just looks it up)
        # but token_teams should not be None (no bypass for non-admins)
        assert data["token_teams"] is not None
