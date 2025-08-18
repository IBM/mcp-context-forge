# -*- coding: utf-8 -*-
"""External plugins package.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Fred Araujo

Exposes external plugin components:
- server
"""

from mcpgateway.plugins.framework.external.mcp.server.server import ExternalPluginServer

__all__ = ["ExternalPluginServer"]
