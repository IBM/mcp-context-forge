# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_email_auth_sso_provisioning.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for internal passwordless SSO user provisioning.
"""

# Standard
from unittest.mock import AsyncMock
from uuid import uuid4

# Third-Party
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.auth_user_helpers import is_passwordless_user, PASSWORDLESS_HASH_TYPE
from mcpgateway.db import EmailAuthEvent, EmailUser, Role, SSOProvider, UserRole, utc_now
from mcpgateway.services.email_auth_service import EmailAuthService, SSOProviderValidationError, UserExistsError
from mcpgateway.services.permission_service import PermissionService
from mcpgateway.services.sso_service import SSOService


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
async def test_create_sso_user_admin_origin_is_api(test_db, monkeypatch) -> None:
    """Manual provisioning records API origin for administrator grants."""
    monkeypatch.setattr("mcpgateway.services.email_auth_service.settings.auto_create_personal_teams", False)
    provider_id = _unique("admin-provider")
    _add_provider(test_db, provider_id)
    service = EmailAuthService(test_db)

    user = await service.create_sso_user(email=f"{_unique('sso-admin')}@example.com", auth_provider=provider_id, is_admin=True)

    assert user.is_admin is True
    assert user.admin_origin == "api"


@pytest.mark.asyncio
@pytest.mark.parametrize("is_admin", [False, True])
async def test_manual_provisioning_permissions_survive_same_provider_login(test_db, monkeypatch, is_admin) -> None:
    """Same-provider login preserves manual grants and does not elevate ordinary users."""
    monkeypatch.setattr("mcpgateway.services.email_auth_service.settings.auto_create_personal_teams", False)
    monkeypatch.setattr("mcpgateway.services.sso_service.settings.sso_auto_admin_domains", [])
    provider_id = _unique("manual-login")
    provider = _add_provider(test_db, provider_id, auto_create_users=False)
    role_name = _unique("manual-role")
    provider.provider_metadata = {"role_mappings": {"Admins": role_name}, "sync_roles": True}
    actor_email = f"{_unique('actor')}@example.com"
    test_db.add(EmailUser(email=actor_email, password_hash="hash", auth_provider="local", is_admin=True))
    test_db.commit()
    role = Role(name=role_name, scope="global", permissions=["users.create"] if is_admin else ["tools.read"], created_by=actor_email)
    test_db.add(role)
    test_db.commit()
    role_id = role.id
    monkeypatch.setattr("mcpgateway.services.email_auth_service.settings.default_admin_role" if is_admin else "mcpgateway.services.email_auth_service.settings.default_user_role", role_name)
    email = f"{_unique('manual-login-user')}@example.com"

    user = await EmailAuthService(test_db).create_sso_user(email=email, auth_provider=provider_id, is_admin=is_admin, granted_by=actor_email)
    assert user.is_admin is is_admin
    assert user.admin_origin == ("api" if is_admin else None)
    assignment = test_db.execute(select(UserRole).where(UserRole.user_email == email, UserRole.role_id == role_id)).scalar_one()
    assignment_id = assignment.id
    assert assignment.grant_source is None
    assert assignment.granted_by == actor_email
    assert assignment.is_active is True
    assert await PermissionService(test_db, audit_enabled=False).check_permission(email, "users.create", allow_admin_bypass=False) is is_admin

    token = await SSOService(test_db).authenticate_or_create_user({"email": email, "provider": provider_id, "email_verified": True, "groups": []})
    assert token is not None

    with Session(bind=test_db.get_bind()) as fresh_db:
        stored = fresh_db.execute(select(EmailUser).where(EmailUser.email == email)).scalar_one()
        retained = fresh_db.get(UserRole, assignment_id)
        assert stored.is_admin is is_admin
        assert stored.admin_origin == ("api" if is_admin else None)
        assert retained is not None and retained.is_active is True
        assert retained.grant_source is None
        assert retained.granted_by == actor_email
        assert await PermissionService(fresh_db, audit_enabled=False).check_permission(email, "users.create", allow_admin_bypass=False) is is_admin


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_stage", ["add", "commit"])
async def test_sso_registration_event_failure_preserves_success(test_db, monkeypatch, failure_stage) -> None:
    """Event failures preserve the successful result, committed account, and duplicate retry behavior."""
    monkeypatch.setattr("mcpgateway.services.email_auth_service.settings.auto_create_personal_teams", False)
    provider_id = _unique("event-failure")
    _add_provider(test_db, provider_id)
    email = f"{_unique('event-failure-user')}@example.com"
    original_add = test_db.add
    original_commit = test_db.commit
    event_failures = []

    def failing_add(instance, **kwargs):
        """Fail only registration event insertion."""
        if failure_stage == "add" and isinstance(instance, EmailAuthEvent) and instance.event_type == "registration":
            event_failures.append(instance.success)
            raise RuntimeError("registration event insertion failed")
        return original_add(instance, **kwargs)

    def failing_commit():
        """Fail only registration event commit after the account commits."""
        if failure_stage == "commit" and any(isinstance(row, EmailAuthEvent) and row.event_type == "registration" for row in test_db.new):
            event_failures.append(True)
            raise RuntimeError("registration event commit failed")
        return original_commit()

    monkeypatch.setattr(test_db, "add", failing_add)
    monkeypatch.setattr(test_db, "commit", failing_commit)
    service = EmailAuthService(test_db)
    user = await service.create_sso_user(email=email, auth_provider=provider_id, full_name="Persisted User")
    assert user.email == email
    assert event_failures == [True]
    with Session(bind=test_db.get_bind()) as fresh_db:
        stored = fresh_db.execute(select(EmailUser).where(EmailUser.email == email)).scalar_one()
        assert stored.full_name == "Persisted User"
        assert stored.password_hash is None
        assert stored.auth_provider == provider_id
        assert fresh_db.execute(select(EmailAuthEvent).where(EmailAuthEvent.user_email == email)).scalars().all() == []

    with pytest.raises(UserExistsError):
        await service.create_sso_user(email=email, auth_provider=provider_id, full_name="Changed User", is_admin=True)
    with Session(bind=test_db.get_bind()) as fresh_db:
        stored = fresh_db.execute(select(EmailUser).where(EmailUser.email == email)).scalar_one()
        assert stored.full_name == "Persisted User"
        assert stored.is_admin is False


@pytest.mark.asyncio
@pytest.mark.parametrize("audit_fails", [False, True])
async def test_sso_account_commit_failure_preserves_original_error_and_retry(test_db, monkeypatch, audit_fails) -> None:
    """Account commit failure leaves no account; event failure cannot replace the original error."""
    monkeypatch.setattr("mcpgateway.services.email_auth_service.settings.auto_create_personal_teams", False)
    provider_id = _unique("account-failure")
    _add_provider(test_db, provider_id)
    email = f"{_unique('account-failure-user')}@example.com"
    original_commit = test_db.commit
    account_error = RuntimeError("account persistence failed")
    commits = 0

    def failing_commit():
        """Fail initial account persistence and optionally the failed-registration event."""
        nonlocal commits
        commits += 1
        if commits == 1:
            raise account_error
        if audit_fails:
            raise RuntimeError("failure event persistence failed")
        return original_commit()

    monkeypatch.setattr(test_db, "commit", failing_commit)
    service = EmailAuthService(test_db)
    with pytest.raises(RuntimeError, match="account persistence failed") as error:
        await service.create_sso_user(email=email, auth_provider=provider_id)
    assert error.value is account_error
    assert commits == 2
    with Session(bind=test_db.get_bind()) as fresh_db:
        assert fresh_db.execute(select(EmailUser).where(EmailUser.email == email)).scalar_one_or_none() is None
        events = fresh_db.execute(select(EmailAuthEvent).where(EmailAuthEvent.user_email == email)).scalars().all()
        assert len(events) == (0 if audit_fails else 1)
        if events:
            assert events[0].success is False

    monkeypatch.setattr(test_db, "commit", original_commit)
    user = await service.create_sso_user(email=email, auth_provider=provider_id)
    assert user.email == email
    with Session(bind=test_db.get_bind()) as fresh_db:
        assert fresh_db.execute(select(EmailUser).where(EmailUser.email == email)).scalar_one().password_hash is None


@pytest.mark.asyncio
async def test_sso_provisioning_uses_shared_duplicate_lookup(test_db, monkeypatch) -> None:
    """Provisioning performs the duplicate lookup once through shared user creation."""
    monkeypatch.setattr("mcpgateway.services.email_auth_service.settings.auto_create_personal_teams", False)
    provider_id = _unique("one-lookup")
    _add_provider(test_db, provider_id)
    service = EmailAuthService(test_db)
    lookup = AsyncMock(wraps=service.get_user_by_email)
    monkeypatch.setattr(service, "get_user_by_email", lookup)
    email = f"{_unique('one-lookup-user')}@example.com"
    await service.create_sso_user(email=email, auth_provider=provider_id)
    lookup.assert_awaited_once_with(email)


@pytest.mark.asyncio
async def test_local_registration_event_errors_keep_existing_behavior(test_db, monkeypatch) -> None:
    """The new best-effort option leaves existing local creation behavior unchanged by default."""
    monkeypatch.setattr("mcpgateway.services.email_auth_service.settings.auto_create_personal_teams", False)
    service = EmailAuthService(test_db)
    monkeypatch.setattr(service.password_service, "hash_password_async", AsyncMock(return_value="hash"))
    original_commit = test_db.commit
    email = f"{_unique('local-event-failure')}@example.com"
    commits = 0

    def failing_event_commit():
        """Allow the account commit, then fail only success-event persistence."""
        nonlocal commits
        commits += 1
        if commits == 2:
            raise RuntimeError("local registration event failed")
        return original_commit()

    monkeypatch.setattr(test_db, "commit", failing_event_commit)
    with pytest.raises(RuntimeError, match="local registration event failed"):
        await service.create_user(email=email, password="", skip_password_validation=True)
