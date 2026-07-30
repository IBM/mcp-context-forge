# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/routers/test_log_search_activity.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for the recent activity feed endpoint (GET /api/logs/activity).

Uses an in-memory SQLite database with real AuditTrail and SecurityEvent rows so
the visibility rules (team scoping, self-only security events, restricted-row
exclusion) are exercised as actual SQL rather than mocked query results.
"""

# Standard
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

# Third-Party
from fastapi import HTTPException
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# First-Party
import cpex.framework as plugin_framework
from mcpgateway.db import AuditTrail, Base, SecurityEvent
from mcpgateway.middleware import rbac as rbac_module
from mcpgateway.routers import log_search

BASE_TIME = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def db_session():
    """In-memory SQLite session shared across all connections within one test."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestSession()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture(autouse=True)
def no_plugin_manager(monkeypatch: pytest.MonkeyPatch):
    """Keep plugin hooks out of the permission path for these tests."""

    async def _no_plugin_manager():
        return None

    monkeypatch.setattr(plugin_framework, "get_plugin_manager", _no_plugin_manager)


@pytest.fixture
def grant_permissions(monkeypatch: pytest.MonkeyPatch):
    """Return a helper that grants or denies specific permissions by name."""

    def _configure(denied=()):
        async def _check(self, **kwargs):  # type: ignore[no-self-use]
            return kwargs.get("permission") not in denied

        monkeypatch.setattr(rbac_module.PermissionService, "check_permission", _check)

    return _configure


@pytest.fixture
def scope(monkeypatch: pytest.MonkeyPatch):
    """Return a helper that pins the token-scoped access context tuple."""

    def _configure(email, teams):
        monkeypatch.setattr(log_search, "get_scoped_resource_access_context", lambda request, user: (email, teams))

    return _configure


def make_audit(db, *, offset_seconds=0, action="create", resource_type="mcp_server", success=True, requires_review=False, team_id=None, data_classification=None, **kwargs):
    """Insert one AuditTrail row and return it.

    Args:
        db: Database session.
        offset_seconds: Seconds added to BASE_TIME for this row's timestamp.
        action: Audited action verb.
        resource_type: Audited resource type.
        success: Whether the audited action succeeded.
        requires_review: Whether the row is flagged for review.
        team_id: Owning team, or None for a public row.
        data_classification: Sensitivity label, or None.
        **kwargs: Extra AuditTrail column overrides.

    Returns:
        AuditTrail: The persisted row.
    """
    row = AuditTrail(
        timestamp=BASE_TIME + timedelta(seconds=offset_seconds),
        action=action,
        resource_type=resource_type,
        resource_name=kwargs.pop("resource_name", "widget"),
        user_id=kwargs.pop("user_id", "user@example.com"),
        user_email=kwargs.pop("user_email", "user@example.com"),
        team_id=team_id,
        data_classification=data_classification,
        success=success,
        requires_review=requires_review,
        **kwargs,
    )
    db.add(row)
    db.commit()
    return row


def make_security(db, *, offset_seconds=0, severity="HIGH", user_email="user@example.com", **kwargs):
    """Insert one SecurityEvent row and return it.

    Args:
        db: Database session.
        offset_seconds: Seconds added to BASE_TIME for this row's timestamp.
        severity: Event severity label.
        user_email: Email the event is attributed to.
        **kwargs: Extra SecurityEvent column overrides.

    Returns:
        SecurityEvent: The persisted row.
    """
    row = SecurityEvent(
        timestamp=BASE_TIME + timedelta(seconds=offset_seconds),
        event_type=kwargs.pop("event_type", "failed_login"),
        severity=severity,
        category=kwargs.pop("category", "authentication"),
        client_ip=kwargs.pop("client_ip", "10.0.0.1"),
        description=kwargs.pop("description", "Repeated failed login attempts detected."),
        user_email=user_email,
        **kwargs,
    )
    db.add(row)
    db.commit()
    return row


async def call_feed(db, *, user_email="user@example.com", limit=50, since=None):
    """Invoke the activity feed handler directly.

    Args:
        db: Database session.
        user_email: Email placed in the authenticated user context.
        limit: Maximum merged items to request.
        since: Strictly-after timestamp filter.

    Returns:
        ActivityListResponse: The handler's response.
    """
    return await log_search.get_activity_feed(
        request=MagicMock(),
        limit=limit,
        since=since,
        user={"email": user_email, "db": db},
        db=db,
    )


@pytest.mark.asyncio
async def test_union_returns_both_sources_newest_first(db_session, grant_permissions, scope):
    """Admin feed merges audit and security rows into one newest-first list."""
    grant_permissions()
    scope("admin@example.com", None)
    make_audit(db_session, offset_seconds=10)
    make_security(db_session, offset_seconds=20)

    response = await call_feed(db_session)

    assert [i.source for i in response.items] == ["security", "audit"]
    assert response.items[0].id.startswith("security:")
    assert response.items[1].id.startswith("audit:")
    for item in response.items:
        assert item.source in ("audit", "security")
        assert item.status in ("success", "error", "warning", "info")
        for field in ("id", "title", "description", "resource_type", "resource_name", "actor", "correlation_id"):
            assert isinstance(getattr(item, field), str)
        assert item.timestamp.tzinfo is not None


@pytest.mark.asyncio
async def test_limit_truncates_across_the_union(db_session, grant_permissions, scope):
    """The merged list is truncated to `limit`, keeping the newest items overall."""
    grant_permissions()
    scope("admin@example.com", None)
    for i in range(5):
        make_audit(db_session, offset_seconds=i * 2)
        make_security(db_session, offset_seconds=i * 2 + 1)

    response = await call_feed(db_session, limit=4)

    assert len(response.items) == 4
    timestamps = [i.timestamp for i in response.items]
    assert timestamps == sorted(timestamps, reverse=True)
    assert timestamps == [BASE_TIME + timedelta(seconds=s) for s in (9, 8, 7, 6)]


@pytest.mark.asyncio
async def test_since_excludes_row_exactly_at_boundary(db_session, grant_permissions, scope):
    """`since` is strictly-after: a row whose timestamp equals it is excluded."""
    grant_permissions()
    scope("admin@example.com", None)
    boundary = BASE_TIME + timedelta(seconds=10)
    make_audit(db_session, offset_seconds=10)
    make_audit(db_session, offset_seconds=20)
    make_security(db_session, offset_seconds=10)
    make_security(db_session, offset_seconds=20)

    response = await call_feed(db_session, since=boundary)

    assert len(response.items) == 2
    assert all(i.timestamp > boundary for i in response.items)


@pytest.mark.asyncio
async def test_audit_timestamp_ties_at_limit_resolve_by_id(db_session, grant_permissions, scope):
    """Rows sharing a timestamp survive the SQL LIMIT by id, not DB row order."""
    grant_permissions()
    scope("admin@example.com", None)
    # Insertion order is deliberately not id order: without the SQL tiebreak SQLite
    # returns these ties in reverse-insertion order, which would keep tie-a instead.
    for suffix in ("b", "c", "a"):
        make_audit(db_session, offset_seconds=0, id=f"tie-{suffix}")

    response = await call_feed(db_session, limit=2)

    assert [i.id for i in response.items] == ["audit:tie-c", "audit:tie-b"]


@pytest.mark.asyncio
async def test_security_timestamp_ties_at_limit_resolve_by_id(db_session, grant_permissions, scope):
    """The security source has the same deterministic (timestamp, id) boundary."""
    grant_permissions()
    scope("admin@example.com", None)
    for suffix in ("b", "c", "a"):
        make_security(db_session, offset_seconds=0, id=f"tie-{suffix}")

    response = await call_feed(db_session, limit=2)

    assert [i.id for i in response.items] == ["security:tie-c", "security:tie-b"]


@pytest.mark.asyncio
async def test_feed_narrows_to_audit_only_without_security_read(db_session, grant_permissions, scope):
    """Missing security:read omits security rows instead of rejecting the request."""
    grant_permissions(denied={"security:read"})
    scope("admin@example.com", None)
    make_audit(db_session, offset_seconds=10)
    make_security(db_session, offset_seconds=20)

    response = await call_feed(db_session)

    assert [i.source for i in response.items] == ["audit"]


@pytest.mark.asyncio
async def test_non_admin_sees_only_own_security_events(db_session, grant_permissions, scope):
    """SecurityEvent has no team column, so non-admins see only their own events."""
    grant_permissions()
    scope("user@x.com", ["team-a"])
    make_security(db_session, offset_seconds=10, user_email="user@x.com")
    make_security(db_session, offset_seconds=20, user_email="other@x.com")

    response = await call_feed(db_session, user_email="user@x.com")

    security_items = [i for i in response.items if i.source == "security"]
    assert len(security_items) == 1
    assert security_items[0].actor == "user@x.com"


@pytest.mark.asyncio
async def test_team_scoped_feed_excludes_other_teams(db_session, grant_permissions, scope):
    """A team-scoped token sees its own team's rows plus public (NULL-team) rows."""
    grant_permissions()
    scope("user@x.com", ["team-a"])
    make_audit(db_session, offset_seconds=10, team_id="team-a", resource_name="a-row")
    make_audit(db_session, offset_seconds=20, team_id="team-b", resource_name="b-row")
    make_audit(db_session, offset_seconds=30, team_id=None, resource_name="public-row")

    response = await call_feed(db_session, user_email="user@x.com")

    names = {i.resource_name for i in response.items}
    assert names == {"a-row", "public-row"}


@pytest.mark.asyncio
async def test_public_only_token_sees_only_null_team_rows(db_session, grant_permissions, scope):
    """An empty team list is public-only: team-owned audit rows are excluded."""
    grant_permissions()
    scope("user@x.com", [])
    make_audit(db_session, offset_seconds=10, team_id="team-a", resource_name="a-row")
    make_audit(db_session, offset_seconds=20, team_id=None, resource_name="public-row")

    response = await call_feed(db_session, user_email="user@x.com")

    assert [i.resource_name for i in response.items] == ["public-row"]


@pytest.mark.asyncio
async def test_non_admin_never_receives_restricted_rows(db_session, grant_permissions, scope):
    """Restricted rows are filtered in SQL; NULL-classified rows stay visible."""
    grant_permissions()
    scope("user@x.com", ["team-a"])
    make_audit(db_session, offset_seconds=10, team_id="team-a", data_classification="restricted", resource_name="secret")
    make_audit(db_session, offset_seconds=20, team_id="team-a", data_classification="internal", resource_name="internal-row")
    make_audit(db_session, offset_seconds=30, team_id="team-a", data_classification=None, resource_name="unclassified")

    response = await call_feed(db_session, user_email="user@x.com")

    assert {i.resource_name for i in response.items} == {"internal-row", "unclassified"}


@pytest.mark.asyncio
async def test_admin_receives_restricted_rows(db_session, grant_permissions, scope):
    """Admin bypass sees restricted rows the team-scoped feed hides."""
    grant_permissions()
    scope("admin@example.com", None)
    make_audit(db_session, offset_seconds=10, data_classification="restricted", resource_name="secret")

    response = await call_feed(db_session)

    assert [i.resource_name for i in response.items] == ["secret"]


@pytest.mark.asyncio
async def test_error_path_returns_500(grant_permissions, scope):
    """A failing query surfaces as a 500 rather than an unhandled exception."""
    grant_permissions()
    scope("admin@example.com", None)
    db = MagicMock()
    db.execute.side_effect = Exception("boom")

    with pytest.raises(HTTPException) as exc_info:
        await call_feed(db)

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "Activity feed query failed"


class TestAuditMapper:
    """_audit_to_activity renders server-owned title, description and status."""

    def test_successful_create(self):
        """A successful create is a success item with a humanised resource label."""
        row = AuditTrail(id="1", timestamp=BASE_TIME, action="create", resource_type="mcp_server", resource_name="github", user_id="u", user_email="u@x.com", success=True, requires_review=False)

        item = log_search._audit_to_activity(row)

        assert item.status == "success"
        assert item.title == "MCP server created"
        assert item.description == "MCP server 'github' was created by u@x.com."
        assert item.id == "audit:1"

    def test_failed_create_carries_error_message(self):
        """A failed action is an error item whose description includes the error."""
        row = AuditTrail(
            id="2",
            timestamp=BASE_TIME,
            action="create",
            resource_type="mcp_server",
            resource_name="github",
            user_id="u",
            user_email="u@x.com",
            success=False,
            requires_review=False,
            error_message="Connection refused",
        )

        item = log_search._audit_to_activity(row)

        assert item.status == "error"
        assert item.title == "MCP server create failed"
        assert "Connection refused" in item.description

    def test_requires_review_is_warning(self):
        """A row flagged for review outranks the default success status."""
        row = AuditTrail(id="3", timestamp=BASE_TIME, action="update", resource_type="tool", user_id="u", success=True, requires_review=True)

        item = log_search._audit_to_activity(row)

        assert item.status == "warning"

    def test_read_action_is_info(self):
        """Read and execute actions are informational, not successes."""
        row = AuditTrail(id="4", timestamp=BASE_TIME, action="read", resource_type="tool", user_id="u", success=True, requires_review=False)

        item = log_search._audit_to_activity(row)

        assert item.status == "info"
        assert item.title == "Tool accessed"

    def test_missing_optional_fields_become_empty_strings(self):
        """Contract fields are never null even when source columns are missing."""
        row = AuditTrail(id="5", timestamp=BASE_TIME, action="delete", resource_type="tool", user_id="u", success=True, requires_review=False)

        item = log_search._audit_to_activity(row)

        assert item.resource_name == ""
        assert item.correlation_id == ""
        assert item.description == "Tool was deleted by u."


class TestSecurityMapper:
    """_security_to_activity derives status from severity."""

    @pytest.mark.parametrize(
        "severity,expected",
        [("CRITICAL", "error"), ("HIGH", "error"), ("MEDIUM", "warning"), ("LOW", "info"), ("bogus", "info"), (None, "info")],
    )
    def test_severity_maps_to_status(self, severity, expected):
        """Each severity level maps to its contract status, unknown values to info."""
        row = SecurityEvent(id="1", timestamp=BASE_TIME, event_type="failed_login", severity=severity, category="auth", client_ip="10.0.0.1", description="Something happened.")

        assert log_search._security_to_activity(row).status == expected

    def test_actor_falls_back_to_system(self):
        """An event with no attributed user is reported as a system actor."""
        row = SecurityEvent(id="2", timestamp=BASE_TIME, event_type="rate_limit_exceeded", severity="LOW", category="abuse", client_ip="10.0.0.1", description="Rate limit exceeded.")

        item = log_search._security_to_activity(row)

        assert item.actor == "system"
        assert item.resource_name == ""
        assert item.title == "Rate limit exceeded"

    def test_naive_timestamp_gets_utc(self):
        """Naive timestamps from SQLite are pinned to UTC for the ISO 8601 contract."""
        row = SecurityEvent(id="3", timestamp=datetime(2025, 1, 1, 12, 0, 0), event_type="x", severity="LOW", category="auth", client_ip="10.0.0.1", description="d")

        assert log_search._security_to_activity(row).timestamp.tzinfo == timezone.utc
