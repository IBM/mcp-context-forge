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

    monkeypatch.setattr("mcpgateway.plugins.get_plugin_manager", _no_plugin_manager)


@pytest.fixture
def grant_permissions(monkeypatch: pytest.MonkeyPatch):
    """Return a helper that grants or denies specific permissions by name."""

    def _configure(denied=()):
        async def _check(self, **kwargs):  # type: ignore[no-self-use]
            _configure.calls.append(kwargs)
            return kwargs.get("permission") not in denied

        monkeypatch.setattr(rbac_module.PermissionService, "check_permission", _check)

    _configure.calls = []
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


async def call_feed(db, *, user_email="user@example.com", limit=50, since=None, token_scopes=None):
    """Invoke the activity feed handler directly.

    Args:
        db: Database session.
        user_email: Email placed in the authenticated user context.
        limit: Maximum merged items to request.
        since: Strictly-after timestamp filter.
        token_scopes: Layer 1 token scopes for the user context, or None for unscoped.

    Returns:
        ActivityListResponse: The handler's response.
    """
    return await log_search.get_activity_feed(
        request=MagicMock(),
        limit=limit,
        since=since,
        user={"email": user_email, "db": db, "token_scopes": token_scopes},
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
    """A team-scoped token sees its own team's rows plus NULL-team rows it authored."""
    grant_permissions()
    scope("user@x.com", ["team-a"])
    make_audit(db_session, offset_seconds=10, team_id="team-a", resource_name="a-row")
    make_audit(db_session, offset_seconds=20, team_id="team-b", resource_name="b-row")
    make_audit(db_session, offset_seconds=30, team_id=None, user_email="user@x.com", resource_name="own-teamless")
    make_audit(db_session, offset_seconds=40, team_id=None, user_email="other@x.com", resource_name="foreign-teamless")

    response = await call_feed(db_session, user_email="user@x.com")

    names = {i.resource_name for i in response.items}
    assert names == {"a-row", "own-teamless"}


@pytest.mark.asyncio
async def test_public_only_token_sees_only_own_null_team_rows(db_session, grant_permissions, scope):
    """NULL team_id means "no team was recorded", not "public": only the actor sees it."""
    grant_permissions()
    scope("user@x.com", [])
    make_audit(db_session, offset_seconds=10, team_id="team-a", resource_name="a-row")
    make_audit(db_session, offset_seconds=20, team_id=None, user_email="user@x.com", resource_name="own-teamless")
    make_audit(db_session, offset_seconds=30, team_id=None, user_email="other@x.com", resource_name="foreign-teamless")

    response = await call_feed(db_session, user_email="user@x.com")

    assert [i.resource_name for i in response.items] == ["own-teamless"]


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


@pytest.mark.asyncio
async def test_token_without_security_scope_gets_audit_only(db_session, grant_permissions, scope):
    """Layer 1: a token scoped to audit:read only drops security rows even when RBAC grants all."""
    grant_permissions()
    scope("admin@example.com", None)
    make_audit(db_session, offset_seconds=10)
    make_security(db_session, offset_seconds=20)

    response = await call_feed(db_session, token_scopes=["audit:read"])

    assert [i.source for i in response.items] == ["audit"]


@pytest.mark.asyncio
async def test_token_with_security_scope_keeps_both_sources(db_session, grant_permissions, scope):
    """A token carrying both scopes still sees the merged feed."""
    grant_permissions()
    scope("admin@example.com", None)
    make_audit(db_session, offset_seconds=10)
    make_security(db_session, offset_seconds=20)

    response = await call_feed(db_session, token_scopes=["audit:read", "security:read"])

    assert {i.source for i in response.items} == {"audit", "security"}


@pytest.mark.asyncio
async def test_security_read_is_checked_across_all_teams(db_session, grant_permissions, scope):
    """The additive security:read check aggregates across teams, matching the decorator."""
    grant_permissions()
    scope("user@x.com", ["team-a"])
    make_audit(db_session, offset_seconds=10, team_id="team-a")

    await call_feed(db_session, user_email="user@x.com")

    security_calls = [c for c in grant_permissions.calls if c.get("permission") == "security:read"]
    assert len(security_calls) == 1
    assert security_calls[0]["check_any_team"] is True


@pytest.mark.asyncio
async def test_missing_audit_read_is_rejected(db_session, grant_permissions, scope):
    """Entry stays gated: without audit:read the request is denied, not narrowed."""
    grant_permissions(denied={"audit:read"})
    scope("user@x.com", ["team-a"])

    with pytest.raises(HTTPException) as exc_info:
        await call_feed(db_session, user_email="user@x.com")

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_unauthenticated_request_is_rejected(db_session, grant_permissions, scope):
    """An absent user context is a 401 before any query runs."""
    grant_permissions()
    scope("user@x.com", ["team-a"])

    with pytest.raises(HTTPException) as exc_info:
        await log_search.get_activity_feed(request=MagicMock(), limit=50, since=None, user=None, db=db_session)

    assert exc_info.value.status_code == 401


class TestAuditMapper:
    """_audit_to_activity renders server-owned title, description and status."""

    def test_successful_create(self):
        """A successful create against the (inert, compat-only) mcp_server key still resolves."""
        row = AuditTrail(id="1", timestamp=BASE_TIME, action="create", resource_type="mcp_server", resource_name="github", user_id="u", user_email="u@x.com", success=True, requires_review=False)

        item = log_search._audit_to_activity(row)

        assert item.status == "success"
        assert item.title == "MCP server created"
        assert item.description == "MCP server 'github' was created by u@x.com."
        assert item.id == "audit:1"

    def test_gateway_create_is_registered(self):
        """gateway_service.py's real write shape: resource_type='gateway', action='create_gateway'."""
        row = AuditTrail(id="1b", timestamp=BASE_TIME, action="create_gateway", resource_type="gateway", resource_name="github", user_id="u", user_email="u@x.com", success=True, requires_review=False)

        item = log_search._audit_to_activity(row)

        assert item.status == "success"
        assert item.title == "MCP server registered"
        assert item.description == "MCP server 'github' was registered by u@x.com."

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
        assert item.title == "Failed to create MCP server"
        assert "Connection refused" in item.description

    def test_failed_gateway_create_uses_infinitive_not_mangled_composite(self):
        """A failed create_gateway must not render as 'MCP server create gateway failed'."""
        row = AuditTrail(id="2b", timestamp=BASE_TIME, action="create_gateway", resource_type="gateway", resource_name="github", user_id="u", success=False, requires_review=False)

        item = log_search._audit_to_activity(row)

        assert item.status == "error"
        assert item.title == "Failed to register MCP server"
        assert "gateway" not in item.title.lower()

    def test_requires_review_is_warning(self):
        """A row flagged for review outranks the default success status."""
        row = AuditTrail(id="3", timestamp=BASE_TIME, action="update", resource_type="tool", user_id="u", success=True, requires_review=True)

        item = log_search._audit_to_activity(row)

        assert item.status == "warning"

    def test_requires_review_outranks_state_transition(self):
        """requires_review must win even over an offline transition."""
        row = AuditTrail(
            id="3b",
            timestamp=BASE_TIME,
            action="set_gateway_state",
            resource_type="gateway",
            user_id="system",
            success=True,
            requires_review=True,
            new_values={"enabled": True, "reachable": False},
        )

        assert log_search._audit_to_activity(row).status == "warning"

    def test_read_action_is_info(self):
        """Read and execute actions are informational, not successes."""
        row = AuditTrail(id="4", timestamp=BASE_TIME, action="read", resource_type="tool", user_id="u", success=True, requires_review=False)

        item = log_search._audit_to_activity(row)

        assert item.status == "info"
        assert item.title == "Tool accessed"

    def test_view_prompt_details_is_info(self):
        """view_prompt_details (a real writer action) resolves via the read family, not literal string match."""
        row = AuditTrail(id="4b", timestamp=BASE_TIME, action="view_prompt_details", resource_type="prompt", user_id="u", success=True, requires_review=False)

        item = log_search._audit_to_activity(row)

        assert item.status == "info"
        assert item.title == "Prompt viewed"

    def test_missing_optional_fields_become_empty_strings(self):
        """Contract fields are never null even when source columns are missing."""
        row = AuditTrail(id="5", timestamp=BASE_TIME, action="delete", resource_type="tool", user_id="u", success=True, requires_review=False)

        item = log_search._audit_to_activity(row)

        assert item.resource_name == ""
        assert item.correlation_id == ""
        assert item.description == "Tool was deleted by u."

    def test_unmapped_action_is_humanised(self):
        """A genuinely unmapped action (no recognised leading verb token) loses its underscores."""
        row = AuditTrail(id="6", timestamp=BASE_TIME, action="something_totally_unmapped", resource_type="tool", user_id="u", success=True, requires_review=False)

        assert log_search._audit_to_activity(row).title == "Tool something totally unmapped"

        row.success = False

        assert log_search._audit_to_activity(row).title == "Tool something totally unmapped failed"

    def test_bulk_create_tools_resolves_via_token_scan(self):
        """bulk_create_tools (a real writer action) resolves through the verb, not the mangled fallback."""
        row = AuditTrail(id="6b", timestamp=BASE_TIME, action="bulk_create_tools", resource_type="tool", user_id="u", success=True, requires_review=False)

        assert log_search._audit_to_activity(row).title == "Tool bulk created"

    def test_action_lookup_is_case_insensitive(self):
        """log_action's own docstring documents actions as uppercase; the resolver must not depend on case."""
        row = AuditTrail(id="6c", timestamp=BASE_TIME, action="CREATE_GATEWAY", resource_type="gateway", user_id="u", success=True, requires_review=False)

        assert log_search._audit_to_activity(row).title == "MCP server registered"

    def test_writer_description_is_preferred_over_synthesised_text(self):
        """log_audit(description=...) callers (e.g. plugin marketplace views) get their own prose verbatim."""
        row = AuditTrail(
            id="7",
            timestamp=BASE_TIME,
            action="view",
            resource_type="plugin",
            resource_id="my-plugin",
            user_id="u",
            success=True,
            requires_review=False,
            context={"description": "Viewed plugin 'my-plugin' details in marketplace"},
        )

        item = log_search._audit_to_activity(row)

        assert item.description == "Viewed plugin 'my-plugin' details in marketplace"

    def test_no_writer_description_falls_back_to_synthesis(self):
        """Rows without a writer-authored description keep the synthesised sentence."""
        row = AuditTrail(id="7b", timestamp=BASE_TIME, action="view", resource_type="plugin", resource_id="my-plugin", user_id="u", success=True, requires_review=False)

        item = log_search._audit_to_activity(row)

        assert item.description == "Plugin 'my-plugin' was viewed by u."


class TestStateTransitions:
    """set_*_state rows render from new_values, not the literal action string."""

    def test_gateway_went_offline_is_warning(self):
        row = AuditTrail(
            id="s1",
            timestamp=BASE_TIME,
            action="set_gateway_state",
            resource_type="gateway",
            resource_name="my-server",
            user_id="system",
            success=True,
            requires_review=False,
            new_values={"enabled": True, "reachable": False},
            context={"action": "activate", "only_update_reachable": True},
        )

        item = log_search._audit_to_activity(row)

        assert item.status == "warning"
        assert item.title == "MCP server went offline"
        assert item.description == "MCP server 'my-server' went offline."
        assert " by " not in item.description

    def test_gateway_came_online_is_success(self):
        row = AuditTrail(
            id="s2",
            timestamp=BASE_TIME,
            action="set_gateway_state",
            resource_type="gateway",
            resource_name="my-server",
            user_id="system",
            success=True,
            requires_review=False,
            new_values={"enabled": True, "reachable": True},
        )

        item = log_search._audit_to_activity(row)

        assert item.status == "success"
        assert item.title == "MCP server came online"

    def test_gateway_disabled_by_admin_is_success(self):
        row = AuditTrail(
            id="s3",
            timestamp=BASE_TIME,
            action="set_gateway_state",
            resource_type="gateway",
            resource_name="my-server",
            user_id="u",
            user_email="admin@x.com",
            success=True,
            requires_review=False,
            new_values={"enabled": False, "reachable": False},
        )

        item = log_search._audit_to_activity(row)

        assert item.status == "success"
        assert item.title == "MCP server disabled"
        assert "by admin@x.com" in item.description

    def test_tool_state_also_supports_reachability(self):
        """set_tool_state carries 'reachable' too, so a tool marked unreachable also renders as offline."""
        row = AuditTrail(
            id="s4",
            timestamp=BASE_TIME,
            action="set_tool_state",
            resource_type="tool",
            resource_name="my-tool",
            user_id="system",
            success=True,
            requires_review=False,
            new_values={"enabled": True, "reachable": False},
        )

        item = log_search._audit_to_activity(row)

        assert item.status == "warning"
        assert item.title == "Tool went offline"

    def test_prompt_state_has_no_reachable_key(self):
        """set_prompt_state only ever carries 'enabled'; it must not require 'reachable' to render."""
        row = AuditTrail(
            id="s5",
            timestamp=BASE_TIME,
            action="set_prompt_state",
            resource_type="prompt",
            resource_name="my-prompt",
            user_id="u",
            user_email="admin@x.com",
            success=True,
            requires_review=False,
            new_values={"enabled": True},
        )

        item = log_search._audit_to_activity(row)

        assert item.status == "success"
        assert item.title == "Prompt enabled"

    def test_missing_new_values_falls_through_without_raising(self):
        row = AuditTrail(id="s6", timestamp=BASE_TIME, action="set_gateway_state", resource_type="gateway", user_id="system", success=True, requires_review=False, new_values=None)

        item = log_search._audit_to_activity(row)

        assert item.status == "success"  # falls through to the state-action fallback override
        assert item.title == "MCP server state updated"

    def test_empty_new_values_falls_through_without_raising(self):
        row = AuditTrail(id="s7", timestamp=BASE_TIME, action="set_gateway_state", resource_type="gateway", user_id="system", success=True, requires_review=False, new_values={})

        item = log_search._audit_to_activity(row)

        assert item.status == "success"

    def test_failed_state_write_is_still_error(self):
        """success=False must win over the transition branch."""
        row = AuditTrail(
            id="s8",
            timestamp=BASE_TIME,
            action="set_gateway_state",
            resource_type="gateway",
            resource_name="my-server",
            user_id="system",
            success=False,
            requires_review=False,
            new_values={"enabled": True, "reachable": False},
        )

        item = log_search._audit_to_activity(row)

        assert item.status == "error"
        assert item.title == "Failed to update MCP server state"


# Every (resource_type, action) pair actually written by AuditTrailService.log_action /
# log_audit callers as of this writing. Hardcoded rather than grep-derived on purpose: a
# new writer action should fail this table by *absence*, forcing a conscious verb
# decision rather than silently falling through to the mangled default. Sourced from
# gateway_service.py, tool_service.py, prompt_service.py, resource_service.py,
# server_service.py and admin.py's log_audit call sites.
REAL_AUDIT_ACTIONS = [
    ("gateway", "create_gateway"),
    ("gateway", "update_gateway"),
    ("gateway", "delete_gateway"),
    ("gateway", "set_gateway_state"),
    ("tool", "create_tool"),
    ("tool", "update_tool"),
    ("tool", "delete_tool"),
    ("tool", "set_tool_state"),
    ("tool", "bulk_create_tools"),
    ("tool", "bulk_update_tools"),
    ("prompt", "create_prompt"),
    ("prompt", "update_prompt"),
    ("prompt", "delete_prompt"),
    ("prompt", "set_prompt_state"),
    ("prompt", "bulk_create_prompts"),
    ("prompt", "bulk_update_prompts"),
    ("prompt", "view_prompt"),
    ("prompt", "view_prompt_details"),
    ("resource", "create_resource"),
    ("resource", "update_resource"),
    ("resource", "delete_resource"),
    ("resource", "set_resource_state"),
    ("resource", "bulk_create_resources"),
    ("resource", "bulk_update_resources"),
    ("server", "create_server"),
    ("server", "update_server"),
    ("server", "delete_server"),
    ("server", "activate_server"),
    ("server", "deactivate_server"),
    ("server", "view_server"),
    ("plugin", "view"),
    ("plugin", "view_details"),
]


class TestRealActionInventoryRegressionGuard:
    """The regression guard: every emitted (resource_type, action) pair must render cleanly.

    This is the test that would have caught #6342. TestAuditMapper's original rows used
    resource_type='mcp_server' / action='create' -- values no writer in the codebase
    produces -- so they passed while every real gateway/tool/prompt/resource/server row
    rendered mangled titles like 'Gateway set gateway state'.
    """

    @pytest.mark.parametrize("resource_type,action", REAL_AUDIT_ACTIONS)
    def test_title_has_no_underscore(self, resource_type, action):
        row = AuditTrail(id=f"{resource_type}:{action}", timestamp=BASE_TIME, action=action, resource_type=resource_type, resource_name="x", user_id="u", success=True, requires_review=False)

        title = log_search._audit_to_activity(row).title

        assert "_" not in title, f"title leaked an underscore: {title!r}"

    @pytest.mark.parametrize("resource_type,action", REAL_AUDIT_ACTIONS)
    def test_title_does_not_repeat_the_label(self, resource_type, action):
        """Kills the 'Gateway set gateway state' / 'Prompt view prompt details' shape."""
        row = AuditTrail(id=f"{resource_type}:{action}", timestamp=BASE_TIME, action=action, resource_type=resource_type, resource_name="x", user_id="u", success=True, requires_review=False)

        title = log_search._audit_to_activity(row).title
        label = log_search._RESOURCE_LABELS.get(resource_type) or resource_type

        words = title.lower().split()
        label_words = label.lower().split()
        # The label may legitimately be the first word(s) of the title ("MCP server went
        # offline"); it must not additionally appear again later in the title.
        remainder = words[len(label_words) :] if words[: len(label_words)] == label_words else words
        for w in label_words:
            assert w not in remainder, f"title repeats the resource label: {title!r}"


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
