# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/test_default_plugin_config.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for the committed default plugin configuration.
"""

# Standard
from pathlib import Path

# Third-Party
import yaml

DEFAULT_PLUGIN_CONFIG = Path(__file__).resolve().parents[4] / "plugins" / "config.yaml"


def test_default_plugin_config_ships_every_plugin_disabled():
    """A deployment that uses the default file must not block or rewrite payloads."""
    config = yaml.safe_load(DEFAULT_PLUGIN_CONFIG.read_text(encoding="utf-8"))

    modes = {plugin["name"]: plugin.get("mode") for plugin in config["plugins"]}

    assert "PIIFilterPlugin" in modes
    assert {name: mode for name, mode in modes.items() if mode != "disabled"} == {}
