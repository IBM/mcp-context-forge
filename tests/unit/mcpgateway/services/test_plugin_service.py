# -*- coding: utf-8 -*-
import pytest
from unittest.mock import AsyncMock, MagicMock
from mcpgateway.services.plugin_service import PluginService, get_plugin_service
import mcpgateway.services.plugin_service as plugin_service_module
from mcpgateway.plugins.framework.models import PluginMode


@pytest.fixture(autouse=True)
def _reset_plugin_stats_cache():
    plugin_service_module._ADMIN_STATS_CACHE = None
    yield
    plugin_service_module._ADMIN_STATS_CACHE = None


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


def test_get_all_plugins_enabled_without_config_has_empty_summary():
    class _Plugin:
        config = None

    class _PluginRef:
        name = "sample-no-config"
        mode = PluginMode.ENFORCE
        priority = 1
        hooks = []
        tags = []
        plugin = _Plugin()

    plugin_ref = _PluginRef()

    mock_manager = MagicMock()
    mock_manager._registry.get_all_plugins.return_value = [plugin_ref]
    mock_manager._config.plugins = []

    service = PluginService(mock_manager)
    plugins = service.get_all_plugins()

    assert plugins[0]["name"] == "sample-no-config"
    assert plugins[0]["config_summary"] == {}


def test_get_all_plugins_skips_disabled_config_already_registered():
    plugin_ref = MagicMock()
    plugin_ref.name = "dup-plugin"
    plugin_ref.mode = PluginMode.ENFORCE
    plugin_ref.priority = 1
    plugin_ref.hooks = []
    plugin_ref.tags = []
    plugin_ref.plugin.config.description = "desc"
    plugin_ref.plugin.config.author = "auth"
    plugin_ref.plugin.config.version = "1.0.0"
    plugin_ref.plugin.config.kind = "kind"
    plugin_ref.plugin.config.namespace = "ns"
    plugin_ref.plugin.config.config = {}

    disabled_conf = MagicMock()
    disabled_conf.name = "dup-plugin"
    disabled_conf.mode = PluginMode.DISABLED
    disabled_conf.description = "disabled"
    disabled_conf.author = "auth2"
    disabled_conf.version = "0.1"
    disabled_conf.priority = 100
    disabled_conf.hooks = []
    disabled_conf.tags = []
    disabled_conf.kind = "kind"
    disabled_conf.namespace = "ns"
    disabled_conf.config = {"k": "v"}

    mock_manager = MagicMock()
    mock_manager._registry.get_all_plugins.return_value = [plugin_ref]
    mock_manager._config.plugins = [disabled_conf]

    service = PluginService(mock_manager)
    plugins = service.get_all_plugins()
    assert [p["name"] for p in plugins] == ["dup-plugin"]


def test_get_all_plugins_disabled_without_config_summary():
    disabled_conf = MagicMock()
    disabled_conf.name = "disabled-no-config"
    disabled_conf.mode = PluginMode.DISABLED
    disabled_conf.description = "disabled"
    disabled_conf.author = "auth2"
    disabled_conf.version = "0.1"
    disabled_conf.priority = 100
    disabled_conf.hooks = []
    disabled_conf.tags = []
    disabled_conf.kind = "kind"
    disabled_conf.namespace = "ns"
    disabled_conf.config = {}

    mock_manager = MagicMock()
    mock_manager._registry.get_all_plugins.return_value = []
    mock_manager._config.plugins = [disabled_conf]

    service = PluginService(mock_manager)
    plugins = service.get_all_plugins()

    assert plugins[0]["name"] == "disabled-no-config"
    assert plugins[0]["config_summary"] == {}


def test_get_plugin_by_name_without_manifest_branch():
    class _Cfg:
        description = "desc"
        author = "auth"
        version = "1.0.0"
        kind = "kind"
        namespace = "ns"
        config = {}

    class _Plugin:
        config = _Cfg()

    class _PluginRef:
        name = "nomani"
        mode = PluginMode.ENFORCE
        priority = 1
        hooks = []
        tags = []
        conditions = []
        plugin = _Plugin()

    plugin_ref = _PluginRef()

    mock_manager = MagicMock()
    mock_manager._registry.get_plugin.return_value = plugin_ref
    mock_manager._config.plugins = []

    service = PluginService(mock_manager)
    plugin = service.get_plugin_by_name("nomani")
    assert plugin["name"] == "nomani"
    assert "manifest" not in plugin


def test_get_plugin_by_name_from_disabled_config_fallback():
    mock_manager = MagicMock()
    mock_manager._registry.get_plugin.return_value = None

    disabled_conf = MagicMock()
    disabled_conf.name = "disabled-only"
    disabled_conf.mode = PluginMode.DISABLED
    disabled_conf.description = "disabled"
    disabled_conf.author = "auth"
    disabled_conf.version = "1.0.0"
    disabled_conf.priority = 10
    disabled_conf.hooks = []
    disabled_conf.tags = []
    disabled_conf.kind = "kind"
    disabled_conf.namespace = "ns"
    disabled_conf.conditions = []
    disabled_conf.config = {"k": "v"}
    mock_manager._config.plugins = [disabled_conf]

    service = PluginService(mock_manager)
    plugin = service.get_plugin_by_name("disabled-only")
    assert plugin is not None
    assert plugin["status"] == "disabled"
    assert plugin["name"] == "disabled-only"


@pytest.mark.asyncio
async def test_plugin_statistics_returns_cached_data(mock_manager):
    service = PluginService(mock_manager)
    fake_cache = MagicMock()
    fake_cache.get_plugin_stats = AsyncMock(return_value={"cached": True})
    plugin_service_module._ADMIN_STATS_CACHE = fake_cache

    stats = await service.get_plugin_statistics()

    assert stats == {"cached": True}


def test_get_admin_stats_cache_returns_existing_singleton():
    sentinel = object()
    plugin_service_module._ADMIN_STATS_CACHE = sentinel

    assert plugin_service_module._get_admin_stats_cache() is sentinel
