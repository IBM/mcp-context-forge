"""Unit tests for JWT token PII cleanup migration (Phase 1).

Tests the helper functions that enable backward-compatible token migration
from email-based to user-ID-based tokens.
"""

import pytest
from unittest.mock import MagicMock
from mcpgateway.auth import get_user_email_from_token
from mcpgateway.auth_context import set_user_context_from_token
from mcpgateway.db import EmailUser


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
    """Test new token format with user ID in sub claim."""
    payload = {"sub": "12345"}

    # Mock database query
    db = MagicMock()
    mock_user = MagicMock(spec=EmailUser)
    mock_user.email = "user@example.com"
    db.query.return_value.filter.return_value.first.return_value = mock_user

    email = await get_user_email_from_token(payload, db)

    assert email == "user@example.com"
    # Should query database for user ID
    db.query.assert_called_once()


@pytest.mark.asyncio
async def test_get_user_email_from_token_with_invalid_user_id():
    """Test invalid user ID returns None."""
    payload = {"sub": "99999"}

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
    """Test setting user context from legacy token with email."""
    request = MagicMock()
    request.state = MagicMock()
    payload = {"sub": "user@example.com", "is_admin": True, "auth_provider": "oauth"}
    db = MagicMock()

    await set_user_context_from_token(request, payload, db)

    assert request.state.user_email == "user@example.com"
    assert request.state.user_id == "user@example.com"
    assert request.state.is_admin is True
    assert request.state.auth_provider == "oauth"


@pytest.mark.asyncio
async def test_set_user_context_from_token_with_user_id():
    """Test setting user context from new token with user ID."""
    request = MagicMock()
    request.state = MagicMock()
    payload = {"sub": "12345", "is_admin": False, "auth_provider": "local"}

    # Mock database query
    db = MagicMock()
    mock_user = MagicMock(spec=EmailUser)
    mock_user.email = "user@example.com"
    db.query.return_value.filter.return_value.first.return_value = mock_user

    await set_user_context_from_token(request, payload, db)

    assert request.state.user_email == "user@example.com"
    assert request.state.user_id == "12345"
    assert request.state.is_admin is False
    assert request.state.auth_provider == "local"


@pytest.mark.asyncio
async def test_set_user_context_from_token_defaults():
    """Test default values when fields are missing."""
    request = MagicMock()
    request.state = MagicMock()
    payload = {"sub": "user@example.com"}
    db = MagicMock()

    await set_user_context_from_token(request, payload, db)

    assert request.state.user_email == "user@example.com"
    assert request.state.user_id == "user@example.com"
    assert request.state.is_admin is False  # Default
    assert request.state.auth_provider == "local"  # Default


@pytest.mark.asyncio
async def test_flattened_token_structure():
    """Test that new tokens have flattened structure (no nested user object)."""
    from mcpgateway.routers.email_auth import create_access_token
    from mcpgateway.db import EmailUser

    # Create mock user
    user = MagicMock(spec=EmailUser)
    user.id = 12345
    user.email = "user@example.com"
    user.is_admin = True
    user.auth_provider = "local"

    token, expires_in = await create_access_token(user)

    # Decode token to check structure
    import jwt
    from mcpgateway.config import settings

    payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm], options={"verify_signature": False})

    # Should have flattened structure
    assert "user" not in payload  # No nested user object
    assert payload["is_admin"] is True  # Flattened
    assert payload["auth_provider"] == "local"  # Flattened
    assert "full_name" not in payload  # PII removed

    # Phase 2: sub now contains user ID instead of email
    assert payload["sub"] == "12345"


@pytest.mark.asyncio
async def test_legacy_token_structure():
    """Test that legacy tokens have flattened structure."""
    from mcpgateway.routers.email_auth import create_legacy_access_token
    from mcpgateway.db import EmailUser

    # Create mock user
    user = MagicMock(spec=EmailUser)
    user.id = 12345
    user.email = "user@example.com"
    user.is_admin = False
    user.auth_provider = "oauth"

    token, expires_in = await create_legacy_access_token(user)

    # Decode token to check structure
    import jwt
    from mcpgateway.config import settings

    payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm], options={"verify_signature": False})

    # Should have flattened structure
    assert payload["is_admin"] is False
    assert payload["auth_provider"] == "oauth"
    assert "full_name" not in payload  # PII removed
    assert "email" not in payload  # Duplicate removed

    # Phase 2: sub now contains user ID instead of email
    assert payload["sub"] == "12345"
