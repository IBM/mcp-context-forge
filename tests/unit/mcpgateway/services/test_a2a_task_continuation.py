# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_a2a_task_continuation.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Continuing an A2A task with a follow-up message (issue #6703).
"""

# Standard
from unittest.mock import AsyncMock, MagicMock

# Third-Party
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# First-Party
from mcpgateway.db import A2ATaskEvent
from mcpgateway.services.a2a_protocol import build_a2a_jsonrpc_request, is_terminal_task_state
from mcpgateway.services.a2a_service import A2AAgentError, A2AAgentNotFoundError, A2AAgentService, A2ATaskStateError


def _wire(state: str) -> dict:
    """Return a stored task in wire format."""
    return {"id": "t1", "contextId": "ctx-1", "status": {"state": state}}


@pytest.fixture
def service():
    """Service with task lookup and agent invocation stubbed."""
    svc = A2AAgentService()
    svc.get_task = AsyncMock(return_value=_wire("input-required"))
    svc.invoke_agent = AsyncMock(return_value={"result": {"id": "t1"}})
    svc._record_task_event = MagicMock()
    return svc


@pytest.mark.parametrize(
    "state, terminal",
    [
        ("completed", True),
        ("TASK_STATE_COMPLETED", True),
        ("failed", True),
        ("TASK_STATE_FAILED", True),
        ("canceled", True),
        ("cancelled", True),
        ("TASK_STATE_CANCELED", True),
        ("rejected", True),
        ("input-required", False),
        ("input_required", False),
        ("TASK_STATE_INPUT_REQUIRED", False),
        ("TASK_STATE_AUTH_REQUIRED", False),
        ("working", False),
        (None, False),
    ],
)
def test_is_terminal_task_state(state, terminal):
    """Both the 0.3 and the 1.0 spellings are recognized."""
    assert is_terminal_task_state(state) is terminal


class TestContinueTask:
    """A2AAgentService.continue_task."""

    @pytest.mark.asyncio
    async def test_binds_message_to_task(self, service):
        """The agent receives the message with taskId and contextId from the stored row."""
        db = MagicMock()
        result = await service.continue_task(db, "agent-1", "t1", {"parts": [{"text": "yes"}]}, user_email="u@example.com", token_teams=["team"])
        assert result == {"result": {"id": "t1"}}
        _, kwargs = service.invoke_agent.call_args
        message = service.invoke_agent.call_args.args[2]["message"]
        assert message["taskId"] == "t1" and message["contextId"] == "ctx-1"
        assert message["role"] == "user" and message["messageId"].startswith("contextforge-")
        assert kwargs["agent_id"] == "agent-1" and kwargs["token_teams"] == ["team"]

    @pytest.mark.asyncio
    async def test_gateway_replaces_caller_message_id(self, service):
        """A caller messageId never reaches the agent or the event log."""
        await service.continue_task(MagicMock(), "agent-1", "t1", {"messageId": "attacker-id", "parts": [{"text": "x"}]})
        message = service.invoke_agent.call_args.args[2]["message"]
        assert message["messageId"] != "attacker-id" and message["messageId"].startswith("contextforge-")
        assert service._record_task_event.call_args.args[4]["message"]["messageId"] == message["messageId"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("role", ["user", "ROLE_USER", "Role_User"])
    async def test_user_role_spellings_are_normalized(self, service, role):
        """Either user-role spelling is accepted and sent as the user role."""
        await service.continue_task(MagicMock(), "agent-1", "t1", {"role": role, "parts": [{"text": "x"}]})
        assert service.invoke_agent.call_args.args[2]["message"]["role"] == "user"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("role", ["agent", "ROLE_AGENT", "system", "", "ROLE_UNSPECIFIED"])
    async def test_non_user_role_rejected(self, service, role):
        """A message that claims an agent or other role is refused before the agent is called."""
        with pytest.raises(A2AAgentError, match="role"):
            await service.continue_task(MagicMock(), "agent-1", "t1", {"role": role, "parts": [{"text": "x"}]})
        service.invoke_agent.assert_not_called()
        service._record_task_event.assert_not_called()

    @pytest.mark.asyncio
    async def test_mismatched_context_id_rejected(self, service):
        """A contextId that differs from the stored task is refused and not forwarded."""
        with pytest.raises(A2AAgentError, match="contextId does not match"):
            await service.continue_task(MagicMock(), "agent-1", "t1", {"contextId": "someone-elses", "parts": [{"text": "x"}]})
        service.invoke_agent.assert_not_called()
        service._record_task_event.assert_not_called()

    @pytest.mark.asyncio
    async def test_matching_context_id_is_accepted(self, service):
        """A contextId equal to the stored one passes and is bound from the stored task."""
        await service.continue_task(MagicMock(), "agent-1", "t1", {"contextId": "ctx-1", "parts": [{"text": "x"}]})
        assert service.invoke_agent.call_args.args[2]["message"]["contextId"] == "ctx-1"

    @pytest.mark.asyncio
    async def test_context_id_rejected_when_task_has_none(self, service):
        """A caller cannot attach a context to a task that has none."""
        service.get_task.return_value = {"id": "t1", "status": {"state": "input-required"}}
        with pytest.raises(A2AAgentError, match="contextId does not match"):
            await service.continue_task(MagicMock(), "agent-1", "t1", {"contextId": "invented", "parts": [{"text": "x"}]})
        service.invoke_agent.assert_not_called()

    @pytest.mark.asyncio
    async def test_task_without_context_sends_none(self, service):
        """A task with no stored context produces a message without contextId."""
        service.get_task.return_value = {"id": "t1", "status": {"state": "input-required"}}
        await service.continue_task(MagicMock(), "agent-1", "t1", {"parts": [{"text": "x"}]})
        assert "contextId" not in service.invoke_agent.call_args.args[2]["message"]

    @pytest.mark.asyncio
    async def test_matching_task_id_is_accepted(self, service):
        """A taskId equal to the path task passes."""
        await service.continue_task(MagicMock(), "agent-1", "t1", {"taskId": "t1", "parts": [{"text": "x"}]})
        service.invoke_agent.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_unknown_or_invisible_task(self, service):
        """A missing or hidden task raises not-found and never reaches the agent."""
        service.get_task.return_value = None
        with pytest.raises(A2AAgentNotFoundError):
            await service.continue_task(MagicMock(), "agent-1", "t1", {"parts": [{"text": "x"}]})
        service.invoke_agent.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("state", ["completed", "TASK_STATE_FAILED", "canceled", "rejected"])
    async def test_terminal_task_rejected(self, service, state):
        """A terminal task raises a state error that names the state."""
        service.get_task.return_value = _wire(state)
        with pytest.raises(A2ATaskStateError, match=state):
            await service.continue_task(MagicMock(), "agent-1", "t1", {"parts": [{"text": "x"}]})
        service.invoke_agent.assert_not_called()

    @pytest.mark.asyncio
    async def test_mismatched_task_id_rejected(self, service):
        """A message that names another task is refused."""
        with pytest.raises(A2AAgentError, match="does not match"):
            await service.continue_task(MagicMock(), "agent-1", "t1", {"taskId": "other", "parts": [{"text": "x"}]})
        service.invoke_agent.assert_not_called()

    @pytest.mark.asyncio
    async def test_records_event_with_state_transition(self, service):
        """The continuation event carries the previous and the new state."""
        service.get_task.side_effect = [_wire("TASK_STATE_AUTH_REQUIRED"), _wire("TASK_STATE_WORKING")]
        await service.continue_task(MagicMock(), "agent-1", "t1", {"parts": [{"text": "x"}]})
        _, _, _, event_type, payload = service._record_task_event.call_args.args
        assert event_type == "task_continued"
        assert (payload["previous_state"], payload["state"]) == ("TASK_STATE_AUTH_REQUIRED", "TASK_STATE_WORKING")

    @pytest.mark.asyncio
    async def test_event_failure_does_not_fail_the_continuation(self, service):
        """The agent already received the message, so an event-log error is logged, not raised."""
        service._record_task_event.side_effect = RuntimeError("db down")
        db = MagicMock()
        assert await service.continue_task(db, "agent-1", "t1", {"parts": [{"text": "x"}]}) == {"result": {"id": "t1"}}
        db.rollback.assert_called_once()


class TestProtocolVersions:
    """The bound message is converted for the agent's protocol version."""

    MESSAGE = {"messageId": "m1", "role": "user", "taskId": "t1", "contextId": "ctx-1", "parts": [{"text": "yes"}]}

    def test_v1_agent(self):
        """A 1.0 agent gets SendMessage with ROLE_USER and no kind markers."""
        request = build_a2a_jsonrpc_request({"message": dict(self.MESSAGE), "taskId": "t1"}, "1.0")
        message = request["params"]["message"]
        assert request["method"] == "SendMessage"
        assert message["role"] == "ROLE_USER" and "kind" not in message
        assert (message["taskId"], message["contextId"]) == ("t1", "ctx-1")

    def test_legacy_agent(self):
        """A 0.3 agent gets message/send with kind markers and the same task binding."""
        request = build_a2a_jsonrpc_request({"message": dict(self.MESSAGE), "taskId": "t1"}, "0.3")
        message = request["params"]["message"]
        assert request["method"] == "message/send"
        assert message["role"] == "user" and message["kind"] == "message"
        assert (message["taskId"], message["contextId"]) == ("t1", "ctx-1")
        assert message["parts"][0]["kind"] == "text"


class TestRecordTaskEvent:
    """Event log sequencing against a real session."""

    def test_sequence_increments_per_task(self):
        """Events for a task get consecutive sequence numbers; other tasks are unaffected."""
        engine = create_engine("sqlite://")
        A2ATaskEvent.__table__.create(engine)
        # Foreign key to a2a_agents is not enforced by SQLite here.
        db = sessionmaker(bind=engine)()
        for task_id in ("t1", "t1", "t2"):
            A2AAgentService._record_task_event(db, "agent-1", task_id, "task_continued", {"n": 1})
        sequences = {(e.task_id, e.sequence) for e in db.query(A2ATaskEvent).all()}
        assert sequences == {("t1", 1), ("t1", 2), ("t2", 1)}


class TestTerminalStatesAcrossVersions:
    """cancel_task and upsert_task honor 1.0 state names."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("state", ["TASK_STATE_COMPLETED", "TASK_STATE_FAILED", "TASK_STATE_CANCELED"])
    async def test_cancel_leaves_v1_terminal_task_unchanged(self, state):
        """Cancelling a finished 1.0 task returns it as stored instead of rewriting its state."""
        svc = A2AAgentService()
        task = MagicMock(state=state, task_id="t1", context_id=None, latest_message=None, last_error=None, payload=None)
        svc._resolve_unique_task = MagicMock(return_value=task)
        svc._check_agent_access = AsyncMock(return_value=True)
        db = MagicMock()
        wire = await svc.cancel_task(db, "t1", agent_id="agent-1")
        assert wire["status"]["state"] == state
        assert task.state == state
        db.commit.assert_not_called()

    def test_upsert_marks_v1_terminal_state_completed(self):
        """A 1.0 terminal state sets completed_at."""
        svc = A2AAgentService()
        task = MagicMock(task_id="t1", context_id=None, latest_message=None, last_error=None, payload=None, completed_at=None)
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = task
        svc.upsert_task(db, "agent-1", "t1", "TASK_STATE_COMPLETED")
        assert task.completed_at is not None
