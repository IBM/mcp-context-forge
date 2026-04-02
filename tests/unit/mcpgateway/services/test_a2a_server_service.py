# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_a2a_server_service.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Unit tests for A2AServerService — virtual-server federation helpers.
"""

# Standard
from unittest.mock import MagicMock
import uuid

# Third-Party
import pytest
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.services.a2a_server_service import A2AServerService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_server(name="test-server", sid=None, description="A test server", version=1, a2a_agents=None):
    """Return a lightweight mock that looks like a DbServer row."""
    server = MagicMock()
    server.id = sid or uuid.uuid4().hex
    server.name = name
    server.description = description
    server.version = version
    server.a2a_agents = a2a_agents if a2a_agents is not None else []
    return server


def _make_interface(binding="https://agent.example.com/a2a", version="1.0", protocol="a2a"):
    """Return a lightweight mock that looks like a DbServerInterface row."""
    iface = MagicMock()
    iface.binding = binding
    iface.version = version
    iface.protocol = protocol
    return iface


def _make_agent(aid=None, name="downstream-agent", enabled=True, capabilities=None):
    """Return a lightweight mock that looks like a DbA2AAgent row."""
    agent = MagicMock()
    agent.id = aid or uuid.uuid4().hex
    agent.name = name
    agent.enabled = enabled
    agent.capabilities = capabilities if capabilities is not None else {}
    return agent


def _make_mapping(server_id="srv-1", server_task_id="stask-1", agent_id="agt-1", agent_task_id="atask-1", status="active"):
    """Return a lightweight mock that looks like a DbServerTaskMapping row."""
    m = MagicMock()
    m.id = uuid.uuid4().hex
    m.server_id = server_id
    m.server_task_id = server_task_id
    m.agent_id = agent_id
    m.agent_task_id = agent_task_id
    m.status = status
    return m


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestA2AServerService:
    """Unit tests for A2AServerService."""

    @pytest.fixture
    def service(self):
        return A2AServerService()

    @pytest.fixture
    def mock_db(self):
        return MagicMock(spec=Session)

    # ------------------------------------------------------------------
    # get_server_agent_card
    # ------------------------------------------------------------------

    def test_get_server_agent_card_found_with_a2a_interface(self, service, mock_db):
        """Server with an enabled A2A interface returns a populated AgentCard dict."""
        server = _make_server(name="my-server", version=2)
        iface = _make_interface(binding="https://a2a.example.com/agent", version="0.9")

        # First db.execute call: find the server
        # Second db.execute call: find the interface (inside _find_a2a_interface)
        exec_side_effects = [
            MagicMock(**{"scalar_one_or_none.return_value": server}),
            MagicMock(**{"scalar_one_or_none.return_value": iface}),
        ]
        mock_db.execute.side_effect = exec_side_effects

        card = service.get_server_agent_card(mock_db, "my-server")

        assert card is not None
        assert card["name"] == "my-server"
        assert card["url"] == "https://a2a.example.com/agent"
        assert card["protocolVersion"] == "0.9"
        assert card["version"] == "2"
        assert card["skills"] == []
        assert card["capabilities"]["streaming"] is False

    def test_get_server_agent_card_server_not_found(self, service, mock_db):
        """Unknown server name returns None."""
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        result = service.get_server_agent_card(mock_db, "no-such-server")

        assert result is None

    def test_get_server_agent_card_no_a2a_interface(self, service, mock_db):
        """Server exists but has no enabled A2A interface → returns None."""
        server = _make_server(name="server-without-a2a")

        exec_side_effects = [
            MagicMock(**{"scalar_one_or_none.return_value": server}),
            MagicMock(**{"scalar_one_or_none.return_value": None}),
        ]
        mock_db.execute.side_effect = exec_side_effects

        result = service.get_server_agent_card(mock_db, "server-without-a2a")

        assert result is None

    def test_get_server_agent_card_aggregates_skills_from_enabled_agents(self, service, mock_db):
        """Skills from enabled associated A2A agents are included in the card."""
        skill = {"id": "summarize", "name": "Summarize"}
        enabled_agent = _make_agent(capabilities={"skills": [skill]}, enabled=True)
        disabled_agent = _make_agent(capabilities={"skills": [{"id": "translate", "name": "Translate"}]}, enabled=False)
        server = _make_server(a2a_agents=[enabled_agent, disabled_agent])
        iface = _make_interface()

        exec_side_effects = [
            MagicMock(**{"scalar_one_or_none.return_value": server}),
            MagicMock(**{"scalar_one_or_none.return_value": iface}),
        ]
        mock_db.execute.side_effect = exec_side_effects

        card = service.get_server_agent_card(mock_db, server.name)

        assert card is not None
        assert len(card["skills"]) == 1
        assert card["skills"][0]["id"] == "summarize"

    # ------------------------------------------------------------------
    # resolve_server_agent
    # ------------------------------------------------------------------

    def test_resolve_server_agent_with_a2a_interface(self, service, mock_db):
        """Server with an A2A interface returns a ResolvedAgent-compatible dict."""
        server = _make_server(name="federated-server", sid="srv-abc")
        iface = _make_interface(binding="https://a2a.example.com/invoke", version="1.1")

        exec_side_effects = [
            MagicMock(**{"scalar_one_or_none.return_value": server}),
            MagicMock(**{"scalar_one_or_none.return_value": iface}),
        ]
        mock_db.execute.side_effect = exec_side_effects

        result = service.resolve_server_agent(mock_db, "federated-server")

        assert result is not None
        assert result["agent_id"] == "srv-abc"
        assert result["name"] == "federated-server"
        assert result["endpoint_url"] == "https://a2a.example.com/invoke"
        assert result["agent_type"] == "server"
        assert result["protocol_version"] == "1.1"
        assert result["auth_type"] is None

    def test_resolve_server_agent_server_not_found(self, service, mock_db):
        """Missing server returns None."""
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        result = service.resolve_server_agent(mock_db, "no-such-server")

        assert result is None

    def test_resolve_server_agent_protocol_version_defaults_to_1_0(self, service, mock_db):
        """When interface.version is None the protocol_version defaults to '1.0'."""
        server = _make_server(name="srv")
        iface = _make_interface(version=None)

        exec_side_effects = [
            MagicMock(**{"scalar_one_or_none.return_value": server}),
            MagicMock(**{"scalar_one_or_none.return_value": iface}),
        ]
        mock_db.execute.side_effect = exec_side_effects

        result = service.resolve_server_agent(mock_db, "srv")

        assert result is not None
        assert result["protocol_version"] == "1.0"

    # ------------------------------------------------------------------
    # select_downstream_agent
    # ------------------------------------------------------------------

    def test_select_downstream_agent_returns_agent_id(self, service, mock_db):
        """When an enabled agent is associated with the server its ID is returned."""
        agent = _make_agent(aid="agt-xyz")
        mock_db.execute.return_value.scalar_one_or_none.return_value = agent

        result = service.select_downstream_agent(mock_db, "srv-1")

        assert result == "agt-xyz"

    def test_select_downstream_agent_no_agents(self, service, mock_db):
        """When no enabled agent is found, None is returned."""
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        result = service.select_downstream_agent(mock_db, "srv-1")

        assert result is None

    # ------------------------------------------------------------------
    # create_task_mapping
    # ------------------------------------------------------------------

    def test_create_task_mapping_returns_dict(self, service, mock_db):
        """create_task_mapping persists the mapping and returns its dict representation."""
        mock_db.add = MagicMock()
        mock_db.flush = MagicMock()

        result = service.create_task_mapping(
            mock_db,
            server_id="srv-1",
            server_task_id="stask-1",
            agent_id="agt-1",
            agent_task_id="atask-1",
        )

        mock_db.add.assert_called_once()
        mock_db.flush.assert_called_once()

        assert result["server_id"] == "srv-1"
        assert result["server_task_id"] == "stask-1"
        assert result["agent_id"] == "agt-1"
        assert result["agent_task_id"] == "atask-1"
        assert result["status"] == "active"
        # id is a UUID string
        assert isinstance(result["id"], str)
        assert len(result["id"]) > 0

    # ------------------------------------------------------------------
    # resolve_task_mapping
    # ------------------------------------------------------------------

    def test_resolve_task_mapping_found(self, service, mock_db):
        """Existing mapping is returned as a dict."""
        mapping = _make_mapping(server_id="srv-1", server_task_id="stask-1", agent_id="agt-1", agent_task_id="atask-99")
        mock_db.execute.return_value.scalar_one_or_none.return_value = mapping

        result = service.resolve_task_mapping(mock_db, "srv-1", "stask-1")

        assert result is not None
        assert result["server_id"] == "srv-1"
        assert result["server_task_id"] == "stask-1"
        assert result["agent_id"] == "agt-1"
        assert result["agent_task_id"] == "atask-99"
        assert result["status"] == "active"
        assert "id" in result

    def test_resolve_task_mapping_not_found(self, service, mock_db):
        """Missing mapping returns None."""
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        result = service.resolve_task_mapping(mock_db, "srv-1", "nonexistent-task")

        assert result is None
