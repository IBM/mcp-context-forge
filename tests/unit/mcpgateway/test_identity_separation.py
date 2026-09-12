# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_identity_separation.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Diverged-identity separation suite (issue #5894).

Proves RBAC, team resolution, audit recording, and cache keys all key on the
canonical ``user_id`` when ``user_id != email``. The fixture user is created
THROUGH the writer paths (``EmailAuthService.create_user`` with an explicit
``user_id``, ``RoleService.assign_role_to_user``, and
``TeamManagementService.add_member_to_team``). Hand-written identity rows are
forbidden here: they would mask writer-side re-keying bugs.

Rolling-deploy matrix part 1: three token formats that predate the canonical
user_id must resolve to the same principal through the mapping seam
(``get_user_email_from_token`` and the payload helpers in
``mcpgateway.auth_context``):

- UUID-sub session token (``sub`` = ``EmailUser.id``, ``token_use="session"``)
- e-mail-sub API token (``sub`` = e-mail, ``token_use="api"``)
- legacy token (``sub`` = e-mail, no ``token_use`` claim)

A fail-closed row asserts that a trust-style opaque subject (not an e-mail,
not a known UUID) resolves to no user and is rejected by the authentication
flow, never silently mapped onto another user. Trust-mode acceptance is Epic 2
scope and is deliberately absent here.
"""

# Standard
import asyncio
from contextlib import contextmanager
import os
from types import SimpleNamespace
import uuid

# Third-Party
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
import jwt
import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

# First-Party
from mcpgateway.auth import get_current_user, get_user_email_from_token
from mcpgateway.auth_context import get_user_email, get_user_id
from mcpgateway.cache.auth_cache import AuthCache, CachedAuthContext
from mcpgateway.config import settings
from mcpgateway.db import AuditTrail, EmailTeam, EmailTeamMember, EmailUser, Role, UserRole
from mcpgateway.services.audit_trail_service import AuditTrailService
from mcpgateway.services.email_auth_service import EmailAuthService
from mcpgateway.services.permission_service import PermissionService
from mcpgateway.services.role_service import RoleService
from mcpgateway.services.team_management_service import TeamManagementService
from mcpgateway.utils.verify_credentials import verify_jwt_token

# Local
from tests.helpers.auth import make_legacy_test_jwt, make_test_jwt

DIVERGED_EMAIL = "dev@example.com"
DIVERGED_USER_ID = "idp-123"
DIVERGED_PERMISSION = "tools.read"
OPAQUE_SUBJECT = "entraopaque987"

TOKEN_FORMATS = ("uuid_sub_session", "email_sub_api", "legacy_no_token_use")


@pytest.fixture(scope="session")
def diverged_identity(test_engine):
    """Create the diverged user and its grants through the writer paths.

    The user gets ``user_id="idp-123"`` with e-mail ``dev@example.com``. The
    role assignment and the team membership go through the real writers, which
    dual-write each row: ``user_email`` stays the FK-valid e-mail and the new
    ``user_id`` column carries the canonical id. The fixture returns plain
    scalars only; tests re-query ORM rows through their own session.

    Args:
        test_engine: Session-scoped test database engine from conftest.

    Returns:
        SimpleNamespace: email, user_id, permission, user_uuid, team_id, role_id.
    """
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

    async def _setup():
        db = testing_session_local()
        try:
            auth_service = EmailAuthService(db)
            user = await auth_service.create_user(
                email=DIVERGED_EMAIL,
                password=os.environ["DEFAULT_USER_PASSWORD"],  # conftest test user password
                user_id=DIVERGED_USER_ID,
                skip_password_validation=True,  # password is irrelevant to identity; the fixed test password fails the strength policy
                skip_onboarding=True,
            )

            # The Role row is authorization data, not an identity row.
            role = Role(
                id=str(uuid.uuid4()),
                name=f"separation-suite-{uuid.uuid4().hex[:8]}",
                scope="global",
                permissions=[DIVERGED_PERMISSION],
                created_by=DIVERGED_EMAIL,
                is_system_role=False,
                is_active=True,
            )
            db.add(role)
            db.commit()

            role_service = RoleService(db)
            assignment = await role_service.assign_role_to_user(user_email=DIVERGED_EMAIL, role_id=role.id, scope="global", scope_id=None, granted_by=DIVERGED_EMAIL)
            assert assignment.user_email == DIVERGED_EMAIL  # FK-valid e-mail, never the canonical id
            assert assignment.user_id == DIVERGED_USER_ID  # canonical id dual-written to user_id

            # The EmailTeam row is a container, not an identity row.
            team = EmailTeam(
                name=f"Separation Suite Team {uuid.uuid4().hex[:8]}",
                slug=f"separation-suite-{uuid.uuid4().hex[:8]}",
                created_by=DIVERGED_EMAIL,
                is_personal=False,
            )
            db.add(team)
            db.commit()

            team_service = TeamManagementService(db)
            membership = await team_service.add_member_to_team(team_id=team.id, user_email=DIVERGED_EMAIL, role="member", invited_by=DIVERGED_EMAIL)
            assert membership.user_email == DIVERGED_EMAIL  # FK-valid e-mail, never the canonical id
            assert membership.user_id == DIVERGED_USER_ID  # canonical id dual-written to user_id

            # Let the fire-and-forget cache invalidations finish before the loop closes.
            await asyncio.sleep(0)

            return {"user_uuid": user.id, "team_id": team.id, "role_id": role.id}
        finally:
            db.close()

    state = asyncio.run(_setup())
    return SimpleNamespace(email=DIVERGED_EMAIL, user_id=DIVERGED_USER_ID, permission=DIVERGED_PERMISSION, **state)


@contextmanager
def _session_scope(session_factory):
    """Yield a fresh session from the factory, closing it on exit."""
    db = session_factory()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def seam_db(test_engine, monkeypatch):
    """Bridge ``mcpgateway.auth`` fresh DB sessions onto the test engine.

    The production seam helpers open their own sessions through
    ``fresh_db_session``. Pointing that factory at the test engine lets the
    suite exercise the real query paths against fixture data. The global auth
    cache singleton is replaced with a fresh instance so cache-key assertions
    are hermetic.

    Returns:
        AuthCache: The fresh cache instance that replaced the singleton.
    """
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    monkeypatch.setattr("mcpgateway.auth.fresh_db_session", lambda: _session_scope(testing_session_local))
    cache = AuthCache(enabled=True)
    monkeypatch.setattr("mcpgateway.cache.auth_cache.auth_cache", cache)
    return cache


def _jwt_secret() -> str:
    """Return the active JWT secret as plain text.

    ``settings.jwt_secret_key`` is a ``SecretStr`` by default, but test and
    doctest code may assign a plain string to the live settings object. Accept
    both so minting and decoding always use the same active key.
    """
    secret = settings.jwt_secret_key
    return secret.get_secret_value() if hasattr(secret, "get_secret_value") else secret


def _mint_token(token_format: str, *, user_uuid: str) -> str:
    """Mint one rolling-deploy token shape through the shared test helpers.

    Args:
        token_format: One of ``TOKEN_FORMATS``.
        user_uuid: The diverged user's ``EmailUser.id`` (UUID).

    Returns:
        str: The signed JWT.
    """
    if token_format == "uuid_sub_session":
        return make_test_jwt(user_uuid, token_use="session")
    if token_format == "email_sub_api":
        return make_test_jwt(DIVERGED_EMAIL, token_use="api")
    if token_format == "legacy_no_token_use":
        return make_legacy_test_jwt(DIVERGED_EMAIL, secret=_jwt_secret(), algorithm=settings.jwt_algorithm)
    raise ValueError(f"Unknown token format: {token_format}")


def _decode(token: str) -> dict:
    """Verify and decode a test token with the configured issuer, audience, and key."""
    return jwt.decode(
        token,
        _jwt_secret(),
        algorithms=[settings.jwt_algorithm],
        audience=settings.jwt_audience,
        issuer=settings.jwt_issuer,
    )


async def _resolve_principal(payload: dict, db) -> EmailUser:
    """Resolve a token payload to the principal through the mapping seam.

    The seam resolves UUID subjects through the DB and returns legacy e-mail
    subjects directly. The ORM row carries the e-mail attribute and the
    canonical ``user_id`` column; both are asserted here so every matrix cell
    starts from the same proven principal.
    """
    email = await get_user_email_from_token(payload, db)
    assert email == DIVERGED_EMAIL
    user = db.execute(select(EmailUser).where(EmailUser.email == email)).scalar_one_or_none()
    assert user is not None
    assert get_user_id(user) == DIVERGED_USER_ID
    assert get_user_email(user) == DIVERGED_EMAIL
    return user


class TestDivergedIdentityMatrix:
    """Three token formats by four identity consumers: RBAC, teams, audit, cache."""

    @pytest.mark.parametrize("token_format", TOKEN_FORMATS)
    async def test_rbac_grant_findable_by_email_and_canonical_id(self, token_format, diverged_identity, test_db):
        """The diverged user's role row is e-mail-keyed for readers and carries the canonical user_id alongside."""
        payload = _decode(_mint_token(token_format, user_uuid=diverged_identity.user_uuid))
        principal = await _resolve_principal(payload, test_db)

        # Row lookups are e-mail-keyed: the principal's e-mail reaches the grant.
        permissions = await PermissionService(test_db).get_user_permissions(get_user_email(principal))
        assert DIVERGED_PERMISSION in permissions

        # The same grant row is findable by both keys: the FK e-mail column and the canonical user_id column.
        by_email = test_db.execute(select(UserRole).where(UserRole.role_id == diverged_identity.role_id, UserRole.user_email == DIVERGED_EMAIL)).scalar_one()
        assert by_email.user_id == DIVERGED_USER_ID
        by_canonical = test_db.execute(select(UserRole).where(UserRole.role_id == diverged_identity.role_id, UserRole.user_id == DIVERGED_USER_ID)).scalar_one()
        assert by_canonical.id == by_email.id

        # Separation control: the canonical id never lands in the FK e-mail column.
        stray = test_db.execute(select(UserRole).where(UserRole.user_email == DIVERGED_USER_ID)).scalars().all()
        assert stray == []

    @pytest.mark.parametrize("token_format", TOKEN_FORMATS)
    async def test_team_membership_findable_by_email_and_canonical_id(self, token_format, diverged_identity, test_db):
        """The diverged user's membership row is e-mail-keyed for readers and carries the canonical user_id alongside."""
        payload = _decode(_mint_token(token_format, user_uuid=diverged_identity.user_uuid))
        principal = await _resolve_principal(payload, test_db)

        # Row lookups are e-mail-keyed (mirrors the membership query in the team-resolution seam).
        team_ids = test_db.execute(select(EmailTeamMember.team_id).where(EmailTeamMember.user_email == get_user_email(principal), EmailTeamMember.is_active.is_(True))).scalars().all()
        assert diverged_identity.team_id in team_ids

        # The same membership row is findable by both keys: the FK e-mail column and the canonical user_id column.
        by_email = test_db.execute(select(EmailTeamMember).where(EmailTeamMember.team_id == diverged_identity.team_id, EmailTeamMember.user_email == DIVERGED_EMAIL)).scalar_one()
        assert by_email.user_id == DIVERGED_USER_ID
        by_canonical = test_db.execute(select(EmailTeamMember).where(EmailTeamMember.team_id == diverged_identity.team_id, EmailTeamMember.user_id == DIVERGED_USER_ID)).scalar_one()
        assert by_canonical.id == by_email.id

        # Separation control: the canonical id never lands in the FK e-mail column.
        stray = test_db.execute(select(EmailTeamMember).where(EmailTeamMember.user_email == DIVERGED_USER_ID)).scalars().all()
        assert stray == []

    @pytest.mark.parametrize("token_format", TOKEN_FORMATS)
    async def test_audit_records_canonical_user_id(self, token_format, diverged_identity, test_db, monkeypatch):
        """The audit identity field records user_id; the e-mail attribute stays the e-mail."""
        monkeypatch.setattr(settings, "audit_trail_enabled", True)
        payload = _decode(_mint_token(token_format, user_uuid=diverged_identity.user_uuid))
        principal = await _resolve_principal(payload, test_db)

        entry = AuditTrailService().log_action(
            action="READ",
            resource_type="tool",
            resource_id="tool-1",
            user_id=get_user_id(principal),
            user_email=get_user_email(principal),
            db=test_db,
        )

        assert entry is not None
        assert entry.user_id == DIVERGED_USER_ID
        assert entry.user_email == DIVERGED_EMAIL

        record = test_db.execute(select(AuditTrail).where(AuditTrail.correlation_id == entry.correlation_id)).scalar_one()
        assert record.user_id == DIVERGED_USER_ID
        assert record.user_email == DIVERGED_EMAIL

    @pytest.mark.parametrize("token_format", TOKEN_FORMATS)
    async def test_cache_keys_on_canonical_user_id(self, token_format, diverged_identity, test_db):
        """The auth-cache builders key on user_id; no key carries the e-mail."""
        payload = _decode(_mint_token(token_format, user_uuid=diverged_identity.user_uuid))
        principal = await _resolve_principal(payload, test_db)
        identity = get_user_id(principal)
        assert identity == DIVERGED_USER_ID

        cache = AuthCache(enabled=True)
        context = CachedAuthContext(user={"user_id": identity, "email": get_user_email(principal)}, personal_team_id=None, is_token_revoked=False)
        await cache.set_auth_context(identity, "jti-matrix", context)
        await cache.set_user_teams(f"{identity}:True", [diverged_identity.team_id])

        # Round-trip through the same identity hits the written entries.
        cached_context = await cache.get_auth_context(identity, "jti-matrix")
        assert cached_context is not None
        assert cached_context.user["user_id"] == DIVERGED_USER_ID
        assert await cache.get_user_teams(f"{identity}:True") == [diverged_identity.team_id]

        # Keys carry the canonical id, never the e-mail.
        redis_key = cache._get_redis_key("ctx", f"{identity}:jti-matrix")  # pylint: disable=protected-access
        assert DIVERGED_USER_ID in redis_key
        assert DIVERGED_EMAIL not in redis_key
        assert any(DIVERGED_USER_ID in key for key in cache._context_cache)  # pylint: disable=protected-access
        assert not any(DIVERGED_EMAIL in key for key in cache._context_cache)  # pylint: disable=protected-access
        assert any(DIVERGED_USER_ID in key for key in cache._teams_list_cache)  # pylint: disable=protected-access
        assert not any(DIVERGED_EMAIL in key for key in cache._teams_list_cache)  # pylint: disable=protected-access


class TestOpaqueSubjectFailsClosed:
    """A trust-style opaque subject is rejected, never silently mapped (pre-Epic-2)."""

    async def test_opaque_subject_resolves_no_user(self, diverged_identity, test_db):
        """The seam produces no principal for an opaque subject."""
        token = make_test_jwt(OPAQUE_SUBJECT, token_use="session")
        payload = _decode(token)

        # The token itself is validly signed; rejection must come from identity resolution.
        assert payload["sub"] == OPAQUE_SUBJECT

        candidate = await get_user_email_from_token(payload, test_db)
        assert candidate != DIVERGED_EMAIL
        resolved = test_db.execute(select(EmailUser).where(EmailUser.email == candidate)).scalar_one_or_none()
        assert resolved is None

    async def test_opaque_subject_rejected_by_auth_flow(self, diverged_identity, seam_db):
        """get_current_user rejects the opaque subject with 401 and maps it to no user."""
        token = make_test_jwt(OPAQUE_SUBJECT, token_use="session")

        # Control: the token passes signature and claim verification.
        verified = await verify_jwt_token(token)
        assert verified["sub"] == OPAQUE_SUBJECT

        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(credentials=credentials)
        assert exc_info.value.status_code == 401
