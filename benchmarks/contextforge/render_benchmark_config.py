# -*- coding: utf-8 -*-
"""Render benchmark-specific plugin configuration from scenario TOML."""

from __future__ import annotations

# Standard
from copy import deepcopy
from pathlib import Path
from typing import Any

# Third-Party
import yaml

BASE_PLUGIN_CONFIG = Path(__file__).resolve().parents[2] / "plugins" / "config.yaml"


def load_plugin_catalog(config_path: Path | None = None) -> dict[str, Any]:
    """Load the base plugin config and build lookup maps."""
    path = config_path or BASE_PLUGIN_CONFIG
    with path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}
    plugins = config.get("plugins", [])
    config["_by_name"] = {plugin["name"]: plugin for plugin in plugins}
    config["_by_lower"] = {plugin["name"].lower(): plugin["name"] for plugin in plugins}
    aliases: dict[str, str] = {}
    for plugin in plugins:
        name = str(plugin["name"])
        lowered = name.lower()
        aliases[lowered] = name
        if lowered.endswith("plugin"):
            aliases[lowered.removesuffix("plugin")] = name
        else:
            aliases[f"{lowered}plugin"] = name
    config["_aliases"] = aliases
    return config


def resolve_plugin_name(name: str, catalog: dict[str, Any]) -> str:
    """Resolve a scenario plugin key to a base config plugin name."""
    if name in catalog["_by_name"]:
        return name
    lowered = name.lower()
    if lowered in catalog["_by_lower"]:
        return catalog["_by_lower"][lowered]
    if lowered in catalog.get("_aliases", {}):
        return catalog["_aliases"][lowered]
    raise KeyError(f"Unknown plugin '{name}' in benchmark scenario")


def render_plugin_config(scenario: dict[str, Any], output_path: Path, base_config_path: Path | None = None) -> Path:
    """Render a plugin YAML for a benchmark scenario."""
    catalog = load_plugin_catalog(base_config_path)
    plugin_settings = deepcopy(catalog.get("plugin_settings", {}))
    rendered_plugins: list[dict[str, Any]] = []

    scenario_plugins = scenario.get("plugins", {}) or {}
    setup = scenario.get("setup", {}) or {}
    plugins_enabled = bool(setup.get("plugins_enabled", False))

    if plugins_enabled:
        for configured_name, benchmark_cfg in scenario_plugins.items():
            resolved_name = resolve_plugin_name(configured_name, catalog)
            base_plugin = deepcopy(catalog["_by_name"][resolved_name])
            plugin_mode = (benchmark_cfg or {}).get("mode", "auto")
            enabled = (benchmark_cfg or {}).get("enabled", plugin_mode != "off")

            if not enabled or plugin_mode == "off":
                base_plugin["mode"] = "disabled"
            else:
                base_plugin["mode"] = (benchmark_cfg or {}).get("policy_mode", "permissive")

            merged_plugin_config = deepcopy(base_plugin.get("config", {}) or {})
            merged_plugin_config.update((benchmark_cfg or {}).get("config", {}))
            if plugin_mode in {"python", "rust", "auto"}:
                merged_plugin_config["implementation_mode"] = plugin_mode
            base_plugin["config"] = merged_plugin_config
            rendered_plugins.append(base_plugin)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    rendered = {"plugin_dirs": catalog.get("plugin_dirs", []), "plugin_settings": plugin_settings, "plugins": rendered_plugins}
    with output_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(rendered, handle, sort_keys=False)
    return output_path
