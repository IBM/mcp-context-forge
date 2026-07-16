# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_cross_env_auth.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0
Authors: Contributors to the MCP-CONTEXT-FORGE project

Integration: cross-environment token rejection at the HTTP layer (GHSA-vgf8-3685-66j9).
"""

# Standard
import datetime
from datetime import timezone
from typing import Generator

# Third-Party
import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# First-Party
import mcpgateway.db
import mcpgateway.utils.jwt_config_helper as jch
from mcpgateway.config import settings
from mcpgateway.db import Base, EmailUser
from mcpgateway.main import app

# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def _test_db_engine():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def client(_test_db_engine) -> Generator:
    TestSessionLocal = sessionmaker(bind=_test_db_engine)

    def override_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    original_session_local = mcpgateway.db.SessionLocal
    original_engine = mcpgateway.db.engine
    mcpgateway.db.SessionLocal = TestSessionLocal
    mcpgateway.db.engine = _test_db_engine

    from mcpgateway.routers.auth import get_db

    app.dependency_overrides[get_db] = override_get_db

    from mcpgateway.services.argon2_service import Argon2PasswordService

    argon2 = Argon2PasswordService()
    db = TestSessionLocal()
    if not db.query(EmailUser).filter_by(email="crossenv@example.com").first():
        db.add(
            EmailUser(
                email="crossenv@example.com",
                password_hash=argon2.hash_password("CrossEnv123!"),  # pragma: allowlist secret
                full_name="Cross Env Test",
                is_admin=False,
                is_active=True,
                auth_provider="local",
                email_verified_at=datetime.datetime.now(timezone.utc),
            )
        )
        db.commit()
    db.close()

    yield TestClient(app)

    app.dependency_overrides.clear()
    mcpgateway.db.SessionLocal = original_session_local
    mcpgateway.db.engine = original_engine


@pytest.fixture(autouse=True)
def _reset_jch_caches():
    jch.clear_jwt_caches()
    yield
    jch.clear_jwt_caches()


@pytest.fixture(autouse=True)
def _restore_settings():
    """Snapshot and restore settings fields mutated by helpers and tests."""
    saved = {
        "jwt_algorithm": settings.jwt_algorithm,
        "jwt_secret_key": settings.jwt_secret_key,
        "derive_key_per_environment": settings.derive_key_per_environment,
        "environment": settings.environment,
    }
    yield
    for attr, val in saved.items():
        setattr(settings, attr, val)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _token_for_env(environment, base="shared-base"):
    from pydantic import SecretStr
    import uuid

    settings.jwt_algorithm = "HS256"
    settings.jwt_secret_key = SecretStr(base)  # type: ignore[assignment]
    settings.derive_key_per_environment = True
    settings.environment = environment
    jch.clear_jwt_caches()
    return pyjwt.encode(
        {
            "sub": "crossenv@example.com",
            "exp": 9999999999,
            "iat": int(datetime.datetime.now(timezone.utc).timestamp()),
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
            "jti": str(uuid.uuid4()),
            "env": environment,
        },
        jch.get_jwt_private_key_or_secret(),
        algorithm="HS256",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_protected_route_rejects_cross_env_token(client, monkeypatch):
    token = _token_for_env("development")
    monkeypatch.setattr(settings, "environment", "production")
    jch.clear_jwt_caches()
    r = client.get("/tools", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


def test_protected_route_accepts_home_env_token(client, monkeypatch):
    token = _token_for_env("production")
    monkeypatch.setattr(settings, "environment", "production")
    jch.clear_jwt_caches()
    r = client.get("/tools", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code in (200, 403)  # authn passes; 403 only if RBAC denies


def test_same_env_federation_parity():
    # Two peers, same base + env + derivation => identical derived key => tokens interop.
    a = _token_for_env("production", base="fed-base")
    key_b = jch._derive_env_key("fed-base", "production")
    payload = pyjwt.decode(a, key_b, algorithms=["HS256"], options={"verify_aud": False})
    assert payload["sub"] == "crossenv@example.com"


def test_session_token_rejects_cross_environment(client, monkeypatch):
    import uuid
    from pydantic import SecretStr

    settings.jwt_algorithm = "HS256"
    settings.jwt_secret_key = SecretStr("shared-base")  # type: ignore[assignment]
    settings.derive_key_per_environment = True
    settings.environment = "development"
    jch.clear_jwt_caches()
    token = pyjwt.encode(
        {
            "sub": "crossenv@example.com",
            "token_use": "session",
            "exp": 9999999999,
            "iat": int(datetime.datetime.now(timezone.utc).timestamp()),
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
            "jti": str(uuid.uuid4()),
            "env": "development",
        },
        jch.get_jwt_private_key_or_secret(),
        algorithm="HS256",
    )
    monkeypatch.setattr(settings, "environment", "production")
    jch.clear_jwt_caches()
    r = client.get("/tools", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


def test_oauth_external_token_unaffected_by_derivation(monkeypatch):
    import mcpgateway.utils.verify_credentials as vc

    monkeypatch.setattr(settings, "derive_key_per_environment", True, raising=False)
    monkeypatch.setattr(settings, "environment", "production", raising=False)
    jch.clear_jwt_caches()
    assert "derive" not in vc.verify_oauth_access_token.__code__.co_names
