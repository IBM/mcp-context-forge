# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_a2a_service_test_agent.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Unit tests for A2AAgentService.test_agent.
"""

# Standard
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

# Third-Party
from pydantic import BaseModel, ValidationError
import pytest

# First-Party
from mcpgateway.services.a2a_service import A2AAgentError, A2AAgentNotFoundError, A2AAgentService, DEFAULT_A2A_TEST_MESSAGE


def _service(agent_type="custom", endpoint="http://agent.example.com/api", invoke=None):
    service = A2AAgentService()
    service.get_agent = AsyncMock(return_value=SimpleNamespace(name="Agent", agent_type=agent_type, endpoint_url=endpoint))
    service.invoke_agent = invoke or AsyncMock(return_value={"ok": True})
    return service


@pytest.mark.asyncio
async def test_success_uses_default_message_and_extended_params():
    service = _service()
    outcome = await service.test_agent(MagicMock(), "a1", user_email="u@x.com", token_teams=[])
    assert outcome.status_code == 200
    assert outcome.body["success"] is True
    assert outcome.body["agent_name"] == "Agent"
    assert "test_timestamp" in outcome.body
    params = service.invoke_agent.call_args.args[2]
    assert params["query"] == DEFAULT_A2A_TEST_MESSAGE
    assert params["test"] is True
    assert "admin" not in DEFAULT_A2A_TEST_MESSAGE.lower()
    assert service.invoke_agent.call_args.args[3] == "test"


@pytest.mark.asyncio
@pytest.mark.parametrize("agent_type,endpoint", [("generic", "http://a/api"), ("jsonrpc", "http://a/api"), ("custom", "http://a/")])
async def test_minimal_params_for_generic_jsonrpc_and_trailing_slash(agent_type, endpoint):
    service = _service(agent_type, endpoint)
    await service.test_agent(MagicMock(), "a1", query="hi")
    assert service.invoke_agent.call_args.args[2] == {"query": "hi"}


@pytest.mark.asyncio
async def test_custom_interaction_type_and_scope_forwarded():
    service = _service()
    await service.test_agent(MagicMock(), "a1", interaction_type="x", user_email="u@x.com", user_id="id", token_teams=["t1"])
    assert service.invoke_agent.call_args.args[3] == "x"
    kwargs = service.invoke_agent.call_args.kwargs
    assert (kwargs["user_email"], kwargs["user_id"], kwargs["token_teams"]) == ("u@x.com", "id", ["t1"])


@pytest.mark.asyncio
async def test_not_found_classified_404():
    service = _service()
    service.get_agent = AsyncMock(side_effect=A2AAgentNotFoundError("missing"))
    outcome = await service.test_agent(MagicMock(), "a1")
    assert outcome.status_code == 404
    assert outcome.body == {"success": False, "error": "missing", "error_type": "not_found", "agent_id": "a1"}


@pytest.mark.asyncio
async def test_agent_error_classified_502():
    service = _service(invoke=AsyncMock(side_effect=A2AAgentError("down")))
    outcome = await service.test_agent(MagicMock(), "a1")
    assert (outcome.status_code, outcome.body["error_type"]) == (502, "agent_error")


@pytest.mark.asyncio
async def test_validation_error_classified_422():
    class M(BaseModel):
        x: int

    try:
        M(x="bad")
    except ValidationError as exc:
        err = exc
    service = _service(invoke=AsyncMock(side_effect=err))
    outcome = await service.test_agent(MagicMock(), "a1")
    assert (outcome.status_code, outcome.body["error_type"]) == (422, "validation_error")


@pytest.mark.asyncio
async def test_unexpected_error_classified_500_and_sanitized():
    service = _service(invoke=AsyncMock(side_effect=RuntimeError("secret-token-123")))
    outcome = await service.test_agent(MagicMock(), "a1")
    assert (outcome.status_code, outcome.body["error_type"]) == (500, "internal_error")
    assert "secret-token-123" not in outcome.body["error"]
