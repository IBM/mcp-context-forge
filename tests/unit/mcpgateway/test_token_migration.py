# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_token_migration.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for JWT token PII cleanup migration (Phase 1).

Tests the helper functions that enable backward-compatible token migration
from email-based to user-ID-based tokens.
"""

import pytest
from unittest.mock import MagicMock, patch
from mcpgateway.auth import get_user_email_from_token
from mcpgateway.auth_context import set_user_context_from_token
from mcpgateway.db import EmailUser

TEST_UUID = "550e8400-e29b-41d4-a716-446655440000"
UNKNOWN_UUID = "00000000-0000-0000-0000-000000000000"


@pytest.mark.asyncio
async def test_get_user_email_from_token_with_email():
    """Test legacy token format with email in sub claim."""
    payload = {"sub": "user@example.com"}
    db = MagicMock()

    email = await get_user_email_from_token(payload, db)

    assert email == "user@example.com"
    # Should not query database for email format
    db.query.assert_not_called()


@pytest.mark.asyncio
async def test_get_user_email_from_token_with_user_id():
    """Test new token format with UUID in sub claim."""
    payload = {"sub": TEST_UUID}

    # Mock database query
    db = MagicMock()
    mock_user = MagicMock(spec=EmailUser)
    mock_user.email = "user@example.com"
    db.query.return_value.filter.return_value.first.return_value = mock_user

    email = await get_user_email_from_token(payload, db)

    assert email == "user@example.com"
    # Should query database for UUID
    db.query.assert_called_once()


@pytest.mark.asyncio
async def test_get_user_email_from_token_with_unknown_uuid():
    """Test unknown UUID returns None."""
    payload = {"sub": UNKNOWN_UUID}

    # Mock database query returning no user
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None

    email = await get_user_email_from_token(payload, db)

    assert email is None


@pytest.mark.asyncio
async def test_get_user_email_from_token_with_missing_sub():
    """Test missing sub claim returns None."""
    payload = {}
    db = MagicMock()

    email = await get_user_email_from_token(payload, db)

    assert email is None


@pytest.mark.asyncio
async def test_get_user_email_from_token_with_none_sub():
    """Test None sub claim returns None."""
    payload = {"sub": None}
    db = MagicMock()

    email = await get_user_email_from_token(payload, db)

    assert email is None


@pytest.mark.asyncio
async def test_get_user_email_from_token_with_non_string_sub():
    """Test non-string sub claim returns None."""
    payload = {"sub": 12345}  # Integer instead of string
    db = MagicMock()

    email = await get_user_email_from_token(payload, db)

    assert email is None


@pytest.mark.asyncio
async def test_set_user_context_from_token_with_email():
    """Test setting user context from legacy token with email — is_admin from DB."""
    request = MagicMock()
    request.state = MagicMock()
    payload = {"sub": "user@example.com", "auth_provider": "oauth"}
    db = MagicMock()

    mock_db_user = MagicMock()
    mock_db_user.is_admin = True

    with patch("mcpgateway.auth._get_user_by_email_sync", return_value=mock_db_user):
        await set_user_context_from_token(request, payload, db)

    assert request.state.user_email == "user@example.com"
    assert request.state.user_id == "user@example.com"
    assert request.state.is_admin is True
    assert request.state.auth_provider == "oauth"


@pytest.mark.asyncio
async def test_set_user_context_from_token_with_user_id():
    """Test setting user context from new token with UUID — is_admin from DB."""
    request = MagicMock()
    request.state = MagicMock()
    payload = {"sub": TEST_UUID, "auth_provider": "local"}

    # Mock database query for UUID→email resolution
    db = MagicMock()
    mock_user = MagicMock(spec=EmailUser)
    mock_user.email = "user@example.com"
    db.query.return_value.filter.return_value.first.return_value = mock_user

    mock_db_user = MagicMock()
    mock_db_user.is_admin = False

    with patch("mcpgateway.auth._get_user_by_email_sync", return_value=mock_db_user):
        await set_user_context_from_token(request, payload, db)

    assert request.state.user_email == "user@example.com"
    assert request.state.user_id == TEST_UUID
    assert request.state.is_admin is False
    assert request.state.auth_provider == "local"


@pytest.mark.asyncio
async def test_set_user_context_from_token_defaults():
    """Test default values when fields are missing — is_admin False when user not in DB."""
    request = MagicMock()
    request.state = MagicMock()
    payload = {"sub": "user@example.com"}
    db = MagicMock()

    with patch("mcpgateway.auth._get_user_by_email_sync", return_value=None):
        await set_user_context_from_token(request, payload, db)

    assert request.state.user_email == "user@example.com"
    assert request.state.user_id == "user@example.com"
    assert request.state.is_admin is False  # Default when no DB user
    assert request.state.auth_provider == "local"  # Default


@pytest.mark.asyncio
async def test_flattened_token_structure():
    """Test that new tokens have flattened structure (no nested user object)."""
    from mcpgateway.routers.email_auth import create_access_token
    from mcpgateway.db import EmailUser

    # Create mock user
    user = MagicMock(spec=EmailUser)
    user.id = TEST_UUID
    user.email = "user@example.com"
    user.is_admin = True
    user.auth_provider = "local"

    token, expires_in = await create_access_token(user)

    # Decode token to check structure
    import jwt
    from mcpgateway.config import settings

    payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm], options={"verify_signature": False})

    # Should have flattened structure with no user attributes
    assert "user" not in payload  # No nested user object
    assert "is_admin" not in payload  # Not in session tokens; fetched from DB on use
    assert payload["auth_provider"] == "local"
    assert "full_name" not in payload  # PII removed

    assert payload["sub"] == TEST_UUID


@pytest.mark.asyncio
async def test_legacy_token_structure():
    """Test that legacy tokens have flattened structure."""
    from mcpgateway.routers.email_auth import create_legacy_access_token
    from mcpgateway.db import EmailUser

    # Create mock user
    user = MagicMock(spec=EmailUser)
    user.id = TEST_UUID
    user.email = "user@example.com"
    user.is_admin = False
    user.auth_provider = "oauth"

    token, expires_in = await create_legacy_access_token(user)

    # Decode token to check structure
    import jwt
    from mcpgateway.config import settings

    payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm], options={"verify_signature": False})

    # Should have no user attributes in session token
    assert "is_admin" not in payload  # Not in session tokens; fetched from DB on use
    assert payload["auth_provider"] == "oauth"
    assert "full_name" not in payload  # PII removed
    assert "email" not in payload  # PII removed

    assert payload["sub"] == TEST_UUID
