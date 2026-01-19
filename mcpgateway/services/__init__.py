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

from importlib import import_module
from typing import Any, TYPE_CHECKING

from mcpgateway.utils.task_scheduler import task_scheduler, Priority  # noqa: E402  # pylint: disable=wrong-import-position

# Public names that previously were exported at package import time. To avoid
# import-time cycles we lazily import the actual service modules when an
# attribute is accessed. Mapping keys are attribute names and values are the
# module paths where the attribute lives.
_LAZY_ATTRS = {
    "ToolService": "mcpgateway.services.tool_service",
    "ToolError": "mcpgateway.services.tool_service",
    "ResourceService": "mcpgateway.services.resource_service",
    "ResourceError": "mcpgateway.services.resource_service",
    "PromptService": "mcpgateway.services.prompt_service",
    "PromptError": "mcpgateway.services.prompt_service",
    "GatewayService": "mcpgateway.services.gateway_service",
    "GatewayError": "mcpgateway.services.gateway_service",
}

if TYPE_CHECKING:
    # Provide names for static analysis (pylint/ruff/mypy) without importing
    # the service submodules at runtime.
    from mcpgateway.services.tool_service import ToolService, ToolError  # noqa: F401
    from mcpgateway.services.resource_service import ResourceService, ResourceError  # noqa: F401
    from mcpgateway.services.prompt_service import PromptService, PromptError  # noqa: F401
    from mcpgateway.services.gateway_service import GatewayService, GatewayError  # noqa: F401


def __getattr__(name: str) -> Any:
    """Lazily import and return package-level attributes.

    This avoids importing many service submodules at package import time,
    which can cause import cycles reported by linters.
    """
    # Expose task scheduler and Priority directly
    if name in {"task_scheduler", "Priority"}:
        return globals()[name]

    # If it's one of the known attributes, import the module and return it
    if name in _LAZY_ATTRS:
        module = import_module(_LAZY_ATTRS[name])
        value = getattr(module, name)
        globals()[name] = value
        return value

    # Allow lazy import of submodules by name, e.g. mcpgateway.services.metrics_query_service
    if name.islower():
        try:
            mod = import_module(f"mcpgateway.services.{name}")
            globals()[name] = mod
            return mod
        except Exception as exc:  # pragma: no cover - defensive
            raise AttributeError(f"module mcpgateway.services has no attribute {name}") from exc

    raise AttributeError(f"module mcpgateway.services has no attribute {name}")


def __dir__() -> list[str]:
    return sorted(list(globals().keys()) + list(_LAZY_ATTRS.keys()))


__all__ = [
    "ToolService",
    "ToolError",
    "ResourceService",
    "ResourceError",
    "PromptService",
    "PromptError",
    "GatewayService",
    "GatewayError",
    "Priority",
    "task_scheduler",
]
