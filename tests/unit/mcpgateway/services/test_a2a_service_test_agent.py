# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_a2a_service_test_agent.py
Copyright contributors to the MCP-CONTEXT-FORGE project
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
from mcpgateway.services.a2a_service import (
    A2A_TEST_AGENT_ERROR_MESSAGE,
    A2A_TEST_NOT_FOUND_MESSAGE,
    A2A_TEST_AGENT_DISABLED_MESSAGE,
    A2AAgentDisabledError,
    A2AAgentError,
    A2AAgentNotFoundError,
    A2AAgentService,
    DEFAULT_A2A_TEST_MESSAGE,
)


def _service(agent_type="custom", endpoint="http://agent.example.com/api", invoke=None):
    service = A2AAgentService()
    service._load_accessible_agent = AsyncMock(return_value=SimpleNamespace(id="a1", name="Agent", agent_type=agent_type, endpoint_url=endpoint))
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
    assert service.invoke_agent.call_args.kwargs["agent_id"] == "a1"


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
async def test_request_context_forwarded_to_invoke():
    service = _service()
    headers = {"x-trace": "abc"}
    await service.test_agent(MagicMock(), "a1", hop_count=2, bearer_token="tok", content_type="application/json", request_headers=headers)
    kwargs = service.invoke_agent.call_args.kwargs
    assert (kwargs["hop_count"], kwargs["bearer_token"], kwargs["content_type"], kwargs["request_headers"]) == (2, "tok", "application/json", headers)


@pytest.mark.asyncio
async def test_empty_query_falls_back_to_default_message():
    service = _service()
    await service.test_agent(MagicMock(), "a1", query="")
    assert service.invoke_agent.call_args.args[2]["query"] == DEFAULT_A2A_TEST_MESSAGE


@pytest.mark.asyncio
async def test_agent_id_is_sanitized_in_logs(caplog):
    service = _service()
    service._load_accessible_agent = AsyncMock(side_effect=A2AAgentNotFoundError("missing"))
    with caplog.at_level("WARNING"):
        await service.test_agent(MagicMock(), "a1\nforged log line")
    assert "\n" not in "".join(record.getMessage() for record in caplog.records)


def test_failure_envelope_rejects_unknown_error_type():
    with pytest.raises(ValidationError):
        A2AAgentService._test_failure(500, "boom", "not_a_type", "a1")


@pytest.mark.asyncio
async def test_not_found_classified_404():
    service = _service()
    service._load_accessible_agent = AsyncMock(side_effect=A2AAgentNotFoundError("missing"))
    outcome = await service.test_agent(MagicMock(), "a1")
    assert outcome.status_code == 404
    assert outcome.body == {"success": False, "error": A2A_TEST_NOT_FOUND_MESSAGE, "error_type": "not_found", "agent_id": "a1"}


@pytest.mark.asyncio
async def test_not_found_detail_returned_when_requested():
    service = _service()
    service._load_accessible_agent = AsyncMock(side_effect=A2AAgentNotFoundError("A2A Agent not found with ID: a1"))
    outcome = await service.test_agent(MagicMock(), "a1", include_agent_error_detail=True)
    assert (outcome.status_code, outcome.body["error"]) == (404, "A2A Agent not found with ID: a1")


@pytest.mark.asyncio
async def test_missing_and_inaccessible_agents_return_identical_404_body():
    missing = _service()
    missing._load_accessible_agent = AsyncMock(side_effect=A2AAgentNotFoundError("A2A Agent not found with ID: a1"))
    inaccessible = _service()
    inaccessible._load_accessible_agent = AsyncMock(side_effect=A2AAgentNotFoundError("Agent not found"))
    missing_outcome = await missing.test_agent(MagicMock(), "a1")
    inaccessible_outcome = await inaccessible.test_agent(MagicMock(), "a1")
    assert missing_outcome == inaccessible_outcome
    assert missing_outcome.status_code == 404


@pytest.mark.asyncio
async def test_agent_error_classified_502_without_upstream_detail():
    service = _service(invoke=AsyncMock(side_effect=A2AAgentError("HTTP 503: connect to internal-host.corp:8443 refused")))
    outcome = await service.test_agent(MagicMock(), "a1")
    assert (outcome.status_code, outcome.body["error_type"]) == (502, "agent_error")
    assert outcome.body["error"] == A2A_TEST_AGENT_ERROR_MESSAGE
    assert "internal-host" not in outcome.body["error"]


@pytest.mark.asyncio
async def test_disabled_agent_gets_distinct_502_code():
    service = _service(invoke=AsyncMock(side_effect=A2AAgentDisabledError("A2A Agent 'Agent' is disabled")))
    outcome = await service.test_agent(MagicMock(), "a1")
    assert (outcome.status_code, outcome.body["error_type"], outcome.body["error"]) == (502, "agent_disabled", A2A_TEST_AGENT_DISABLED_MESSAGE)


@pytest.mark.asyncio
async def test_disabled_agent_keeps_admin_contract():
    service = _service(invoke=AsyncMock(side_effect=A2AAgentDisabledError("A2A Agent 'Agent' is disabled")))
    outcome = await service.test_agent(MagicMock(), "a1", include_agent_error_detail=True)
    assert (outcome.body["error_type"], outcome.body["error"]) == ("agent_error", "A2A Agent 'Agent' is disabled")


@pytest.mark.asyncio
async def test_agent_error_detail_returned_when_requested():
    service = _service(invoke=AsyncMock(side_effect=A2AAgentError("HTTP 503: Service Unavailable")))
    outcome = await service.test_agent(MagicMock(), "a1", include_agent_error_detail=True)
    assert (outcome.status_code, outcome.body["error_type"]) == (502, "agent_error")
    assert outcome.body["error"] == "HTTP 503: Service Unavailable"


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


@pytest.mark.asyncio
async def test_agents_sharing_a_name_resolve_by_id():
    """Two team agents with one name must not raise MultipleResultsFound."""
    # Third-Party
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    # First-Party
    from mcpgateway.db import A2AAgent, Base

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    for agent_id, team in (("dup-a", "team-a"), ("dup-b", "team-b")):
        db.add(A2AAgent(id=agent_id, name="shared-name", slug=f"shared-name-{team}", endpoint_url="https://example.com/a", visibility="team", team_id=team, enabled=False))
    db.commit()

    outcome = await A2AAgentService().test_agent(db, "dup-b", user_email="u@x.com", token_teams=["team-b"])

    assert (outcome.status_code, outcome.body["error_type"]) == (502, "agent_disabled")
    db.close()


@pytest.mark.asyncio
async def test_public_only_token_gets_404_for_private_agent():
    """A public-only caller sees the same 404 for a private agent as for a missing one."""
    # Third-Party
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    # First-Party
    from mcpgateway.db import A2AAgent, Base

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    db.add(A2AAgent(id="priv", name="priv", slug="priv", endpoint_url="https://example.com/a", visibility="private", owner_email="owner@x.com", enabled=True))
    db.commit()

    service = A2AAgentService()
    hidden = await service.test_agent(db, "priv", user_email="other@x.com", token_teams=[])
    missing = await service.test_agent(db, "nope", user_email="other@x.com", token_teams=[])

    assert hidden.status_code == 404
    assert hidden.body["error"] == missing.body["error"] == A2A_TEST_NOT_FOUND_MESSAGE
    db.close()
