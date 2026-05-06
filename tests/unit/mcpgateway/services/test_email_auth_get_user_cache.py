# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_email_auth_get_user_cache.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Tests for get_user_by_email() cache integration and mutation invalidation (Issue #3061).
"""

# Standard
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.db import EmailUser
from mcpgateway.services.email_auth_service import EmailAuthService, _user_dict_to_obj, _user_obj_to_dict

_NOW = datetime(2025, 1, 1, tzinfo=timezone.utc)

_USER_DICT = {
    "email": "test@example.com",
    "full_name": "Test User",
    "is_admin": False,
    "is_active": True,
    "auth_provider": "local",
    "password_hash_type": "argon2id",
    "password_change_required": False,
    "failed_login_attempts": 0,
    "locked_until": None,
    "email_verified_at": None,
    "created_at": "2025-01-01T00:00:00+00:00",
    "updated_at": "2025-01-01T00:00:00+00:00",
    "last_login": None,
    "admin_origin": None,
    "password_changed_at": None,
}


def _make_email_user(email="test@example.com"):
    return EmailUser(
        email=email,
        password_hash="$argon2id$...",
        full_name="Test User",
        is_admin=False,
        is_active=True,
        auth_provider="local",
        password_hash_type="argon2id",
        password_change_required=False,
        failed_login_attempts=0,
        locked_until=None,
        email_verified_at=None,
        created_at=_NOW,
        updated_at=_NOW,
        last_login=None,
        admin_origin=None,
        password_changed_at=None,
    )


@pytest.fixture
def mock_db():
    db = MagicMock()
    db.execute.return_value.scalar_one_or_none.return_value = None
    db.execute.return_value.scalars.return_value.all.return_value = []
    return db


@pytest.fixture
def service(mock_db):
    with patch("mcpgateway.services.email_auth_service.Argon2PasswordService"):
        svc = EmailAuthService(mock_db)
        return svc


# ---------- Helper serialisation round-trip ----------


def test_user_obj_to_dict_round_trip():
    user = _make_email_user()
    d = _user_obj_to_dict(user)
    assert d["email"] == "test@example.com"
    assert d["is_admin"] is False
    assert d["locked_until"] is None
    assert isinstance(d["created_at"], str)


def test_user_dict_to_obj_round_trip():
    obj = _user_dict_to_obj(_USER_DICT)
    assert obj.email == "test@example.com"
    assert obj.is_admin is False
    assert obj.created_at.tzinfo is not None


def test_user_dict_to_obj_accepts_datetime_objects():
    """Line 110: _dt() returns v directly when v is already a datetime."""
    d = dict(_USER_DICT)
    d["created_at"] = _NOW
    d["updated_at"] = _NOW
    obj = _user_dict_to_obj(d)
    assert obj.created_at == _NOW
    assert obj.updated_at == _NOW


# ---------- get_user_by_email cache hit ----------


@pytest.mark.asyncio
async def test_get_user_by_email_cache_hit_skips_db(service, mock_db):
    mock_cache = AsyncMock()
    mock_cache.get_user = AsyncMock(return_value=_USER_DICT)

    with patch("mcpgateway.cache.auth_cache.auth_cache", mock_cache):
        result = await service.get_user_by_email("test@example.com")

    assert result is not None
    assert result.email == "test@example.com"
    mock_db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_get_user_by_email_cache_miss_populates_cache(service, mock_db):
    db_user = _make_email_user()
    mock_db.execute.return_value.scalar_one_or_none.return_value = db_user

    mock_cache = AsyncMock()
    mock_cache.get_user = AsyncMock(return_value=None)
    mock_cache.set_user = AsyncMock()

    with patch("mcpgateway.cache.auth_cache.auth_cache", mock_cache):
        result = await service.get_user_by_email("test@example.com")

    assert result is not None
    assert result.email == "test@example.com"
    mock_cache.set_user.assert_awaited_once()
    call_args = mock_cache.set_user.call_args
    assert call_args[0][0] == "test@example.com"
    assert call_args[0][1]["email"] == "test@example.com"


@pytest.mark.asyncio
async def test_get_user_by_email_cache_error_falls_back_to_db(service, mock_db):
    db_user = _make_email_user()
    mock_db.execute.return_value.scalar_one_or_none.return_value = db_user

    mock_cache = AsyncMock()
    mock_cache.get_user = AsyncMock(side_effect=RuntimeError("Redis down"))

    with patch("mcpgateway.cache.auth_cache.auth_cache", mock_cache):
        result = await service.get_user_by_email("test@example.com")

    assert result is not None
    assert result.email == "test@example.com"
    mock_db.execute.assert_called_once()


# ---------- Mutation invalidation ----------


@pytest.mark.asyncio
async def test_update_user_invalidates_cache(service, mock_db):
    db_user = _make_email_user()
    mock_db.execute.return_value.scalar_one_or_none.return_value = db_user

    with patch.object(service, "_invalidate_user_auth_cache", new_callable=AsyncMock) as mock_inv:
        with patch("mcpgateway.services.email_auth_service.settings") as mock_settings:
            mock_settings.password_min_length = 8
            mock_settings.password_require_uppercase = False
            mock_settings.password_require_lowercase = False
            mock_settings.password_require_numbers = False
            mock_settings.password_require_special = False
            mock_settings.admin_role_name = "platform_admin"
            mock_settings.user_role_name = "developer"
            await service.update_user("test@example.com", full_name="Updated Name")

    mock_inv.assert_awaited_once_with("test@example.com")


@pytest.mark.asyncio
async def test_activate_user_invalidates_cache(service, mock_db):
    db_user = _make_email_user()
    mock_db.execute.return_value.scalar_one_or_none.return_value = db_user

    with patch.object(service, "_invalidate_user_auth_cache", new_callable=AsyncMock) as mock_inv:
        await service.activate_user("test@example.com")

    mock_inv.assert_awaited_once_with("test@example.com")


@pytest.mark.asyncio
async def test_deactivate_user_invalidates_cache(service, mock_db):
    db_user = _make_email_user()
    mock_db.execute.return_value.scalar_one_or_none.return_value = db_user

    with patch.object(service, "_invalidate_user_auth_cache", new_callable=AsyncMock) as mock_inv:
        await service.deactivate_user("test@example.com")

    mock_inv.assert_awaited_once_with("test@example.com")


@pytest.mark.asyncio
async def test_get_user_by_email_set_cache_error_still_returns_user(service, mock_db):
    """Line 598: except block when auth_cache.set_user() raises."""
    db_user = _make_email_user()
    mock_db.execute.return_value.scalar_one_or_none.return_value = db_user

    mock_cache = AsyncMock()
    mock_cache.get_user = AsyncMock(return_value=None)
    mock_cache.set_user = AsyncMock(side_effect=RuntimeError("Cache write failed"))

    with patch("mcpgateway.cache.auth_cache.auth_cache", mock_cache):
        result = await service.get_user_by_email("test@example.com")

    assert result is not None
    assert result.email == "test@example.com"


# ---------- Mutation paths bypass cache (CWE-307 / CWE-613 regression) ----------


def test_user_obj_to_dict_excludes_password_hash():
    """password_hash must not be serialised into Redis (CWE-312)."""
    user = _make_email_user()
    d = _user_obj_to_dict(user)
    assert "password_hash" not in d


def test_user_dict_to_obj_is_active_fails_closed():
    """is_active missing from cache dict must default to False, not True (CWE-20)."""
    d = dict(_USER_DICT)
    d.pop("is_active", None)
    obj = _user_dict_to_obj(d)
    assert obj.is_active is False


def test_fetch_user_from_db_queries_db_directly(service, mock_db):
    """_fetch_user_from_db must hit DB, not cache — ensures ORM tracking for mutations."""
    db_user = _make_email_user()
    mock_db.execute.return_value.scalar_one_or_none.return_value = db_user

    result = service._fetch_user_from_db("test@example.com")

    assert result is db_user
    mock_db.execute.assert_called_once()


def test_fetch_user_from_db_returns_none_on_error(service, mock_db):
    mock_db.execute.side_effect = RuntimeError("DB down")

    result = service._fetch_user_from_db("test@example.com")

    assert result is None


@pytest.mark.asyncio
async def test_unlock_user_account_invalidates_cache(service, mock_db):
    """unlock_user_account must invalidate cache after DB commit (CWE-613)."""
    db_user = _make_email_user()
    mock_db.execute.return_value.scalar_one_or_none.return_value = db_user

    with patch.object(service, "_invalidate_user_auth_cache", new_callable=AsyncMock) as mock_inv:
        with patch.object(service, "_log_auth_event"):
            await service.unlock_user_account("test@example.com", unlocked_by="admin@example.com")

    mock_inv.assert_awaited_once_with("test@example.com")
