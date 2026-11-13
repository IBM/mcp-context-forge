# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_a2a_protocol_binding.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for the stored A2A protocol binding (create, read and update).
"""

# Future
from __future__ import annotations

# Standard
from unittest.mock import AsyncMock, MagicMock, Mock, patch

# Third-Party
from pydantic import ValidationError
import pytest

# First-Party
from mcpgateway.schemas import A2AAgentCreate, A2AAgentRead, A2AAgentUpdate
from mcpgateway.services.a2a_service import A2AAgentService


@pytest.fixture
def a2a_service():
    """Create an A2AAgentService instance."""
    return A2AAgentService()


@pytest.fixture
def mock_db():
    """Create a mock database session."""
    db = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db.execute = Mock(return_value=result)
    return db


def _create(**overrides) -> A2AAgentCreate:
    data = {"name": "binding_agent", "endpoint_url": "https://agent.example/a2a/", "agent_type": "custom"}
    data.update(overrides)
    return A2AAgentCreate(**data)


class TestProtocolBindingSchemas:
    def test_create_defaults_to_none(self):
        assert _create().protocol_binding is None

    @pytest.mark.parametrize("binding", ["jsonrpc", "http_json"])
    def test_create_accepts_known_bindings(self, binding):
        assert _create(protocol_binding=binding).protocol_binding == binding

    def test_create_rejects_unknown_binding(self):
        with pytest.raises(ValidationError):
            _create(protocol_binding="grpc")

    def test_update_rejects_unknown_binding(self):
        with pytest.raises(ValidationError):
            A2AAgentUpdate(protocol_binding="grpc")

    def test_read_exposes_binding(self):
        assert "protocol_binding" in A2AAgentRead.model_fields


class TestProtocolBindingPersistence:
    @pytest.mark.asyncio
    async def test_register_stores_binding(self, a2a_service, mock_db, monkeypatch):
        mock_read = Mock()
        mock_read.masked.return_value = mock_read
        monkeypatch.setattr(a2a_service, "convert_agent_to_read", Mock(return_value=mock_read))

        # First-Party
        from mcpgateway.services.tool_service import tool_service

        with patch.object(tool_service, "create_tool_from_a2a_agent", new=AsyncMock(return_value=None)):
            await a2a_service.register_agent(mock_db, _create(protocol_binding="http_json"))

        added_agent = mock_db.add.call_args[0][0]
        assert added_agent.protocol_binding == "http_json"

    @pytest.mark.asyncio
    async def test_update_sets_binding(self, a2a_service, mock_db, monkeypatch):
        agent = MagicMock()
        agent.id = "agent-123"
        agent.name = "binding_agent"
        agent.endpoint_url = "https://agent.example/a2a/"
        agent.auth_type = None
        agent.auth_value = None
        agent.auth_query_params = None
        agent.enabled = True
        agent.version = 1
        agent.visibility = "public"
        agent.team_id = None
        agent.owner_email = None
        agent.passthrough_headers = None
        agent.protocol_binding = None
        agent.__table__ = MagicMock()
        agent.__table__.columns = []

        mock_read = Mock()
        mock_read.masked.return_value = mock_read
        monkeypatch.setattr(a2a_service, "convert_agent_to_read", Mock(return_value=mock_read))

        # First-Party
        from mcpgateway.services.tool_service import tool_service

        with patch("mcpgateway.services.a2a_service.get_for_update", return_value=agent):
            with patch.object(tool_service, "update_tool_from_a2a_agent", new=AsyncMock()):
                await a2a_service.update_agent(mock_db, "agent-123", A2AAgentUpdate(protocol_binding="jsonrpc"))

        assert agent.protocol_binding == "jsonrpc"
