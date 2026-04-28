# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_a2a_server_service.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

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

    def test_get_server_agent_card_hidden_server_returns_none(self, service, mock_db):
        server = _make_server(name="private-server")
        server.visibility = "private"
        server.owner_email = "other@example.com"
        mock_db.execute.return_value.scalar_one_or_none.return_value = server

        result = service.get_server_agent_card(mock_db, "private-server", user_email="user@example.com", token_teams=[])

        assert result is None

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

    def test_resolve_server_agent_hidden_server_returns_none(self, service, mock_db):
        server = _make_server(name="private-server")
        server.visibility = "private"
        server.owner_email = "other@example.com"
        mock_db.execute.return_value.scalar_one_or_none.return_value = server

        result = service.resolve_server_agent(mock_db, "private-server", user_email="user@example.com", token_teams=[])

        assert result is None

    def test_resolve_server_agent_without_a2a_interface_returns_none(self, service, mock_db):
        server = _make_server(name="srv")
        mock_db.execute.side_effect = [
            MagicMock(**{"scalar_one_or_none.return_value": server}),
            MagicMock(**{"scalar_one_or_none.return_value": None}),
        ]

        result = service.resolve_server_agent(mock_db, "srv")

        assert result is None

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

    def test_select_downstream_agent_respects_order_by_name(self, service, mock_db):
        """Selection is deterministic: ``ORDER BY name LIMIT 1`` picks the first.

        The SQL ordering is emitted in the query construction.  We exercise
        the statement builder to confirm (a) an ORDER BY name clause is
        present and (b) the result comes from ``scalar_one_or_none`` (single
        row, not a collection).
        """
        # First-Party
        from mcpgateway.db import A2AAgent as DbA2AAgent  # pylint: disable=import-outside-toplevel

        chosen = _make_agent(aid="agt-a", name="alpha")
        captured_query = {}

        def capture_execute(query):
            captured_query["stmt"] = query
            return MagicMock(**{"scalar_one_or_none.return_value": chosen})

        mock_db.execute.side_effect = capture_execute

        result = service.select_downstream_agent(mock_db, "srv-1")

        assert result == "agt-a"
        compiled = str(captured_query["stmt"].compile(compile_kwargs={"literal_binds": False}))
        assert "ORDER BY" in compiled.upper()
        assert DbA2AAgent.__tablename__ + ".name" in compiled or "name" in compiled.split("ORDER BY", 1)[1].lower()

    def test_select_downstream_agent_filters_out_disabled(self, service, mock_db):
        """Disabled agents are filtered in SQL; an all-disabled server returns None.

        We assert the ``enabled = TRUE`` predicate is present in the
        statement — this is the guarantee callers rely on.
        """
        mock_db.execute.return_value.scalar_one_or_none.return_value = None
        captured_query = {}

        def capture_execute(query):
            captured_query["stmt"] = query
            return MagicMock(**{"scalar_one_or_none.return_value": None})

        mock_db.execute.side_effect = capture_execute

        assert service.select_downstream_agent(mock_db, "srv-1") is None

        compiled = str(captured_query["stmt"].compile(compile_kwargs={"literal_binds": True}))
        # The exact compiled SQL varies by dialect — assert on a normalized
        # substring that pins the enabled-filter predicate.
        assert "enabled" in compiled.lower()

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


# ---------------------------------------------------------------------------
# _check_server_access visibility tests
# ---------------------------------------------------------------------------


class TestCheckServerAccess:
    """Unit tests for _check_server_access visibility scoping.

    Each branch of the visibility logic (public, admin bypass, no-user,
    public-only token, private/owner, team) is tested explicitly.
    """

    @staticmethod
    def _make_server(visibility="public", owner_email=None, team_id=None):
        server = MagicMock()
        server.visibility = visibility
        server.owner_email = owner_email
        server.team_id = team_id
        return server

    # -- Public visibility --------------------------------------------------

    def test_public_visible_to_everyone(self):
        from mcpgateway.services.a2a_server_service import _check_server_access

        server = self._make_server(visibility="public")
        assert _check_server_access(server, "user@test.com", ["team-a"]) is True
        assert _check_server_access(server, None, []) is True
        assert _check_server_access(server, None, None) is True

    # -- Admin bypass -------------------------------------------------------

    def test_admin_bypass_denies_private(self):
        """PR #4341: anonymous admin bypass must NOT see another user's private server."""
        from mcpgateway.services.a2a_server_service import _check_server_access

        server = self._make_server(visibility="private", owner_email="other@test.com")
        assert _check_server_access(server, None, None) is False

    def test_admin_bypass_sees_team(self):
        from mcpgateway.services.a2a_server_service import _check_server_access

        server = self._make_server(visibility="team", team_id="team-x")
        assert _check_server_access(server, None, None) is True

    def test_db_admin_with_email_sees_own_private(self):
        """PR #4341 carve-out: DB-admin (email, None) shape sees own private but not others'."""
        from mcpgateway.services.a2a_server_service import _check_server_access

        own_private = self._make_server(visibility="private", owner_email="admin@test.com")
        others_private = self._make_server(visibility="private", owner_email="other@test.com")
        assert _check_server_access(own_private, "admin@test.com", None) is True
        assert _check_server_access(others_private, "admin@test.com", None) is False

    # -- No user context (not admin) ----------------------------------------

    def test_no_user_email_denied_for_private(self):
        from mcpgateway.services.a2a_server_service import _check_server_access

        server = self._make_server(visibility="private", owner_email="owner@test.com")
        assert _check_server_access(server, None, ["team-a"]) is False

    def test_no_user_email_denied_for_team(self):
        from mcpgateway.services.a2a_server_service import _check_server_access

        server = self._make_server(visibility="team", team_id="team-a")
        assert _check_server_access(server, None, ["team-a"]) is False

    # -- Public-only token (empty teams) ------------------------------------

    def test_empty_teams_denied_for_private(self):
        from mcpgateway.services.a2a_server_service import _check_server_access

        server = self._make_server(visibility="private", owner_email="user@test.com")
        assert _check_server_access(server, "user@test.com", []) is False

    def test_empty_teams_denied_for_team(self):
        from mcpgateway.services.a2a_server_service import _check_server_access

        server = self._make_server(visibility="team", team_id="team-a")
        assert _check_server_access(server, "user@test.com", []) is False

    # -- Private visibility / owner match -----------------------------------

    def test_private_visible_to_owner(self):
        from mcpgateway.services.a2a_server_service import _check_server_access

        server = self._make_server(visibility="private", owner_email="user@test.com")
        assert _check_server_access(server, "user@test.com", ["team-a"]) is True

    def test_private_hidden_from_non_owner(self):
        from mcpgateway.services.a2a_server_service import _check_server_access

        server = self._make_server(visibility="private", owner_email="other@test.com")
        assert _check_server_access(server, "user@test.com", ["team-a"]) is False

    # -- Team visibility ----------------------------------------------------

    def test_team_visible_to_member(self):
        from mcpgateway.services.a2a_server_service import _check_server_access

        server = self._make_server(visibility="team", team_id="team-a")
        assert _check_server_access(server, "user@test.com", ["team-a", "team-b"]) is True

    def test_team_hidden_from_non_member(self):
        from mcpgateway.services.a2a_server_service import _check_server_access

        server = self._make_server(visibility="team", team_id="team-x")
        assert _check_server_access(server, "user@test.com", ["team-a", "team-b"]) is False

    def test_team_visible_with_admin_token_teams_none(self):
        """token_teams=None with user_email set → admin-like, allows team access."""
        from mcpgateway.services.a2a_server_service import _check_server_access

        server = self._make_server(visibility="team", team_id="team-a")
        assert _check_server_access(server, "admin@test.com", None) is True

    # -- Unknown visibility -------------------------------------------------

    def test_unknown_visibility_defaults_to_deny(self):
        from mcpgateway.services.a2a_server_service import _check_server_access

        server = self._make_server(visibility="unknown-value", owner_email="user@test.com")
        assert _check_server_access(server, "user@test.com", ["team-a"]) is False
