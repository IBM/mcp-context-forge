# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_server_a2a_tool_association.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

An A2A agent on a virtual server must bring its derived tool along (#7672).
"""

# Standard
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import uuid

# Third-Party
import pytest

# First-Party
from mcpgateway.schemas import ServerCreate, ServerUpdate
from mcpgateway.services.server_service import _associate_server_entities, _require_visible_a2a_agents, _sync_agent_tools, _update_server_associations, ServerError
from mcpgateway.db import A2AAgent as DbA2AAgent


A1, A2, A3, T1, T2 = (uuid.uuid4().hex for _ in range(5))


def _agent(agent_id, tool=None):
    """Build an agent stand-in with an optional derived tool."""
    return SimpleNamespace(id=agent_id, name=agent_id, tool=tool)


def _tool(tool_id, agent_id=A1, integration_type="A2A"):
    """Build a tool stand-in."""
    return SimpleNamespace(id=tool_id, integration_type=integration_type, annotations={"a2a_agent_id": agent_id} if agent_id else {})


def _server(tools=(), agents=()):
    """Build a server stand-in with mutable association lists."""
    return SimpleNamespace(name="srv", tools=list(tools), a2a_agents=list(agents), resources=[], prompts=[])


def _db_returning(*objs):
    """Return a session whose queries yield ``objs``."""
    db = MagicMock()
    db.execute.return_value.scalars.return_value.all.return_value = list(objs)
    db.get.side_effect = lambda model, key: next((o for o in objs if o.id == key), None)
    return db


class TestSyncAgentTools:
    """The derived tool follows its agent."""

    def test_adds_the_tool_of_each_agent(self):
        tool = _tool(T1)
        server = _server(agents=[_agent(A1, tool)])

        _sync_agent_tools(server)

        assert server.tools == [tool]

    def test_does_not_add_a_tool_twice(self):
        tool = _tool(T1)
        server = _server(tools=[tool], agents=[_agent(A1, tool)])

        _sync_agent_tools(server)

        assert server.tools == [tool]

    def test_agent_without_a_tool_adds_nothing(self):
        server = _server(agents=[_agent(A1)])

        _sync_agent_tools(server)

        assert server.tools == []

    def test_dropped_agent_takes_its_tool_along(self):
        tool, other = _tool(T1), _tool(T2)
        dropped = _agent(A1, tool)
        server = _server(tools=[tool, other])

        _sync_agent_tools(server, dropped_agents=[dropped])

        assert server.tools == [other]

    def test_dropped_agent_keeps_a_tool_that_another_agent_uses(self):
        tool = _tool(T1, A2)
        server = _server(tools=[tool], agents=[_agent(A2, tool)])

        _sync_agent_tools(server, dropped_agents=[_agent(A1, tool)])

        assert server.tools == [tool]

    @pytest.mark.parametrize("agent_id,integration_type", [(A2, "A2A"), (None, "A2A"), (A1, "REST")])
    def test_invalid_link_cannot_attach_or_detach_tool(self, agent_id, integration_type):
        """An invalid reverse link leaves independent server tools intact."""
        tool = _tool(T1, agent_id, integration_type)
        agent = _agent(A1, tool)
        server = _server(agents=[agent])
        _sync_agent_tools(server)
        assert server.tools == []

        server.tools.append(tool)
        server.a2a_agents.clear()
        _sync_agent_tools(server, dropped_agents=[agent])
        assert server.tools == [tool]

    def test_agent_that_stays_keeps_its_tool(self):
        tool = _tool(T1)
        agent = _agent(A1, tool)
        server = _server(tools=[tool], agents=[agent])

        _sync_agent_tools(server, dropped_agents=[agent])

        assert server.tools == [tool]


class TestAssociateOnCreate:
    """Create attaches the tool of every listed agent."""

    def test_single_agent(self):
        tool, agent = _tool(T1), _agent(A1, _tool(T1))
        agent.tool = tool
        server = _server()

        _associate_server_entities(_db_returning(agent), server, ServerCreate(name="srv", associated_a2a_agents=[A1]))

        assert server.a2a_agents == [agent] and server.tools == [tool]

    def test_several_agents(self):
        agents = [_agent(A1, _tool(T1)), _agent(A2, _tool(T2, A2)), _agent(A3)]
        server = _server()

        _associate_server_entities(_db_returning(*agents), server, ServerCreate(name="srv", associated_a2a_agents=[A1, A2, A3]))

        assert [t.id for t in server.tools] == [T1, T2]


class TestUpdateKeepsTools:
    """Update re-adds derived tools after it replaces associations."""

    def test_put_without_the_derived_tool_keeps_it(self):
        tool = _tool(T1)
        server = _server(tools=[tool], agents=[_agent(A1, tool)])

        _update_server_associations(_db_returning(), server, ServerUpdate(associated_tools=[]))

        assert server.tools == [tool]

    def test_put_with_other_tools_keeps_the_derived_tool(self):
        tool, other = _tool(T1), _tool(T2)
        server = _server(tools=[tool], agents=[_agent(A1, tool)])

        _update_server_associations(_db_returning(other), server, ServerUpdate(associated_tools=[T2]))

        assert {t.id for t in server.tools} == {T1, T2}

    def test_adding_an_agent_adds_its_tool(self):
        tool, agent = _tool(T1), _agent(A1, _tool(T1))
        agent.tool = tool
        server = _server()

        _update_server_associations(_db_returning(agent), server, ServerUpdate(associated_a2a_agents=[A1]))

        assert server.tools == [tool]

    def test_removing_an_agent_removes_its_tool(self):
        tool = _tool(T1)
        server = _server(tools=[tool], agents=[_agent(A1, tool)])

        _update_server_associations(_db_returning(), server, ServerUpdate(associated_a2a_agents=[]))

        assert server.tools == [] and server.a2a_agents == []

    def test_removing_an_agent_removes_its_tool_even_when_the_payload_lists_it(self):
        """A client that sends back a read removes the agent and keeps the old tool list."""
        tool = _tool(T1)
        server = _server(tools=[tool], agents=[_agent(A1, tool)])

        _update_server_associations(_db_returning(tool), server, ServerUpdate(associated_a2a_agents=[], associated_tools=[T1]))

        assert server.a2a_agents == [] and server.tools == []

    def test_rename_does_not_reattach_a_tool_the_operator_detached(self):
        tool = _tool(T1)
        server = _server(tools=[], agents=[_agent(A1, tool)])

        _update_server_associations(_db_returning(), server, ServerUpdate(description="x"))

        assert server.tools == []

    def test_update_without_association_fields_changes_nothing(self):
        tool = _tool(T1)
        server = _server(tools=[tool], agents=[_agent(A1, tool)])

        _update_server_associations(_db_returning(), server, ServerUpdate(description="x"))

        assert server.tools == [tool]


def test_model_has_the_tool_relationship_the_fix_relies_on():
    """The agent model exposes the derived tool."""
    assert hasattr(DbA2AAgent, "tool") and hasattr(DbA2AAgent, "tool_id")


def _scoped_agent(agent_id, visibility, team_id=None, owner_email=None):
    """Build an agent stand-in with visibility fields."""
    return SimpleNamespace(id=agent_id, name=agent_id, visibility=visibility, team_id=team_id, owner_email=owner_email, tool=None)


@pytest.fixture(autouse=True)
def _caller_is_not_admin():
    """Treat every caller as a non-admin."""
    with patch("mcpgateway.utils.admin_check.is_user_admin", return_value=False):
        yield


class TestAgentVisibility:
    """A caller can attach only the agents it can see."""

    def test_public_agent_is_allowed_for_a_public_only_token(self):
        agent = _scoped_agent(A1, "public")

        _require_visible_a2a_agents(_db_returning(agent), [A1], "user@example.com", [])

    def test_team_agent_of_another_team_is_denied(self):
        agent = _scoped_agent(A1, "team", team_id="team-b")

        with pytest.raises(ServerError):
            _require_visible_a2a_agents(_db_returning(agent), [A1], "user@example.com", ["team-a"])

    def test_team_agent_of_the_caller_team_is_allowed(self):
        agent = _scoped_agent(A1, "team", team_id="team-a")

        _require_visible_a2a_agents(_db_returning(agent), [A1], "user@example.com", ["team-a"])

    def test_team_agent_is_denied_for_a_public_only_token(self):
        agent = _scoped_agent(A1, "team", team_id="team-a")

        with pytest.raises(ServerError):
            _require_visible_a2a_agents(_db_returning(agent), [A1], "user@example.com", [])

    def test_private_agent_of_another_user_is_denied(self):
        agent = _scoped_agent(A1, "private", owner_email="owner@example.com")

        with pytest.raises(ServerError):
            _require_visible_a2a_agents(_db_returning(agent), [A1], "user@example.com", ["team-a"])

    def test_private_agent_of_the_caller_is_allowed(self):
        agent = _scoped_agent(A1, "private", owner_email="user@example.com")

        _require_visible_a2a_agents(_db_returning(agent), [A1], "user@example.com", ["team-a"])

    def test_unknown_agent_is_denied(self):
        with pytest.raises(ServerError):
            _require_visible_a2a_agents(_db_returning(), [A1], "user@example.com", ["team-a"])

    def test_missing_and_invisible_agents_return_the_same_error(self):
        hidden = _scoped_agent(A1, "private", owner_email="owner@example.com")

        with pytest.raises(ServerError) as missing:
            _require_visible_a2a_agents(_db_returning(), [A1], "user@example.com", ["team-a"])
        with pytest.raises(ServerError) as invisible:
            _require_visible_a2a_agents(_db_returning(hidden), [A1], "user@example.com", ["team-a"])

        assert str(missing.value) == str(invisible.value)

    def test_one_invisible_agent_denies_the_whole_request(self):
        visible, hidden = _scoped_agent(A1, "public"), _scoped_agent(A2, "team", team_id="team-b")

        with pytest.raises(ServerError):
            _require_visible_a2a_agents(_db_returning(visible, hidden), [A1, A2], "user@example.com", ["team-a"])

    def test_agent_already_on_the_server_needs_no_new_check(self):
        attached = _scoped_agent(A1, "team", team_id="team-b")

        _require_visible_a2a_agents(_db_returning(), [A1], "user@example.com", ["team-a"], attached=[attached])

    def test_no_agent_ids_runs_no_query(self):
        db = _db_returning()

        _require_visible_a2a_agents(db, None, "user@example.com", [])
        _require_visible_a2a_agents(db, [], "user@example.com", [])

        db.execute.assert_not_called()
