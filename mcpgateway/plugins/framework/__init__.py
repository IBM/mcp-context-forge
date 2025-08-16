# -*- coding: utf-8 -*-
"""Plugin framework package.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Fred Araujo

Exposes plugin framework components:
- Plugin (base class)
- PluginManager (loader)
- Models
"""

from mcpgateway.plugins.framework.base import Plugin
from mcpgateway.plugins.framework.external.mcp.server import run_plugin_mcp_server
from mcpgateway.plugins.framework.loader.config import ConfigLoader
from mcpgateway.plugins.framework.manager import PluginManager

__all__ = ["ConfigLoader", "Plugin", "PluginManager", "run_plugin_mcp_server"]
