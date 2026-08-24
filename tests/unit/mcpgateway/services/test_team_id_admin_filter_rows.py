# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_team_id_admin_filter_rows.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Row-level contract for ``?team_id=`` on every BaseService list endpoint.

Companion to test_team_id_admin_filter.py, which asserts on compiled SQL. String
assertions cannot distinguish ``or_(team_match, public)`` from
``and_(team_match, public)`` -- both render the same substrings while behaving
oppositely. That is precisely how PR #5929 slipped past the guard test added in
PR #4773. These tests seed rows and assert on the IDs actually returned, so a
flipped connective fails loudly.

Contract under test (issue #5496, semantics per issue #4732 / PR #4773):
    * team-scoped rows of the requested team   -> returned
    * team-scoped rows of *other* teams        -> excluded
    * globally-public rows of other teams      -> returned
    * globally-public rows with no team        -> returned
    * caller's own private rows in that team   -> returned only when the caller has an
                                                  identity (never on the anonymous bypass)
    * another owner's private rows in that team -> excluded
"""

# Future
from __future__ import annotations

# Standard
from datetime import datetime, timezone
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock
import uuid

# Third-Party
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# First-Party
from mcpgateway.db import A2AAgent as DbA2AAgent
from mcpgateway.db import Base, EmailTeam
from mcpgateway.db import Gateway as DbGateway
from mcpgateway.db import Prompt as DbPrompt
from mcpgateway.db import Resource as DbResource
from mcpgateway.db import Server as DbServer
from mcpgateway.db import Tool as DbTool
from mcpgateway.services.a2a_service import A2AAgentService
from mcpgateway.services.gateway_service import GatewayService
from mcpgateway.services.prompt_service import PromptService
from mcpgateway.services.resource_service import ResourceService
from mcpgateway.services.server_service import ServerService
from mcpgateway.services.tool_service import ToolService

OWNER = "admin@example.com"
OTHER_OWNER = "someone-else@example.com"

# Row shapes seeded for every service: (label, team key or None, visibility, owner, expectation).
# "always"     -> returned for both caller shapes
# "never"      -> returned for neither
# "owner_only" -> returned only when the caller has an identity to owner-match against;
#                 the anonymous bypass passes no owner_email, so private rows stay hidden.
ROW_SHAPES = [
    ("alpha_team", "alpha", "team", OWNER, "always"),
    ("beta_team", "beta", "team", OWNER, "never"),
    ("beta_public", "beta", "public", OWNER, "always"),
    ("noteam_public", None, "public", OWNER, "always"),
    ("alpha_private_own", "alpha", "private", OWNER, "owner_only"),
    ("alpha_private_other", "alpha", "private", OTHER_OWNER, "never"),
]


def _make_row(model, tag: str, team_id: str | None, visibility: str, owner_email: str = OWNER):
    """Build a minimal persistable row for the given model.

    Args:
        model: SQLAlchemy model class to instantiate.
        tag: Unique-per-row suffix used for names/URIs.
        team_id: Owning team, or None for a team-less row.
        visibility: One of private/team/public.
        owner_email: Row owner, used to exercise owner-matching on private rows.

    Returns:
        An unsaved model instance.

    Raises:
        AssertionError: If the model is not one of the six list-endpoint models.
    """
    now = datetime.now(timezone.utc)
    common: Dict[str, Any] = {
        "id": uuid.uuid4().hex,
        "team_id": team_id,
        "visibility": visibility,
        "owner_email": owner_email,
        "created_at": now,
        "updated_at": now,
    }
    if model is DbGateway:
        return model(name=f"gw_{tag}", slug=f"gw-{tag}", url=f"https://example.invalid/{tag}", transport="SSE", capabilities={}, enabled=True, reachable=True, **common)
    if model is DbTool:
        return model(original_name=f"tool_{tag}", custom_name=f"tool_{tag}", url=f"https://example.invalid/{tag}", integration_type="REST", request_type="GET", input_schema={}, enabled=True, **common)
    if model is DbServer:
        return model(name=f"srv_{tag}", description="d", enabled=True, **common)
    if model is DbResource:
        return model(uri=f"rows://{tag}", name=f"res_{tag}", description="d", text_content="x", mime_type="text/plain", size=1, enabled=True, **common)
    if model is DbPrompt:
        return model(
            name=f"pr_{tag}",
            original_name=f"pr_{tag}",
            custom_name=f"pr_{tag}",
            custom_name_slug=f"pr-{tag}",
            description="d",
            template="hello {{x}}",
            argument_schema={"type": "object", "properties": {}},
            enabled=True,
            **common,
        )
    if model is DbA2AAgent:
        return model(name=f"ag_{tag}", slug=f"ag-{tag}", endpoint_url=f"https://example.invalid/{tag}", agent_type="generic", enabled=True, **common)
    raise AssertionError(f"unhandled model {model!r}")


LIST_ENDPOINTS = [
    ("gateways", GatewayService, "list_gateways", DbGateway),
    ("tools", ToolService, "list_tools", DbTool),
    ("servers", ServerService, "list_servers", DbServer),
    ("resources", ResourceService, "list_resources", DbResource),
    ("prompts", PromptService, "list_prompts", DbPrompt),
    ("a2a_agents", A2AAgentService, "list_agents", DbA2AAgent),
]


@pytest.fixture()
def rows_db():
    """Isolated session configured like production's ``SessionLocal``.

    ``expire_on_commit=False`` matters here: the services call ``db.commit()``
    before converting rows, and the converters read ``row.__dict__``. With the
    default ``expire_on_commit=True`` that dict is empty post-commit and every
    row fails conversion, which would mask the filtering behaviour under test.

    Yields:
        A SQLAlchemy session bound to a fresh in-memory database.
    """
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def _no_registry_cache(monkeypatch):
    """Force a cache miss so every assertion exercises the query path.

    Args:
        monkeypatch: pytest monkeypatch fixture.
    """
    cache = MagicMock()
    cache.get = AsyncMock(return_value=None)
    cache.set = AsyncMock()
    cache.hash_filters = MagicMock(return_value="miss")
    for module in ("gateway_service", "tool_service", "server_service", "resource_service", "prompt_service", "a2a_service"):
        monkeypatch.setattr(f"mcpgateway.services.{module}._get_registry_cache", lambda: cache, raising=False)


def _returned_ids(result) -> List[str]:
    """Normalise a list_* return value into the set of row ids.

    Args:
        result: Return value of a service list method.

    Returns:
        List of row id strings.
    """
    rows = result[0] if isinstance(result, tuple) else result.get("data", [])
    return [getattr(r, "id", None) or r.get("id") for r in rows]


@pytest.mark.asyncio
@pytest.mark.parametrize("label, service_cls, method, model", LIST_ENDPOINTS, ids=[e[0] for e in LIST_ENDPOINTS])
@pytest.mark.parametrize("user_email", [OWNER, None], ids=["db_admin", "anonymous"])
async def test_team_id_returns_own_team_plus_globally_public(label, service_cls, method, model, user_email, rows_db, monkeypatch, _no_registry_cache):
    """team_id narrows to the team but never hides globally-public rows.

    Args:
        label: Collection name, used for row tagging.
        service_cls: Service class under test.
        method: Name of the list method on that service.
        model: SQLAlchemy model backing the collection.
        user_email: Caller identity (DB admin, or anonymous bypass).
        rows_db: Isolated session fixture.
        monkeypatch: pytest monkeypatch fixture.
        _no_registry_cache: Forces cache misses.
    """
    monkeypatch.setattr("mcpgateway.services.base_service.is_user_admin", lambda *a, **kw: True)

    run = uuid.uuid4().hex[:8]
    teams = {}
    for key in ("alpha", "beta"):
        team = EmailTeam(id=uuid.uuid4().hex, name=f"{key}-{run}", slug=f"{key}-{run}", created_by=OWNER, is_personal=False, visibility="private", is_active=True)
        rows_db.add(team)
        teams[key] = team.id

    expected, excluded = set(), set()
    for shape, team_key, visibility, owner, expectation in ROW_SHAPES:
        row = _make_row(model, f"{label}_{shape}_{run}", teams.get(team_key) if team_key else None, visibility, owner)
        rows_db.add(row)
        should_return = expectation == "always" or (expectation == "owner_only" and user_email == owner)
        (expected if should_return else excluded).add(row.id)
    rows_db.commit()

    service = service_cls()
    try:
        result = await getattr(service, method)(rows_db, user_email=user_email, token_teams=None, team_id=teams["alpha"])
    finally:
        client = getattr(service, "_http_client", None)
        if client is not None:
            await client.aclose()

    returned = set(_returned_ids(result))

    missing = expected - returned
    assert not missing, f"{label}: rows that should be visible were filtered out (or_ flipped to and_?): {sorted(missing)}"

    leaked = excluded & returned
    assert not leaked, f"{label}: rows that must stay hidden were returned: {sorted(leaked)}"
