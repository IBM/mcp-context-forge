# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_server_interfaces.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for publishing protocol interfaces on virtual servers.
"""

# Standard
from types import SimpleNamespace

# Third-Party
from pydantic import ValidationError
import pytest

# First-Party
from mcpgateway.db import ServerInterface as DbServerInterface
from mcpgateway.schemas import ServerCreate, ServerInterfaceInput, ServerUpdate
from mcpgateway.services.server_service import _apply_server_interfaces


def _iface(**overrides):
    data = {"protocol": "a2a", "binding": "https://agent.example.com/a2a", "version": "1.0"}
    data.update(overrides)
    return ServerInterfaceInput(**data)


class TestInterfaceSchemas:
    def test_create_accepts_interfaces(self):
        server = ServerCreate(name="agent-server", interfaces=[{"protocol": " a2a ", "binding": "https://agent.example.com/a2a"}])
        assert server.interfaces[0].protocol == "a2a"
        assert server.interfaces[0].enabled is True

    def test_interfaces_default_to_none(self):
        assert ServerCreate(name="s").interfaces is None
        assert ServerUpdate().interfaces is None

    def test_duplicate_protocol_binding_rejected(self):
        with pytest.raises(ValidationError):
            ServerCreate(name="s", interfaces=[{"protocol": "a2a", "binding": "https://agent.example.com/a2a"}, {"protocol": "A2A", "binding": "https://agent.example.com/A2A"}])

    def test_update_rejects_duplicates(self):
        with pytest.raises(ValidationError):
            ServerUpdate(interfaces=[{"protocol": "a2a", "binding": "https://agent.example.com/a2a"}, {"protocol": "a2a", "binding": "https://agent.example.com/a2a"}])

    @pytest.mark.parametrize("binding", ["JSONRPC", "javascript:alert(1)", "http://169.254.169.254/latest/meta-data"])
    def test_non_url_or_blocked_binding_rejected(self, binding):
        with pytest.raises(ValidationError):
            ServerInterfaceInput(protocol="a2a", binding=binding)

    def test_empty_protocol_rejected(self):
        with pytest.raises(ValidationError):
            ServerInterfaceInput(protocol="", binding="https://agent.example.com/a2a")


class TestApplyServerInterfaces:
    def test_none_leaves_interfaces_untouched(self):
        existing = DbServerInterface(protocol="a2a", binding="https://agent.example.com/a2a", enabled=True)
        server = SimpleNamespace(interfaces=[existing])
        _apply_server_interfaces(server, None)
        assert server.interfaces == [existing]

    def test_creates_new_interface(self):
        server = SimpleNamespace(interfaces=[])
        _apply_server_interfaces(server, [_iface(tenant="acme")])
        assert len(server.interfaces) == 1
        row = server.interfaces[0]
        assert (row.protocol, row.binding, row.version, row.tenant, row.enabled) == ("a2a", "https://agent.example.com/a2a", "1.0", "acme", True)

    def test_updates_matching_row_in_place(self):
        existing = DbServerInterface(id="keep-me", protocol="a2a", binding="https://agent.example.com/a2a", enabled=True, config={"k": "v"})
        server = SimpleNamespace(interfaces=[existing])
        _apply_server_interfaces(server, [_iface(binding="https://agent.example.com/A2A", enabled=False)])
        assert server.interfaces == [existing]
        assert existing.enabled is False
        assert existing.id == "keep-me"
        assert existing.config == {"k": "v"}

    def test_omitted_interfaces_are_removed(self):
        existing = DbServerInterface(protocol="a2a", binding="https://agent.example.com/a2a", enabled=True)
        server = SimpleNamespace(interfaces=[existing])
        _apply_server_interfaces(server, [])
        assert server.interfaces == []
