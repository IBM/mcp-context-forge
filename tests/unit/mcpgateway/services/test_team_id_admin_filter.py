# -*- coding: utf-8 -*-
"""Regression tests for admin team_id filtering on list endpoints.

Companion to the gateway fix in #5929 / issue #5496. For admin callers the
``_apply_access_control`` bypass branches return before ``team_id`` is applied,
so ``GET /tools|/resources|/prompts|/servers|/a2a?team_id=<id>`` used to ignore
the filter and leak items from other teams (issue #6150). Each list method now
applies an exact ``team_id`` filter after access control, exactly as
``list_gateways`` already does.
"""

# Standard
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

# Third-Party
import pytest

# First-Party
from mcpgateway.services.a2a_service import A2AAgentService
from mcpgateway.services.prompt_service import PromptService
from mcpgateway.services.resource_service import ResourceService
from mcpgateway.services.server_service import ServerService
from mcpgateway.services.tool_service import ToolService


# (service factory, module path for patching, list method name, table name)
_CASES = [
    (ToolService, "mcpgateway.services.tool_service", "list_tools", "tools"),
    (ResourceService, "mcpgateway.services.resource_service", "list_resources", "resources"),
    (PromptService, "mcpgateway.services.prompt_service", "list_prompts", "prompts"),
    (ServerService, "mcpgateway.services.server_service", "list_servers", "servers"),
    (A2AAgentService, "mcpgateway.services.a2a_service", "list_agents", "a2a_agents"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("service_cls, module, method_name, table", _CASES, ids=[c[3] for c in _CASES])
async def test_admin_team_id_is_an_exact_filter(service_cls, module, method_name, table, monkeypatch):
    """Admin team_id filtering restricts to the requested team on every list endpoint."""
    db = MagicMock()

    mock_cache = MagicMock()
    mock_cache.get = AsyncMock(return_value=None)
    mock_cache.set = AsyncMock()
    mock_cache.hash_filters = MagicMock(return_value="h")
    monkeypatch.setattr(f"{module}._get_registry_cache", lambda: mock_cache)

    mock_paginate = AsyncMock(return_value=([], None))
    monkeypatch.setattr(f"{module}.unified_paginate", mock_paginate)
    monkeypatch.setattr("mcpgateway.services.base_service.is_user_admin", MagicMock(return_value=True))

    service = service_cls()
    await getattr(service, method_name)(
        db,
        user_email="admin@test.com",
        token_teams=None,
        team_id="team-1",
    )

    query = mock_paginate.await_args.kwargs["query"]
    compiled = str(query.compile(compile_kwargs={"literal_binds": True}))
    assert f"{table}.team_id = 'team-1'" in compiled
