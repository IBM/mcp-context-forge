# -*- coding: utf-8 -*-
import pytest
from unittest.mock import MagicMock
from mcpgateway.services.plugin_service import PluginService, get_plugin_service
from mcpgateway.plugins.framework.models import PluginMode


@pytest.fixture
def mock_manager():
    m = MagicMock()
    plugin_ref = MagicMock()
    plugin_ref.name = "sample"
    plugin_ref.mode = PluginMode.ENFORCE
    plugin_ref.priority = 10
    plugin_ref.hooks = ["hookA"]
    plugin_ref.tags = ["tag1", "tag2"]
    plugin_ref.conditions = ["cond"]
    plugin_ref.manifest.available_hooks = ["hookA"]
    plugin_ref.manifest.default_config = {"x": 1}
    plugin_ref.plugin.config.description = "desc"
    plugin_ref.plugin.config.author = "auth"
    plugin_ref.plugin.config.version = "1.0.0"
    plugin_ref.plugin.config.kind = "kind"
    plugin_ref.plugin.config.namespace = "ns"
    plugin_ref.plugin.config.config = {"key": "val"}
    m._registry.get_all_plugins.return_value = [plugin_ref]
    m._registry.get_plugin.side_effect = lambda name: plugin_ref if name == "sample" else None

    disabled_conf = MagicMock()
    disabled_conf.name = "disabled_plugin"
    disabled_conf.mode = PluginMode.DISABLED
    disabled_conf.description = "disabled"
    disabled_conf.author = "auth2"
    disabled_conf.version = "0.1"
    disabled_conf.priority = 100
    disabled_conf.hooks = []
    disabled_conf.tags = ["tagD"]
    disabled_conf.kind = "kind"
    disabled_conf.namespace = "ns"
    disabled_conf.config = {"k": "v"}
    m._config.plugins = [disabled_conf]
    return m


def test_get_plugin_manager_and_setter(mock_manager):
    service = PluginService()
    assert service.get_plugin_manager() is None
    service.set_plugin_manager(mock_manager)
    assert service.get_plugin_manager() == mock_manager


def test_get_all_plugins_empty_manager():
    service = PluginService()
    assert service.get_all_plugins() == []


def test_get_all_plugins_with_manager(mock_manager):
    service = PluginService(mock_manager)
    plugins = service.get_all_plugins()
    names = [p["name"] for p in plugins]
    assert "sample" in names and "disabled_plugin" in names
    assert all("config_summary" in p for p in plugins)


def test_get_plugin_by_name_success(mock_manager):
    service = PluginService(mock_manager)
    plugin = service.get_plugin_by_name("sample")
    assert plugin["name"] == "sample"
    assert "manifest" in plugin


def test_get_plugin_by_name_not_found(mock_manager):
    service = PluginService(mock_manager)
    assert service.get_plugin_by_name("unknown") is None


def test_get_plugin_by_name_no_manager():
    service = PluginService()
    assert service.get_plugin_by_name("something") is None


@pytest.mark.asyncio
async def test_plugin_statistics_no_manager():
    service = PluginService()
    stats = await service.get_plugin_statistics()
    assert stats["total_plugins"] == 0


@pytest.mark.asyncio
async def test_plugin_statistics_with_data(mock_manager):
    service = PluginService(mock_manager)
    stats = await service.get_plugin_statistics()
    assert stats["enabled_plugins"] > 0
    assert "plugins_by_hook" in stats
    assert "plugins_by_mode" in stats
    assert "plugins_by_author" in stats


def test_search_plugins(mock_manager):
    service = PluginService(mock_manager)
    all_p = service.search_plugins()
    assert all_p
    assert service.search_plugins(query="sample")
    assert service.search_plugins(mode=PluginMode.ENFORCE)
    assert service.search_plugins(hook="hookA")
    assert service.search_plugins(tag="tag1")


def test_get_plugin_service_singleton():
    service1 = get_plugin_service()
    service2 = get_plugin_service()
    assert service1 is service2


def test_get_all_plugins_disabled_plugin_config_summary():
    service = PluginService()
    disabled_conf = MagicMock()
    disabled_conf.name = "only_disabled"
    disabled_conf.mode = PluginMode.DISABLED
    disabled_conf.description = "desc"
    disabled_conf.author = "auth"
    disabled_conf.version = "1.1"
    disabled_conf.priority = 50
    disabled_conf.hooks = []
    disabled_conf.tags = []
    disabled_conf.kind = "kind"
    disabled_conf.namespace = "ns"
    disabled_conf.config = {"a": 1, "b": 2, "c": 3, "d": 4, "e": 5, "f": 6}
    mock_manager = MagicMock()
    mock_manager._registry.get_all_plugins.return_value = []
    mock_manager._config.plugins = [disabled_conf]
    service.set_plugin_manager(mock_manager)

    plugins = service.get_all_plugins()
    assert plugins[0]["status"] == "disabled"
    assert len(plugins[0]["config_summary"]) <= 5
