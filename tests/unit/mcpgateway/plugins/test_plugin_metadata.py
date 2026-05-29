# -*- coding: utf-8 -*-
"""Tests for plugin display metadata resolution."""

# Standard
from email.message import Message
from types import ModuleType, SimpleNamespace

# Third-Party
from cpex.framework.models import Config, PluginConfig

# First-Party
from mcpgateway.plugins import metadata as plugin_metadata


class _Distribution:
    def __init__(self, version: str, author: str | None = None, summary: str | None = None):
        self.version = version
        self.metadata = Message()
        if author is not None:
            self.metadata["Author"] = author
        if summary is not None:
            self.metadata["Summary"] = summary


def test_enrich_config_uses_distribution_metadata_before_config(monkeypatch):
    def _distribution(distribution_name):
        assert distribution_name == "sample-plugin"
        return _Distribution("2.0.0", author="Package Author", summary="Package summary")

    monkeypatch.setattr(plugin_metadata.importlib_metadata, "packages_distributions", lambda: {"sample_plugin": ["sample-plugin"]})
    monkeypatch.setattr(plugin_metadata.importlib_metadata, "distribution", _distribution)

    config = Config(
        plugins=[
            PluginConfig(
                name="sample",
                kind="sample_plugin.SamplePlugin",
                description="config description",
                author="config author",
                version="1.0.0",
            )
        ]
    )

    enriched = plugin_metadata.enrich_config_plugin_metadata(config)
    plugin = enriched.plugins[0]

    assert plugin.version == "2.0.0"
    assert plugin.author == "Package Author"
    assert plugin.description == "Package summary"


def test_resolve_plugin_metadata_uses_loaded_module_without_import(monkeypatch):
    module = ModuleType("module_plugin")
    module.__version__ = "3.0.0"
    module.__author__ = "Module Author"
    module.__description__ = "Module description"

    monkeypatch.setitem(plugin_metadata.sys.modules, "module_plugin", module)
    monkeypatch.setattr(
        plugin_metadata,
        "importlib_metadata",
        SimpleNamespace(packages_distributions=lambda: {}, distribution=lambda _distribution_name: (_ for _ in ()).throw(Exception()), PackageNotFoundError=Exception),
    )

    metadata = plugin_metadata.resolve_plugin_metadata(PluginConfig(name="sample", kind="module_plugin.ModulePlugin"))

    assert metadata["version"] == "3.0.0"
    assert metadata["author"] == "Module Author"
    assert metadata["description"] == "Module description"


def test_resolve_plugin_metadata_falls_back_per_field_when_distribution_metadata_incomplete(monkeypatch):
    def _distribution(distribution_name):
        assert distribution_name == "sample-plugin"
        return _Distribution("2.0.0")

    monkeypatch.setattr(plugin_metadata.importlib_metadata, "packages_distributions", lambda: {"sample_plugin": ["sample-plugin"]})
    monkeypatch.setattr(plugin_metadata.importlib_metadata, "distribution", _distribution)

    metadata = plugin_metadata.resolve_plugin_metadata(
        PluginConfig(
            name="sample",
            kind="sample_plugin.SamplePlugin",
            description="config description",
            author="config author",
            version="1.0.0",
        )
    )

    assert metadata["version"] == "2.0.0"
    assert metadata["author"] == "config author"
    assert metadata["description"] == "config description"


def test_resolve_plugin_metadata_handles_colon_style_kind(monkeypatch):
    def _distribution(distribution_name):
        assert distribution_name == "sample-plugin"
        return _Distribution("2.0.0", author="Package Author", summary="Package summary")

    monkeypatch.setattr(plugin_metadata.importlib_metadata, "packages_distributions", lambda: {"sample_plugin": ["sample-plugin"]})
    monkeypatch.setattr(plugin_metadata.importlib_metadata, "distribution", _distribution)

    metadata = plugin_metadata.resolve_plugin_metadata(PluginConfig(name="sample", kind="sample_plugin.module:SamplePlugin"))

    assert metadata["version"] == "2.0.0"
    assert metadata["author"] == "Package Author"
    assert metadata["description"] == "Package summary"


def test_enrich_config_does_not_write_display_defaults_for_missing_metadata(monkeypatch):
    monkeypatch.setattr(plugin_metadata.importlib_metadata, "packages_distributions", lambda: {})

    config = Config(plugins=[PluginConfig(name="local", kind="plugins.local.LocalPlugin")])
    enriched = plugin_metadata.enrich_config_plugin_metadata(config)
    plugin = enriched.plugins[0]

    assert plugin.description is None
    assert plugin.author is None
    assert plugin.version is None
