# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_server_a2a_tool_association.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

An A2A agent on a virtual server must bring its derived tool along (#7672).
"""

# Standard
from types import SimpleNamespace
from unittest.mock import MagicMock
import uuid

# First-Party
from mcpgateway.schemas import ServerCreate, ServerUpdate
from mcpgateway.services.server_service import _associate_server_entities, _attach_agent_tools, _update_server_associations
from mcpgateway.db import A2AAgent as DbA2AAgent


A1, A2, A3, T1, T2 = (uuid.uuid4().hex for _ in range(5))


def _agent(agent_id, tool=None):
    """Build an agent stand-in with an optional derived tool."""
    return SimpleNamespace(id=agent_id, name=agent_id, tool=tool)


def _tool(tool_id):
    """Build a tool stand-in."""
    return SimpleNamespace(id=tool_id)


def _server(tools=(), agents=()):
    """Build a server stand-in with mutable association lists."""
    return SimpleNamespace(name="srv", tools=list(tools), a2a_agents=list(agents), resources=[], prompts=[])


def _db_returning(*objs):
    """Return a session whose queries yield ``objs``."""
    db = MagicMock()
    db.execute.return_value.scalars.return_value.all.return_value = list(objs)
    db.get.side_effect = lambda model, key: next((o for o in objs if o.id == key), None)
    return db


class TestAttachAgentTools:
    """The derived tool follows its agent."""

    def test_adds_the_tool_of_each_agent(self):
        tool = _tool(T1)
        server = _server(agents=[_agent(A1, tool)])

        _attach_agent_tools(server)

        assert server.tools == [tool]

    def test_does_not_add_a_tool_twice(self):
        tool = _tool(T1)
        server = _server(tools=[tool], agents=[_agent(A1, tool)])

        _attach_agent_tools(server)

        assert server.tools == [tool]

    def test_agent_without_a_tool_adds_nothing(self):
        server = _server(agents=[_agent(A1)])

        _attach_agent_tools(server)

        assert server.tools == []

    def test_dropped_agent_takes_its_tool_along(self):
        tool, other = _tool(T1), _tool(T2)
        dropped = _agent(A1, tool)
        server = _server(tools=[tool, other])

        _attach_agent_tools(server, dropped_agents=[dropped])

        assert server.tools == [other]

    def test_dropped_agent_keeps_a_tool_the_caller_listed(self):
        tool = _tool(T1)
        server = _server(tools=[tool])

        _attach_agent_tools(server, dropped_agents=[_agent(A1, tool)], keep_tool_ids={T1})

        assert server.tools == [tool]

    def test_agent_that_stays_keeps_its_tool(self):
        tool = _tool(T1)
        agent = _agent(A1, tool)
        server = _server(tools=[tool], agents=[agent])

        _attach_agent_tools(server, dropped_agents=[agent])

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
        agents = [_agent(A1, _tool(T1)), _agent(A2, _tool(T2)), _agent(A3)]
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

    def test_removing_an_agent_keeps_a_tool_the_payload_lists(self):
        tool = _tool(T1)
        server = _server(tools=[tool], agents=[_agent(A1, tool)])

        _update_server_associations(_db_returning(tool), server, ServerUpdate(associated_a2a_agents=[], associated_tools=[T1]))

        assert server.tools == [tool]

    def test_update_without_association_fields_changes_nothing(self):
        tool = _tool(T1)
        server = _server(tools=[tool], agents=[_agent(A1, tool)])

        _update_server_associations(_db_returning(), server, ServerUpdate(description="x"))

        assert server.tools == [tool]


def test_model_has_the_tool_relationship_the_fix_relies_on():
    """The agent model exposes the derived tool."""
    assert hasattr(DbA2AAgent, "tool") and hasattr(DbA2AAgent, "tool_id")
