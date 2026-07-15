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


# More tests can be added following the same pattern...
