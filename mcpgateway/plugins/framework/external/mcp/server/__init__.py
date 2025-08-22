# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/framework/external/mcp/server/__init__.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Fred Araujo

External plugins package.
Exposes external plugin components:
- server
"""

from mcpgateway.plugins.framework.external.mcp.server.server import ExternalPluginServer

__all__ = ["ExternalPluginServer"]
