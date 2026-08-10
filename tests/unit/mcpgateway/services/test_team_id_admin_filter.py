# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_team_id_admin_filter.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

team_id filtering for admin callers across every BaseService list endpoint.

All six services share BaseService._apply_access_control, whose admin bypass
branches used to return before team_id was applied, so ?team_id= was ignored
for admin callers. These cases assert both halves of the contract: rows are
narrowed to the requested team, and the globally-public condition survives.
"""

# Standard
from unittest.mock import AsyncMock, MagicMock

# Third-Party
import pytest

# First-Party
from mcpgateway.services.a2a_service import A2AAgentService
from mcpgateway.services.gateway_service import GatewayService
from mcpgateway.services.prompt_service import PromptService
from mcpgateway.services.resource_service import ResourceService
from mcpgateway.services.server_service import ServerService
from mcpgateway.services.tool_service import ToolService

TEAM_ID = "team-1"

# (module under mcpgateway.services, service class, list method, SQL table name)
LIST_ENDPOINTS = [
    ("gateway_service", GatewayService, "list_gateways", "gateways"),
    ("tool_service", ToolService, "list_tools", "tools"),
    ("resource_service", ResourceService, "list_resources", "resources"),
    ("prompt_service", PromptService, "list_prompts", "prompts"),
    ("server_service", ServerService, "list_servers", "servers"),
    ("a2a_service", A2AAgentService, "list_agents", "a2a_agents"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("module, service_cls, method, table", LIST_ENDPOINTS, ids=[e[3] for e in LIST_ENDPOINTS])
@pytest.mark.parametrize("user_email", ["admin@test.com", None], ids=["db_admin", "anonymous"])
async def test_admin_team_id_scopes_to_team_and_keeps_public(module, service_cls, method, table, user_email, monkeypatch):
    """Admin team_id filtering hides other teams' team-scoped rows, keeps public ones.

    Covers both bypass shapes: a DB-resolved admin, and the anonymous bypass
    where no user context is present.
    """
    cache = MagicMock()
    cache.get = AsyncMock(return_value=None)
    cache.set = AsyncMock()
    cache.hash_filters = MagicMock(return_value="h")
    monkeypatch.setattr(f"mcpgateway.services.{module}._get_registry_cache", lambda: cache)

    paginate = AsyncMock(return_value=([], None))
    monkeypatch.setattr(f"mcpgateway.services.{module}.unified_paginate", paginate)
    monkeypatch.setattr("mcpgateway.services.base_service.is_user_admin", MagicMock(return_value=True))

    service = service_cls()
    try:
        await getattr(service, method)(
            MagicMock(),
            user_email=user_email,
            token_teams=None,
            team_id=TEAM_ID,
        )
    finally:
        client = getattr(service, "_http_client", None)
        if client is not None:
            await client.aclose()

    compiled = str(paginate.await_args.kwargs["query"].compile(compile_kwargs={"literal_binds": True}))
    # Rows are narrowed to the requested team ...
    assert f"{table}.team_id = '{TEAM_ID}'" in compiled
    # ... but globally-public rows from any team are still ORed in.
    assert f"{table}.visibility = 'public'" in compiled
