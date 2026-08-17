# -*- coding: utf-8 -*-
# pylint: disable=wrong-import-position,wrong-import-order,no-name-in-module
# ruff: noqa: E402
"""Location: ./mcpgateway/plugins/cpex_compat.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

CPEX version compatibility helpers.

Feature-detects ``ControlExecutionRecord`` availability rather than pinning
a hard import, so the gateway degrades gracefully against older CPEX builds
that do not yet expose execution records.

The minimum supported CPEX version for control-execution telemetry is 0.1.2.
``execution_records_supported()`` is the single guard that all consumption
sites must check before accessing ``PluginResult.executions``.

Examples:
    >>> # When cpex 0.1.2+ is installed:
    >>> from mcpgateway.plugins.cpex_compat import execution_records_supported, get_executions
    >>> isinstance(execution_records_supported(), bool)
    True
    >>> get_executions(None)
    []
"""

from typing import Any, List, Optional

# First-Party
# isort: off
from mcpgateway.utils.mcp_v2_compat import install_mcp_v2_cpex_compat

install_mcp_v2_cpex_compat()

# Third-Party
from cpex.framework import (
    AgentHookType,
    AgentPostInvokePayload,
    AgentPreInvokePayload,
    ConfigLoader,
    GlobalContext,
    HookPayloadPolicy,
    HttpAuthCheckPermissionPayload,
    HttpAuthResolveUserPayload,
    HttpHeaderPayload,
    HttpHookType,
    HttpPostRequestPayload,
    HttpPreRequestPayload,
    ObservabilityProvider,
    OnError,
    PluginContextTable,
    PluginError,
    PluginManager,
    PluginMode,
    PluginViolationError,
    PromptHookType,
    PromptPosthookPayload,
    PromptPrehookPayload,
    ResourceHookType,
    ResourcePostFetchPayload,
    ResourcePreFetchPayload,
    TenantPluginManager,
    ToolHookType,
    ToolPostInvokePayload,
    ToolPreInvokePayload,
    UserContext,
)
from cpex.framework.constants import GATEWAY_METADATA, TOOL_METADATA
from cpex.framework.extensions import Extensions, RequestExtension
from cpex.framework.models import Config
from cpex.framework.observability import current_trace_id
from cpex.framework.settings import settings as plugin_settings
from cpex.framework.utils import parse_class_name, payload_matches

# isort: on

__all__ = [
    "AgentHookType",
    "AgentPostInvokePayload",
    "AgentPreInvokePayload",
    "Config",
    "ConfigLoader",
    "Extensions",
    "GATEWAY_METADATA",
    "GlobalContext",
    "HookPayloadPolicy",
    "HttpAuthCheckPermissionPayload",
    "HttpAuthResolveUserPayload",
    "HttpHeaderPayload",
    "HttpHookType",
    "HttpPostRequestPayload",
    "HttpPreRequestPayload",
    "ObservabilityProvider",
    "OnError",
    "PluginContextTable",
    "PluginError",
    "PluginManager",
    "PluginMode",
    "PluginViolationError",
    "PromptHookType",
    "PromptPosthookPayload",
    "PromptPrehookPayload",
    "RequestExtension",
    "ResourceHookType",
    "ResourcePostFetchPayload",
    "ResourcePreFetchPayload",
    "TOOL_METADATA",
    "TenantPluginManager",
    "ToolHookType",
    "ToolPostInvokePayload",
    "ToolPreInvokePayload",
    "UserContext",
    "current_trace_id",
    "execution_records_supported",
    "get_cpex_cli_module",
    "get_executions",
    "parse_class_name",
    "payload_matches",
    "plugin_settings",
]

_EXECUTION_RECORDS_SUPPORTED: Optional[bool] = None


def get_cpex_cli_module() -> Any:
    """Return the CPEX Typer CLI module after installing MCP v2 aliases."""
    import cpex.tools.cli as plugins  # pylint: disable=import-outside-toplevel

    return plugins


def execution_records_supported() -> bool:
    """Return True if the installed CPEX version exposes ControlExecutionRecord.

    Result is cached after the first call — config is frozen after startup.
    Safe to call from any thread; the cache write is idempotent.

    Returns:
        True when ``cpex.framework.ControlExecutionRecord`` can be imported,
        False otherwise (older CPEX build or CPEX not installed).

    Examples:
        >>> isinstance(execution_records_supported(), bool)
        True
    """
    global _EXECUTION_RECORDS_SUPPORTED  # pylint: disable=global-statement
    if _EXECUTION_RECORDS_SUPPORTED is None:
        try:
            from cpex.framework import ControlExecutionRecord, ControlExecutionStatus  # noqa: F401  # pylint: disable=import-outside-toplevel,unused-import

            _EXECUTION_RECORDS_SUPPORTED = True
        except ImportError:
            _EXECUTION_RECORDS_SUPPORTED = False
    return _EXECUTION_RECORDS_SUPPORTED


def get_executions(result: Any) -> List[Any]:
    """Safely extract the executions list from a PluginResult.

    Returns an empty list if the field is absent (older CPEX), the result is
    None, or any unexpected error occurs.  Never raises.

    Args:
        result: PluginResult returned by ``invoke_hook()`` (may be None).

    Returns:
        A new list containing the ``ControlExecutionRecord`` entries, or ``[]``.

    Examples:
        >>> get_executions(None)
        []
    """
    if result is None:
        return []
    try:
        return list(getattr(result, "executions", None) or [])
    except Exception:  # noqa: BLE001
        return []
