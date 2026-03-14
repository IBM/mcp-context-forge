# -*- coding: utf-8 -*-
"""Shared Pact contract testing fixtures.

Provides common fixtures for both consumer and provider contract tests.
"""

import os
import tempfile
from unittest.mock import MagicMock, patch

from _pytest.monkeypatch import MonkeyPatch
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.testclient import TestClient

import mcpgateway.db as db_mod

from tests.utils.rbac_mocks import create_mock_user_context

PACT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "pacts")


class _AlwaysGrantPermissionService:
    """Stub PermissionService that grants every request."""

    def __init__(self, *args, **kwargs):
        pass

    async def check_permission(self, **kwargs):
        return True

    async def check_admin_permission(self, email):
        return True


@pytest.fixture(scope="session")
def pact_dir():
    """Return the directory where pact files are written."""
    os.makedirs(PACT_DIR, exist_ok=True)
    return PACT_DIR


@pytest.fixture(scope="module")
def provider_app():
    """Create a FastAPI test application for provider verification with RBAC bypassed."""
    mp = MonkeyPatch()

    fd, path = tempfile.mkstemp(suffix=".db")
    url = f"sqlite:///{path}"

    from mcpgateway.config import settings

    mp.setattr(settings, "database_url", url, raising=False)
    mp.setattr(settings, "auth_required", False, raising=False)

    engine = create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    mp.setattr(db_mod, "engine", engine, raising=False)
    mp.setattr(db_mod, "SessionLocal", TestSessionLocal, raising=False)

    import mcpgateway.main as main_mod

    mp.setattr(main_mod, "SessionLocal", TestSessionLocal, raising=False)

    import mcpgateway.middleware.auth_middleware as auth_middleware_mod
    import mcpgateway.middleware.rbac as rbac_mod
    import mcpgateway.services.audit_trail_service as audit_trail_mod
    import mcpgateway.services.log_aggregator as log_aggregator_mod
    import mcpgateway.services.security_logger as sec_logger_mod
    import mcpgateway.services.structured_logger as struct_logger_mod

    mp.setattr(auth_middleware_mod, "SessionLocal", TestSessionLocal, raising=False)
    mp.setattr(sec_logger_mod, "SessionLocal", TestSessionLocal, raising=False)
    mp.setattr(struct_logger_mod, "SessionLocal", TestSessionLocal, raising=False)
    mp.setattr(audit_trail_mod, "SessionLocal", TestSessionLocal, raising=False)
    mp.setattr(log_aggregator_mod, "SessionLocal", TestSessionLocal, raising=False)

    # Bypass RBAC: patch PermissionService to always grant access
    mp.setattr(rbac_mod, "PermissionService", _AlwaysGrantPermissionService, raising=False)

    db_mod.Base.metadata.create_all(bind=engine)

    from mcpgateway.main import app

    # Override auth dependencies with admin-level mock user
    from mcpgateway.auth import get_current_user
    from mcpgateway.db import get_db
    from mcpgateway.middleware.rbac import get_current_user_with_permissions
    from mcpgateway.utils.create_jwt_token import get_jwt_token
    from mcpgateway.utils.verify_credentials import require_admin_auth, require_auth

    test_user_context = create_mock_user_context(email="pact-test@example.com", full_name="Pact Test User", is_admin=True)
    test_db = TestSessionLocal()
    test_user_context["db"] = test_db

    mock_email_user = MagicMock()
    mock_email_user.email = "pact-test@example.com"
    mock_email_user.full_name = "Pact Test User"
    mock_email_user.is_admin = True
    mock_email_user.is_active = True

    async def mock_user_with_permissions():
        return test_user_context

    async def mock_require_auth():
        return "pact-test@example.com"

    async def mock_require_admin():
        return "pact-test@example.com"

    async def mock_jwt_token():
        return "mock-pact-jwt-token"

    def override_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[require_auth] = mock_require_auth
    app.dependency_overrides[get_current_user] = lambda: mock_email_user
    app.dependency_overrides[require_admin_auth] = mock_require_admin
    app.dependency_overrides[get_jwt_token] = mock_jwt_token
    app.dependency_overrides[get_current_user_with_permissions] = mock_user_with_permissions
    app.dependency_overrides[get_db] = override_get_db

    # Mock security_logger to prevent database access issues
    mock_sec_logger = MagicMock()
    mock_sec_logger.log_authentication_attempt = MagicMock(return_value=None)
    mock_sec_logger.log_security_event = MagicMock(return_value=None)
    sec_patcher = patch("mcpgateway.middleware.auth_middleware.security_logger", mock_sec_logger)
    sec_patcher.start()

    yield app

    sec_patcher.stop()
    test_db.close()
    app.dependency_overrides.clear()
    mp.undo()
    engine.dispose()
    os.close(fd)
    os.unlink(path)


@pytest.fixture(scope="module")
def provider_client(provider_app):
    """Create a TestClient for provider verification."""
    with TestClient(provider_app) as client:
        yield client
