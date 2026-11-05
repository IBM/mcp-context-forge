# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/token_backends/test_db_backend.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for DatabaseTokenBackend.
"""

# Standard
import asyncio
from datetime import datetime, timedelta, timezone
import logging
import tempfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch

# Third-Party
from filelock import FileLock
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

# First-Party
from mcpgateway.config import get_settings
from mcpgateway.db import Base, EmailUser, Gateway, OAuthToken
from mcpgateway.services.oauth_manager import OAuthInvalidGrantError
from mcpgateway.services.token_backends import db_backend
from mcpgateway.services.token_backends.db_backend import DatabaseTokenBackend


@pytest.fixture(autouse=True)
def _refresh_lock_files_in_tmp_path(tmp_path, monkeypatch):
    """Keep the refresh lock files of every test in the test's temp directory."""
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))


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
async def test_store_tokens_none_learned_aud_preserves_existing(backend_with_encryption, mock_db):
    """store_tokens(learned_aud=None) on re-auth must NOT erase a previously stored
    learned_aud value.

    Regression guard for the round-1 fix: before the fix, passing learned_aud=None
    would unconditionally overwrite the existing learned_aud column with None,
    silently breaking per-user audience validation for all subsequent tool calls.
    """
    existing_token = OAuthToken(
        gateway_id="gw-1",
        user_id="oauth-user-1",
        app_user_email="alice@example.com",
        access_token="encrypted_old",
        refresh_token="encrypted_old_rt",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        scopes=["read"],
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    # Simulate a previously learned audience value on the existing row
    existing_token.learned_aud = "https://api.example.com"
    existing_token.learned_iss = "https://idp.example.com"

    mock_db.execute.return_value.scalar_one_or_none.return_value = existing_token
    mock_db.query.return_value.filter.return_value.first.return_value = Mock(
        id="gw-1",
        url="https://example.com",
    )

    # Re-authorize: IdP refresh response omits aud/iss → caller passes None
    await backend_with_encryption.store_tokens(
        gateway_id="gw-1",
        team_id="team-1",
        user_id="oauth-user-1",
        app_user_email="alice@example.com",
        access_token="new_access_token",
        refresh_token="new_refresh_token",
        expires_in=3600,
        scopes=["read", "write"],
        learned_aud=None,  # ← must NOT erase the existing value
        learned_iss=None,  # ← must NOT erase the existing value
    )

    # Previously-learned audience must survive the re-auth update
    assert existing_token.learned_aud == "https://api.example.com", (
        "store_tokens(learned_aud=None) erased a previously-stored learned_aud"
    )
    assert existing_token.learned_iss == "https://idp.example.com", (
        "store_tokens(learned_iss=None) erased a previously-stored learned_iss"
    )


@pytest.mark.asyncio
async def test_two_user_isolation_write_and_read(backend_with_encryption, mock_db):
    """User A's learned_aud write must not leak into User B's row for the same gateway.

    Regression guard: if the UPSERT query matched on gateway_id alone (without
    app_user_email), user A's re-auth would overwrite user B's row and user B's
    get_user_learned_audience() call would return user A's aud value.
    """
    row_alice = OAuthToken(
        gateway_id="gw-shared",
        user_id="oauth-alice",
        app_user_email="alice@example.com",
        access_token="enc_alice",
        refresh_token=None,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        scopes=["read"],
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    row_alice.learned_aud = "aud-for-alice"
    row_alice.learned_iss = "iss-for-alice"

    row_bob = OAuthToken(
        gateway_id="gw-shared",
        user_id="oauth-bob",
        app_user_email="bob@example.com",
        access_token="enc_bob",
        refresh_token=None,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        scopes=["read"],
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    row_bob.learned_aud = "aud-for-bob"
    row_bob.learned_iss = "iss-for-bob"

    # get_user_learned_audience calls _resolve_mcp_url (db.get) then _vault_request
    # (no DB).  The backend uses db.execute for the SELECT query.
    # First call → alice, second call → bob.
    alice_result = MagicMock()
    alice_result.one_or_none.return_value = row_alice
    alice_result.scalar_one_or_none.return_value = row_alice

    bob_result = MagicMock()
    bob_result.one_or_none.return_value = row_bob
    bob_result.scalar_one_or_none.return_value = row_bob

    mock_db.execute.side_effect = [alice_result, bob_result]
    mock_db.query.return_value.filter.return_value.first.return_value = Mock(
        id="gw-shared",
        url="https://shared-gateway.example.com",
    )

    # Alice's lookup must return only Alice's record
    aud_alice, iss_alice = await backend_with_encryption.get_user_learned_audience(
        gateway_id="gw-shared",
        team_id="team-1",
        app_user_email="alice@example.com",
    )
    assert aud_alice == "aud-for-alice", f"Expected alice's aud, got: {aud_alice}"

    # Bob's lookup must return only Bob's record
    aud_bob, iss_bob = await backend_with_encryption.get_user_learned_audience(
        gateway_id="gw-shared",
        team_id="team-1",
        app_user_email="bob@example.com",
    )
    assert aud_bob == "aud-for-bob", f"Expected bob's aud, got: {aud_bob}"

    # The two users' audiences must be distinct — no cross-contamination
    assert aud_alice != aud_bob, "Alice and Bob share the same learned_aud — isolation failure"





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
    """Test that storage exceptions raise a generic OAuthError (CWE-209: no internal detail leaked)."""
    mock_db.execute.return_value.scalar_one_or_none.side_effect = Exception("DB error")

    with pytest.raises(Exception, match="Token storage failed"):
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
    stored_row = SimpleNamespace(expires_at=past_time, updated_at=token_record.updated_at, access_token="stored_access", refresh_token="stored_refresh")
    mock_db.execute.return_value.one_or_none.return_value = stored_row

    # Mock _refresh_access_token to return a new token
    with patch.object(backend_with_encryption, "_refresh_access_token", new_callable=AsyncMock) as mock_refresh:
        mock_refresh.return_value = "refreshed_token"

        result = await backend_with_encryption.get_user_token(
            gateway_id="gw-1",
            team_id="team-1",
            app_user_email="user@test.com",
            threshold_seconds=0,
        )

        mock_refresh.assert_called_once_with(token_record, "stored_refresh")
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
    """get_token_info logs and re-raises on failure rather than returning None.

    None is reserved for "no token stored" - collapsing a lookup failure into the same
    value would make it indistinguishable from "never authorized" to callers exposing
    this through a user-facing status field.
    """
    mock_db.execute.side_effect = Exception("Database error")

    with patch("mcpgateway.services.token_backends.db_backend.logger") as mock_logger:
        with pytest.raises(Exception, match="Database error"):
            await backend_with_encryption.get_token_info(
                gateway_id="gw-1",
                team_id="team-1",
                app_user_email="user@test.com",
            )

        mock_logger.error.assert_called_once()


# ---------- get_token_info_bulk ----------


@pytest.mark.asyncio
async def test_get_token_info_bulk_empty_ids_short_circuits(backend_with_encryption, mock_db):
    """An empty gateway_ids list returns {} without issuing a query."""
    result = await backend_with_encryption.get_token_info_bulk(gateway_ids=[], team_id="team-1", app_user_email="user@test.com")

    assert result == {}
    mock_db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_get_token_info_bulk_single_query_mixed_results(backend_with_encryption, mock_db):
    """One query answers the whole batch: ids with a stored token get metadata, ids with no
    matching row map to None - this is the fix for the batch endpoint's N+1 token lookup."""
    found = _make_token_record(gateway_id="gw-1", expires_at=datetime.now(timezone.utc) + timedelta(hours=1))
    mock_db.execute.return_value.scalars.return_value.all.return_value = [found]

    result = await backend_with_encryption.get_token_info_bulk(gateway_ids=["gw-1", "gw-2"], team_id="team-1", app_user_email="user@test.com")

    assert mock_db.execute.call_count == 1
    assert result["gw-2"] is None
    assert result["gw-1"] is not None
    assert result["gw-1"]["status"] == "valid"
    assert "access_token" not in result["gw-1"]


@pytest.mark.asyncio
async def test_get_token_info_bulk_marks_expired_and_near_expiry(backend_with_encryption, mock_db):
    """Status classification (expired/near_expiry/valid) matches the single-item get_token_info()."""
    expired = _make_token_record(gateway_id="gw-expired", expires_at=datetime.now(timezone.utc) - timedelta(seconds=10))
    near_expiry = _make_token_record(gateway_id="gw-near", expires_at=datetime.now(timezone.utc) + timedelta(seconds=60))
    mock_db.execute.return_value.scalars.return_value.all.return_value = [expired, near_expiry]

    result = await backend_with_encryption.get_token_info_bulk(gateway_ids=["gw-expired", "gw-near"], team_id="team-1", app_user_email="user@test.com")

    assert result["gw-expired"]["status"] == "expired"
    assert result["gw-near"]["status"] == "near_expiry"


@pytest.mark.asyncio
async def test_get_token_info_bulk_exception(backend_with_encryption, mock_db):
    """A query failure logs and re-raises rather than swallowing to an empty/partial result -
    the whole batch's token status is backed by this one query, so a failure here should not
    silently read as "no gateway in the batch has a token"."""
    mock_db.execute.side_effect = Exception("Database error")

    with patch("mcpgateway.services.token_backends.db_backend.logger") as mock_logger:
        with pytest.raises(Exception, match="Database error"):
            await backend_with_encryption.get_token_info_bulk(gateway_ids=["gw-1"], team_id="team-1", app_user_email="user@test.com")

        mock_logger.error.assert_called_once()


@pytest.mark.asyncio
async def test_refresh_token_with_client_secret_decrypt_failure(backend_with_encryption, mock_db):
    """Test refresh fails closed when client_secret decryption returns None (PR #5244 behavior)."""
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
    mock_db.execute.return_value.one_or_none.return_value = SimpleNamespace(refresh_token="encrypted_refresh")

    # Mock refresh token decryption success but client_secret returns None (wrong key)
    async def decrypt_side_effect(value):
        if value == "encrypted_refresh":
            return "decrypted_refresh"
        return None  # Decryption failure returns None, not raises

    backend_with_encryption.encryption.decrypt_secret_async.side_effect = decrypt_side_effect

    with patch("mcpgateway.services.token_backends.db_backend.OAuthManager") as mock_oauth_class:
        mock_oauth = AsyncMock()
        mock_oauth.refresh_token.return_value = {
            "access_token": "new_token",
            "expires_in": 3600
        }
        mock_oauth_class.return_value = mock_oauth

        result = await backend_with_encryption._refresh_access_token(token_record)

        # PR #5244: Fail closed on decryption failure - returns None, preserves token
        assert result is None
        # Token should NOT be deleted (OAuthError, not OAuthInvalidGrantError)
        mock_db.delete.assert_not_called()


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

    with patch("mcpgateway.services.token_backends.refresh_helpers.logger") as mock_logger:
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

        with patch("mcpgateway.services.token_backends.refresh_helpers.logger") as mock_logger:
            result = await backend_with_encryption._refresh_access_token(token_record)

            assert result == "new_token"
            # Should log about preserving prior TTL (from refresh_helpers)
            info_calls = [call for call in mock_logger.info.call_args_list if "preserving prior TTL" in str(call)]
            assert len(info_calls) > 0


@pytest.mark.asyncio
async def test_refresh_access_token_invalid_error_clears_tokens(backend_with_encryption, mock_db):
    """Test that OAuthInvalidGrantError deletes tokens (PR #5244 behavior)."""
    from mcpgateway.services.oauth_manager import OAuthInvalidGrantError

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
        # PR #5244: Only OAuthInvalidGrantError deletes tokens, not generic exceptions
        mock_oauth.refresh_token.side_effect = OAuthInvalidGrantError("invalid_grant: refresh token expired")
        mock_oauth_class.return_value = mock_oauth

        with patch("mcpgateway.services.token_backends.db_backend.logger") as mock_logger:
            result = await backend_with_encryption._refresh_access_token(token_record)

            assert result is None
            # Should log warning about invalid_grant and delete token
            warning_calls = [call for call in mock_logger.warning.call_args_list
                           if "permanently invalid" in str(call) or "invalid_grant" in str(call)]
            assert len(warning_calls) > 0
            # Token should be deleted for invalid_grant
            mock_db.delete.assert_called_once_with(token_record)
            mock_db.commit.assert_called_once()


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


# ===========================================================================
# Tests for get_user_learned_audience (lines 546-562)
# ===========================================================================


@pytest.mark.asyncio
async def test_get_user_learned_audience_returns_values(backend_with_encryption, mock_db):
    """get_user_learned_audience returns (aud, iss) from token record (lines 546-555)."""
    token_record = MagicMock()
    token_record.learned_aud = "https://api.example.com"
    token_record.learned_iss = "https://idp.example.com"
    mock_db.execute.return_value.one_or_none.return_value = token_record

    result = await backend_with_encryption.get_user_learned_audience(
        gateway_id="gw-1",
        team_id="team-1",
        app_user_email="user@test.com",
    )

    assert result == ("https://api.example.com", "https://idp.example.com")


@pytest.mark.asyncio
async def test_get_user_learned_audience_no_record(backend_with_encryption, mock_db):
    """get_user_learned_audience returns (None, None) when no record exists (lines 553-554)."""
    mock_db.execute.return_value.one_or_none.return_value = None

    result = await backend_with_encryption.get_user_learned_audience(
        gateway_id="gw-1",
        team_id="team-1",
        app_user_email="user@test.com",
    )

    assert result == (None, None)


@pytest.mark.asyncio
async def test_get_user_learned_audience_exception_returns_none(backend_with_encryption, mock_db):
    """get_user_learned_audience swallows DB exceptions and returns (None, None) (lines 556-562)."""
    mock_db.execute.side_effect = Exception("DB error")

    with patch("mcpgateway.services.token_backends.db_backend.logger") as mock_logger:
        result = await backend_with_encryption.get_user_learned_audience(
            gateway_id="gw-1",
            team_id="team-1",
            app_user_email="user@test.com",
        )

    assert result == (None, None)
    mock_logger.debug.assert_called_once()


# ---------------------------------------------------------------------------
# Round-7 coverage: DatabaseTokenBackend encryption init failures (lines 135,137)
# ---------------------------------------------------------------------------


def test_db_backend_encryption_import_error():
    """DatabaseTokenBackend handles ImportError on encryption init (line 135)."""
    from mcpgateway.services.token_backends.db_backend import DatabaseTokenBackend
    from unittest.mock import MagicMock, patch

    db = MagicMock()
    settings = MagicMock()
    settings.auth_encryption_secret = "test-secret"  # pragma: allowlist secret

    with patch("mcpgateway.services.token_backends.db_backend.get_encryption_service", side_effect=ImportError("no crypto")):
        backend = DatabaseTokenBackend(db, settings)
    assert backend.encryption is None


def test_db_backend_encryption_attribute_error():
    """DatabaseTokenBackend handles AttributeError on encryption init (line 137)."""
    from mcpgateway.services.token_backends.db_backend import DatabaseTokenBackend
    from unittest.mock import MagicMock, patch

    db = MagicMock()
    settings = MagicMock()
    settings.auth_encryption_secret = "test-secret"  # pragma: allowlist secret

    with patch("mcpgateway.services.token_backends.db_backend.get_encryption_service", side_effect=AttributeError("no attr")):
        backend = DatabaseTokenBackend(db, settings)
    assert backend.encryption is None


# ---------- concurrent refresh against a rotating token endpoint (#7207) ----------

TOKEN_OWNER = "owner@test.com"


@pytest.fixture
def token_db(tmp_path):
    """SQLite file database with one gateway and one expired token that has a refresh token.

    Each session opens its own connection, like a separate request or worker.
    """
    engine = create_engine(f"sqlite:///{tmp_path / 'tokens.db'}")
    Base.metadata.create_all(engine, tables=[EmailUser.__table__, Gateway.__table__, OAuthToken.__table__])
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with session_factory() as db:
        gateway = Gateway(
            name="rotating",
            slug="rotating",
            url="https://mcp.example.com/mcp",
            capabilities={},
            oauth_config={"grant_type": "authorization_code", "client_id": "cid", "token_url": "https://auth.example.com/token"},
        )
        db.add(gateway)
        db.flush()
        db.add(
            OAuthToken(
                gateway_id=gateway.id,
                user_id="oauth-user",
                app_user_email=TOKEN_OWNER,
                access_token="access-0",
                refresh_token="refresh-0",
                expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
                scopes=[],
            )
        )
        db.commit()
        gateway_id = gateway.id
    yield session_factory, gateway_id
    engine.dispose()


class _RotatingTokenEndpoint:
    """Token endpoint that issues a new refresh token on each refresh and accepts each refresh token once."""

    def __init__(self, expires_in=3600):
        self.valid_refresh_token = "refresh-0"
        self.received = []
        self.issued = 0
        self.expires_in = expires_in

    async def refresh_token(self, refresh_token, _credentials, **_kwargs):
        self.received.append(refresh_token)
        # Hold the request open so that a concurrent caller can reach the endpoint too.
        await asyncio.sleep(0.05)
        if refresh_token != self.valid_refresh_token:
            raise OAuthInvalidGrantError("invalid_grant: refresh token was already used")
        self.issued += 1
        self.valid_refresh_token = f"refresh-{self.issued}"
        return {"access_token": f"access-{self.issued}", "refresh_token": self.valid_refresh_token, "expires_in": self.expires_in}


class _LatestIssuedWinsEndpoint:
    """Token endpoint that accepts a used refresh token again, but only the latest issued one stays valid.

    Two refreshes with the same refresh token both succeed. The pair issued first is
    then superseded, as in the provider log of #7207.
    """

    def __init__(self):
        self.valid_refresh_tokens = {"refresh-0"}
        self.received = []
        self.issued = 0

    async def refresh_token(self, refresh_token, _credentials, **_kwargs):
        self.received.append(refresh_token)
        await asyncio.sleep(0.05)
        if refresh_token not in self.valid_refresh_tokens:
            raise OAuthInvalidGrantError("invalid_grant: refresh token was superseded")
        self.issued += 1
        new_refresh_token = f"refresh-{self.issued}"
        self.valid_refresh_tokens = {refresh_token, new_refresh_token}
        return {"access_token": f"access-{self.issued}", "refresh_token": new_refresh_token, "expires_in": 3600}


class _OneLockPerCall:
    """Stands in for the per-process lock map: each call gets its own lock, as in separate worker processes."""

    def setdefault(self, _key, default):
        return default


def _separate_worker_processes():
    return patch.object(DatabaseTokenBackend, "_refresh_locks", _OneLockPerCall(), create=True)


def _patch_token_endpoint(endpoint):
    return patch("mcpgateway.services.token_backends.db_backend.OAuthManager", return_value=endpoint)


async def _get_token(session, gateway_id):
    return await DatabaseTokenBackend(session, get_settings()).get_user_token(gateway_id, "team-1", TOKEN_OWNER)


def _store_refresh_from_other_worker(session_factory, gateway_id, access_token, refresh_token):
    """Commit a refreshed token pair through another session, as a second worker does."""
    with session_factory() as db:
        record = db.execute(select(OAuthToken).where(OAuthToken.gateway_id == gateway_id)).scalar_one()
        record.access_token = access_token
        record.refresh_token = refresh_token
        record.expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
        db.commit()


def _stored_token_pair(session_factory, gateway_id):
    with session_factory() as db:
        record = db.execute(select(OAuthToken).where(OAuthToken.gateway_id == gateway_id)).scalar_one_or_none()
        return (record.access_token, record.refresh_token) if record else None


@pytest.mark.asyncio
async def test_concurrent_requests_refresh_rotating_token_once(token_db):
    """Two requests that find the same expired token send its refresh token to the endpoint once."""
    session_factory, gateway_id = token_db
    endpoint = _RotatingTokenEndpoint()

    with session_factory() as db_a, session_factory() as db_b, _patch_token_endpoint(endpoint):
        results = await asyncio.gather(_get_token(db_a, gateway_id), _get_token(db_b, gateway_id))

    assert endpoint.received == ["refresh-0"]
    assert results == ["access-1", "access-1"]
    assert _stored_token_pair(session_factory, gateway_id) == ("access-1", "refresh-1")


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint_class", [_RotatingTokenEndpoint, _LatestIssuedWinsEndpoint])
async def test_separate_worker_processes_refresh_token_once(token_db, endpoint_class):
    """Requests in separate worker processes send the refresh token once, for both kinds of rotating endpoint."""
    session_factory, gateway_id = token_db
    endpoint = endpoint_class()

    with session_factory() as db_a, session_factory() as db_b, _separate_worker_processes(), _patch_token_endpoint(endpoint):
        results = await asyncio.gather(_get_token(db_a, gateway_id), _get_token(db_b, gateway_id))

    assert endpoint.received == ["refresh-0"]
    assert results == ["access-1", "access-1"]
    assert _stored_token_pair(session_factory, gateway_id) == ("access-1", "refresh-1")


@pytest.mark.asyncio
async def test_waiting_request_uses_token_that_expires_within_threshold(token_db):
    """A waiting request uses a new token even when its lifetime is shorter than the refresh threshold."""
    session_factory, gateway_id = token_db
    endpoint = _RotatingTokenEndpoint(expires_in=60)

    with session_factory() as db_a, session_factory() as db_b, _patch_token_endpoint(endpoint):
        results = await asyncio.gather(_get_token(db_a, gateway_id), _get_token(db_b, gateway_id))

    assert endpoint.received == ["refresh-0"]
    assert results == ["access-1", "access-1"]


@pytest.mark.asyncio
async def test_refresh_proceeds_when_refresh_lock_stays_busy(token_db, caplog):
    """A refresh lock held past the wait limit delays the refresh but does not stop it."""
    session_factory, gateway_id = token_db
    endpoint = _RotatingTokenEndpoint()
    other_process_lock = FileLock(db_backend._refresh_lock_path(gateway_id, TOKEN_OWNER))
    other_process_lock.acquire()
    try:
        with session_factory() as db, _patch_token_endpoint(endpoint), patch.object(db_backend, "_REFRESH_LOCK_WAIT_SECONDS", 0.1), caplog.at_level(logging.WARNING):
            result = await _get_token(db, gateway_id)
    finally:
        other_process_lock.release()

    assert result == "access-1"
    assert endpoint.received == ["refresh-0"]
    assert "still busy" in caplog.text


@pytest.mark.asyncio
async def test_refresh_proceeds_when_refresh_lock_file_fails(token_db, caplog):
    """A lock file that cannot be opened does not stop the refresh."""
    session_factory, gateway_id = token_db
    endpoint = _RotatingTokenEndpoint()
    broken_lock = MagicMock()
    broken_lock.acquire.side_effect = PermissionError("read-only temp directory")

    with session_factory() as db, _patch_token_endpoint(endpoint), patch.object(db_backend, "FileLock", return_value=broken_lock), caplog.at_level(logging.WARNING):
        result = await _get_token(db, gateway_id)

    assert result == "access-1"
    assert endpoint.received == ["refresh-0"]
    broken_lock.release.assert_not_called()
    assert "not usable" in caplog.text


@pytest.mark.asyncio
async def test_expired_read_uses_token_refreshed_by_other_worker(token_db):
    """A request that read the expired row before another worker refreshed it uses the stored token."""
    session_factory, gateway_id = token_db
    endpoint = _RotatingTokenEndpoint()

    with session_factory() as db, _patch_token_endpoint(endpoint):
        expired_read = db.execute(select(OAuthToken).where(OAuthToken.gateway_id == gateway_id)).scalar_one()
        assert expired_read.refresh_token == "refresh-0"
        with session_factory() as other_worker_db:
            assert await _get_token(other_worker_db, gateway_id) == "access-1"
        result = await _get_token(db, gateway_id)

    assert result == "access-1"
    assert endpoint.received == ["refresh-0"]
    assert _stored_token_pair(session_factory, gateway_id) == ("access-1", "refresh-1")


@pytest.mark.asyncio
async def test_invalid_grant_keeps_token_refreshed_by_other_worker(token_db):
    """invalid_grant does not delete a token that another worker refreshed while the request was open."""
    session_factory, gateway_id = token_db

    async def other_worker_uses_refresh_token_first(*_args, **_kwargs):
        _store_refresh_from_other_worker(session_factory, gateway_id, "access-1", "refresh-1")
        raise OAuthInvalidGrantError("invalid_grant: refresh token was already used")

    endpoint = MagicMock(refresh_token=AsyncMock(side_effect=other_worker_uses_refresh_token_first))
    with session_factory() as db, _patch_token_endpoint(endpoint):
        result = await _get_token(db, gateway_id)
        assert not db.in_transaction()

    assert result == "access-1"
    assert _stored_token_pair(session_factory, gateway_id) == ("access-1", "refresh-1")


@pytest.mark.asyncio
async def test_refresh_keeps_token_stored_by_other_worker(token_db):
    """A refresh response does not overwrite tokens that another worker stored while the request was open."""
    session_factory, gateway_id = token_db

    async def other_worker_stores_first(*_args, **_kwargs):
        _store_refresh_from_other_worker(session_factory, gateway_id, "access-1", "refresh-1")
        return {"access_token": "access-2", "refresh_token": "refresh-2", "expires_in": 3600}

    endpoint = MagicMock(refresh_token=AsyncMock(side_effect=other_worker_stores_first))
    with session_factory() as db, _patch_token_endpoint(endpoint):
        result = await _get_token(db, gateway_id)
        assert not db.in_transaction()

    assert result == "access-1"
    assert _stored_token_pair(session_factory, gateway_id) == ("access-1", "refresh-1")


@pytest.mark.asyncio
async def test_refresh_does_not_restore_token_revoked_during_refresh(token_db):
    """A refresh response does not bring back a token that was revoked while the request was open."""
    session_factory, gateway_id = token_db

    async def user_revokes_during_refresh(*_args, **_kwargs):
        with session_factory() as other_db:
            assert await DatabaseTokenBackend(other_db, get_settings()).revoke_user_tokens(gateway_id, "team-1", TOKEN_OWNER)
        return {"access_token": "access-1", "refresh_token": "refresh-1", "expires_in": 3600}

    endpoint = MagicMock(refresh_token=AsyncMock(side_effect=user_revokes_during_refresh))
    with session_factory() as db, _patch_token_endpoint(endpoint):
        result = await _get_token(db, gateway_id)
        assert not db.in_transaction()

    assert result is None
    assert _stored_token_pair(session_factory, gateway_id) is None


@pytest.mark.asyncio
async def test_invalid_grant_deletes_unchanged_token(token_db):
    """invalid_grant for the refresh token that is still stored deletes the token, as before."""
    session_factory, gateway_id = token_db
    endpoint = MagicMock(refresh_token=AsyncMock(side_effect=OAuthInvalidGrantError("invalid_grant: refresh token revoked")))

    with session_factory() as db, _patch_token_endpoint(endpoint):
        result = await _get_token(db, gateway_id)

    assert result is None
    endpoint.refresh_token.assert_awaited_once()
    assert _stored_token_pair(session_factory, gateway_id) is None


@pytest.mark.asyncio
async def test_concurrent_requests_send_revoked_refresh_token_once(token_db):
    """A request that waits for a refresh rejected with invalid_grant does not send the refresh token again."""
    session_factory, gateway_id = token_db
    endpoint = _RotatingTokenEndpoint()
    endpoint.valid_refresh_token = None

    with session_factory() as db_a, session_factory() as db_b, _patch_token_endpoint(endpoint):
        results = await asyncio.gather(_get_token(db_a, gateway_id), _get_token(db_b, gateway_id))

    assert endpoint.received == ["refresh-0"]
    assert results == [None, None]
    assert _stored_token_pair(session_factory, gateway_id) is None
