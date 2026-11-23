# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_a2a_service_validation_policy.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests that the A2A agent toggle honours a tool validation refusal.
"""

# Standard
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

# Third-Party
import pytest
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.services.a2a_service import A2AAgentService


@pytest.mark.asyncio
async def test_activating_an_agent_never_enables_a_refused_tool(monkeypatch):
    """The cascading tool update enables the tool only when no validation refusal is stored."""
    service = A2AAgentService()
    service.convert_agent_to_read = MagicMock(return_value=MagicMock())
    agent = SimpleNamespace(id="a1", enabled=False, name="ag", reachable=True, tool_id="t1", tool=SimpleNamespace(name="my-tool", gateway_id="gw1"))
    tool_update_result = MagicMock()
    tool_update_result.rowcount = 1
    db = MagicMock(spec=Session)
    db.execute.side_effect = [MagicMock(scalar_one_or_none=MagicMock(return_value=agent)), tool_update_result]
    monkeypatch.setattr("mcpgateway.services.a2a_service._get_registry_cache", lambda: SimpleNamespace(invalidate_agents=AsyncMock(), invalidate_tools=AsyncMock()))
    monkeypatch.setattr("mcpgateway.services.a2a_service._get_tool_lookup_cache", lambda: SimpleNamespace(invalidate=AsyncMock()))

    await service.set_agent_state(db, "a1", activate=True)

    statement = str(db.execute.call_args_list[1].args[0].compile(compile_kwargs={"literal_binds": True}))
    assert "UPDATE tools" in statement
    assert "CASE WHEN (tools.validation_refusal IS NULL) THEN true ELSE false END" in statement.replace("1", "true").replace("0", "false")
