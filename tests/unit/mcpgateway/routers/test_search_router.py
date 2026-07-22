# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/routers/test_search_router.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for the versioned unified search router (``GET /v1/search``).

Covers the feature-request acceptance criteria: route mounted at the versioned
path, unauthenticated rejection, invalid entity_types (400), ``users`` protection,
``team_id`` scoping, ``limit``/``limit_per_type``, and response-shape parity with
``/admin/search``.
"""

# Standard
from unittest.mock import AsyncMock, MagicMock

# Third-Party
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import get_db
from mcpgateway.middleware.rbac import get_current_user_with_permissions
from mcpgateway.routers.search import router as search_router, unified_search

USER = {"email": "user@example.com"}


@pytest.fixture
def mock_db():
    """A mock SQLAlchemy session (never actually queried — entity searches are patched)."""
    return MagicMock(spec=Session)


@pytest.fixture
def patched_search(monkeypatch):
    """Patch every ``admin_search_*`` the core delegates to, plus team/permission helpers.

    Returns the map of entity name -> AsyncMock so tests can assert on the
    arguments each per-entity search was called with.
    """
    mocks = {
        "servers": AsyncMock(return_value={"servers": [{"id": "srv-1", "name": "Server 1"}], "count": 1}),
        "gateways": AsyncMock(return_value={"gateways": [], "count": 0}),
        "tools": AsyncMock(return_value={"tools": [{"id": "tool-1", "name": "Tool 1"}], "count": 1}),
        "resources": AsyncMock(return_value={"resources": [], "count": 0}),
        "prompts": AsyncMock(return_value={"prompts": [], "count": 0}),
        "a2a_agents": AsyncMock(return_value={"agents": [], "count": 0}),
        "teams": AsyncMock(return_value={"teams": [], "count": 0}),
        "users": AsyncMock(return_value={"users": [{"id": "user-1"}], "count": 1}),
        "roots": AsyncMock(return_value={"roots": [], "count": 0}),
    }
    for name, mock in mocks.items():
        monkeypatch.setattr(f"mcpgateway.admin.admin_search_{name}", mock)
    # Deterministic team scope and user-management permission (grant by default).
    monkeypatch.setattr("mcpgateway.admin._get_user_team_ids", AsyncMock(return_value=[]))
    monkeypatch.setattr("mcpgateway.admin._has_permission", AsyncMock(return_value=True))
    return mocks


# ---------------------------------------------------------------------------
# Route wiring
# ---------------------------------------------------------------------------


def test_search_route_mounted_on_v1_independent_of_admin_api():
    """/v1/search is exposed as an always-on route, even when the admin API is disabled.

    This is the whole point of the endpoint: client-facing search must not
    depend on the admin dashboard being mounted. The default test config runs
    with MCPGATEWAY_ADMIN_API_ENABLED=False, so /v1/admin/search is absent here
    while /v1/search is still present.
    """
    # First-Party
    from mcpgateway.config import settings
    from mcpgateway.main import app

    paths = app.openapi().get("paths", {})
    assert "/v1/search" in paths
    assert "get" in paths["/v1/search"]
    # When the admin API is enabled, the legacy /admin/search route coexists as
    # the fallback during UI migration; when disabled, only /v1/search remains.
    if settings.mcpgateway_admin_api_enabled:
        assert "/v1/admin/search" in paths


# ---------------------------------------------------------------------------
# Deny path: authentication
# ---------------------------------------------------------------------------


def test_unified_search_unauthenticated_returns_401():
    """No auth context -> 401, before any search runs."""
    app = FastAPI()
    app.include_router(search_router)

    async def deny_auth():
        raise HTTPException(status_code=401, detail="Not authenticated")

    app.dependency_overrides[get_current_user_with_permissions] = deny_auth
    app.dependency_overrides[get_db] = lambda: MagicMock(spec=Session)

    client = TestClient(app)
    resp = client.get("/search", params={"q": "core"})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Happy path + response shape parity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_response_shape_matches_admin_search_contract(mock_db, patched_search):
    """Grouped + flattened result carries every key of the /admin/search contract."""
    result = await unified_search(
        q="core",
        tags=None,
        entity_types="servers,tools",
        include_inactive=False,
        limit=8,
        limit_per_type=None,
        gateway_id=None,
        team_id=None,
        db=mock_db,
        user=USER,
    )

    # Top-level contract keys.
    assert set(result) >= {"query", "tags", "entity_types", "limit_per_type", "filters_applied", "results", "groups", "items", "count"}
    assert result["filters_applied"].keys() >= {"q", "tags", "tag_groups"}

    # Grouped shape.
    assert result["entity_types"] == ["servers", "tools"]
    assert [g["entity_type"] for g in result["groups"]] == ["servers", "tools"]
    for group in result["groups"]:
        assert group["count"] == len(group["items"])

    # Flattened shape: every item is tagged with its entity_type and count matches.
    assert result["count"] == len(result["items"])
    assert {item["entity_type"] for item in result["items"]} == {"servers", "tools"}


@pytest.mark.asyncio
async def test_router_delegates_to_core_unchanged(mock_db, patched_search):
    """The router adds nothing of its own: its output equals the shared core's."""
    # First-Party
    from mcpgateway.admin import perform_unified_search

    kwargs = dict(
        q="core",
        tags=None,
        entity_types="servers,tools",
        include_inactive=False,
        limit=8,
        limit_per_type=None,
        gateway_id=None,
        team_id=None,
        db=mock_db,
        user=USER,
    )
    via_router = await unified_search(**kwargs)
    via_core = await perform_unified_search(**kwargs)
    assert via_router == via_core


@pytest.mark.asyncio
async def test_authenticated_http_request_returns_200_grouped(mock_db, patched_search):
    """End-to-end through the router: authenticated GET /search -> 200 grouped payload."""
    app = FastAPI()
    app.include_router(search_router)
    app.dependency_overrides[get_current_user_with_permissions] = lambda: USER
    app.dependency_overrides[get_db] = lambda: mock_db

    client = TestClient(app)
    resp = client.get("/search", params={"q": "core", "entity_types": "tools"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["entity_types"] == ["tools"]
    assert body["results"]["tools"][0]["id"] == "tool-1"


# ---------------------------------------------------------------------------
# Restricted entity types: users
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_users_dropped_when_not_permitted(mock_db, patched_search, monkeypatch):
    """Without user-management permission, users are silently dropped (no leak)."""
    monkeypatch.setattr("mcpgateway.admin._has_permission", AsyncMock(return_value=False))

    result = await unified_search(
        q="alice",
        tags=None,
        entity_types="tools,users",
        include_inactive=False,
        limit=8,
        limit_per_type=None,
        gateway_id=None,
        team_id=None,
        db=mock_db,
        user=USER,
    )

    assert result["entity_types"] == ["tools"]
    assert "users" not in result["results"]
    patched_search["users"].assert_not_called()


@pytest.mark.asyncio
async def test_users_only_request_forbidden_when_not_permitted(mock_db, patched_search, monkeypatch):
    """Explicitly requesting only users without permission -> 403 (matches /admin/search)."""
    monkeypatch.setattr("mcpgateway.admin._has_permission", AsyncMock(return_value=False))

    with pytest.raises(HTTPException) as excinfo:
        await unified_search(
            q="alice",
            tags=None,
            entity_types="users",
            include_inactive=False,
            limit=8,
            limit_per_type=None,
            gateway_id=None,
            team_id=None,
            db=mock_db,
            user=USER,
        )
    assert excinfo.value.status_code == 403


# ---------------------------------------------------------------------------
# Invalid input
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_entity_types_returns_400(mock_db, patched_search):
    """entity_types containing only unsupported values -> 400."""
    with pytest.raises(HTTPException) as excinfo:
        await unified_search(
            q="core",
            tags=None,
            entity_types="bogus,nonsense",
            include_inactive=False,
            limit=8,
            limit_per_type=None,
            gateway_id=None,
            team_id=None,
            db=mock_db,
            user=USER,
        )
    assert excinfo.value.status_code == 400


# ---------------------------------------------------------------------------
# team_id scoping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_team_id_forwarded_to_entity_searches(mock_db, patched_search):
    """A validated team_id is forwarded to per-entity searches for server-side scoping."""
    valid_team_id = "0123456789abcdef0123456789abcdef"  # valid 32-char hex UUID  # pragma: allowlist secret
    await unified_search(
        q="core",
        tags=None,
        entity_types="tools",
        include_inactive=False,
        limit=8,
        limit_per_type=None,
        gateway_id=None,
        team_id=valid_team_id,
        db=mock_db,
        user=USER,
    )
    assert patched_search["tools"].await_args.kwargs["team_id"] == valid_team_id


# ---------------------------------------------------------------------------
# limit / limit_per_type
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_limit_per_type_overrides_limit(mock_db, patched_search):
    """limit_per_type takes precedence over limit and is what per-entity searches receive."""
    result = await unified_search(
        q="core",
        tags=None,
        entity_types="tools",
        include_inactive=False,
        limit=5,
        limit_per_type=3,
        gateway_id=None,
        team_id=None,
        db=mock_db,
        user=USER,
    )
    assert result["limit_per_type"] == 3
    assert patched_search["tools"].await_args.kwargs["limit"] == 3


@pytest.mark.asyncio
async def test_limit_used_when_no_limit_per_type(mock_db, patched_search):
    """Without limit_per_type, the plain limit is forwarded."""
    result = await unified_search(
        q="core",
        tags=None,
        entity_types="tools",
        include_inactive=False,
        limit=5,
        limit_per_type=None,
        gateway_id=None,
        team_id=None,
        db=mock_db,
        user=USER,
    )
    assert result["limit_per_type"] == 5
    assert patched_search["tools"].await_args.kwargs["limit"] == 5
