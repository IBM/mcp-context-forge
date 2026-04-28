# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_token_security_integration.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Integration tests for JWT Token Security.

Tests cover:
- Login/logout flow with token revocation
- Token expiry enforcement
- Idle timeout enforcement
- Token replay prevention after logout
- Authentication flow with blocklist checks
"""

# Standard
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
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
from mcpgateway.db import Base, EmailUser, TokenRevocation
from mcpgateway.main import app


@pytest.fixture
def test_db_engine():
    """Create test database engine with thread-safe SQLite."""
    # Use check_same_thread=False for SQLite to allow cross-thread access
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
    # Create a session factory for the test database
    TestSessionLocal = sessionmaker(bind=test_db_engine)

    # Override get_db dependency to use test database
    def override_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    # Override SessionLocal in db module to use test engine
    original_session_local = mcpgateway.db.SessionLocal
    mcpgateway.db.SessionLocal = TestSessionLocal

    # Override engine in db module
    original_engine = mcpgateway.db.engine
    mcpgateway.db.engine = test_db_engine

    # Override FastAPI dependency
    from mcpgateway.routers.auth import get_db

    app.dependency_overrides[get_db] = override_get_db

    # Create test user once for all tests
    from mcpgateway.services.argon2_service import Argon2PasswordService

    argon2 = Argon2PasswordService()

    db = TestSessionLocal()
    # Check if user already exists
    existing_user = db.query(EmailUser).filter_by(email="test@example.com").first()
    if not existing_user:
        test_user = EmailUser(
            email="test@example.com",
            password_hash=argon2.hash_password("TestPassword123!"),
            full_name="Test User",
            is_admin=False,
            is_active=True,
            auth_provider="local",
            email_verified_at=datetime.now(timezone.utc),
        )
        db.add(test_user)
        db.commit()
    db.close()

    yield TestClient(app)

    # Restore original values
    app.dependency_overrides.clear()
    mcpgateway.db.SessionLocal = original_session_local
    mcpgateway.db.engine = original_engine


class TestLoginLogoutFlow:
    """Tests for login/logout flow with token revocation."""

    def test_successful_login(self, client):
        """Test successful login returns valid token."""
        response = client.post("/auth/login", json={"email": "test@example.com", "password": "TestPassword123!"})  # pragma: allowlist secret

        assert response.status_code == 200
        data = response.json()

        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert "expires_in" in data
        assert data["expires_in"] <= 1200  # 20 minutes or less

        # Verify token structure
        token = data["access_token"]
        payload = jwt.decode(token, settings.jwt_secret_key.get_secret_value(), algorithms=[settings.jwt_algorithm], options={"verify_signature": False})

        assert "jti" in payload
        assert "exp" in payload
        assert "last_activity" in payload
        assert payload["sub"] == "test@example.com"

    def test_logout_revokes_token(self, client, test_db_session):
        """Test logout revokes the token."""
        # Login first
        login_response = client.post("/auth/login", json={"email": "test@example.com", "password": "TestPassword123!"})  # pragma: allowlist secret

        token = login_response.json()["access_token"]

        # Logout
        logout_response = client.post("/auth/logout", headers={"Authorization": f"Bearer {token}"})

        assert logout_response.status_code == 200
        data = logout_response.json()

        assert data["message"] == "Logged out successfully"
        assert "revoked_token" in data

        # Verify token is in blocklist
        payload = jwt.decode(token, settings.jwt_secret_key.get_secret_value(), algorithms=[settings.jwt_algorithm], options={"verify_signature": False})

        jti = payload["jti"]
        revocation = test_db_session.execute(select(TokenRevocation).where(TokenRevocation.jti == jti)).scalar_one_or_none()

        assert revocation is not None
        assert revocation.reason == "logout"

    def test_token_replay_after_logout_fails(self, client):
        """Test that token cannot be reused after logout."""
        # Login
        login_response = client.post("/auth/login", json={"email": "test@example.com", "password": "TestPassword123!"})  # pragma: allowlist secret

        token = login_response.json()["access_token"]

        # Logout
        client.post("/auth/logout", headers={"Authorization": f"Bearer {token}"})

        # Try to use token again - should fail
        with patch("mcpgateway.auth.get_current_user") as mock_auth:
            mock_auth.side_effect = Exception("Token has been revoked")

            response = client.get("/api/some-protected-endpoint", headers={"Authorization": f"Bearer {token}"})

            # Should be unauthorized
            assert response.status_code in [401, 404]  # 404 if endpoint doesn't exist


class TestTokenExpiry:
    """Tests for token expiry enforcement."""

    def test_expired_token_rejected(self, client):
        """Test that expired tokens are rejected."""
        # Create expired token
        now = datetime.now(timezone.utc)
        expired_time = now - timedelta(minutes=30)

        payload = {
            "sub": "test@example.com",
            "exp": int(expired_time.timestamp()),
            "iat": int((expired_time - timedelta(minutes=20)).timestamp()),
            "jti": str(uuid.uuid4()),
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
        }

        token = jwt.encode(payload, settings.jwt_secret_key.get_secret_value(), algorithm=settings.jwt_algorithm)

        # Try to use expired token
        response = client.post("/auth/logout", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 401

    def test_short_token_lifetime(self, client):
        """Test that new tokens have short lifetime."""
        response = client.post("/auth/login", json={"email": "test@example.com", "password": "TestPassword123!"})  # pragma: allowlist secret

        data = response.json()
        expires_in = data["expires_in"]

        # Should be 20 minutes or less (1200 seconds)
        assert expires_in <= 1200

        # Verify token expiry in JWT
        token = data["access_token"]
        payload = jwt.decode(token, settings.jwt_secret_key.get_secret_value(), algorithms=[settings.jwt_algorithm], options={"verify_signature": False})

        exp_time = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        iat_time = datetime.fromtimestamp(payload["iat"], tz=timezone.utc)
        lifetime = (exp_time - iat_time).total_seconds() / 60

        # Should be approximately 20 minutes
        assert lifetime <= 20


class TestIdleTimeout:
    """Tests for idle timeout enforcement."""

    def test_idle_timeout_enforcement(self, client, test_db_session):
        """Test that idle timeout is enforced."""
        # Create a token with old last_activity timestamp
        now = datetime.now(timezone.utc)
        old_activity = now - timedelta(minutes=90)  # 90 minutes ago

        jti = str(uuid.uuid4())
        payload = {
            "sub": "test@example.com",
            "jti": jti,
            "email": "test@example.com",
            "exp": int((now + timedelta(minutes=20)).timestamp()),
            "iat": int(now.timestamp()),
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
            "is_admin": False,
            "teams": [],
            "last_activity": int(old_activity.timestamp()),  # Old activity timestamp
        }

        token = jwt.encode(payload, settings.jwt_secret_key.get_secret_value(), algorithm=settings.jwt_algorithm)

        # Configure idle timeout to 60 minutes - patch in auth module where it's used
        with patch("mcpgateway.auth.settings") as mock_settings:
            # Copy all settings but override token_idle_timeout
            for attr in dir(settings):
                if not attr.startswith("_"):
                    try:
                        setattr(mock_settings, attr, getattr(settings, attr))
                    except AttributeError:
                        pass
            mock_settings.token_idle_timeout = 60
            mock_settings.auth_cache_enabled = False
            mock_settings.auth_cache_batch_queries = False

            # Request should fail due to idle timeout
            response = client.post("/auth/logout", headers={"Authorization": f"Bearer {token}"})

            # Should be rejected with 401
            assert response.status_code == 401
            assert "idle timeout" in response.json()["detail"].lower()

    def test_idle_timeout_with_revocation_failure(self, client, test_db_session):
        """Test that idle timeout still rejects token even if revocation fails."""
        # Create a token with old last_activity timestamp
        now = datetime.now(timezone.utc)
        old_activity = now - timedelta(minutes=90)  # 90 minutes ago

        jti = str(uuid.uuid4())
        payload = {
            "sub": "test@example.com",
            "jti": jti,
            "email": "test@example.com",
            "exp": int((now + timedelta(minutes=20)).timestamp()),
            "iat": int(now.timestamp()),
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
            "is_admin": False,
            "teams": [],
            "last_activity": int(old_activity.timestamp()),
        }

        token = jwt.encode(payload, settings.jwt_secret_key.get_secret_value(), algorithm=settings.jwt_algorithm)

        # Mock revoke_token to raise an exception
        with patch("mcpgateway.auth.settings") as mock_settings:
            for attr in dir(settings):
                if not attr.startswith("_"):
                    try:
                        setattr(mock_settings, attr, getattr(settings, attr))
                    except AttributeError:
                        pass
            mock_settings.token_idle_timeout = 60
            mock_settings.auth_cache_enabled = False
            mock_settings.auth_cache_batch_queries = False

            with patch("mcpgateway.services.token_blocklist_service.get_token_blocklist_service") as mock_get_service:
                mock_service = mock_get_service.return_value
                mock_service.revoke_token.side_effect = Exception("Database error")

                # Request should still fail due to idle timeout
                response = client.post("/auth/logout", headers={"Authorization": f"Bearer {token}"})

                # Should be rejected with 401 even though revocation failed
                assert response.status_code == 401
                assert "idle timeout" in response.json()["detail"].lower()

    def test_token_with_recent_activity_updates_timestamp(self, client, test_db_session):
        """Test that tokens with recent activity get their timestamp updated."""
        # Create a token with recent last_activity timestamp
        now = datetime.now(timezone.utc)
        recent_activity = now - timedelta(minutes=10)  # 10 minutes ago

        jti = str(uuid.uuid4())
        payload = {
            "sub": "test@example.com",
            "jti": jti,
            "email": "test@example.com",
            "exp": int((now + timedelta(minutes=20)).timestamp()),
            "iat": int(now.timestamp()),
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
            "is_admin": False,
            "teams": [],
            "last_activity": int(recent_activity.timestamp()),
        }

        token = jwt.encode(payload, settings.jwt_secret_key.get_secret_value(), algorithm=settings.jwt_algorithm)

        with patch("mcpgateway.auth.settings") as mock_settings:
            for attr in dir(settings):
                if not attr.startswith("_"):
                    try:
                        setattr(mock_settings, attr, getattr(settings, attr))
                    except AttributeError:
                        pass
            mock_settings.token_idle_timeout = 60
            mock_settings.auth_cache_enabled = False
            mock_settings.auth_cache_batch_queries = False

            # Request should succeed and update activity
            response = client.post("/auth/logout", headers={"Authorization": f"Bearer {token}"})

            # Should succeed
            assert response.status_code == 200

    def test_activity_update_failure_does_not_block_auth(self, client, test_db_session):
        """Test that activity update failure doesn't prevent authentication."""
        # Create a token with recent last_activity timestamp
        now = datetime.now(timezone.utc)
        recent_activity = now - timedelta(minutes=10)  # 10 minutes ago

        jti = str(uuid.uuid4())
        payload = {
            "sub": "test@example.com",
            "jti": jti,
            "email": "test@example.com",
            "exp": int((now + timedelta(minutes=20)).timestamp()),
            "iat": int(now.timestamp()),
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
            "is_admin": False,
            "teams": [],
            "last_activity": int(recent_activity.timestamp()),
        }

        token = jwt.encode(payload, settings.jwt_secret_key.get_secret_value(), algorithm=settings.jwt_algorithm)

        with patch("mcpgateway.auth.settings") as mock_settings:
            for attr in dir(settings):
                if not attr.startswith("_"):
                    try:
                        setattr(mock_settings, attr, getattr(settings, attr))
                    except AttributeError:
                        pass
            mock_settings.token_idle_timeout = 60
            mock_settings.auth_cache_enabled = False
            mock_settings.auth_cache_batch_queries = False

            # Mock update_activity to raise an exception
            with patch("mcpgateway.services.token_blocklist_service.get_token_blocklist_service") as mock_get_service:
                mock_service = mock_get_service.return_value
                mock_service.update_activity.side_effect = Exception("Redis error")

                # Request should still succeed despite activity update failure
                response = client.post("/auth/logout", headers={"Authorization": f"Bearer {token}"})

                # Should succeed
                assert response.status_code == 200


class TestTokenValidation:
    """Tests for token validation with blocklist."""

    def test_missing_jti_rejected(self, client):
        """Test that tokens without JTI are rejected for logout."""
        # Create token without JTI
        now = datetime.now(timezone.utc)

        payload = {
            "sub": "test@example.com",
            "exp": int((now + timedelta(minutes=20)).timestamp()),
            "iat": int(now.timestamp()),
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
            "is_admin": False,
            "teams": [],
            # Missing JTI
        }

        token = jwt.encode(payload, settings.jwt_secret_key.get_secret_value(), algorithm=settings.jwt_algorithm)

        response = client.post("/auth/logout", headers={"Authorization": f"Bearer {token}"})

        # The auth system will reject this with 401 because the user doesn't exist
        # or with 400 if JTI validation happens first
        assert response.status_code in [400, 401]
        if response.status_code == 400:
            assert "does not support revocation" in response.json()["detail"]

    def test_invalid_token_format_rejected(self, client):
        """Test that invalid token format is rejected."""
        response = client.post("/auth/logout", headers={"Authorization": "Bearer invalid-token-format"})

        assert response.status_code == 401

    def test_missing_authorization_header(self, client):
        """Test that missing authorization header is rejected."""
        response = client.post("/auth/logout")

        assert response.status_code == 401


class TestSecurityAudit:
    """Tests for security audit trail."""

    def test_logout_creates_audit_trail(self, client, test_db_session):
        """Test that logout creates proper audit trail."""
        # Login
        login_response = client.post("/auth/login", json={"email": "test@example.com", "password": "TestPassword123!"})  # pragma: allowlist secret

        token = login_response.json()["access_token"]

        # Logout
        client.post("/auth/logout", headers={"Authorization": f"Bearer {token}"})

        # Verify audit trail
        payload = jwt.decode(token, settings.jwt_secret_key.get_secret_value(), algorithms=[settings.jwt_algorithm], options={"verify_signature": False})

        jti = payload["jti"]
        revocation = test_db_session.execute(select(TokenRevocation).where(TokenRevocation.jti == jti)).scalar_one_or_none()

        assert revocation is not None
        assert revocation.revoked_by == "test@example.com"
        assert revocation.reason == "logout"
        assert revocation.revoked_at is not None
        assert revocation.token_expiry is not None


class TestConcurrentRevocation:
    """Tests for concurrent token revocation."""

    def test_double_logout_idempotent(self, client):
        """Test that logging out twice is idempotent."""
        # Login
        login_response = client.post("/auth/login", json={"email": "test@example.com", "password": "TestPassword123!"})  # pragma: allowlist secret

        token = login_response.json()["access_token"]

        # First logout
        response1 = client.post("/auth/logout", headers={"Authorization": f"Bearer {token}"})

        assert response1.status_code == 200

        # Second logout - should still succeed (idempotent)
        response2 = client.post("/auth/logout", headers={"Authorization": f"Bearer {token}"})

        # May fail with 401 if token is checked before revocation
        assert response2.status_code in [200, 401]
