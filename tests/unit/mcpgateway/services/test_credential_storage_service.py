# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_credential_storage_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Unit tests for CredentialStorageService."""

# Standard
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.services.credential_storage_service import (
    VALID_CREDENTIAL_TYPES,
    CredentialStorageService,
)


@pytest.fixture
def mock_db():
    return MagicMock()


@pytest.fixture
def service(mock_db):
    with patch("mcpgateway.services.credential_storage_service.get_settings") as mock_settings, patch(
        "mcpgateway.services.credential_storage_service.get_encryption_service"
    ) as mock_enc:
        mock_settings.return_value = MagicMock(auth_encryption_secret="test-salt")
        mock_enc_instance = MagicMock()
        mock_enc_instance.encrypt_secret_async = AsyncMock(return_value="encrypted_value")
        mock_enc_instance.decrypt_secret_async = AsyncMock(return_value="decrypted_value")
        mock_enc.return_value = mock_enc_instance
        svc = CredentialStorageService(mock_db)
    return svc


@pytest.fixture
def service_no_encryption(mock_db):
    with patch("mcpgateway.services.credential_storage_service.get_settings", side_effect=ImportError):
        svc = CredentialStorageService(mock_db)
    assert svc.encryption is None
    return svc


def _make_credential_record(**overrides):
    defaults = {
        "id": "cred-1",
        "gateway_id": "gw-1",
        "app_user_email": "user@test.com",
        "credential_type": "api_key",
        "credential_value": "encrypted_api_key",
        "label": "My API Key",
        "created_at": MagicMock(isoformat=MagicMock(return_value="2026-01-01T00:00:00+00:00")),
        "updated_at": MagicMock(isoformat=MagicMock(return_value="2026-01-01T00:00:00+00:00")),
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# ---------- store_credential ----------


@pytest.mark.asyncio
async def test_store_credential_new(service, mock_db):
    """Test storing a new credential."""
    mock_db.execute.return_value.scalar_one_or_none.return_value = None
    record = await service.store_credential(
        gateway_id="gw-1",
        app_user_email="user@test.com",
        credential_type="api_key",
        credential_value="my-secret-key",
        label="Test Key",
    )
    mock_db.add.assert_called_once()
    mock_db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_store_credential_update(service, mock_db):
    """Test updating an existing credential."""
    existing = _make_credential_record()
    mock_db.execute.return_value.scalar_one_or_none.return_value = existing
    record = await service.store_credential(
        gateway_id="gw-1",
        app_user_email="user@test.com",
        credential_type="bearer_token",
        credential_value="new-token",
        label="Updated",
    )
    assert existing.credential_type == "bearer_token"
    assert existing.label == "Updated"
    mock_db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_store_credential_invalid_type(service):
    """Test that invalid credential types are rejected."""
    with pytest.raises(ValueError, match="Invalid credential_type"):
        await service.store_credential(
            gateway_id="gw-1",
            app_user_email="user@test.com",
            credential_type="invalid_type",
            credential_value="secret",
        )


# ---------- get_credential ----------


@pytest.mark.asyncio
async def test_get_credential_found(service, mock_db):
    """Test getting a stored credential (decrypted)."""
    record = _make_credential_record()
    mock_db.execute.return_value.scalar_one_or_none.return_value = record
    value = await service.get_credential("gw-1", "user@test.com")
    assert value == "decrypted_value"


@pytest.mark.asyncio
async def test_get_credential_not_found(service, mock_db):
    """Test getting a credential that doesn't exist."""
    mock_db.execute.return_value.scalar_one_or_none.return_value = None
    value = await service.get_credential("gw-1", "user@test.com")
    assert value is None


@pytest.mark.asyncio
async def test_get_credential_no_encryption(service_no_encryption, mock_db):
    """Test getting a credential when encryption is not available."""
    record = _make_credential_record(credential_value="plain_text_secret")
    mock_db.execute.return_value.scalar_one_or_none.return_value = record
    value = await service_no_encryption.get_credential("gw-1", "user@test.com")
    assert value == "plain_text_secret"


# ---------- get_credential_info ----------


@pytest.mark.asyncio
async def test_get_credential_info(service, mock_db):
    """Test getting credential metadata (no secret)."""
    record = _make_credential_record()
    mock_db.execute.return_value.scalar_one_or_none.return_value = record
    info = await service.get_credential_info("gw-1", "user@test.com")
    assert info is not None
    assert info["credential_type"] == "api_key"
    assert info["label"] == "My API Key"
    assert "credential_value" not in info


@pytest.mark.asyncio
async def test_get_credential_info_not_found(service, mock_db):
    """Test getting info for non-existent credential."""
    mock_db.execute.return_value.scalar_one_or_none.return_value = None
    info = await service.get_credential_info("gw-1", "user@test.com")
    assert info is None


# ---------- revoke_credential ----------


@pytest.mark.asyncio
async def test_revoke_credential_success(service, mock_db):
    """Test revoking an existing credential."""
    mock_db.execute.return_value.rowcount = 1
    result = await service.revoke_credential("gw-1", "user@test.com")
    assert result is True
    mock_db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_revoke_credential_not_found(service, mock_db):
    """Test revoking a non-existent credential."""
    mock_db.execute.return_value.rowcount = 0
    result = await service.revoke_credential("gw-1", "user@test.com")
    assert result is False


# ---------- list_user_credentials ----------


@pytest.mark.asyncio
async def test_list_user_credentials(service, mock_db):
    """Test listing all credentials for a user."""
    records = [
        _make_credential_record(gateway_id="gw-1", credential_type="api_key"),
        _make_credential_record(gateway_id="gw-2", credential_type="bearer_token"),
    ]
    mock_db.execute.return_value.scalars.return_value.all.return_value = records
    result = await service.list_user_credentials("user@test.com")
    assert len(result) == 2
    assert result[0]["gateway_id"] == "gw-1"
    assert result[1]["credential_type"] == "bearer_token"


# ---------- build_auth_headers ----------


def test_build_auth_headers_bearer_token():
    """Test building Bearer token headers."""
    headers = CredentialStorageService.build_auth_headers("bearer_token", "my-token")
    assert headers == {"Authorization": "Bearer my-token"}


def test_build_auth_headers_api_key():
    """Test building API key headers (Basic auth with X password)."""
    import base64

    headers = CredentialStorageService.build_auth_headers("api_key", "my-api-key")
    expected = base64.b64encode(b"my-api-key:X").decode()
    assert headers == {"Authorization": f"Basic {expected}"}


def test_build_auth_headers_basic_auth():
    """Test building Basic auth headers."""
    import base64

    headers = CredentialStorageService.build_auth_headers("basic_auth", "user:pass")
    expected = base64.b64encode(b"user:pass").decode()
    assert headers == {"Authorization": f"Basic {expected}"}


def test_build_auth_headers_unknown_type():
    """Test building headers with unknown type returns empty dict."""
    headers = CredentialStorageService.build_auth_headers("unknown", "value")
    assert headers == {}


# ---------- valid credential types ----------


def test_valid_credential_types():
    """Test that valid credential types are defined."""
    assert "api_key" in VALID_CREDENTIAL_TYPES
    assert "bearer_token" in VALID_CREDENTIAL_TYPES
    assert "basic_auth" in VALID_CREDENTIAL_TYPES
