# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/__init__.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Services Package.
Exposes core MCP Gateway services:
- Tool management
- Resource handling
- Prompt templates
- Gateway coordination
"""

from mcpgateway.utils.task_scheduler import task_scheduler, Priority  # noqa: E402  # pylint: disable=wrong-import-position

# The following imports expose service classes at package-level for convenience.
# They are intentionally placed after the scheduler definition to avoid import
# cycles at module import time. Silence pylint's import-position complaint.
from mcpgateway.services.gateway_service import GatewayError, GatewayService  # pylint: disable=wrong-import-position  # noqa: E402
from mcpgateway.services.prompt_service import PromptError, PromptService  # pylint: disable=wrong-import-position  # noqa: E402
from mcpgateway.services.resource_service import ResourceError, ResourceService  # pylint: disable=wrong-import-position  # noqa: E402
from mcpgateway.services.tool_service import ToolError, ToolService  # pylint: disable=wrong-import-position  # noqa: E402

__all__ = [
    "ToolService",
    "ToolError",
    "ResourceService",
    "ResourceError",
    "PromptService",
    "PromptError",
    "GatewayService",
    "GatewayError",
]

