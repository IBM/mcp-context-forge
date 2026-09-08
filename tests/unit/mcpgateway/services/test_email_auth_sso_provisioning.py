# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_email_auth_sso_provisioning.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for internal passwordless SSO user provisioning.
"""

# Standard
from uuid import uuid4

# Third-Party
import pytest
from sqlalchemy import select

# First-Party
from mcpgateway.auth_user_helpers import is_passwordless_user, PASSWORDLESS_HASH_TYPE
from mcpgateway.db import EmailUser, SSOProvider, utc_now
from mcpgateway.services.email_auth_service import EmailAuthService, SSOProviderValidationError, UserExistsError


def _unique(prefix: str) -> str:
    """Return a unique identifier for shared test DB fixtures."""
    return f"{prefix}-{uuid4().hex}"


def _add_provider(db, provider_id: str, *, name: str | None = None, is_enabled: bool = True, auto_create_users: bool = True) -> SSOProvider:
    """Add an SSO provider row for provisioning tests."""
    provider = SSOProvider(
        id=provider_id,
        name=name or provider_id,
        display_name=f"{provider_id} provider",
        provider_type="oidc",
        is_enabled=is_enabled,
        client_id=f"{provider_id}-client",
        client_secret_encrypted="encrypted",
        authorization_url=f"https://{provider_id}.example.com/authorize",
        token_url=f"https://{provider_id}.example.com/token",
        userinfo_url=f"https://{provider_id}.example.com/userinfo",
        auto_create_users=auto_create_users,
    )
    db.add(provider)
    db.commit()
    return provider


@pytest.mark.asyncio
async def test_create_sso_user_creates_passwordless_user(test_db, monkeypatch) -> None:
    """Enabled providers can create explicit passwordless SSO users."""
    monkeypatch.setattr("mcpgateway.services.email_auth_service.settings.auto_create_personal_teams", False)
    _add_provider(test_db, "entra")
    service = EmailAuthService(test_db)
    email = f"{_unique('sso-user')}@example.com"

    user = await service.create_sso_user(email=email, auth_provider="azure-ad", full_name="SSO User", granted_by="admin@example.com")

    assert user.email == email
    assert user.full_name == "SSO User"
    assert user.password_hash is None
    assert user.password_hash_type == PASSWORDLESS_HASH_TYPE
    assert user.password_changed_at is None
    assert user.auth_provider == "entra"
    assert user.email_verified_at is None
    assert user.password_change_required is False
    assert is_passwordless_user(user) is True

    stored = test_db.execute(select(EmailUser).where(EmailUser.email == email)).scalar_one()
    assert stored.password_hash is None
    assert stored.password_hash_type == PASSWORDLESS_HASH_TYPE


@pytest.mark.asyncio
async def test_create_sso_user_accepts_unknown_configured_provider(test_db, monkeypatch) -> None:
    """Custom provider IDs pass canonicalization when configured and enabled."""
    monkeypatch.setattr("mcpgateway.services.email_auth_service.settings.auto_create_personal_teams", False)
    provider_id = _unique("custom-oidc")
    _add_provider(test_db, provider_id)
    service = EmailAuthService(test_db)

    user = await service.create_sso_user(email=f"{_unique('custom-sso')}@example.com", auth_provider=provider_id.upper())

    assert user.auth_provider == provider_id
    assert user.password_hash is None
    assert user.password_hash_type == PASSWORDLESS_HASH_TYPE


@pytest.mark.asyncio
async def test_create_sso_user_does_not_match_provider_name(test_db) -> None:
    """Provider validation matches SSOProvider.id only, not the display name or name."""
    provider_id = _unique("provider-id")
    _add_provider(test_db, provider_id, name="name-only-provider")
    service = EmailAuthService(test_db)

    with pytest.raises(SSOProviderValidationError, match="not configured"):
        await service.create_sso_user(email=f"{_unique('name-match')}@example.com", auth_provider="name-only-provider")


@pytest.mark.asyncio
async def test_create_sso_user_rejects_missing_disabled_and_overlength_provider(test_db) -> None:
    """Provider failures use the typed provider validation error."""
    disabled_provider_id = _unique("disabled")
    _add_provider(test_db, disabled_provider_id, is_enabled=False)
    service = EmailAuthService(test_db)

    with pytest.raises(SSOProviderValidationError, match="not configured"):
        await service.create_sso_user(email=f"{_unique('missing')}@example.com", auth_provider=_unique("missing-provider"))

    with pytest.raises(SSOProviderValidationError, match="disabled"):
        await service.create_sso_user(email=f"{_unique('disabled-user')}@example.com", auth_provider=disabled_provider_id)

    with pytest.raises(SSOProviderValidationError, match="exceeds 50"):
        await service.create_sso_user(email=f"{_unique('long-provider')}@example.com", auth_provider="x" * 51)


@pytest.mark.asyncio
async def test_create_sso_user_provider_error_precedes_duplicate(test_db) -> None:
    """Provider validation happens before duplicate checks for actionable errors."""
    email = f"{_unique('duplicate-provider-order')}@example.com"
    existing = EmailUser(email=email, password_hash="hash", password_hash_type="argon2id", auth_provider="local")
    test_db.add(existing)
    test_db.commit()
    service = EmailAuthService(test_db)

    with pytest.raises(SSOProviderValidationError, match="not configured"):
        await service.create_sso_user(email=email, auth_provider=_unique("missing-provider"))

    stored = test_db.execute(select(EmailUser).where(EmailUser.email == email)).scalar_one()
    assert stored.password_hash == "hash"
    assert stored.password_hash_type == "argon2id"
    assert stored.auth_provider == "local"


@pytest.mark.asyncio
async def test_create_sso_user_duplicate_leaves_existing_user_unchanged(test_db) -> None:
    """Duplicate email raises UserExistsError and does not mutate the existing row."""
    provider_id = _unique("dup-provider")
    _add_provider(test_db, provider_id)
    email = f"{_unique('duplicate-sso')}@example.com"
    changed_at = utc_now()
    existing = EmailUser(
        email=email,
        password_hash="existing-hash",
        password_hash_type="argon2id",
        full_name="Existing User",
        auth_provider="local",
        password_changed_at=changed_at,
    )
    test_db.add(existing)
    test_db.commit()
    service = EmailAuthService(test_db)

    with pytest.raises(UserExistsError, match="already exists"):
        await service.create_sso_user(email=email, auth_provider=provider_id, full_name="Changed User")

    stored = test_db.execute(select(EmailUser).where(EmailUser.email == email)).scalar_one()
    assert stored.full_name == "Existing User"
    assert stored.password_hash == "existing-hash"
    assert stored.password_hash_type == "argon2id"
    assert stored.auth_provider == "local"
    assert stored.password_changed_at is not None
    assert stored.password_changed_at.replace(tzinfo=changed_at.tzinfo) == changed_at


@pytest.mark.asyncio
async def test_create_sso_user_ignores_auto_create_users_policy(test_db, monkeypatch) -> None:
    """Admin/service provisioning intentionally bypasses browser JIT auto-create policy."""
    monkeypatch.setattr("mcpgateway.services.email_auth_service.settings.auto_create_personal_teams", False)
    provider_id = _unique("manual-provider")
    _add_provider(test_db, provider_id, auto_create_users=False)
    service = EmailAuthService(test_db)

    user = await service.create_sso_user(email=f"{_unique('manual-provisioned')}@example.com", auth_provider=provider_id)

    assert user.auth_provider == provider_id
    assert user.password_hash is None
    assert user.password_hash_type == PASSWORDLESS_HASH_TYPE


@pytest.mark.asyncio
async def test_create_sso_user_admin_origin_is_sso(test_db, monkeypatch) -> None:
    """SSO-provisioned admins are marked as SSO-origin admins."""
    monkeypatch.setattr("mcpgateway.services.email_auth_service.settings.auto_create_personal_teams", False)
    provider_id = _unique("admin-provider")
    _add_provider(test_db, provider_id)
    service = EmailAuthService(test_db)

    user = await service.create_sso_user(email=f"{_unique('sso-admin')}@example.com", auth_provider=provider_id, is_admin=True)

    assert user.is_admin is True
    assert user.admin_origin == "sso"
