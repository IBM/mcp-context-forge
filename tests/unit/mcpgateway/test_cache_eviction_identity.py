# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_cache_eviction_identity.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Eviction-identity contract for ``AuthCache`` (#7599).

Cache writes key some entries by the canonical ``user_id`` and others by the
e-mail. Every eviction must therefore cover both identities. These tests use a
diverged user (``user_id != email``) and a real in-memory ``AuthCache``, so an
eviction that only targets the e-mail leaves a stale entry and fails.
"""

# Standard
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

# Third-Party
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# First-Party
from mcpgateway.auth_context import get_cache_identity, get_eviction_identities, identity_or_email
from mcpgateway.cache.auth_cache import AuthCache, CachedAuthContext
from mcpgateway.db import Base, EmailTeam, EmailTeamMember, EmailUser
from mcpgateway.services.email_auth_service import EmailAuthService
from mcpgateway.services.team_management_service import TeamManagementService
import mcpgateway.transports.streamablehttp_transport as tr

EMAIL = "alice@example.com"
USER_ID = "entra-sub-123"
OWNER = "owner@example.com"


@pytest.fixture
def db():
    """In-memory SQLite session with FK enforcement enabled."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def cache():
    """Real in-memory AuthCache with Redis disabled."""
    auth_cache = AuthCache(enabled=True)
    auth_cache._get_redis_client = AsyncMock(return_value=None)
    return auth_cache


def _seed_diverged_member(db):
    """Insert an owner, a diverged member and a shared non-personal team."""
    db.add(EmailUser(email=OWNER, user_id=OWNER, password_hash=None, is_active=True))
    db.add(EmailUser(email=EMAIL, user_id=USER_ID, password_hash=None, is_active=True))
    db.commit()
    suffix = uuid.uuid4().hex[:8]
    team = EmailTeam(name=f"Team {suffix}", slug=f"team-{suffix}", created_by=OWNER, is_personal=False, visibility="private", is_active=True)
    db.add(team)
    db.commit()
    db.refresh(team)
    db.add(EmailTeamMember(team_id=team.id, user_email=OWNER, user_id=OWNER, role="owner", is_active=True))
    db.add(EmailTeamMember(team_id=team.id, user_email=EMAIL, user_id=USER_ID, role="member", invited_by=OWNER, is_active=True))
    db.commit()
    return team


async def _seed_cache_under_both_identities(cache, team_id):
    """Write the entries that a diverged user holds under e-mail and canonical id."""
    for identity in (EMAIL, USER_ID):
        await cache.set_user_teams(f"{identity}:True", [team_id])
        await cache.set_auth_context(identity, "jti-1", CachedAuthContext(user={"email": EMAIL}))
        await cache.set_user_role(identity, team_id, "member")


async def _assert_nothing_cached(cache, team_id):
    for identity in (EMAIL, USER_ID):
        assert await cache.get_user_teams(f"{identity}:True") is None, f"stale teams entry under {identity}"
        assert await cache.get_auth_context(identity, "jti-1") is None, f"stale context under {identity}"
        assert await cache.get_user_role(identity, team_id) is None, f"stale role under {identity}"


async def _drain_background_tasks():
    """Let fire-and-forget eviction tasks finish."""
    current = asyncio.current_task()
    pending = [task for task in asyncio.all_tasks() if task is not current]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


# --------------------------------------------------------------------------- helpers


def test_eviction_identities_diverged_user_returns_email_and_canonical(db):
    db.add(EmailUser(email=EMAIL, user_id=USER_ID, password_hash=None, is_active=True))
    db.commit()
    assert get_eviction_identities(EMAIL, db) == (EMAIL, USER_ID)


def test_eviction_identities_unmapped_email_returns_email_only(db):
    assert get_eviction_identities("ghost@example.com", db) == ("ghost@example.com",)


def test_eviction_identities_equal_canonical_returns_single_identity(db):
    db.add(EmailUser(email=OWNER, user_id=OWNER, password_hash=None, is_active=True))
    db.commit()
    assert get_eviction_identities(OWNER, db) == (OWNER,)


def test_eviction_identities_explicit_user_id_skips_lookup():
    db = MagicMock()
    assert get_eviction_identities(EMAIL, db, USER_ID) == (EMAIL, USER_ID)
    db.query.assert_not_called()


def test_eviction_identities_lookup_failure_still_evicts_email():
    db = MagicMock()
    db.query.side_effect = OperationalError("select", {}, Exception("db down"))
    assert get_eviction_identities(EMAIL, db) == (EMAIL,)


@pytest.mark.parametrize(
    "identity, expected",
    [
        (USER_ID, USER_ID),
        ("unknown", EMAIL),
        ("0b1c2d3e-0000-4000-8000-000000000001", EMAIL),
    ],
)
def test_identity_or_email(identity, expected):
    assert identity_or_email(identity, EMAIL) == expected


@pytest.mark.parametrize(
    "payload, expected",
    [
        ({}, EMAIL),
        ({"user": {"email": EMAIL}}, EMAIL),
        ({"user": {"user_id": USER_ID, "email": EMAIL}}, USER_ID),
        ({"user": {"user_id": "0b1c2d3e-0000-4000-8000-000000000001"}}, EMAIL),
        ({"sub": "0b1c2d3e-0000-4000-8000-000000000001"}, EMAIL),
    ],
)
def test_cache_identity(payload, expected):
    assert get_cache_identity(payload, EMAIL) == expected


# --------------------------------------------------------------------------- eviction (deny path)


@pytest.mark.asyncio
async def test_remove_member_evicts_cached_entries_of_diverged_user(db, cache):
    """Deny path: a removed member must not keep cached teams, context or role under either identity."""
    team = _seed_diverged_member(db)
    await _seed_cache_under_both_identities(cache, team.id)

    with patch("mcpgateway.services.team_management_service.auth_cache", cache):
        assert await TeamManagementService(db).remove_member_from_team(team.id, EMAIL, removed_by=OWNER) is True
        await _drain_background_tasks()

    await _assert_nothing_cached(cache, team.id)


@pytest.mark.asyncio
async def test_delete_team_evicts_cached_entries_of_diverged_member(db, cache):
    team = _seed_diverged_member(db)
    await _seed_cache_under_both_identities(cache, team.id)

    with patch("mcpgateway.services.team_management_service.auth_cache", cache):
        assert await TeamManagementService(db).delete_team(team.id, OWNER) is True
        await _drain_background_tasks()

    for identity in (EMAIL, USER_ID):
        assert await cache.get_user_teams(f"{identity}:True") is None
        assert await cache.get_auth_context(identity, "jti-1") is None


@pytest.mark.asyncio
async def test_update_member_role_evicts_role_cache_under_both_identities(db, cache):
    team = _seed_diverged_member(db)
    await _seed_cache_under_both_identities(cache, team.id)

    with patch("mcpgateway.services.team_management_service.auth_cache", cache):
        assert await TeamManagementService(db).update_member_role(team.id, EMAIL, "owner", updated_by=OWNER) is True
        await _drain_background_tasks()

    for identity in (EMAIL, USER_ID):
        assert await cache.get_user_role(identity, team.id) is None


@pytest.mark.asyncio
async def test_user_auth_cache_invalidation_covers_both_identities(db):
    db.add(EmailUser(email=EMAIL, user_id=USER_ID, password_hash=None, is_active=True))
    db.commit()
    auth_cache = MagicMock()
    auth_cache.invalidate_user = AsyncMock()

    with patch("mcpgateway.cache.auth_cache.auth_cache", auth_cache):
        await EmailAuthService(db)._invalidate_user_auth_cache(EMAIL)

    assert {call.args[0] for call in auth_cache.invalidate_user.await_args_list} == {EMAIL, USER_ID}


@pytest.mark.asyncio
async def test_deleted_user_invalidation_covers_every_captured_identity(db):
    auth_cache = MagicMock()
    auth_cache.invalidate_user = AsyncMock()
    auth_cache.invalidate_user_teams = AsyncMock()
    auth_cache.invalidate_team_membership = AsyncMock()

    with patch("mcpgateway.cache.auth_cache.auth_cache", auth_cache):
        await EmailAuthService(db)._invalidate_deleted_user_auth_caches(EMAIL, (EMAIL, USER_ID))

    for method in (auth_cache.invalidate_user, auth_cache.invalidate_user_teams, auth_cache.invalidate_team_membership):
        assert {call.args[0] for call in method.await_args_list} == {EMAIL, USER_ID}


@pytest.mark.asyncio
async def test_delete_user_captures_canonical_id_before_the_row_is_deleted(db):
    """The canonical id is unresolvable once the user row is gone, so delete_user must capture it first."""
    db.add(EmailUser(email=EMAIL, user_id=USER_ID, password_hash=None, is_active=True))
    db.commit()
    service = EmailAuthService(db)
    service._invalidate_deleted_user_auth_caches = AsyncMock()

    assert await service.delete_user(EMAIL) is True

    service._invalidate_deleted_user_auth_caches.assert_awaited_once_with(EMAIL, (EMAIL, USER_ID))


# --------------------------------------------------------------------------- transport keys


@pytest.mark.asyncio
async def test_transport_reads_auth_context_under_get_current_user_identity(monkeypatch):
    auth_cache = MagicMock()
    auth_cache.get_auth_context = AsyncMock(return_value=CachedAuthContext(user={"email": EMAIL, "is_admin": False}))
    monkeypatch.setattr("mcpgateway.cache.auth_cache.get_auth_cache", lambda: auth_cache)
    monkeypatch.setattr(tr.settings, "auth_cache_enabled", True)
    monkeypatch.setattr(tr.settings, "require_user_in_db", False)
    monkeypatch.setattr(tr, "_resolve_jwt_user_email_for_streamable", AsyncMock(return_value=EMAIL))

    with patch("mcpgateway.auth.resolve_session_teams", new_callable=AsyncMock, return_value=[]):
        await tr._normalize_jwt_payload({"sub": EMAIL, "user": {"user_id": USER_ID, "email": EMAIL}, "token_use": "session", "jti": "jti-1"})

    auth_cache.get_auth_context.assert_awaited_once_with(USER_ID, "jti-1")


@pytest.mark.asyncio
async def test_transport_writes_auth_context_under_get_current_user_identity(monkeypatch):
    auth_cache = MagicMock()
    auth_cache.get_auth_context = AsyncMock(return_value=None)
    auth_cache.set_auth_context = AsyncMock()
    monkeypatch.setattr("mcpgateway.cache.auth_cache.get_auth_cache", lambda: auth_cache)
    monkeypatch.setattr(tr.settings, "auth_cache_enabled", True)
    monkeypatch.setattr(tr.settings, "auth_cache_batch_queries", True)
    monkeypatch.setattr(tr.settings, "require_user_in_db", False)
    monkeypatch.setattr(tr, "_resolve_jwt_user_email_for_streamable", AsyncMock(return_value=EMAIL))
    monkeypatch.setattr(
        "mcpgateway.auth._get_auth_context_batched_sync",
        MagicMock(return_value={"user": {"email": EMAIL, "is_admin": False, "is_active": True}, "personal_team_id": None, "is_token_revoked": False}),
    )

    with patch("mcpgateway.auth.resolve_session_teams", new_callable=AsyncMock, return_value=[]):
        await tr._normalize_jwt_payload({"sub": EMAIL, "user": {"user_id": USER_ID, "email": EMAIL}, "token_use": "session", "jti": "jti-1"})

    assert auth_cache.set_auth_context.await_args.args[0] == USER_ID
