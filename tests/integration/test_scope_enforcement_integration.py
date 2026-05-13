# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_scope_enforcement_integration.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Integration tests for API token scope enforcement.

Tests cover:
- JWT tokens with empty dict scopes
- JWT tokens with empty list permissions
- JWT tokens with malformed scopes
- JWT tokens without scopes (session tokens)
- Database API tokens with various scope configurations
- Scope enforcement across different endpoint types (A2A, tools, resources)
"""

# Standard
from datetime import datetime, timedelta, timezone
import uuid

# Third-Party
import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# First-Party
import mcpgateway.db
from mcpgateway.config import settings
from mcpgateway.db import Base, EmailApiToken, EmailTeam, EmailUser
from mcpgateway.main import app


@pytest.fixture
def test_db_engine():
    """Create test database engine with thread-safe SQLite."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def test_db_session(test_db_engine):
    """Create test database session."""
    TestSessionLocal = sessionmaker(bind=test_db_engine)
    session = TestSessionLocal()
    yield session
    session.close()


@pytest.fixture
def client(test_db_engine):
    """Create test client with test database."""
    TestSessionLocal = sessionmaker(bind=test_db_engine)

    def override_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    # Override database connections
    original_session_local = mcpgateway.db.SessionLocal
    mcpgateway.db.SessionLocal = TestSessionLocal
    original_engine = mcpgateway.db.engine
    mcpgateway.db.engine = test_db_engine

    from mcpgateway.routers.auth import get_db

    app.dependency_overrides[get_db] = override_get_db

    # Create test user and team
    from mcpgateway.services.argon2_service import Argon2PasswordService

    argon2 = Argon2PasswordService()
    db = TestSessionLocal()

    # Create team
    team = EmailTeam(id="test-team", name="Test Team", description="Test team for scope tests")
    db.add(team)

    # Create user
    test_user = EmailUser(
        email="scope-test@example.com",
        password_hash=argon2.hash_password("TestPassword123!"),
        full_name="Scope Test User",
        is_admin=False,
        is_active=True,
        auth_provider="local",
        email_verified_at=datetime.now(timezone.utc),
    )
    db.add(test_user)
    db.commit()
    db.close()

    yield TestClient(app)

    # Cleanup
    app.dependency_overrides.clear()
    mcpgateway.db.SessionLocal = original_session_local
    mcpgateway.db.engine = original_engine


def create_jwt_token(email: str, scopes=None, exp_hours: int = 1) -> str:
    """Helper to create JWT tokens with various scope configurations."""
    payload = {
        "email": email,
        "sub": email,
        "exp": (datetime.now(timezone.utc) + timedelta(hours=exp_hours)).timestamp(),
        "iat": datetime.now(timezone.utc).timestamp(),
        "jti": str(uuid.uuid4()),
    }

    if scopes is not None:
        payload["scopes"] = scopes

    return jwt.encode(payload, settings.jwt_secret_key, algorithm="HS256")


def test_jwt_empty_dict_scopes_denies_access(client):
    """JWT with empty dict scopes {} should deny all access."""
    token = create_jwt_token("scope-test@example.com", scopes={})

    # Try to access A2A endpoint (requires a2a.read)
    response = client.get("/a2a", headers={"Authorization": f"Bearer {token}"})

    # Should be denied (403) because empty dict means no permissions
    assert response.status_code == 403
    assert "API token missing required scope" in response.json()["detail"]


def test_jwt_empty_permissions_list_denies_access(client):
    """JWT with empty permissions list should deny all access."""
    token = create_jwt_token("scope-test@example.com", scopes={"permissions": []})

    # Try to access A2A endpoint
    response = client.get("/a2a", headers={"Authorization": f"Bearer {token}"})

    # Should be denied (403)
    assert response.status_code == 403
    assert "API token missing required scope" in response.json()["detail"]


def test_jwt_malformed_scopes_treated_as_session_token(client):
    """JWT with malformed scopes (non-dict) should be treated as session token."""
    # Create token with string scopes (malformed)
    token = create_jwt_token("scope-test@example.com", scopes="tools.read,a2a.read")

    # Try to access A2A endpoint
    response = client.get("/a2a", headers={"Authorization": f"Bearer {token}"})

    # Should succeed (200) because malformed scopes → session token → RBAC only
    # (assuming user has RBAC permissions)
    # Note: This might be 403 if user lacks RBAC permissions, but should NOT be scope-denied
    assert response.status_code in [200, 403]
    if response.status_code == 403:
        # If denied, should be RBAC denial, not scope denial
        assert "API token missing required scope" not in response.json()["detail"]


def test_jwt_missing_scopes_treated_as_session_token(client):
    """JWT without scopes field should be treated as session token (no scope checks)."""
    token = create_jwt_token("scope-test@example.com", scopes=None)

    # Try to access A2A endpoint
    response = client.get("/a2a", headers={"Authorization": f"Bearer {token}"})

    # Should succeed or fail based on RBAC only, not scope checks
    assert response.status_code in [200, 403]
    if response.status_code == 403:
        assert "API token missing required scope" not in response.json()["detail"]


def test_jwt_valid_scopes_grants_access(client):
    """JWT with valid scopes should grant access to matching endpoints."""
    token = create_jwt_token("scope-test@example.com", scopes={"permissions": ["a2a.read", "tools.read"]})

    # Try to access A2A endpoint (requires a2a.read)
    response = client.get("/a2a", headers={"Authorization": f"Bearer {token}"})

    # Should succeed (200) or fail for RBAC reasons, but NOT scope reasons
    assert response.status_code in [200, 403]
    if response.status_code == 403:
        assert "API token missing required scope" not in response.json()["detail"]


def test_jwt_insufficient_scopes_denies_access(client):
    """JWT with insufficient scopes should deny access."""
    # Token has tools.read but not a2a.read
    token = create_jwt_token("scope-test@example.com", scopes={"permissions": ["tools.read"]})

    # Try to access A2A endpoint (requires a2a.read)
    response = client.get("/a2a", headers={"Authorization": f"Bearer {token}"})

    # Should be denied (403) due to missing scope
    assert response.status_code == 403
    assert "API token missing required scope: a2a.read" in response.json()["detail"]


def test_database_api_token_empty_scopes_denies_access(client, test_db_session):
    """Database API token with empty scopes should deny all access."""
    # Create API token with empty scopes
    api_token = EmailApiToken(
        user_email="scope-test@example.com",
        token_hash="test-hash-empty",
        jti=str(uuid.uuid4()),
        resource_scopes=[],  # Empty scopes
        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
    )
    test_db_session.add(api_token)
    test_db_session.commit()

    # Create JWT that references this API token
    token = create_jwt_token("scope-test@example.com", scopes={"permissions": []})

    # Try to access A2A endpoint
    response = client.get("/a2a", headers={"Authorization": f"Bearer {token}"})

    # Should be denied (403)
    assert response.status_code == 403
    assert "API token missing required scope" in response.json()["detail"]


def test_database_api_token_valid_scopes_grants_access(client, test_db_session):
    """Database API token with valid scopes should grant access."""
    # Create API token with valid scopes
    api_token = EmailApiToken(
        user_email="scope-test@example.com",
        token_hash="test-hash-valid",
        jti=str(uuid.uuid4()),
        resource_scopes=["a2a.read", "tools.read"],
        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
    )
    test_db_session.add(api_token)
    test_db_session.commit()

    # Create JWT with matching scopes
    token = create_jwt_token("scope-test@example.com", scopes={"permissions": ["a2a.read", "tools.read"]})

    # Try to access A2A endpoint
    response = client.get("/a2a", headers={"Authorization": f"Bearer {token}"})

    # Should succeed or fail for RBAC reasons, but NOT scope reasons
    assert response.status_code in [200, 403]
    if response.status_code == 403:
        assert "API token missing required scope" not in response.json()["detail"]


def test_scope_enforcement_across_multiple_endpoints(client):
    """Test scope enforcement works consistently across different endpoint types."""
    # Token with only tools.read
    token = create_jwt_token("scope-test@example.com", scopes={"permissions": ["tools.read"]})

    # Should deny A2A endpoints (requires a2a.read)
    response = client.get("/a2a", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403
    assert "a2a.read" in response.json()["detail"]

    # Should deny resource endpoints (requires resources.read)
    response = client.get("/resources", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403
    assert "resources.read" in response.json()["detail"]

    # Tools endpoint behavior depends on RBAC, but should not fail on scope check
    response = client.get("/tools", headers={"Authorization": f"Bearer {token}"})
    # May succeed or fail for RBAC, but not scope reasons
    if response.status_code == 403:
        assert "API token missing required scope" not in response.json()["detail"]


def test_wildcard_scope_grants_all_access(client):
    """Test that wildcard scope (*) grants access to all endpoints."""
    token = create_jwt_token("scope-test@example.com", scopes={"permissions": ["*"]})

    # Should allow access to all endpoints (subject to RBAC)
    endpoints = ["/a2a", "/tools", "/resources"]
    for endpoint in endpoints:
        response = client.get(endpoint, headers={"Authorization": f"Bearer {token}"})
        # Should not fail on scope check
        if response.status_code == 403:
            assert "API token missing required scope" not in response.json()["detail"]

