# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_admin_bypass_owner_visibility.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Integration tests for admin-bypass owner matching on endpoints that centralized
Layer-1 visibility derivation.

Several endpoints previously nulled ``user_email`` when granting admin bypass and
now forward the caller's email instead. Against the real service layer
(``BaseService._apply_visibility_scope``) that difference decides whether a
DB-admin's *own* private rows are returned:

- ``token_teams=None, user_email=None``  -> public + team, no private rows at all
- ``token_teams=None, user_email=admin`` -> public + team + the admin's own private rows

These tests exercise the real auth pipeline against a real database rather than
mocking the Layer-1 helper, so they prove the row actually becomes visible and,
critically, that another user's private row still does not.
"""

# Standard
from datetime import datetime, timezone
import os
import tempfile
import uuid

# Third-Party
from fastapi import Depends, Request as FastAPIRequest
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# First-Party
import mcpgateway.db as db_mod
import mcpgateway.main as main_mod
from mcpgateway.auth import get_current_user
from mcpgateway.config import settings
from mcpgateway.db import Base, EmailUser
from mcpgateway.middleware.rbac import get_current_user_with_permissions

ADMIN_EMAIL = "owner-vis-admin@example.com"
OTHER_EMAIL = "owner-vis-other@example.com"
ADMIN_PASSWORD = "TestPass123!"  # pragma: allowlist secret
OTHER_PASSWORD = "OtherPass123!"  # pragma: allowlist secret

ADMIN_PRIVATE_TAG = "owner-vis-admin-private"
OTHER_PRIVATE_TAG = "owner-vis-other-private"
PUBLIC_TAG = "owner-vis-public"


def _make_tool(owner_email: str, name: str, visibility: str, tag: str):
    """Build a Tool row owned by ``owner_email`` carrying a single ``tag``.

    Args:
        owner_email: Email recorded as the tool owner.
        name: Unique original name for the tool.
        visibility: One of ``public`` / ``team`` / ``private``.
        tag: Single tag applied to the tool.

    Returns:
        An unpersisted ``db_mod.Tool`` instance.
    """
    return db_mod.Tool(
        id=uuid.uuid4().hex,
        original_name=name,
        url="http://example.com/tool",
        owner_email=owner_email,
        visibility=visibility,
        integration_type="REST",
        request_type="GET",
        input_schema={},
        output_schema={},
        enabled=True,
        deprecated=False,
        created_by=owner_email,
        tags=[tag],
    )


@pytest.fixture
def client_and_db():
    """Provision a temp-DB app with an admin, a second user, and three tagged tools.

    Uses the real auth pipeline so ``request.state.token_use`` / ``token_teams`` are
    populated the way production sets them; only RBAC permission resolution is
    stubbed, since these tests target Layer-1 visibility rather than Layer-2.

    Yields:
        The configured ``TestClient``.
    """
    # Third-Party
    from _pytest.monkeypatch import MonkeyPatch

    mp = MonkeyPatch()
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    url = f"sqlite:///{path}"

    mp.setattr(settings, "database_url", url, raising=False)
    engine = create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    mp.setattr(db_mod, "engine", engine, raising=False)
    mp.setattr(db_mod, "SessionLocal", TestSessionLocal, raising=False)
    mp.setattr(main_mod, "SessionLocal", TestSessionLocal, raising=False)

    # First-Party
    import mcpgateway.middleware.auth_middleware as auth_middleware_mod
    import mcpgateway.services.audit_trail_service as audit_trail_mod
    import mcpgateway.services.log_aggregator as log_aggregator_mod
    import mcpgateway.services.security_logger as sec_logger_mod
    import mcpgateway.services.structured_logger as struct_logger_mod

    for mod in (auth_middleware_mod, sec_logger_mod, struct_logger_mod, audit_trail_mod, log_aggregator_mod):
        mp.setattr(mod, "SessionLocal", TestSessionLocal, raising=False)

    Base.metadata.create_all(bind=engine)

    def override_get_db():
        """Yield a session bound to the temp database.

        Yields:
            A SQLAlchemy session.
        """
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    # First-Party
    from mcpgateway.db import get_db as mcpgateway_get_db
    from mcpgateway.middleware.rbac import get_db as rbac_get_db
    from mcpgateway.routers.auth import get_db as auth_get_db

    main_mod.app.dependency_overrides[mcpgateway_get_db] = override_get_db
    main_mod.app.dependency_overrides[auth_get_db] = override_get_db
    main_mod.app.dependency_overrides[rbac_get_db] = override_get_db

    async def mock_user_with_permissions(request: FastAPIRequest, user=Depends(get_current_user)):
        """Return the authenticated user without running Layer-2 permission checks.

        Args:
            request: Incoming request (unused; keeps the real dependency signature).
            user: User resolved by the real auth pipeline.

        Returns:
            The user context dict handlers expect.
        """
        return {
            "email": user.email,
            "full_name": user.full_name,
            "is_admin": user.is_admin,
            "ip_address": "127.0.0.1",
            "user_agent": "test-client",
        }

    main_mod.app.dependency_overrides[get_current_user_with_permissions] = mock_user_with_permissions

    # First-Party
    from mcpgateway.services.argon2_service import Argon2PasswordService

    argon2 = Argon2PasswordService()
    db = TestSessionLocal()
    for email, password, is_admin in ((ADMIN_EMAIL, ADMIN_PASSWORD, True), (OTHER_EMAIL, OTHER_PASSWORD, False)):
        db.add(
            EmailUser(
                id=str(uuid.uuid4()),
                email=email,
                password_hash=argon2.hash_password(password),
                full_name=f"Owner Vis {email}",
                is_admin=is_admin,
                is_active=True,
                auth_provider="local",
                email_verified_at=datetime.now(timezone.utc),
            )
        )
    db.commit()

    db.add(_make_tool(ADMIN_EMAIL, "owner-vis-admin-private-tool", "private", ADMIN_PRIVATE_TAG))
    db.add(_make_tool(OTHER_EMAIL, "owner-vis-other-private-tool", "private", OTHER_PRIVATE_TAG))
    db.add(_make_tool(OTHER_EMAIL, "owner-vis-public-tool", "public", PUBLIC_TAG))
    db.commit()

    # Grant the non-admin caller Layer-2 tags.read so the request reaches the Layer-1
    # filter under test; without it RBAC rejects with 403 before visibility is derived.
    reader_role = db_mod.Role(
        id=str(uuid.uuid4()),
        name="owner-vis-tag-reader",
        scope="global",
        permissions=["tags.read"],
        created_by=ADMIN_EMAIL,
        is_active=True,
    )
    db.add(reader_role)
    db.commit()
    db.add(
        db_mod.UserRole(
            id=str(uuid.uuid4()),
            user_email=OTHER_EMAIL,
            role_id=reader_role.id,
            scope="global",
            granted_by=ADMIN_EMAIL,
            is_active=True,
        )
    )
    db.commit()
    db.close()

    test_client = TestClient(main_mod.app, raise_server_exceptions=False)
    try:
        yield test_client
    finally:
        main_mod.app.dependency_overrides.clear()
        mp.undo()
        engine.dispose()
        os.unlink(path)


def _auth_headers(test_client: TestClient, email: str, password: str) -> dict:
    """Authenticate via the real session-login route and return a bearer header.

    Logging in for real (rather than minting a token by hand) is the point: it is what
    populates ``request.state.token_use`` and ``token_teams``, which drive the Layer-1
    derivation under test.

    Args:
        test_client: Client used to perform the login.
        email: Account email.
        password: Account password.

    Returns:
        An ``Authorization`` header dict carrying the issued session token.
    """
    resp = test_client.post("/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, f"Login failed for {email}: {resp.text}"
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _tag_names(resp) -> set:
    """Extract the set of tag names from a ``/tags`` response.

    Args:
        resp: The HTTP response returned by the tags endpoint.

    Returns:
        Set of tag name strings.
    """
    assert resp.status_code == 200, resp.text
    return {entry["name"] for entry in resp.json()}


class TestAdminBypassOwnerVisibility:
    """End-to-end Layer-1 behavior on the tag endpoints, against a real database."""

    def test_admin_sees_own_private_tag(self, client_and_db):
        """A DB-admin with an unrestricted token sees tags from their own private rows.

        This is the behavior change: the superseded inline derivation nulled the admin's
        email, which excluded every private row including the admin's own.
        """
        headers = _auth_headers(client_and_db, ADMIN_EMAIL, ADMIN_PASSWORD)

        names = _tag_names(client_and_db.get("/tags", headers=headers))

        assert ADMIN_PRIVATE_TAG in names
        assert PUBLIC_TAG in names

    def test_admin_does_not_see_another_users_private_tag(self, client_and_db):
        """Admin bypass must not widen visibility to another user's private rows.

        This is the invariant that makes preserving the email safe; if it ever fails,
        forwarding the email has become a data leak rather than owner matching.
        """
        headers = _auth_headers(client_and_db, ADMIN_EMAIL, ADMIN_PASSWORD)

        names = _tag_names(client_and_db.get("/tags", headers=headers))

        assert OTHER_PRIVATE_TAG not in names

    def test_non_admin_sees_only_public_tags(self, client_and_db):
        """A non-admin caller is unaffected and still sees public rows only."""
        headers = _auth_headers(client_and_db, OTHER_EMAIL, OTHER_PASSWORD)

        names = _tag_names(client_and_db.get("/tags", headers=headers))

        assert PUBLIC_TAG in names
        assert ADMIN_PRIVATE_TAG not in names

    def test_admin_lists_own_private_entity_by_tag(self, client_and_db):
        """The entity lookup resolves the admin's own private tool for its tag."""
        headers = _auth_headers(client_and_db, ADMIN_EMAIL, ADMIN_PASSWORD)

        resp = client_and_db.get(f"/tags/{ADMIN_PRIVATE_TAG}/entities", headers=headers)

        assert resp.status_code == 200, resp.text
        assert any(entity.get("name") == "owner-vis-admin-private-tool" for entity in resp.json())

    def test_admin_cannot_list_another_users_private_entity_by_tag(self, client_and_db):
        """The entity lookup does not resolve another user's private tool, even for an admin."""
        headers = _auth_headers(client_and_db, ADMIN_EMAIL, ADMIN_PASSWORD)

        resp = client_and_db.get(f"/tags/{OTHER_PRIVATE_TAG}/entities", headers=headers)

        assert resp.status_code == 200, resp.text
        assert not [entity for entity in resp.json() if entity.get("name") == "owner-vis-other-private-tool"]
