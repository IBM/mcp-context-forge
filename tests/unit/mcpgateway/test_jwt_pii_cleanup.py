"""Unit tests for JWT PII cleanup migration.

Tests the token structure changes to eliminate PII from JWT payloads.
"""

import pytest
from unittest.mock import Mock
from mcpgateway.auth import get_user_email_from_token


@pytest.mark.asyncio
async def test_get_user_email_from_token_with_email():
    """Test extracting email from sub claim."""
    mock_db = Mock()
    payload = {"sub": "user@example.com"}

    # Execute
    result = await get_user_email_from_token(payload, mock_db)

    # Verify
    assert result == "user@example.com"


@pytest.mark.asyncio
async def test_get_user_email_from_token_missing_sub():
    """Test handling of missing sub claim."""
    mock_db = Mock()
    payload = {}

    # Execute
    result = await get_user_email_from_token(payload, mock_db)

    # Verify
    assert result is None


@pytest.mark.asyncio
async def test_token_payload_structure_new_format():
    """Test new token format has no PII in nested objects."""
    from mcpgateway.routers.email_auth import create_access_token
    from mcpgateway.db import EmailUser

    # Create mock user
    user = Mock(spec=EmailUser)
    user.id = 12345
    user.email = "user@example.com"
    user.full_name = "Test User"
    user.is_admin = False
    user.auth_provider = "local"

    # Generate token
    token, expires_in = await create_access_token(user)

    # Decode token (without verification for testing)
    import jwt

    payload = jwt.decode(token, options={"verify_signature": False})

    # Verify structure - email in sub, no nested user object
    assert payload["sub"] == "12345"  # User ID in sub
    assert "user" not in payload  # No nested user object
    assert "email" not in payload  # No separate email field
    assert "full_name" not in payload  # No full_name field
    assert payload["is_admin"] is False  # Flattened
    assert payload["auth_provider"] == "local"  # Flattened
    assert payload["token_use"] == "session"


@pytest.mark.asyncio
async def test_token_payload_structure_legacy_format():
    """Test legacy token format has no PII."""
    from mcpgateway.routers.email_auth import create_legacy_access_token
    from mcpgateway.db import EmailUser

    # Create mock user
    user = Mock(spec=EmailUser)
    user.id = 12345
    user.email = "user@example.com"
    user.full_name = "Test User"
    user.is_admin = True
    user.auth_provider = "oauth"

    # Generate token
    token, expires_in = await create_legacy_access_token(user)

    # Decode token (without verification for testing)
    import jwt

    payload = jwt.decode(token, options={"verify_signature": False})

    # Verify structure - user ID in sub, no PII fields
    assert payload["sub"] == "12345"  # User ID in sub
    assert "email" not in payload  # No email field
    assert "full_name" not in payload  # No full_name field
    assert payload["is_admin"] is True  # Flattened
    assert payload["auth_provider"] == "oauth"  # Flattened
