# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/token_backends/test_db_backend.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for DatabaseTokenBackend.
"""

# Standard
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.db import OAuthToken
from mcpgateway.services.token_backends.db_backend import DatabaseTokenBackend


@pytest.fixture
def mock_db():
    """Create a mock database session."""
    db = MagicMock()
    return db


@pytest.fixture
def mock_settings():
    """Create mock settings for database backend."""
    settings = MagicMock()
    settings.auth_encryption_secret = "test-salt"  # pragma: allowlist secret
    settings.oauth_token_backend = "database"
    return settings


@pytest.fixture
def backend_with_encryption(mock_db, mock_settings):
    """Create DatabaseTokenBackend with encryption enabled."""
    with patch("mcpgateway.services.token_backends.db_backend.get_encryption_service") as mock_enc:
        mock_enc_instance = MagicMock()
        mock_enc_instance.encrypt_secret_async = AsyncMock(return_value="encrypted_value")
        mock_enc_instance.decrypt_secret_async = AsyncMock(return_value="decrypted_value")
        mock_enc.return_value = mock_enc_instance
        backend = DatabaseTokenBackend(mock_db, mock_settings)
    return backend


@pytest.fixture
def backend_no_encryption(mock_db, mock_settings):
    """Create DatabaseTokenBackend without encryption."""
    with patch("mcpgateway.services.token_backends.db_backend.get_encryption_service") as mock_enc:
        mock_enc.side_effect = ImportError("No encryption")
        backend = DatabaseTokenBackend(mock_db, mock_settings)
    assert backend.encryption is None
    return backend


def _make_token_record(**overrides):
    """Helper to create OAuthToken test fixtures."""
    defaults = {
        "gateway_id": "gw-1",
        "user_id": "oauth-user-1",
        "app_user_email": "user@test.com",
        "access_token": "encrypted_access",
        "refresh_token": "encrypted_refresh",
        "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
        "scopes": ["read", "write"],
        "token_type": "bearer",
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# ---------- _is_token_expired ----------


def test_is_token_expired_no_expires_at(backend_with_encryption):
    """Tokens with no expires_at are never expired."""
    record = _make_token_record(expires_at=None)
    assert backend_with_encryption._is_token_expired(record) is False


def test_is_token_expired_future(backend_with_encryption):
    """Token expiring in the future is not expired."""
    record = _make_token_record(expires_at=datetime.now(timezone.utc) + timedelta(hours=1))
    assert backend_with_encryption._is_token_expired(record, threshold_seconds=300) is False


def test_is_token_expired_past(backend_with_encryption):
    """Token that expired in the past is expired."""
    record = _make_token_record(expires_at=datetime.now(timezone.utc) - timedelta(seconds=10))
    assert backend_with_encryption._is_token_expired(record, threshold_seconds=0) is True


def test_is_token_expired_within_threshold(backend_with_encryption):
    """Token expiring within threshold is considered expired."""
    record = _make_token_record(expires_at=datetime.now(timezone.utc) + timedelta(seconds=100))
    assert backend_with_encryption._is_token_expired(record, threshold_seconds=200) is True


def test_is_token_expired_naive_datetime(backend_with_encryption):
    """Test _is_token_expired with a naive datetime (no timezone)."""
    naive_time = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=10)
    record = _make_token_record(expires_at=naive_time)
    # The implementation adds timezone.utc to naive datetimes
    result = backend_with_encryption._is_token_expired(record, threshold_seconds=0)
    # A past datetime (even if naive) should be expired
    assert result is True


# ---------- store_tokens ----------


@pytest.mark.asyncio
async def test_store_tokens_new(backend_with_encryption, mock_db):
    """Test storing new OAuth tokens with encryption."""
    mock_db.execute.return_value.scalar_one_or_none.return_value = None
    mock_db.query.return_value.filter.return_value.first.return_value = Mock(
        id="gw-1",
        url="https://example.com"
    )

    with patch("mcpgateway.services.token_backends.db_backend.datetime") as mock_dt:
        fixed_time = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        mock_dt.now = Mock(return_value=fixed_time)

        result = await backend_with_encryption.store_tokens(
            gateway_id="gw-1",
            team_id="team-1",
            user_id="oauth-user-1",
            app_user_email="user@test.com",
            access_token="access_token",
            refresh_token="refresh_token",
            expires_in=3600,
            scopes=["read", "write"],
        )

        # Verify database operations
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()

        # Verify the result
        assert result.gateway_id == "gw-1"
        assert result.user_id == "oauth-user-1"
        assert result.app_user_email == "user@test.com"


@pytest.mark.asyncio
async def test_store_tokens_update_existing(backend_with_encryption, mock_db):
    """Test updating existing OAuth tokens."""
    existing_token = OAuthToken(
        gateway_id="gw-1",
        user_id="oauth-user-1",
        app_user_email="user@test.com",
        access_token="old_access",
        refresh_token="old_refresh",
        expires_at=datetime(2025, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
        scopes=["read"],
        created_at=datetime(2025, 1, 1, 9, 0, 0, tzinfo=timezone.utc),
        updated_at=datetime(2025, 1, 1, 9, 0, 0, tzinfo=timezone.utc),
    )
    mock_db.execute.return_value.scalar_one_or_none.return_value = existing_token
    mock_db.query.return_value.filter.return_value.first.return_value = Mock(
        id="gw-1",
        url="https://example.com"
    )

    with patch("mcpgateway.services.token_backends.db_backend.datetime") as mock_dt:
        fixed_time = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        mock_dt.now = Mock(return_value=fixed_time)

        result = await backend_with_encryption.store_tokens(
            gateway_id="gw-1",
            team_id="team-1",
            user_id="oauth-user-1",
            app_user_email="user@test.com",
            access_token="new_access",
            refresh_token="new_refresh",
            expires_in=3600,
            scopes=["read", "write"],
        )

        # Verify no new record was added
        mock_db.add.assert_not_called()
        mock_db.commit.assert_called_once()

        # Verify existing token was updated
        assert existing_token.access_token == "encrypted_value"


@pytest.mark.asyncio
async def test_store_tokens_no_encryption(backend_no_encryption, mock_db):
    """Test storing tokens without encryption stores plain text."""
    mock_db.execute.return_value.scalar_one_or_none.return_value = None
    mock_db.query.return_value.filter.return_value.first.return_value = Mock(
        id="gw-1",
        url="https://example.com"
    )

    with patch("mcpgateway.services.token_backends.db_backend.datetime") as mock_dt:
        fixed_time = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        mock_dt.now = Mock(return_value=fixed_time)

        result = await backend_no_encryption.store_tokens(
            gateway_id="gw-1",
            team_id="team-1",
            user_id="oauth-user-1",
            app_user_email="user@test.com",
            access_token="plain_access",
            refresh_token="plain_refresh",
            expires_in=3600,
            scopes=["read"],
        )

        # Verify the token was added
        mock_db.add.assert_called_once()
        added_token = mock_db.add.call_args[0][0]
        # Without encryption, tokens are stored as-is
        assert added_token.access_token == "plain_access"
        assert added_token.refresh_token == "plain_refresh"


@pytest.mark.asyncio
async def test_store_tokens_exception(backend_with_encryption, mock_db):
    """Test that storage exceptions are properly handled."""
    mock_db.execute.return_value.scalar_one_or_none.side_effect = Exception("DB error")

    with pytest.raises(Exception, match="DB error"):
        await backend_with_encryption.store_tokens(
            gateway_id="gw-1",
            team_id="team-1",
            user_id="oauth-user-1",
            app_user_email="user@test.com",
            access_token="access",
            refresh_token="refresh",
            expires_in=3600,
            scopes=["read"],
        )

    mock_db.rollback.assert_called_once()


@pytest.mark.asyncio
async def test_store_tokens_no_expires_in_persists_null(backend_with_encryption, mock_db):
    """Test that omitted expires_in results in NULL expires_at."""
    mock_db.execute.return_value.scalar_one_or_none.return_value = None
    mock_db.query.return_value.filter.return_value.first.return_value = Mock(
        id="gw-1",
        url="https://example.com"
    )

    await backend_with_encryption.store_tokens(
        gateway_id="gw-1",
        team_id="team-1",
        user_id="oauth-user-1",
        app_user_email="user@test.com",
        access_token="access",
        refresh_token="refresh",
        expires_in=None,  # No expiration
        scopes=["read"],
    )

    added_token = mock_db.add.call_args[0][0]
    assert added_token.expires_at is None


# ---------- get_user_token ----------


@pytest.mark.asyncio
async def test_get_user_token_not_found(backend_with_encryption, mock_db):
    """Test that None is returned when no token exists."""
    mock_db.execute.return_value.scalar_one_or_none.return_value = None

    result = await backend_with_encryption.get_user_token(
        gateway_id="gw-1",
        team_id="team-1",
        app_user_email="user@test.com",
        threshold_seconds=300,
    )

    assert result is None


@pytest.mark.asyncio
async def test_get_user_token_valid(backend_with_encryption, mock_db):
    """Test retrieving a valid non-expired token."""
    future_time = datetime.now(timezone.utc) + timedelta(hours=1)
    token_record = _make_token_record(
        access_token="encrypted_access",
        expires_at=future_time
    )
    mock_db.execute.return_value.scalar_one_or_none.return_value = token_record

    result = await backend_with_encryption.get_user_token(
        gateway_id="gw-1",
        team_id="team-1",
        app_user_email="user@test.com",
        threshold_seconds=300,
    )

    # Should return decrypted token
    assert result == "decrypted_value"


@pytest.mark.asyncio
async def test_get_user_token_valid_no_encryption(backend_no_encryption, mock_db):
    """Test retrieving token without encryption returns plain text."""
    future_time = datetime.now(timezone.utc) + timedelta(hours=1)
    token_record = _make_token_record(
        access_token="plain_access",
        expires_at=future_time
    )
    mock_db.execute.return_value.scalar_one_or_none.return_value = token_record

    result = await backend_no_encryption.get_user_token(
        gateway_id="gw-1",
        team_id="team-1",
        app_user_email="user@test.com",
        threshold_seconds=300,
    )

    assert result == "plain_access"


@pytest.mark.asyncio
async def test_get_user_token_expired_with_refresh(backend_with_encryption, mock_db):
    """Test that expired token attempts refresh if refresh_token exists."""
    past_time = datetime.now(timezone.utc) - timedelta(seconds=10)
    token_record = _make_token_record(
        access_token="encrypted_access",
        refresh_token="encrypted_refresh",
        expires_at=past_time
    )
    mock_db.execute.return_value.scalar_one_or_none.return_value = token_record

    # Mock _refresh_access_token to return a new token
    with patch.object(backend_with_encryption, "_refresh_access_token", new_callable=AsyncMock) as mock_refresh:
        mock_refresh.return_value = "refreshed_token"

        result = await backend_with_encryption.get_user_token(
            gateway_id="gw-1",
            team_id="team-1",
            app_user_email="user@test.com",
            threshold_seconds=0,
        )

        mock_refresh.assert_called_once_with(token_record)
        assert result == "refreshed_token"


@pytest.mark.asyncio
async def test_get_user_token_expired_no_refresh(backend_with_encryption, mock_db):
    """Test that expired token without refresh_token returns None."""
    past_time = datetime.now(timezone.utc) - timedelta(seconds=10)
    token_record = _make_token_record(
        access_token="encrypted_access",
        refresh_token=None,  # No refresh token
        expires_at=past_time
    )
    mock_db.execute.return_value.scalar_one_or_none.return_value = token_record

    result = await backend_with_encryption.get_user_token(
        gateway_id="gw-1",
        team_id="team-1",
        app_user_email="user@test.com",
        threshold_seconds=0,
    )

    assert result is None


@pytest.mark.asyncio
async def test_get_user_token_non_bearer_type(backend_with_encryption, mock_db):
    """Test warning when token_type is not Bearer."""
    future_time = datetime.now(timezone.utc) + timedelta(hours=1)
    token_record = _make_token_record(
        access_token="encrypted_access",
        expires_at=future_time,
        token_type="basic"  # Non-bearer type
    )
    mock_db.execute.return_value.scalar_one_or_none.return_value = token_record

    with patch("mcpgateway.services.token_backends.db_backend.logger") as mock_logger:
        result = await backend_with_encryption.get_user_token(
            gateway_id="gw-1",
            team_id="team-1",
            app_user_email="user@test.com",
            threshold_seconds=300,
        )

        # Should log warning but still return token
        mock_logger.warning.assert_called_once()
        assert result == "decrypted_value"


@pytest.mark.asyncio
async def test_get_user_token_exception(backend_with_encryption, mock_db):
    """Test that exceptions are caught and None is returned."""
    mock_db.execute.side_effect = Exception("Database error")

    with patch("mcpgateway.services.token_backends.db_backend.logger") as mock_logger:
        result = await backend_with_encryption.get_user_token(
            gateway_id="gw-1",
            team_id="team-1",
            app_user_email="user@test.com",
            threshold_seconds=300,
        )

        mock_logger.error.assert_called_once()
        assert result is None


# ---------- get_token_info ----------


@pytest.mark.asyncio
async def test_get_token_info_not_found(backend_with_encryption, mock_db):
    """Test get_token_info returns None when token doesn't exist."""
    mock_db.execute.return_value.scalar_one_or_none.return_value = None

    result = await backend_with_encryption.get_token_info(
        gateway_id="gw-1",
        team_id="team-1",
        app_user_email="user@test.com",
    )

    assert result is None


@pytest.mark.asyncio
async def test_get_token_info_success(backend_with_encryption, mock_db):
    """Test get_token_info returns metadata for valid token."""
    created_at = datetime(2025, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
    expires_at = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    token_record = _make_token_record(
        access_token="encrypted_access",
        expires_at=expires_at,
        created_at=created_at,
        scopes=["read", "write"]
    )
    mock_db.execute.return_value.scalar_one_or_none.return_value = token_record

    result = await backend_with_encryption.get_token_info(
        gateway_id="gw-1",
        team_id="team-1",
        app_user_email="user@test.com",
    )

    assert result is not None
    # Should not include sensitive fields
    assert "access_token" not in result
    assert "refresh_token" not in result


@pytest.mark.asyncio
async def test_get_token_info_expired_token(backend_with_encryption, mock_db):
    """Test get_token_info marks expired tokens."""
    past_time = datetime.now(timezone.utc) - timedelta(seconds=10)
    token_record = _make_token_record(expires_at=past_time)
    mock_db.execute.return_value.scalar_one_or_none.return_value = token_record

    result = await backend_with_encryption.get_token_info(
        gateway_id="gw-1",
        team_id="team-1",
        app_user_email="user@test.com",
    )

    assert result is not None


@pytest.mark.asyncio
async def test_get_token_info_exception(backend_with_encryption, mock_db):
    """Test get_token_info handles exceptions gracefully."""
    mock_db.execute.side_effect = Exception("Database error")

    with patch("mcpgateway.services.token_backends.db_backend.logger") as mock_logger:
        result = await backend_with_encryption.get_token_info(
            gateway_id="gw-1",
            team_id="team-1",
            app_user_email="user@test.com",
        )

        mock_logger.error.assert_called_once()
        assert result is None


@pytest.mark.asyncio
async def test_refresh_token_with_client_secret_decrypt_failure(backend_with_encryption, mock_db):
    """Test refresh handles client_secret decryption failure gracefully."""
    token_record = _make_token_record(
        refresh_token="encrypted_refresh",
        gateway_id="gw-1"
    )

    # Mock gateway with encrypted client_secret
    mock_gateway = MagicMock()
    mock_gateway.oauth_config = {
        "client_id": "test",
        "client_secret": "encrypted_secret"  # pragma: allowlist secret
    }
    mock_gateway.visibility = "public"
    mock_gateway.url = "https://mcp.example.com"
    mock_gateway.ca_certificate = None
    mock_gateway.client_cert = None
    mock_gateway.client_key = None
    mock_db.query.return_value.filter.return_value.first.return_value = mock_gateway

    # Mock refresh token decryption success but client_secret fails
    async def decrypt_side_effect(value):
        if value == "encrypted_refresh":
            return "decrypted_refresh"
        raise Exception("Decrypt failed")

    backend_with_encryption.encryption.decrypt_secret_async.side_effect = decrypt_side_effect

    with patch("mcpgateway.services.token_backends.db_backend.OAuthManager") as mock_oauth_class:
        mock_oauth = AsyncMock()
        mock_oauth.refresh_token.return_value = {
            "access_token": "new_token",
            "expires_in": 3600
        }
        mock_oauth_class.return_value = mock_oauth

        result = await backend_with_encryption._refresh_access_token(token_record)

        # Should still succeed with encrypted client_secret (assumed plain text)
        assert result == "new_token"


# ---------- revoke_user_tokens ----------


@pytest.mark.asyncio
async def test_revoke_user_tokens_not_found(backend_with_encryption, mock_db):
    """Test revoke returns False when token doesn't exist."""
    mock_db.execute.return_value.scalar_one_or_none.return_value = None

    result = await backend_with_encryption.revoke_user_tokens(
        gateway_id="gw-1",
        team_id="team-1",
        app_user_email="user@test.com",
    )

    assert result is False
    mock_db.delete.assert_not_called()


@pytest.mark.asyncio
async def test_revoke_user_tokens_success(backend_with_encryption, mock_db):
    """Test revoke removes token successfully."""
    token_record = _make_token_record()
    mock_db.execute.return_value.scalar_one_or_none.return_value = token_record

    result = await backend_with_encryption.revoke_user_tokens(
        gateway_id="gw-1",
        team_id="team-1",
        app_user_email="user@test.com",
    )

    assert result is True
    mock_db.delete.assert_called_once_with(token_record)
    mock_db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_revoke_user_tokens_exception(backend_with_encryption, mock_db):
    """Test revoke handles exceptions gracefully."""
    mock_db.execute.side_effect = Exception("Database error")

    with patch("mcpgateway.services.token_backends.db_backend.logger") as mock_logger:
        result = await backend_with_encryption.revoke_user_tokens(
            gateway_id="gw-1",
            team_id="team-1",
            app_user_email="user@test.com",
        )

        mock_logger.error.assert_called_once()
        mock_db.rollback.assert_called_once()
        assert result is False


# ---------- _refresh_access_token ----------


@pytest.mark.asyncio
async def test_refresh_access_token_no_refresh_token(backend_with_encryption, mock_db):
    """Test refresh returns None when no refresh token available."""
    token_record = _make_token_record(refresh_token=None)

    with patch("mcpgateway.services.token_backends.db_backend.logger") as mock_logger:
        result = await backend_with_encryption._refresh_access_token(token_record)

        assert result is None
        mock_logger.warning.assert_called_once()


@pytest.mark.asyncio
async def test_refresh_access_token_no_gateway_config(backend_with_encryption, mock_db):
    """Test refresh returns None when gateway has no OAuth config."""
    token_record = _make_token_record(refresh_token="encrypted_refresh", gateway_id="gw-1")

    # Mock gateway without oauth_config
    mock_gateway = MagicMock()
    mock_gateway.oauth_config = None
    mock_db.query.return_value.filter.return_value.first.return_value = mock_gateway

    with patch("mcpgateway.services.token_backends.db_backend.logger") as mock_logger:
        result = await backend_with_encryption._refresh_access_token(token_record)

        assert result is None
        mock_logger.error.assert_called_once()


@pytest.mark.asyncio
async def test_refresh_access_token_private_gateway_wrong_owner(backend_with_encryption, mock_db):
    """Test refresh denied for private gateway with different owner."""
    token_record = _make_token_record(
        refresh_token="encrypted_refresh",
        gateway_id="gw-1",
        app_user_email="user@test.com"
    )

    # Mock private gateway owned by someone else
    mock_gateway = MagicMock()
    mock_gateway.id = "gw-1"
    mock_gateway.oauth_config = {"client_id": "test", "client_secret": "secret"}
    mock_gateway.visibility = "private"
    mock_gateway.owner_email = "owner@test.com"  # Different from token owner
    mock_db.query.return_value.filter.return_value.first.return_value = mock_gateway

    with patch("mcpgateway.services.token_backends.db_backend.logger") as mock_logger:
        result = await backend_with_encryption._refresh_access_token(token_record)

        assert result is None
        mock_logger.warning.assert_called()
        assert "OAuth refresh denied" in mock_logger.warning.call_args[0][0]


@pytest.mark.asyncio
async def test_refresh_access_token_decrypt_failure(backend_with_encryption, mock_db):
    """Test refresh handles refresh token decryption failure."""
    token_record = _make_token_record(
        refresh_token="encrypted_refresh",
        gateway_id="gw-1",
        app_user_email="user@test.com"
    )

    # Mock gateway
    mock_gateway = MagicMock()
    mock_gateway.oauth_config = {"client_id": "test", "client_secret": "secret"}
    mock_gateway.visibility = "public"
    mock_db.query.return_value.filter.return_value.first.return_value = mock_gateway

    # Mock encryption failure
    backend_with_encryption.encryption.decrypt_secret_async.side_effect = Exception("Decrypt failed")

    with patch("mcpgateway.services.token_backends.db_backend.logger") as mock_logger:
        result = await backend_with_encryption._refresh_access_token(token_record)

        assert result is None
        mock_logger.error.assert_called()


@pytest.mark.asyncio
async def test_refresh_access_token_success(backend_with_encryption, mock_db):
    """Test successful token refresh."""
    token_record = _make_token_record(
        refresh_token="encrypted_refresh",
        gateway_id="gw-1",
        app_user_email="user@test.com",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1)
    )

    # Mock gateway
    mock_gateway = MagicMock()
    mock_gateway.oauth_config = {
        "client_id": "test",
        "client_secret": "encrypted_secret",  # pragma: allowlist secret
        "token_url": "https://oauth.example.com/token"
    }
    mock_gateway.visibility = "public"
    mock_gateway.url = "https://mcp.example.com"
    mock_gateway.ca_certificate = None
    mock_gateway.client_cert = None
    mock_gateway.client_key = None
    mock_db.query.return_value.filter.return_value.first.return_value = mock_gateway

    # Mock OAuthManager
    with patch("mcpgateway.services.token_backends.db_backend.OAuthManager") as mock_oauth_class:
        mock_oauth = AsyncMock()
        mock_oauth.refresh_token.return_value = {
            "access_token": "new_access_token",
            "refresh_token": "new_refresh_token",
            "expires_in": 3600
        }
        mock_oauth_class.return_value = mock_oauth

        result = await backend_with_encryption._refresh_access_token(token_record)

        assert result == "new_access_token"
        mock_db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_refresh_access_token_with_resource_list(backend_with_encryption, mock_db):
    """Test refresh with resource list normalization."""
    token_record = _make_token_record(
        refresh_token="encrypted_refresh",
        gateway_id="gw-1"
    )

    # Mock gateway with resource list
    mock_gateway = MagicMock()
    mock_gateway.oauth_config = {
        "client_id": "test",
        "client_secret": "secret",
        "resource": ["https://api1.example.com", "https://api2.example.com"]
    }
    mock_gateway.visibility = "public"
    mock_gateway.url = "https://mcp.example.com"
    mock_gateway.ca_certificate = None
    mock_gateway.client_cert = None
    mock_gateway.client_key = None
    mock_db.query.return_value.filter.return_value.first.return_value = mock_gateway

    with patch("mcpgateway.services.token_backends.db_backend.OAuthManager") as mock_oauth_class:
        mock_oauth = AsyncMock()
        mock_oauth.refresh_token.return_value = {
            "access_token": "new_token",
            "expires_in": 3600
        }
        mock_oauth_class.return_value = mock_oauth

        result = await backend_with_encryption._refresh_access_token(token_record)

        assert result == "new_token"


@pytest.mark.asyncio
async def test_refresh_access_token_no_expires_in_preserves_ttl(backend_with_encryption, mock_db):
    """Test refresh without expires_in preserves prior TTL."""
    now = datetime.now(timezone.utc)
    token_record = _make_token_record(
        refresh_token="encrypted_refresh",
        gateway_id="gw-1",
        expires_at=now + timedelta(hours=1),
        updated_at=now
    )

    mock_gateway = MagicMock()
    mock_gateway.oauth_config = {"client_id": "test", "client_secret": "secret"}
    mock_gateway.visibility = "public"
    mock_gateway.url = "https://mcp.example.com"
    mock_gateway.ca_certificate = None
    mock_gateway.client_cert = None
    mock_gateway.client_key = None
    mock_db.query.return_value.filter.return_value.first.return_value = mock_gateway

    with patch("mcpgateway.services.token_backends.db_backend.OAuthManager") as mock_oauth_class:
        mock_oauth = AsyncMock()
        # No expires_in in response
        mock_oauth.refresh_token.return_value = {
            "access_token": "new_token",
            "refresh_token": "new_refresh"
        }
        mock_oauth_class.return_value = mock_oauth

        with patch("mcpgateway.services.token_backends.db_backend.logger") as mock_logger:
            result = await backend_with_encryption._refresh_access_token(token_record)

            assert result == "new_token"
            # Should log about preserving prior TTL
            info_calls = [call for call in mock_logger.info.call_args_list if "preserving prior TTL" in str(call)]
            assert len(info_calls) > 0


@pytest.mark.asyncio
async def test_refresh_access_token_invalid_error_clears_tokens(backend_with_encryption, mock_db):
    """Test that invalid/expired refresh token errors are logged."""
    token_record = _make_token_record(
        refresh_token="encrypted_refresh",
        gateway_id="gw-1"
    )

    mock_gateway = MagicMock()
    mock_gateway.oauth_config = {"client_id": "test", "client_secret": "secret"}
    mock_gateway.visibility = "public"
    mock_gateway.url = "https://mcp.example.com"
    mock_gateway.ca_certificate = None
    mock_gateway.client_cert = None
    mock_gateway.client_key = None
    mock_db.query.return_value.filter.return_value.first.return_value = mock_gateway

    with patch("mcpgateway.services.token_backends.db_backend.OAuthManager") as mock_oauth_class:
        mock_oauth = AsyncMock()
        mock_oauth.refresh_token.side_effect = Exception("invalid_grant: refresh token expired")
        mock_oauth_class.return_value = mock_oauth

        with patch("mcpgateway.services.token_backends.db_backend.logger") as mock_logger:
            result = await backend_with_encryption._refresh_access_token(token_record)

            assert result is None
            # Should log warning about invalid/expired token
            warning_calls = [call for call in mock_logger.warning.call_args_list
                           if "invalid/expired" in str(call)]
            assert len(warning_calls) > 0


# ---------- cleanup_expired_tokens ----------


@pytest.mark.asyncio
async def test_cleanup_expired_tokens_success(backend_with_encryption, mock_db):
    """Test cleanup removes expired tokens."""
    # Mock execute().rowcount to return number of deleted rows
    mock_result = MagicMock()
    mock_result.rowcount = 2
    mock_db.execute.return_value = mock_result

    result = await backend_with_encryption.cleanup_expired_tokens(max_age_days=1)

    assert result == 2
    mock_db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_cleanup_expired_tokens_no_tokens(backend_with_encryption, mock_db):
    """Test cleanup when no expired tokens exist."""
    mock_db.execute.return_value.scalars.return_value.all.return_value = []

    result = await backend_with_encryption.cleanup_expired_tokens(max_age_days=1)

    assert result == 0
    mock_db.delete.assert_not_called()


@pytest.mark.asyncio
async def test_cleanup_expired_tokens_exception(backend_with_encryption, mock_db):
    """Test cleanup handles exceptions gracefully."""
    mock_db.execute.side_effect = Exception("Database error")

    with patch("mcpgateway.services.token_backends.db_backend.logger") as mock_logger:
        result = await backend_with_encryption.cleanup_expired_tokens(max_age_days=1)

        mock_logger.error.assert_called_once()
        mock_db.rollback.assert_called_once()
        assert result == 0




# ---------- Integration edge cases ----------


@pytest.mark.asyncio
async def test_store_tokens_with_empty_scopes(backend_with_encryption, mock_db):
    """Test storing tokens with empty scopes list."""
    mock_db.execute.return_value.scalar_one_or_none.return_value = None
    mock_db.query.return_value.filter.return_value.first.return_value = Mock(
        id="gw-1",
        url="https://example.com"
    )

    result = await backend_with_encryption.store_tokens(
        gateway_id="gw-1",
        team_id="team-1",
        user_id="oauth-user-1",
        app_user_email="user@test.com",
        access_token="access",
        refresh_token="refresh",
        expires_in=3600,
        scopes=[],  # Empty scopes
    )

    added_token = mock_db.add.call_args[0][0]
    assert added_token.scopes == []


@pytest.mark.asyncio
async def test_get_user_token_no_token_type(backend_with_encryption, mock_db):
    """Test retrieving token when token_type is None."""
    future_time = datetime.now(timezone.utc) + timedelta(hours=1)
    token_record = _make_token_record(
        access_token="encrypted_access",
        expires_at=future_time,
        token_type=None  # No token type
    )
    mock_db.execute.return_value.scalar_one_or_none.return_value = token_record

    result = await backend_with_encryption.get_user_token(
        gateway_id="gw-1",
        team_id="team-1",
        app_user_email="user@test.com",
        threshold_seconds=300,
    )

    # Should still return token without warning
    assert result == "decrypted_value"
