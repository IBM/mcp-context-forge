# -*- coding: utf-8 -*-
"""Unit tests for TokenStorageService."""

# Standard
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.services.token_storage_service import TokenStorageService


@pytest.fixture
def mock_db():
    db = MagicMock()
    return db


@pytest.fixture
def service(mock_db):
    with patch("mcpgateway.services.token_storage_service.get_settings") as mock_settings, patch("mcpgateway.services.token_storage_service.get_encryption_service") as mock_enc:
        mock_settings.return_value = MagicMock(auth_encryption_secret="test-salt")
        mock_enc_instance = MagicMock()
        mock_enc_instance.encrypt_secret_async = AsyncMock(return_value="encrypted_value")
        mock_enc_instance.decrypt_secret_async = AsyncMock(return_value="decrypted_value")
        mock_enc.return_value = mock_enc_instance
        svc = TokenStorageService(mock_db)
    return svc


@pytest.fixture
def service_no_encryption(mock_db):
    with patch("mcpgateway.services.token_storage_service.get_settings", side_effect=ImportError):
        svc = TokenStorageService(mock_db)
    assert svc.encryption is None
    return svc


def _make_token_record(**overrides):
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


def test_is_token_expired_no_expires_at(service):
    record = _make_token_record(expires_at=None)
    assert service._is_token_expired(record) is False


def test_is_token_expired_future(service):
    record = _make_token_record(expires_at=datetime.now(timezone.utc) + timedelta(hours=1))
    assert service._is_token_expired(record, threshold_seconds=300) is False


def test_is_token_expired_past(service):
    record = _make_token_record(expires_at=datetime.now(timezone.utc) - timedelta(seconds=10))
    assert service._is_token_expired(record, threshold_seconds=0) is True


def test_is_token_expired_within_threshold(service):
    record = _make_token_record(expires_at=datetime.now(timezone.utc) + timedelta(seconds=100))
    assert service._is_token_expired(record, threshold_seconds=200) is True


def test_is_token_expired_naive_datetime(service):
    """Test _is_token_expired with a naive datetime (no timezone)."""
    naive_time = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=10)
    record = _make_token_record(expires_at=naive_time)
    # The implementation adds timezone.utc to naive datetimes, so comparison works correctly
    result = service._is_token_expired(record, threshold_seconds=0)
    # A past datetime (even if naive) should be expired
    assert result is True


# ---------- store_tokens ----------


@pytest.mark.asyncio
async def test_store_tokens_new(service, mock_db):
    mock_db.execute.return_value.scalar_one_or_none.return_value = None
    result = await service.store_tokens(
        gateway_id="gw-1",
        user_id="user-1",
        app_user_email="user@test.com",
        access_token="access123",
        refresh_token="refresh123",
        expires_in=3600,
        scopes=["read"],
    )
    mock_db.add.assert_called_once()
    mock_db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_store_tokens_update_existing(service, mock_db):
    existing = _make_token_record()
    mock_db.execute.return_value.scalar_one_or_none.return_value = existing
    result = await service.store_tokens(
        gateway_id="gw-1",
        user_id="user-1",
        app_user_email="user@test.com",
        access_token="new_access",
        refresh_token="new_refresh",
        expires_in=3600,
        scopes=["read"],
    )
    assert existing.access_token == "encrypted_value"
    mock_db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_store_tokens_no_encryption(service_no_encryption, mock_db):
    mock_db.execute.return_value.scalar_one_or_none.return_value = None
    result = await service_no_encryption.store_tokens(
        gateway_id="gw-1",
        user_id="user-1",
        app_user_email="user@test.com",
        access_token="plain_access",
        refresh_token=None,
        expires_in=3600,
        scopes=["read"],
    )
    mock_db.add.assert_called_once()


@pytest.mark.asyncio
async def test_store_tokens_exception(service, mock_db):
    mock_db.execute.side_effect = Exception("DB error")
    with pytest.raises(Exception, match="Token storage failed"):
        await service.store_tokens(
            gateway_id="gw-1",
            user_id="user-1",
            app_user_email="user@test.com",
            access_token="access",
            refresh_token=None,
            expires_in=3600,
            scopes=[],
        )
    mock_db.rollback.assert_called_once()


@pytest.mark.asyncio
async def test_store_tokens_no_expires_in_persists_null(service, mock_db, caplog):
    mock_db.execute.return_value.scalar_one_or_none.return_value = None
    # Standard
    import logging

    with caplog.at_level(logging.INFO):
        await service.store_tokens(
            gateway_id="gw-1",
            user_id="user-1",
            app_user_email="user@test.com",
            access_token="access123",
            refresh_token="refresh123",
            expires_in=None,
            scopes=["read"],
        )
    mock_db.add.assert_called_once()
    new_record = mock_db.add.call_args.args[0]
    assert new_record.expires_at is None
    assert any("token will not auto-expire" in msg for msg in caplog.messages)


@pytest.mark.asyncio
async def test_store_tokens_update_existing_clears_expires_at_when_no_expires_in(service, mock_db):
    existing = _make_token_record()
    assert existing.expires_at is not None
    mock_db.execute.return_value.scalar_one_or_none.return_value = existing
    await service.store_tokens(
        gateway_id="gw-1",
        user_id="user-1",
        app_user_email="user@test.com",
        access_token="new_access",
        refresh_token="new_refresh",
        expires_in=None,
        scopes=["read"],
    )
    assert existing.expires_at is None


# ---------- get_user_token ----------


@pytest.mark.asyncio
async def test_get_user_token_not_found(service, mock_db):
    mock_db.execute.return_value.scalar_one_or_none.return_value = None
    result = await service.get_user_token("gw-1", "user@test.com")
    assert result is None


@pytest.mark.asyncio
async def test_get_user_token_valid(service, mock_db):
    record = _make_token_record()
    mock_db.execute.return_value.scalar_one_or_none.return_value = record
    result = await service.get_user_token("gw-1", "user@test.com")
    assert result == "decrypted_value"


@pytest.mark.asyncio
async def test_get_user_token_valid_no_encryption(service_no_encryption, mock_db):
    record = _make_token_record(access_token="plain_token")
    mock_db.execute.return_value.scalar_one_or_none.return_value = record
    result = await service_no_encryption.get_user_token("gw-1", "user@test.com")
    assert result == "plain_token"


@pytest.mark.asyncio
async def test_get_user_token_expired_no_refresh(service, mock_db):
    record = _make_token_record(expires_at=datetime.now(timezone.utc) - timedelta(hours=1), refresh_token=None)
    mock_db.execute.return_value.scalar_one_or_none.return_value = record
    result = await service.get_user_token("gw-1", "user@test.com")
    assert result is None


@pytest.mark.asyncio
async def test_get_user_token_expired_with_refresh(service, mock_db):
    record = _make_token_record(expires_at=datetime.now(timezone.utc) - timedelta(hours=1))
    mock_db.execute.return_value.scalar_one_or_none.return_value = record
    with patch.object(service, "_refresh_access_token", AsyncMock(return_value="new_token")):
        result = await service.get_user_token("gw-1", "user@test.com")
    assert result == "new_token"


@pytest.mark.asyncio
async def test_get_user_token_expired_refresh_fails(service, mock_db):
    record = _make_token_record(expires_at=datetime.now(timezone.utc) - timedelta(hours=1))
    mock_db.execute.return_value.scalar_one_or_none.return_value = record
    with patch.object(service, "_refresh_access_token", AsyncMock(return_value=None)):
        result = await service.get_user_token("gw-1", "user@test.com")
    assert result is None


@pytest.mark.asyncio
async def test_get_user_token_exception(service, mock_db):
    mock_db.execute.side_effect = Exception("DB error")
    result = await service.get_user_token("gw-1", "user@test.com")
    assert result is None


# ---------- _refresh_access_token ----------


@pytest.mark.asyncio
async def test_refresh_no_refresh_token(service):
    record = _make_token_record(refresh_token=None)
    result = await service._refresh_access_token(record)
    assert result is None


@pytest.mark.asyncio
async def test_refresh_no_gateway(service, mock_db):
    record = _make_token_record()
    mock_db.query.return_value.filter.return_value.first.return_value = None
    result = await service._refresh_access_token(record)
    assert result is None


@pytest.mark.asyncio
async def test_refresh_no_oauth_config(service, mock_db):
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
    gw = MagicMock(oauth_config={"token_url": "https://token", "client_id": "cid", "client_secret": "sec"}, url="https://gw.com")
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
async def test_refresh_client_secret_decrypt_fails_uses_plaintext(service, mock_db):
    gw = MagicMock(oauth_config={"token_url": "https://token", "client_id": "cid", "client_secret": "maybe_plain"}, url="https://gw.com")
    mock_db.query.return_value.filter.return_value.first.return_value = gw

    call_count = 0
    original_decrypt = service.encryption.decrypt_secret_async

    async def selective_decrypt(value):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return "decrypted_refresh"
        raise Exception("decrypt failed for client_secret")

    service.encryption.decrypt_secret_async = AsyncMock(side_effect=selective_decrypt)
    mock_oauth_manager = MagicMock()
    mock_oauth_manager.refresh_token = AsyncMock(return_value={"access_token": "new_access", "expires_in": 3600})
    with patch("mcpgateway.services.oauth_manager.OAuthManager", return_value=mock_oauth_manager):
        result = await service._refresh_access_token(_make_token_record())
    assert result == "new_access"


@pytest.mark.asyncio
async def test_refresh_exception_invalid_clears_tokens(service, mock_db):
    gw = MagicMock(oauth_config={"token_url": "https://token", "client_id": "cid"}, url="https://gw.com")
    mock_db.query.return_value.filter.return_value.first.return_value = gw
    mock_oauth_manager = MagicMock()
    mock_oauth_manager.refresh_token = AsyncMock(side_effect=Exception("Token is invalid"))
    record = _make_token_record()
    with patch("mcpgateway.services.oauth_manager.OAuthManager", return_value=mock_oauth_manager):
        result = await service._refresh_access_token(record)
    assert result is None
    mock_db.delete.assert_called_once_with(record)


@pytest.mark.asyncio
async def test_refresh_exception_expired_clears_tokens(service, mock_db):
    gw = MagicMock(oauth_config={"token_url": "https://token", "client_id": "cid"}, url="https://gw.com")
    mock_db.query.return_value.filter.return_value.first.return_value = gw
    mock_oauth_manager = MagicMock()
    mock_oauth_manager.refresh_token = AsyncMock(side_effect=Exception("Token has expired"))
    record = _make_token_record()
    with patch("mcpgateway.services.oauth_manager.OAuthManager", return_value=mock_oauth_manager):
        result = await service._refresh_access_token(record)
    assert result is None
    mock_db.delete.assert_called_once()


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
