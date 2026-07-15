# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_token_storage_service.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for TokenStorageService façade.
"""

# Standard
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, Mock, patch

# Third-Party
from pydantic import SecretStr
import pytest

# First-Party
from mcpgateway.services.token_storage_service import TokenStorageService


@pytest.fixture
def mock_db():
    """Create a mock database session."""
    db = MagicMock()
    return db


@pytest.fixture
def mock_settings_database():
    """Create mock settings for database backend."""
    settings = MagicMock()
    settings.auth_encryption_secret = "test-salt"  # pragma: allowlist secret
    settings.oauth_token_backend = "database"
    return settings


@pytest.fixture
def mock_settings_vault():
    """Create mock settings for Vault backend."""
    settings = MagicMock()
    settings.oauth_token_backend = "vault"
    settings.vault_addr = "https://vault.example.com"
    settings.vault_token = SecretStr("test-token")  # pragma: allowlist secret
    settings.vault_mount_point = "secret"
    return settings


# ---------- Initialization Tests ----------


def test_init_database_backend(mock_db, mock_settings_database):
    """Test TokenStorageService initializes with database backend."""
    with patch("mcpgateway.services.token_storage_service.get_settings") as mock_get_settings:
        mock_get_settings.return_value = mock_settings_database

        with patch("mcpgateway.services.token_backends.db_backend.get_encryption_service") as mock_enc:
            mock_enc.return_value = MagicMock()
            service = TokenStorageService(mock_db)

            assert service.db == mock_db
            assert service._backend is not None
            # Verify it's a DatabaseTokenBackend
            from mcpgateway.services.token_backends.db_backend import DatabaseTokenBackend
            assert isinstance(service._backend, DatabaseTokenBackend)


def test_init_vault_backend(mock_db, mock_settings_vault):
    """Test TokenStorageService initializes with Vault backend."""
    with patch("mcpgateway.services.token_storage_service.get_settings") as mock_get_settings:
        mock_get_settings.return_value = mock_settings_vault

        # VaultTokenBackend uses httpx, not hvac
        service = TokenStorageService(mock_db)

        assert service.db == mock_db
        assert service._backend is not None
        # Verify it's a VaultTokenBackend
        from mcpgateway.services.token_backends.vault_backend import VaultTokenBackend
        assert isinstance(service._backend, VaultTokenBackend)


def test_init_invalid_backend(mock_db):
    """Test TokenStorageService raises error for invalid backend."""
    with patch("mcpgateway.services.token_storage_service.get_settings") as mock_get_settings:
        mock_settings = MagicMock()
        mock_settings.oauth_token_backend = "invalid"
        mock_get_settings.return_value = mock_settings

        with pytest.raises(ValueError, match="Unknown OAUTH_TOKEN_BACKEND"):
            TokenStorageService(mock_db)


def test_init_with_user_context(mock_db, mock_settings_database):
    """Test TokenStorageService accepts user_context parameter."""
    with patch("mcpgateway.services.token_storage_service.get_settings") as mock_get_settings:
        mock_get_settings.return_value = mock_settings_database

        with patch("mcpgateway.services.token_backends.db_backend.get_encryption_service"):
            user_context = {'email': 'user@example.com', 'teams': ['engineering']}
            service = TokenStorageService(mock_db, user_context=user_context)

            assert service.user_context == user_context


# ---------- Team ID Extraction Tests ----------


def test_get_team_id_from_teams_list(mock_db, mock_settings_database):
    """Test _get_team_id extracts first team from teams list when gateway.team_id is None."""
    with patch("mcpgateway.services.token_storage_service.get_settings") as mock_get_settings:
        mock_get_settings.return_value = mock_settings_database

        with patch("mcpgateway.services.token_backends.db_backend.get_encryption_service"):
            # Mock gateway lookup to return None (fallback to user teams)
            mock_db.get = Mock(return_value=None)
            user_context = {'email': 'user@example.com', 'teams': ['engineering', 'admin']}
            service = TokenStorageService(mock_db, user_context=user_context)

            team_id = service._get_team_id('gw-123', 'user@example.com')
            assert team_id == 'engineering'


def test_get_team_id_empty_teams(mock_db, mock_settings_database):
    """Test _get_team_id returns None when user_context has empty teams (shared path fallback)."""
    with patch("mcpgateway.services.token_storage_service.get_settings") as mock_get_settings:
        mock_get_settings.return_value = mock_settings_database

        with patch("mcpgateway.services.token_backends.db_backend.get_encryption_service"):
            user_context = {'email': 'user@example.com', 'teams': []}
            mock_gateway = Mock()
            mock_gateway.team_id = None
            mock_db.get = Mock(return_value=mock_gateway)
            service = TokenStorageService(mock_db, user_context=user_context)

            # Mock database query to return empty list (no team memberships)
            scalars_mock = Mock()
            scalars_mock.all = Mock(return_value=[])
            execute_result = Mock()
            execute_result.scalars = Mock(return_value=scalars_mock)
            mock_db.execute = Mock(return_value=execute_result)

            team_id = service._get_team_id('gw-123', 'user@example.com')
            assert team_id is None  # Returns None for shared path fallback


def test_get_team_id_no_user_context(mock_db, mock_settings_database):
    """Test _get_team_id returns None when no user_context (shared path fallback)."""
    with patch("mcpgateway.services.token_storage_service.get_settings") as mock_get_settings:
        mock_get_settings.return_value = mock_settings_database

        with patch("mcpgateway.services.token_backends.db_backend.get_encryption_service"):
            mock_gateway = Mock()
            mock_gateway.team_id = None
            mock_db.get = Mock(return_value=mock_gateway)
            service = TokenStorageService(mock_db)

            # Mock database query to return empty list (no team memberships)
            scalars_mock = Mock()
            scalars_mock.all = Mock(return_value=[])
            execute_result = Mock()
            execute_result.scalars = Mock(return_value=scalars_mock)
            mock_db.execute = Mock(return_value=execute_result)

            team_id = service._get_team_id('gw-123', 'user@example.com')
            assert team_id is None  # Returns None for shared path fallback


# ---------- Façade Method Delegation Tests ----------


@pytest.mark.asyncio
async def test_store_tokens_delegates_to_backend(mock_db, mock_settings_database):
    """Test store_tokens delegates to backend with team_id."""
    with patch("mcpgateway.services.token_storage_service.get_settings") as mock_get_settings:
        mock_get_settings.return_value = mock_settings_database

        with patch("mcpgateway.services.token_backends.db_backend.get_encryption_service"):
            # Mock gateway with team_id
            mock_gateway = Mock()
            mock_gateway.team_id = "engineering"
            mock_db.get = Mock(return_value=mock_gateway)

            user_context = {'email': 'user@example.com', 'teams': ['engineering']}
            service = TokenStorageService(mock_db, user_context=user_context)

            # Mock the backend's store_tokens method
            service._backend.store_tokens = AsyncMock(return_value=MagicMock(
                gateway_id="gw-1",
                team_id="engineering",
                user_id="oauth-user-1",
                app_user_email="user@example.com",
                mcp_url="https://example.com"
            ))

            result = await service.store_tokens(
                gateway_id="gw-1",
                user_id="oauth-user-1",
                app_user_email="user@example.com",
                access_token="access",
                refresh_token="refresh",
                expires_in=3600,
                scopes=["read"],
            )

            # Verify backend was called with team_id
            service._backend.store_tokens.assert_called_once_with(
                gateway_id="gw-1",
                team_id="engineering",
                user_id="oauth-user-1",
                app_user_email="user@example.com",
                access_token="access",
                refresh_token="refresh",
                expires_in=3600,
                scopes=["read"],
            )

            assert result.gateway_id == "gw-1"
            assert result.team_id == "engineering"


@pytest.mark.asyncio
async def test_get_user_token_delegates_to_backend(mock_db, mock_settings_database):
    """Test get_user_token delegates to backend with team_id."""
    with patch("mcpgateway.services.token_storage_service.get_settings") as mock_get_settings:
        mock_get_settings.return_value = mock_settings_database

        with patch("mcpgateway.services.token_backends.db_backend.get_encryption_service"):
            mock_gateway = Mock()
            mock_gateway.team_id = "engineering"
            mock_db.get = Mock(return_value=mock_gateway)

            user_context = {'email': 'user@example.com', 'teams': ['engineering']}
            service = TokenStorageService(mock_db, user_context=user_context)

            # Mock the backend's get_user_token method
            service._backend.get_user_token = AsyncMock(return_value="decrypted_token")

            result = await service.get_user_token(
                gateway_id="gw-1",
                app_user_email="user@example.com",
                threshold_seconds=300,
            )

            # Verify backend was called with team_id
            service._backend.get_user_token.assert_called_once_with(
                gateway_id="gw-1",
                team_id="engineering",
                app_user_email="user@example.com",
                threshold_seconds=300,
            )

            assert result == "decrypted_token"


@pytest.mark.asyncio
async def test_get_token_info_delegates_to_backend(mock_db, mock_settings_database):
    """Test get_token_info delegates to backend with team_id."""
    with patch("mcpgateway.services.token_storage_service.get_settings") as mock_get_settings:
        mock_get_settings.return_value = mock_settings_database

        with patch("mcpgateway.services.token_backends.db_backend.get_encryption_service"):
            mock_gateway = Mock()
            mock_gateway.team_id = "engineering"
            mock_db.get = Mock(return_value=mock_gateway)

            user_context = {'email': 'user@example.com', 'teams': ['engineering']}
            service = TokenStorageService(mock_db, user_context=user_context)

            # Mock the backend's get_token_info method
            service._backend.get_token_info = AsyncMock(return_value={
                "user_id": "oauth-user-1",
                "app_user_email": "user@example.com",
                "token_type": "bearer",
                "expires_at": None,
                "scopes": ["read"],
            })

            result = await service.get_token_info(
                gateway_id="gw-1",
                app_user_email="user@example.com",
            )

            # Verify backend was called with team_id
            service._backend.get_token_info.assert_called_once_with(
                gateway_id="gw-1",
                team_id="engineering",
                app_user_email="user@example.com",
            )

            assert result["user_id"] == "oauth-user-1"


@pytest.mark.asyncio
async def test_revoke_user_tokens_delegates_to_backend(mock_db, mock_settings_database):
    """Test revoke_user_tokens delegates to backend with team_id."""
    with patch("mcpgateway.services.token_storage_service.get_settings") as mock_get_settings:
        mock_get_settings.return_value = mock_settings_database

        with patch("mcpgateway.services.token_backends.db_backend.get_encryption_service"):
            mock_gateway = Mock()
            mock_gateway.team_id = "engineering"
            mock_db.get = Mock(return_value=mock_gateway)

            user_context = {'email': 'user@example.com', 'teams': ['engineering']}
            service = TokenStorageService(mock_db, user_context=user_context)

            # Mock the backend's revoke_user_tokens method
            service._backend.revoke_user_tokens = AsyncMock(return_value=True)

            result = await service.revoke_user_tokens(
                gateway_id="gw-1",
                app_user_email="user@example.com",
            )

            # Verify backend was called with team_id
            service._backend.revoke_user_tokens.assert_called_once_with(
                gateway_id="gw-1",
                team_id="engineering",
                app_user_email="user@example.com",
            )

            assert result is True


@pytest.mark.asyncio
async def test_cleanup_expired_tokens_delegates_to_backend(mock_db, mock_settings_database):
    """Test cleanup_expired_tokens delegates to backend."""
    with patch("mcpgateway.services.token_storage_service.get_settings") as mock_get_settings:
        mock_get_settings.return_value = mock_settings_database

        with patch("mcpgateway.services.token_backends.db_backend.get_encryption_service"):
            service = TokenStorageService(mock_db)

            # Mock the backend's cleanup_expired_tokens method
            service._backend.cleanup_expired_tokens = AsyncMock(return_value=5)

            result = await service.cleanup_expired_tokens(max_age_days=30)

            # Verify backend was called
            service._backend.cleanup_expired_tokens.assert_called_once_with(max_age_days=30)

            assert result == 5


def test_get_team_id_with_user_context(mock_db, mock_settings_database):
    """Test _get_team_id uses user_context when available."""
    with patch("mcpgateway.services.token_storage_service.get_settings") as mock_get_settings:
        mock_get_settings.return_value = mock_settings_database

        with patch("mcpgateway.services.token_backends.db_backend.get_encryption_service"):
            user_context = {"teams": ["engineering", "platform"]}
            mock_db.get = Mock(return_value=None)
            service = TokenStorageService(mock_db, user_context=user_context)

            team_id = service._get_team_id("gw-123", "user@example.com")

            # Should return first team from user_context
            assert team_id == "engineering"


def test_get_team_id_returns_none_when_context_empty(mock_db, mock_settings_database):
    """Test _get_team_id returns None when user_context is empty (JWT teams claim is sole authority)."""
    with patch("mcpgateway.services.token_storage_service.get_settings") as mock_get_settings:
        mock_get_settings.return_value = mock_settings_database

        with patch("mcpgateway.services.token_backends.db_backend.get_encryption_service"):
            # Empty user_context (simulates OAuth callback without authentication)
            mock_gateway = Mock()
            mock_gateway.team_id = None
            mock_db.get = Mock(return_value=mock_gateway)
            service = TokenStorageService(mock_db, user_context={})

            team_id = service._get_team_id("gw-123", "user@example.com")

            # JWT teams claim is the ONLY source of truth - no database query fallback
            assert team_id is None


def test_get_team_id_falls_back_to_default_when_no_teams(mock_db, mock_settings_database):
    """Test _get_team_id returns None when user has no team memberships (shared path fallback)."""
    with patch("mcpgateway.services.token_storage_service.get_settings") as mock_get_settings:
        mock_get_settings.return_value = mock_settings_database

        with patch("mcpgateway.services.token_backends.db_backend.get_encryption_service"):
            # Empty user_context
            mock_gateway = Mock()
            mock_gateway.team_id = None
            mock_db.get = Mock(return_value=mock_gateway)
            service = TokenStorageService(mock_db, user_context={})

            # Mock database query to return empty list (no team memberships)
            scalars_mock = Mock()
            scalars_mock.all = Mock(return_value=[])
            execute_result = Mock()
            execute_result.scalars = Mock(return_value=scalars_mock)
            mock_db.execute = Mock(return_value=execute_result)

            team_id = service._get_team_id("gw-123", "user@example.com")
    gw = MagicMock(oauth_config=None)
    mock_db.query.return_value.filter.return_value.first.return_value = gw
    result = await service._refresh_access_token(_make_token_record())
    assert result is None


@pytest.mark.asyncio
async def test_refresh_denied_for_private_gateway_with_other_owner(service, mock_db):
    """PR #4341: refresh must be denied when gateway is private and owner != token owner.

    Without this gate, a token whose ``gateway_id`` points to a private gateway
    owned by a different user could trigger an OAuth refresh that decrypts and
    forwards the gateway's stored ``client_secret``, leaking the secret to a
    non-owner.
    """
    gw = MagicMock(oauth_config={"token_url": "https://token", "client_id": "cid"}, url="https://gw.com")
    gw.visibility = "private"
    gw.owner_email = "owner@example.com"
    mock_db.query.return_value.filter.return_value.first.return_value = gw

    record = _make_token_record(app_user_email="not-owner@example.com")
    result = await service._refresh_access_token(record)

    assert result is None


@pytest.mark.asyncio
async def test_refresh_allowed_for_private_gateway_owned_by_token_owner(service, mock_db):
    """PR #4341 carve-out: refresh succeeds when token owner IS the gateway owner."""
    gw = MagicMock(oauth_config={"token_url": "https://token", "client_id": "cid"}, url="https://gw.com")
    gw.visibility = "private"
    gw.owner_email = "owner@example.com"
    mock_db.query.return_value.filter.return_value.first.return_value = gw

    mock_oauth_manager = MagicMock()
    mock_oauth_manager.refresh_token = AsyncMock(return_value={"access_token": "new_access", "expires_in": 3600})
    record = _make_token_record(app_user_email="owner@example.com")
    with patch("mcpgateway.services.oauth_manager.OAuthManager", return_value=mock_oauth_manager):
        result = await service._refresh_access_token(record)

    assert result == "new_access"


@pytest.mark.asyncio
async def test_refresh_decrypt_refresh_token_fails(service, mock_db):
    gw = MagicMock(oauth_config={"token_url": "https://token", "client_id": "cid"}, url="https://gw.com")
    mock_db.query.return_value.filter.return_value.first.return_value = gw
    service.encryption.decrypt_secret_async = AsyncMock(side_effect=Exception("decrypt failed"))
    result = await service._refresh_access_token(_make_token_record())
    assert result is None


@pytest.mark.asyncio
async def test_refresh_success(service, mock_db):
    gw = MagicMock(oauth_config={"token_url": "https://token", "client_id": "cid", "client_secret": "sec"}, url="https://gw.com")  # pragma: allowlist secret
    mock_db.query.return_value.filter.return_value.first.return_value = gw
    mock_oauth_manager = MagicMock()
    mock_oauth_manager.refresh_token = AsyncMock(return_value={"access_token": "new_access", "refresh_token": "new_refresh", "expires_in": 3600})
    with patch("mcpgateway.services.oauth_manager.OAuthManager", return_value=mock_oauth_manager):
        result = await service._refresh_access_token(_make_token_record())
    assert result == "new_access"
    mock_db.commit.assert_called()


@pytest.mark.asyncio
async def test_refresh_without_expires_in_preserves_prior_ttl(service, mock_db):
    """Refresh response missing expires_in: preserve the prior TTL so proactive refresh keeps working."""
    gw = MagicMock(oauth_config={"token_url": "https://token", "client_id": "cid"}, url="https://gw.com")
    mock_db.query.return_value.filter.return_value.first.return_value = gw
    mock_oauth_manager = MagicMock()
    mock_oauth_manager.refresh_token = AsyncMock(return_value={"access_token": "new_access", "refresh_token": "new_refresh"})

    # Token issued 100 seconds ago with a 1-hour TTL.
    record = _make_token_record()
    issued = datetime.now(tz=timezone.utc) - timedelta(seconds=100)
    record.updated_at = issued
    record.expires_at = issued + timedelta(seconds=3600)

    with patch("mcpgateway.services.oauth_manager.OAuthManager", return_value=mock_oauth_manager):
        result = await service._refresh_access_token(record)

    assert result == "new_access"
    # Prior TTL preserved: new expires_at should be ~3600s after the refresh moment (now).
    assert record.expires_at is not None
    delta = (record.expires_at - record.updated_at).total_seconds()
    assert 3599 <= delta <= 3601


@pytest.mark.asyncio
async def test_refresh_without_expires_in_no_prior_ttl_stays_none(service, mock_db):
    """Refresh response missing expires_in AND no prior TTL: expires_at stays None."""
    gw = MagicMock(oauth_config={"token_url": "https://token", "client_id": "cid"}, url="https://gw.com")
    mock_db.query.return_value.filter.return_value.first.return_value = gw
    mock_oauth_manager = MagicMock()
    mock_oauth_manager.refresh_token = AsyncMock(return_value={"access_token": "new_access", "refresh_token": "new_refresh"})

    # Token had no prior expiry (e.g. GitHub OAuth Apps).
    record = _make_token_record()
    record.expires_at = None

    with patch("mcpgateway.services.oauth_manager.OAuthManager", return_value=mock_oauth_manager):
        result = await service._refresh_access_token(record)

    assert result == "new_access"
    assert record.expires_at is None


@pytest.mark.asyncio
async def test_refresh_success_with_resource_list(service, mock_db):
    gw = MagicMock(oauth_config={"token_url": "https://token", "client_id": "cid", "resource": ["https://api.example.com", "https://other.com"]}, url="https://gw.com")
    mock_db.query.return_value.filter.return_value.first.return_value = gw
    mock_oauth_manager = MagicMock()
    mock_oauth_manager.refresh_token = AsyncMock(return_value={"access_token": "new_access", "expires_in": 3600})
    with patch("mcpgateway.services.oauth_manager.OAuthManager", return_value=mock_oauth_manager):
        result = await service._refresh_access_token(_make_token_record())
    assert result == "new_access"


@pytest.mark.asyncio
async def test_refresh_success_with_single_resource(service, mock_db):
    gw = MagicMock(oauth_config={"token_url": "https://token", "client_id": "cid", "resource": "https://api.example.com"}, url="https://gw.com")
    mock_db.query.return_value.filter.return_value.first.return_value = gw
    mock_oauth_manager = MagicMock()
    mock_oauth_manager.refresh_token = AsyncMock(return_value={"access_token": "new_access", "expires_in": 3600})
    with patch("mcpgateway.services.oauth_manager.OAuthManager", return_value=mock_oauth_manager):
        result = await service._refresh_access_token(_make_token_record())
    assert result == "new_access"


@pytest.mark.asyncio
async def test_refresh_derives_resource_from_gateway_url(service, mock_db):
    gw = MagicMock(oauth_config={"token_url": "https://token", "client_id": "cid"}, url="https://gw.example.com/api")
    mock_db.query.return_value.filter.return_value.first.return_value = gw
    mock_oauth_manager = MagicMock()
    mock_oauth_manager.refresh_token = AsyncMock(return_value={"access_token": "new_access", "expires_in": 3600})
    with patch("mcpgateway.services.oauth_manager.OAuthManager", return_value=mock_oauth_manager):
        result = await service._refresh_access_token(_make_token_record())
    assert result == "new_access"


@pytest.mark.asyncio
async def test_refresh_preserves_opaque_resource_list(service, mock_db):
    """Opaque audience identifiers (non-URL) survive token refresh as-is.

    This is the round-trip scenario for IdPs that don't honor RFC 8707 and
    return aud=client_id (e.g. ServiceNow, Authentik).  The learned audience
    must not be stripped during refresh, otherwise validation regresses to
    the unfixed-bug state on the first refresh after callback.
    """
    gw = MagicMock(oauth_config={"token_url": "https://token", "client_id": "cid", "resource": ["client-id-1", "client-id-2"]}, url="https://gw.com")
    mock_db.query.return_value.filter.return_value.first.return_value = gw
    mock_oauth_manager = MagicMock()
    mock_oauth_manager.refresh_token = AsyncMock(return_value={"access_token": "new_access", "expires_in": 3600})
    with patch("mcpgateway.services.oauth_manager.OAuthManager", return_value=mock_oauth_manager):
        result = await service._refresh_access_token(_make_token_record())
    assert result == "new_access"
    refresh_call_oauth_config = mock_oauth_manager.refresh_token.call_args[0][1]
    assert refresh_call_oauth_config["resource"] == ["client-id-1", "client-id-2"]


@pytest.mark.asyncio
async def test_refresh_preserves_opaque_single_resource(service, mock_db):
    """Opaque single-string audience identifier survives refresh as-is."""
    gw = MagicMock(oauth_config={"token_url": "https://token", "client_id": "cid", "resource": "my-client-id"}, url="https://gw.com")
    mock_db.query.return_value.filter.return_value.first.return_value = gw
    mock_oauth_manager = MagicMock()
    mock_oauth_manager.refresh_token = AsyncMock(return_value={"access_token": "new_access", "expires_in": 3600})
    with patch("mcpgateway.services.oauth_manager.OAuthManager", return_value=mock_oauth_manager):
        result = await service._refresh_access_token(_make_token_record())
    assert result == "new_access"
    refresh_call_oauth_config = mock_oauth_manager.refresh_token.call_args[0][1]
    assert refresh_call_oauth_config["resource"] == "my-client-id"


@pytest.mark.asyncio
async def test_refresh_resource_list_all_empty_logs_warning(service, mock_db, caplog):
    """Line 339: when every entry in the resource list normalizes to empty, log a warning.

    Empty strings inside the list short-circuit ``normalize_resource`` to ``None`` via
    its ``if not url`` guard, leaving the filtered list empty.  The gateway warns
    operators that a misconfiguration silently dropped every audience identifier.
    """
    gw = MagicMock(
        oauth_config={"token_url": "https://token", "client_id": "cid", "resource": ["", ""]},
        url="https://gw.com",
    )
    mock_db.query.return_value.filter.return_value.first.return_value = gw
    mock_oauth_manager = MagicMock()
    mock_oauth_manager.refresh_token = AsyncMock(return_value={"access_token": "new_access", "expires_in": 3600})

    # Standard
    import logging

    with caplog.at_level(logging.WARNING):
        with patch("mcpgateway.services.oauth_manager.OAuthManager", return_value=mock_oauth_manager):
            result = await service._refresh_access_token(_make_token_record())

    assert result == "new_access"
    assert any("All 2 configured resource values were empty and removed during refresh" in msg for msg in caplog.messages)
    refresh_call_oauth_config = mock_oauth_manager.refresh_token.call_args[0][1]
    assert refresh_call_oauth_config["resource"] == []


@pytest.mark.asyncio
async def test_refresh_resource_string_normalizes_to_empty_logs_warning(service, mock_db, caplog):
    """Line 343: when a non-list resource normalizes to empty, log a warning.

    Defensive code path: ``normalize_resource`` does not return falsy for truthy
    URL inputs in the natural flow.  Patching ``urllib.parse.urlunparse`` to return
    an empty string forces the defensive branch so the warning is exercised.
    """
    gw = MagicMock(
        oauth_config={"token_url": "https://token", "client_id": "cid", "resource": "https://api.example.com"},
        url="https://gw.com",
    )
    mock_db.query.return_value.filter.return_value.first.return_value = gw
    mock_oauth_manager = MagicMock()
    mock_oauth_manager.refresh_token = AsyncMock(return_value={"access_token": "new_access", "expires_in": 3600})

    # Standard
    import logging

    with caplog.at_level(logging.WARNING):
        with patch("urllib.parse.urlunparse", return_value=""):
            with patch("mcpgateway.services.oauth_manager.OAuthManager", return_value=mock_oauth_manager):
                result = await service._refresh_access_token(_make_token_record())

    assert result == "new_access"
    assert any("Configured resource was empty and removed during refresh: https://api.example.com" in msg for msg in caplog.messages)


@pytest.mark.asyncio
async def test_refresh_derived_gateway_url_normalizes_to_empty_logs_warning(service, mock_db, caplog):
    """Line 349: when the auto-derived ``gateway.url`` normalizes to empty, log a warning.

    Defensive code path: with no explicit ``resource`` configured, the gateway falls
    back to ``gateway.url``.  ``normalize_resource`` does not return falsy for truthy
    URL inputs in the natural flow, so we patch ``urllib.parse.urlunparse`` to return
    an empty string and trip the defensive warning.
    """
    gw = MagicMock(
        oauth_config={"token_url": "https://token", "client_id": "cid"},
        url="https://gw.example.com/api",
    )
    mock_db.query.return_value.filter.return_value.first.return_value = gw
    mock_oauth_manager = MagicMock()
    mock_oauth_manager.refresh_token = AsyncMock(return_value={"access_token": "new_access", "expires_in": 3600})

    # Standard
    import logging

    with caplog.at_level(logging.WARNING):
        with patch("urllib.parse.urlunparse", return_value=""):
            with patch("mcpgateway.services.oauth_manager.OAuthManager", return_value=mock_oauth_manager):
                result = await service._refresh_access_token(_make_token_record())

    assert result == "new_access"
    assert any("Gateway URL is empty, skipping resource parameter: https://gw.example.com/api" in msg for msg in caplog.messages)


@pytest.mark.asyncio
async def test_refresh_client_secret_decrypt_fails_preserves_token_and_returns_none(service, mock_db):
    """Decryption failure is fail-closed; token is preserved for retry.

    decrypt_secret_async() is the idempotent wrapper — on wrong-key or corrupted-ciphertext
    it returns None (never raises). The fix checks for None and raises OAuthError, which is
    caught by the OAuthError handler: token preserved, None returned.  The IdP never receives
    a None or raw ciphertext as a client credential.
    """
    gw = MagicMock(
        oauth_config={"token_url": "https://token", "client_id": "cid", "client_secret": "v2:encrypted_data"},  # pragma: allowlist secret
        url="https://gw.com",
        ca_certificate=None,
        client_cert=None,
        client_key=None,
        visibility="public",
        owner_email=None,
    )
    mock_db.query.return_value.filter.return_value.first.return_value = gw

    # Mimic real behaviour: refresh token decrypts OK; client_secret decryption returns None
    # (wrong AUTH_ENCRYPTION_SECRET — the real method never raises, it returns None).
    service.encryption.decrypt_secret_async = AsyncMock(
        side_effect=["decrypted_refresh_token", None]
    )

    record = _make_token_record()

    result = await service._refresh_access_token(record)

    # OAuthError raised on None → caught by OAuthError handler → token kept, None returned.
    mock_db.delete.assert_not_called()
    assert result is None


@pytest.mark.asyncio
async def test_refresh_exception_invalid_grant_clears_tokens(service, mock_db):
    """Fix #1: Only OAuthInvalidGrantError deletes tokens, not generic OAuthError messages.

    OAuthManager now raises the typed OAuthInvalidGrantError subclass when the provider
    explicitly returns {"error": "invalid_grant"}.  Substring-matching on the error
    message string is no longer used — the exception type is the discriminator.
    """
    gw = MagicMock(
        oauth_config={"token_url": "https://token", "client_id": "cid"},
        url="https://gw.com",
        ca_certificate=None,
        client_cert=None,
        client_key=None,
        visibility="public",
        owner_email=None,
    )
    mock_db.query.return_value.filter.return_value.first.return_value = gw
    mock_oauth_manager = MagicMock()
    # OAuthInvalidGrantError is the typed exception raised by OAuthManager on invalid_grant
    from mcpgateway.services.oauth_manager import OAuthInvalidGrantError
    mock_oauth_manager.refresh_token = AsyncMock(side_effect=OAuthInvalidGrantError("Refresh token permanently invalid (invalid_grant): {'error': 'invalid_grant'}"))
    record = _make_token_record()
    with patch("mcpgateway.services.oauth_manager.OAuthManager", return_value=mock_oauth_manager):
        result = await service._refresh_access_token(record)
    assert result is None
    mock_db.delete.assert_called_once_with(record)


@pytest.mark.asyncio
async def test_refresh_exception_expired_preserves_tokens(service, mock_db):
    """Bug fix #5237.2c: Generic 'expired' errors no longer delete tokens."""
    gw = MagicMock(oauth_config={"token_url": "https://token", "client_id": "cid"}, url="https://gw.com")
    mock_db.query.return_value.filter.return_value.first.return_value = gw
    mock_oauth_manager = MagicMock()
    # Non-OAuthError or OAuthError without "invalid_grant" should preserve token
    mock_oauth_manager.refresh_token = AsyncMock(side_effect=Exception("Token has expired"))
    record = _make_token_record()
    with patch("mcpgateway.services.oauth_manager.OAuthManager", return_value=mock_oauth_manager):
        result = await service._refresh_access_token(record)
    assert result is None
    # Token should NOT be deleted
    mock_db.delete.assert_not_called()


@pytest.mark.asyncio
async def test_refresh_exception_generic_no_cleanup(service, mock_db):
    gw = MagicMock(oauth_config={"token_url": "https://token", "client_id": "cid"}, url="https://gw.com")
    mock_db.query.return_value.filter.return_value.first.return_value = gw
    mock_oauth_manager = MagicMock()
    mock_oauth_manager.refresh_token = AsyncMock(side_effect=Exception("Network error"))
    with patch("mcpgateway.services.oauth_manager.OAuthManager", return_value=mock_oauth_manager):
        result = await service._refresh_access_token(_make_token_record())
    assert result is None
    mock_db.delete.assert_not_called()


@pytest.mark.asyncio
async def test_refresh_no_encryption(service_no_encryption, mock_db):
    gw = MagicMock(oauth_config={"token_url": "https://token", "client_id": "cid"}, url="https://gw.com")
    mock_db.query.return_value.filter.return_value.first.return_value = gw
    mock_oauth_manager = MagicMock()
    mock_oauth_manager.refresh_token = AsyncMock(return_value={"access_token": "new_plain", "expires_in": 3600})
    with patch("mcpgateway.services.oauth_manager.OAuthManager", return_value=mock_oauth_manager):
        result = await service_no_encryption._refresh_access_token(_make_token_record(refresh_token="plain_refresh"))
    assert result == "new_plain"


# ---------- get_token_info ----------


@pytest.mark.asyncio
async def test_get_token_info_found(service, mock_db):
    record = _make_token_record()
    mock_db.execute.return_value.scalar_one_or_none.return_value = record
    result = await service.get_token_info("gw-1", "user@test.com")
    assert result is not None
    assert result["user_id"] == "oauth-user-1"
    assert "is_expired" in result


@pytest.mark.asyncio
async def test_get_token_info_not_found(service, mock_db):
    mock_db.execute.return_value.scalar_one_or_none.return_value = None
    result = await service.get_token_info("gw-1", "user@test.com")
    assert result is None


@pytest.mark.asyncio
async def test_get_token_info_exception(service, mock_db):
    mock_db.execute.side_effect = Exception("DB error")
    result = await service.get_token_info("gw-1", "user@test.com")
    assert result is None


# ---------- revoke_user_tokens ----------


@pytest.mark.asyncio
async def test_revoke_user_tokens_found(service, mock_db):
    record = _make_token_record()
    mock_db.execute.return_value.scalar_one_or_none.return_value = record
    result = await service.revoke_user_tokens("gw-1", "user@test.com")
    assert result is True
    mock_db.delete.assert_called_once()
    mock_db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_revoke_user_tokens_not_found(service, mock_db):
    mock_db.execute.return_value.scalar_one_or_none.return_value = None
    result = await service.revoke_user_tokens("gw-1", "user@test.com")
    assert result is False


@pytest.mark.asyncio
async def test_revoke_user_tokens_exception(service, mock_db):
    mock_db.execute.side_effect = Exception("DB error")
    result = await service.revoke_user_tokens("gw-1", "user@test.com")
    assert result is False
    mock_db.rollback.assert_called_once()


# ---------- cleanup_expired_tokens ----------


@pytest.mark.asyncio
async def test_cleanup_expired_tokens_some_cleaned(service, mock_db):
    mock_db.execute.return_value.rowcount = 5
    result = await service.cleanup_expired_tokens(max_age_days=30)
    assert result == 5
    mock_db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_cleanup_expired_tokens_none_cleaned(service, mock_db):
    mock_db.execute.return_value.rowcount = 0
    result = await service.cleanup_expired_tokens(max_age_days=30)
    assert result == 0


@pytest.mark.asyncio
async def test_cleanup_expired_tokens_exception(service, mock_db):
    mock_db.execute.side_effect = Exception("DB error")
    result = await service.cleanup_expired_tokens(max_age_days=30)
    assert result == 0
    mock_db.rollback.assert_called_once()


@pytest.mark.asyncio
async def test_cleanup_expired_tokens_targets_null_expires_at(service, mock_db):
    mock_db.execute.return_value.rowcount = 3
    await service.cleanup_expired_tokens(max_age_days=30)

    delete_stmt = mock_db.execute.call_args.args[0]
    rendered = str(delete_stmt.compile(compile_kwargs={"literal_binds": True})).lower()
    assert "expires_at is null" in rendered
    # NULL-expires_at rows must be aged out by updated_at (re-auth advances it),
    # not created_at (which would delete recently re-authorized tokens).
    assert "updated_at" in rendered
    assert "created_at" not in rendered


# ---------- token_type validation in get_user_token ----------


@pytest.mark.asyncio
async def test_get_user_token_warns_on_non_bearer_token_type(service, mock_db, caplog):
    """get_user_token logs a warning when token_type is not 'Bearer'."""
    record = _make_token_record(token_type="mac")
    mock_db.execute.return_value.scalar_one_or_none.return_value = record

    # Standard
    import logging

    with caplog.at_level(logging.WARNING):
        result = await service.get_user_token("gw-1", "user@test.com")

    # Token should still be returned (warning only)
    assert result == "decrypted_value"
    assert any("token_type" in msg.lower() and "mac" in msg.lower() for msg in caplog.messages)


@pytest.mark.asyncio
async def test_get_user_token_no_warning_for_bearer(service, mock_db, caplog):
    """get_user_token does not warn when token_type is 'Bearer' or 'bearer'."""
    record = _make_token_record(token_type="Bearer")
    mock_db.execute.return_value.scalar_one_or_none.return_value = record

    # Standard
    import logging

    with caplog.at_level(logging.WARNING):
        result = await service.get_user_token("gw-1", "user@test.com")

    assert result == "decrypted_value"
    assert not any("token_type" in msg.lower() for msg in caplog.messages)
=======
            # Should fall back to None for shared path
            assert team_id is None
