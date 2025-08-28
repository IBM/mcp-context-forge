# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_multi_user_basic.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Basic Multi-User System Tests.
Tests core functionality of the multi-user authentication system.
"""

# Standard
import pytest
from unittest.mock import Mock, patch

# Third-Party
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import Base, User, ApiToken
from mcpgateway.services.user_service import UserService, PasswordPolicy
from mcpgateway.services.jwt_service import JWTService


# Test fixtures
@pytest.fixture
def test_db():
    """Create a test database."""
    engine = create_engine("sqlite:///test_multi_user.db", echo=False)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)

    session = SessionLocal()
    yield session

    session.close()
    Base.metadata.drop_all(engine)


@pytest.fixture
def user_service(test_db):
    """Create UserService with test database."""
    return UserService(test_db)


@pytest.fixture
def jwt_service(test_db):
    """Create JWTService with test database."""
    return JWTService(test_db)


# Password Policy Tests
class TestPasswordPolicy:
    """Test password policy validation."""

    def test_valid_password(self):
        """Test that valid passwords pass validation."""
        policy = PasswordPolicy()
        errors = policy.validate("SecurePassword123!")
        assert len(errors) == 0

    def test_too_short_password(self):
        """Test that short passwords fail validation."""
        policy = PasswordPolicy()
        errors = policy.validate("short")
        assert any("at least" in error for error in errors)

    def test_common_password_rejected(self):
        """Test that common passwords are rejected."""
        policy = PasswordPolicy()
        errors = policy.validate("password")
        assert any("common" in error.lower() for error in errors)

    def test_password_hashing(self):
        """Test that password hashing works correctly."""
        policy = PasswordPolicy()
        password = "TestPassword123!"
        hash1 = policy.hash_password(password)
        hash2 = policy.hash_password(password)

        # Hashes should be different (due to salt)
        assert hash1 != hash2

        # But both should verify correctly
        assert policy.verify_password(password, hash1)
        assert policy.verify_password(password, hash2)

        # Wrong password should not verify
        assert not policy.verify_password("wrong", hash1)


# User Service Tests
class TestUserService:
    """Test UserService functionality."""

    @pytest.mark.asyncio
    async def test_create_user(self, user_service):
        """Test user creation."""
        user = await user_service.create_user(
            username="testuser",
            password="TestPassword123!",
            email="test@example.com",
            full_name="Test User"
        )

        assert user.username == "testuser"
        assert user.email == "test@example.com"
        assert user.full_name == "Test User"
        assert user.is_active is True
        assert user.is_admin is False
        assert user.password_hash != "TestPassword123!"  # Should be hashed

    @pytest.mark.asyncio
    async def test_create_admin_user(self, user_service):
        """Test admin user creation."""
        user = await user_service.create_user(
            username="adminuser",
            password="AdminPassword123!",
            is_admin=True
        )

        assert user.is_admin is True

    @pytest.mark.asyncio
    async def test_duplicate_username_rejected(self, user_service):
        """Test that duplicate usernames are rejected."""
        # Create first user
        await user_service.create_user(
            username="testuser",
            password="TestPassword123!"
        )

        # Try to create second user with same username
        with pytest.raises(Exception):
            await user_service.create_user(
                username="testuser",
                password="AnotherPassword123!"
            )

    @pytest.mark.asyncio
    async def test_authenticate_user_success(self, user_service):
        """Test successful user authentication."""
        # Create user
        await user_service.create_user(
            username="testuser",
            password="TestPassword123!"
        )

        # Authenticate
        user = await user_service.authenticate_user(
            username="testuser",
            password="TestPassword123!"
        )

        assert user is not None
        assert user.username == "testuser"

    @pytest.mark.asyncio
    async def test_authenticate_user_failure(self, user_service):
        """Test failed user authentication."""
        # Create user
        await user_service.create_user(
            username="testuser",
            password="TestPassword123!"
        )

        # Try wrong password
        user = await user_service.authenticate_user(
            username="testuser",
            password="WrongPassword"
        )

        assert user is None

    @pytest.mark.asyncio
    async def test_authenticate_nonexistent_user(self, user_service):
        """Test authentication with non-existent user."""
        user = await user_service.authenticate_user(
            username="nonexistent",
            password="TestPassword123!"
        )

        assert user is None

    @pytest.mark.asyncio
    async def test_change_password(self, user_service):
        """Test password change functionality."""
        # Create user
        user = await user_service.create_user(
            username="testuser",
            password="OldPassword123!"
        )

        # Change password
        success = await user_service.change_password(
            user_id=user.id,
            current_password="OldPassword123!",
            new_password="NewPassword456!"
        )

        assert success is True

        # Verify old password no longer works
        old_auth = await user_service.authenticate_user(
            username="testuser",
            password="OldPassword123!"
        )
        assert old_auth is None

        # Verify new password works
        new_auth = await user_service.authenticate_user(
            username="testuser",
            password="NewPassword456!"
        )
        assert new_auth is not None


# JWT Service Tests
class TestJWTService:
    """Test JWT Service functionality."""

    @pytest.mark.asyncio
    async def test_create_token(self, jwt_service, user_service):
        """Test JWT token creation."""
        # Create user
        user = await user_service.create_user(
            username="testuser",
            password="TestPassword123!"
        )

        # Create token
        token_data = await jwt_service.create_token(
            user=user,
            name="test-token",
            description="Test token"
        )

        assert "token" in token_data
        assert "jti" in token_data
        assert token_data["name"] == "test-token"
        assert token_data["description"] == "Test token"

    @pytest.mark.asyncio
    async def test_verify_token(self, jwt_service, user_service):
        """Test JWT token verification."""
        # Create user
        user = await user_service.create_user(
            username="testuser",
            password="TestPassword123!"
        )

        # Create token
        token_data = await jwt_service.create_token(
            user=user,
            name="test-token"
        )

        # Verify token
        payload = await jwt_service.verify_token(token_data["token"])

        assert payload["sub"] == user.id
        assert payload["username"] == user.username
        assert "jti" in payload

    @pytest.mark.asyncio
    async def test_revoke_token(self, jwt_service, user_service):
        """Test JWT token revocation."""
        # Create user
        user = await user_service.create_user(
            username="testuser",
            password="TestPassword123!"
        )

        # Create token
        token_data = await jwt_service.create_token(
            user=user,
            name="test-token"
        )

        # Verify token works
        payload = await jwt_service.verify_token(token_data["token"])
        assert payload is not None

        # Revoke token
        await jwt_service.revoke_token(token_data["jti"], user.id)

        # Verify token no longer works
        with pytest.raises(Exception):
            await jwt_service.verify_token(token_data["token"])

    @pytest.mark.asyncio
    async def test_list_user_tokens(self, jwt_service, user_service):
        """Test listing user tokens."""
        # Create user
        user = await user_service.create_user(
            username="testuser",
            password="TestPassword123!"
        )

        # Create multiple tokens
        await jwt_service.create_token(user=user, name="token1")
        await jwt_service.create_token(user=user, name="token2")

        # List tokens
        tokens = await jwt_service.list_user_tokens(user.id)

        assert len(tokens) == 2
        token_names = [token["name"] for token in tokens]
        assert "token1" in token_names
        assert "token2" in token_names


# Configuration Tests
class TestMultiUserConfiguration:
    """Test multi-user configuration."""

    def test_multi_user_enabled_by_default(self):
        """Test that multi-user is enabled by default."""
        # This tests the default configuration
        assert settings.multi_user_enabled is True

    def test_legacy_auth_mode_disabled_by_default(self):
        """Test that legacy auth mode is disabled by default."""
        assert settings.legacy_auth_mode is False

    def test_password_policy_settings(self):
        """Test password policy configuration."""
        assert settings.password_min_length >= 8
        assert settings.password_bcrypt_rounds >= 10


if __name__ == "__main__":
    pytest.main([__file__])
