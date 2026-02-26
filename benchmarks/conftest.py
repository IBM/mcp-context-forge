# -*- coding: utf-8 -*-
"""Fixtures for benchmarks (a2a invoke, etc.).

When running `pytest benchmarks/`, only this conftest and repo root conftest
(if any) are loaded. We provide app, test client, and auth so benchmark tests
do not depend on tests/conftest.
"""

# Standard
import os
import sys
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
from _pytest.monkeypatch import MonkeyPatch
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# First-Party
import mcpgateway.db as db_mod
from mcpgateway.config import settings
from pydantic import SecretStr

# Test JWT secret (must be at least 32 chars for HS256)
TEST_JWT_SECRET = "unit-test-jwt-secret-key-with-minimum-32-bytes"


@pytest.fixture(scope="module")
def app_with_temp_db():
    """FastAPI app wired to a temporary SQLite DB for benchmarks."""
    mp = MonkeyPatch()

    fd, path = tempfile.mkstemp(suffix=".db")
    url = f"sqlite:///{path}"

    mp.setattr(settings, "database_url", url, raising=False)
    mp.setattr(settings, "auth_required", False, raising=False)

    engine = create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    mp.setattr(db_mod, "engine", engine, raising=False)
    mp.setattr(db_mod, "SessionLocal", TestSessionLocal, raising=False)

    import mcpgateway.main as main_mod

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

    db_mod.Base.metadata.create_all(bind=engine)

    from mcpgateway.main import app

    yield app

    mp.undo()
    engine.dispose()
    os.close(fd)
    try:
        os.unlink(path)
    except OSError:
        pass


@pytest.fixture
def a2a_bench_client(app_with_temp_db):
    """TestClient with auth overrides and mocked A2A service for invoke benchmark."""
    from fastapi import HTTPException, status
    from fastapi.testclient import TestClient

    from mcpgateway.auth import get_current_user
    from mcpgateway.db import EmailUser
    from mcpgateway.middleware.rbac import get_current_user_with_permissions
    from mcpgateway.utils.verify_credentials import require_auth

    mock_user = EmailUser(
        email="bench@example.com",
        full_name="Bench User",
        is_admin=True,
        is_active=True,
        auth_provider="test",
    )

    app_with_temp_db.dependency_overrides[require_auth] = lambda: "bench_user"
    app_with_temp_db.dependency_overrides[get_current_user] = lambda credentials=None, db=None: mock_user
    app_with_temp_db.dependency_overrides[get_current_user_with_permissions] = (
        lambda request=None, credentials=None, jwt_token=None: {
            "email": "bench@example.com",
            "full_name": "Bench User",
            "is_admin": True,
            "ip_address": "127.0.0.1",
            "user_agent": "bench",
        }
    )

    from mcpgateway.services.permission_service import PermissionService

    _original = getattr(PermissionService, "_original_check_permission", PermissionService.check_permission)

    async def mock_check_permission(
        self,
        user_email: str,
        permission: str,
        resource_type=None,
        resource_id=None,
        team_id=None,
        token_teams=None,
        ip_address=None,
        user_agent=None,
        allow_admin_bypass=True,
        check_any_team=False,
        **_kwargs,
    ):
        return True

    PermissionService.check_permission = mock_check_permission

    sec_logger = MagicMock()
    sec_logger.log_authentication_attempt = MagicMock(return_value=None)
    sec_logger.log_security_event = MagicMock(return_value=None)
    sec_patcher = patch("mcpgateway.middleware.auth_middleware.security_logger", sec_logger)
    sec_patcher.start()

    async def mock_require_auth_override(auth_header=None, jwt_token=None):
        import jwt as jwt_lib

        token = jwt_token
        if not token and auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:]
        if not token:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authorization required")
        key = settings.jwt_secret_key
        if hasattr(key, "get_secret_value") and callable(getattr(key, "get_secret_value", None)):
            key = key.get_secret_value()
        payload = jwt_lib.decode(token, key, algorithms=[settings.jwt_algorithm], options={"verify_aud": False})
        return payload.get("sub") or "bench_user"

    doc_patcher = patch("mcpgateway.main.require_docs_auth_override", mock_require_auth_override)
    doc_patcher.start()

    orig_secret = settings.jwt_secret_key
    if hasattr(orig_secret, "get_secret_value"):
        settings.jwt_secret_key = SecretStr(TEST_JWT_SECRET)
    else:
        settings.jwt_secret_key = TEST_JWT_SECRET

    client = TestClient(app_with_temp_db)

    yield client

    settings.jwt_secret_key = orig_secret
    app_with_temp_db.dependency_overrides.pop(require_auth, None)
    app_with_temp_db.dependency_overrides.pop(get_current_user, None)
    app_with_temp_db.dependency_overrides.pop(get_current_user_with_permissions, None)
    sec_patcher.stop()
    doc_patcher.stop()
    if hasattr(PermissionService, "_original_check_permission"):
        PermissionService.check_permission = _original


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Print vs-baseline summary table for A2A invoke benchmarks."""
    comparisons = []
    for mod in sys.modules.values():
        if mod is not None and hasattr(mod, "_BASELINE_COMPARISONS"):
            comparisons = getattr(mod, "_BASELINE_COMPARISONS", [])
            if comparisons:
                break
    if not comparisons:
        return
    lines = []
    lines.append("---------------------------------------------------------------------- vs baseline (main) -----")
    lines.append(f"{'Name (time in ms)':<42} {'Mean':>12} {'Baseline':>12} {'vs base':>16}")
    lines.append("-------------------------------------------------------------------------------------------------")
    for scenario_id, mean_ms, base_mean, x_mean in comparisons:
        lines.append(f"{scenario_id:<42} {mean_ms:>11.3f} {base_mean:>11.3f} {x_mean:>16}")
    lines.append("-------------------------------------------------------------------------------------------------")
    for line in lines:
        terminalreporter.write_line(line)


@pytest.fixture
def a2a_bench_auth_headers():
    """Bearer token for benchmark client."""
    import jwt

    payload = {
        "sub": "bench@example.com",
        "email": "bench@example.com",
        "iss": "mcpgateway",
        "aud": "mcpgateway-api",
    }
    secret = settings.jwt_secret_key
    if hasattr(secret, "get_secret_value") and callable(getattr(secret, "get_secret_value", None)):
        secret = secret.get_secret_value()
    token = jwt.encode(payload, secret, algorithm=settings.jwt_algorithm)
    return {"Authorization": f"Bearer {token}"}
