# -*- coding: utf-8 -*-
"""Tests for mcpgateway.plugins.framework.base."""

# Standard
from unittest.mock import MagicMock

# Third-Party
import pytest
from pydantic import BaseModel

# First-Party
from mcpgateway.plugins.framework.base import Plugin
from mcpgateway.plugins.framework.errors import PluginError
from mcpgateway.plugins.framework.models import PluginConfig, PluginResult
from mcpgateway.plugins.framework.hooks import registry as hook_registry


class DummyPayload(BaseModel):
    value: int


def _config() -> PluginConfig:
    return PluginConfig(
        name="test_plugin",
        description="test",
        author="tester",
        kind="test.Plugin",
        version="1.0.0",
        hooks=["hook"],
        tags=["tag"],
    )


def test_json_to_payload_uses_instance_mapping():
    plugin = Plugin(_config(), hook_payloads={"hook": DummyPayload})
    payload = plugin.json_to_payload("hook", {"value": 7})
    assert isinstance(payload, DummyPayload)
    assert payload.value == 7


def test_json_to_payload_uses_registry(monkeypatch):
    plugin = Plugin(_config())
    registry = MagicMock()
    registry.get_payload_type.return_value = DummyPayload
    monkeypatch.setattr(hook_registry, "get_hook_registry", lambda: registry)

    payload = plugin.json_to_payload("hook", '{"value": 3}')
    assert isinstance(payload, DummyPayload)
    assert payload.value == 3


def test_json_to_payload_missing_type(monkeypatch):
    plugin = Plugin(_config())
    registry = MagicMock()
    registry.get_payload_type.return_value = None
    monkeypatch.setattr(hook_registry, "get_hook_registry", lambda: registry)

    with pytest.raises(PluginError):
        plugin.json_to_payload("missing", {"value": 1})


def test_json_to_result_uses_instance_mapping():
    plugin = Plugin(_config(), hook_results={"hook": PluginResult})
    result = plugin.json_to_result("hook", {"continue_processing": False})
    assert isinstance(result, PluginResult)
    assert result.continue_processing is False


def test_json_to_result_uses_registry(monkeypatch):
    plugin = Plugin(_config())
    registry = MagicMock()
    registry.get_result_type.return_value = PluginResult
    monkeypatch.setattr(hook_registry, "get_hook_registry", lambda: registry)

    result = plugin.json_to_result("hook", '{"continue_processing": true}')
    assert isinstance(result, PluginResult)
    assert result.continue_processing is True


def test_json_to_result_missing_type(monkeypatch):
    plugin = Plugin(_config())
    registry = MagicMock()
    registry.get_result_type.return_value = None
    monkeypatch.setattr(hook_registry, "get_hook_registry", lambda: registry)

    with pytest.raises(PluginError):
        plugin.json_to_result("missing", {"continue_processing": True})
