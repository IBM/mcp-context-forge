# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_session_admin_bypass.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Integration tests for session token admin bypass (PR #5232, issue #5232).

Exercises the real auth pipeline end-to-end: session login via /auth/email/login
followed by a request that triggers get_rpc_filter_context. Catches regressions
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

    from mcpgateway.routers.auth import get_db as auth_get_db
    from mcpgateway.middleware.rbac import get_db as rbac_get_db

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

    # Seed an admin user with a valid UUID for the id field
    import uuid

    from mcpgateway.services.argon2_service import Argon2PasswordService

    argon2 = Argon2PasswordService()
    db = TestSessionLocal()
    admin_user = EmailUser(
        id=str(uuid.uuid4()),
        email="admin-bypass@example.com",
        password_hash=argon2.hash_password("TestPass123!"),
        full_name="Admin Bypass Test",
        is_admin=True,
        is_active=True,
        auth_provider="local",
        email_verified_at=datetime.now(timezone.utc),
    )
    db.add(admin_user)
    db.commit()
    db.close()

    client = TestClient(main_mod.app)
    yield client

    # Teardown
    main_mod.app.dependency_overrides.clear()
    mp.undo()
    engine.dispose()
    os.close(fd)
    os.unlink(path)


class TestSessionAdminBypassRealPipeline:
    """Exercises the real auth pipeline for session token admin bypass."""

    def test_admin_bypass_via_real_session_login(self, app_and_client):
        """Full pipeline: real login → authenticated request → admin bypass fires.

        This catches regressions where auth.py stops setting
        request.state.token_use, which unit tests (mocking request.state
        directly) would silently pass.
        """
        client = app_and_client

        # Step 1: Real login via /auth/login - get a real session JWT
        login_resp = client.post(
            "/auth/login",
            json={"email": "admin-bypass@example.com", "password": "TestPass123!"},
        )
        assert login_resp.status_code == 200, f"Login failed: {login_resp.text}"
        token = login_resp.json()["access_token"]

        # Step 2: Verify the token is a session token
        payload = jwt.decode(
            token,
            settings.jwt_secret_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
            options={"verify_signature": False},
        )
        assert payload.get("token_use") == "session", "Expected session token"

        # Step 3: Use the session JWT to call /servers/ endpoint
        # This exercises the real auth pipeline:
        #   require_auth → get_current_user → _inject_userinfo_instate
        #   → request.state.token_use = "session"
        #   → get_rpc_filter_context → admin bypass fires
        headers = {"Authorization": f"Bearer {token}"}
        resp = client.get("/servers/", headers=headers)

        # The endpoint should succeed (empty list is fine - no servers exist)
        # The key assertion is that we get 200, not 401/403
        assert resp.status_code == 200, f"Request failed: {resp.text}"
        assert resp.json() == []  # No servers in DB
