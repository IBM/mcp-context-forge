# SPDX-License-Identifier: Apache-2.0
"""Expose gateway contracts independently of the installed CPEX runtime."""

from contextvars import ContextVar
from dataclasses import dataclass
from importlib import import_module
from types import ModuleType
from typing import Any, Protocol

from pydantic import BaseModel

from mcpgateway.plugins.models import (
    AgentHookType,
    AgentPostInvokePayload,
    AgentPreInvokePayload,
    GlobalContext,
    HttpAuthCheckPermissionPayload,
    HttpAuthCheckPermissionResultPayload,
    HttpAuthResolveUserPayload,
    HttpHeaderPayload,
    HttpHookType,
    HttpPostRequestPayload,
    HttpPreRequestPayload,
    OnError,
    PluginContext,
    PluginContextTable,
    PluginErrorModel,
    PluginMode,
    PluginPayload,
    PluginResult,
    PluginViolation,
    PromptHookType,
    PromptPosthookPayload,
    PromptPrehookPayload,
    RequestExtension,
    ResourceHookType,
    ResourcePostFetchPayload,
    ResourcePreFetchPayload,
    ToolHookType,
    ToolPostInvokePayload,
    ToolPreInvokePayload,
    UserContext,
)

GATEWAY_METADATA = "gateway"
TOOL_METADATA = "tool"
current_trace_id: ContextVar[str | None] = ContextVar("plugin_trace_id", default=None)
_legacy: ModuleType | None
try:
    _legacy = import_module("cpex.framework")
except ModuleNotFoundError as exc:
    if exc.name != "cpex.framework":
        raise
    _legacy = None
LEGACY_RUNTIME_AVAILABLE = _legacy is not None


class PluginRuntimeUnavailable(RuntimeError):
    """Reject unsupported runtime configuration."""


def require_legacy_runtime() -> None:
    """Require the legacy SDK before loading its manager."""
    if not LEGACY_RUNTIME_AVAILABLE:
        raise PluginRuntimeUnavailable("Legacy plugin management requires the CPEX 0.1 SDK")


def require_plugin_runtime() -> None:
    """Require an explicit configuration for native execution."""
    from mcpgateway.plugins.settings import GatewayNativeSettings

    native = GatewayNativeSettings().native_config_file
    if LEGACY_RUNTIME_AVAILABLE:
        if native:
            raise PluginRuntimeUnavailable("Native execution requires the CPEX 0.3.1 wheel")
    elif not native:
        raise PluginRuntimeUnavailable("Set PLUGINS_NATIVE_CONFIG_FILE or disable plugins")


class PluginViolationError(Exception):
    """Carry a plugin denial to gateway error handlers."""

    def __init__(self, message: str, violation: PluginViolation | None = None) -> None:
        """Store the message and structured denial."""
        self.message = message
        self.violation = violation
        self.executions: list[Any] | None = None
        super().__init__(message)


class PluginError(Exception):
    """Carry a plugin execution failure."""

    def __init__(self, error: PluginErrorModel) -> None:
        """Store the structured execution failure."""
        self.error = error
        super().__init__(error.message)


@dataclass(frozen=True)
class HookPayloadPolicy:
    """Declare payload fields that plugins can modify."""

    writable_fields: frozenset[str]


class Extensions(BaseModel):
    """Carry gateway request telemetry."""

    request: RequestExtension | None = None


class PluginManager(Protocol):
    """Describe the manager operations used by gateway hooks."""

    def has_hooks_for(self, hook: str) -> bool:
        """Return whether a hook is registered."""
        ...

    async def invoke_hook(self, hook: str, **kwargs: Any) -> tuple[Any, Any]:
        """Execute a hook with gateway payloads."""
        ...


class ObservabilityProvider(Protocol):
    """Describe the gateway observability provider."""

    def start_span(self, **kwargs: Any) -> str | None:
        """Start an observability span."""
        ...


TenantPluginManager = PluginManager

if _legacy is not None:
    for _name in (
        "PluginMode",
        "OnError",
        "PluginErrorModel",
        "PluginViolation",
        "UserContext",
        "GlobalContext",
        "PluginContext",
        "PluginPayload",
        "HttpHeaderPayload",
        "HttpHookType",
        "HttpPreRequestPayload",
        "HttpPostRequestPayload",
        "HttpAuthResolveUserPayload",
        "HttpAuthCheckPermissionPayload",
        "HttpAuthCheckPermissionResultPayload",
        "ToolHookType",
        "ToolPreInvokePayload",
        "ToolPostInvokePayload",
        "PromptHookType",
        "PromptPrehookPayload",
        "PromptPosthookPayload",
        "ResourceHookType",
        "ResourcePreFetchPayload",
        "ResourcePostFetchPayload",
        "AgentHookType",
        "AgentPreInvokePayload",
        "AgentPostInvokePayload",
        "PluginContextTable",
        "PluginResult",
        "PluginError",
        "PluginViolationError",
        "PluginManager",
        "TenantPluginManager",
        "ObservabilityProvider",
        "HookPayloadPolicy",
    ):
        globals()[_name] = getattr(_legacy, _name)
    _extensions = import_module("cpex.framework.extensions")
    globals()["Extensions"] = _extensions.Extensions
    globals()["RequestExtension"] = _extensions.RequestExtension
    current_trace_id = import_module("cpex.framework.observability").current_trace_id

__all__ = [
    "PluginMode",
    "OnError",
    "PluginErrorModel",
    "PluginViolation",
    "UserContext",
    "GlobalContext",
    "PluginContext",
    "PluginPayload",
    "HttpHeaderPayload",
    "HttpHookType",
    "HttpPreRequestPayload",
    "HttpPostRequestPayload",
    "HttpAuthResolveUserPayload",
    "HttpAuthCheckPermissionPayload",
    "HttpAuthCheckPermissionResultPayload",
    "ToolHookType",
    "ToolPreInvokePayload",
    "ToolPostInvokePayload",
    "PromptHookType",
    "PromptPrehookPayload",
    "PromptPosthookPayload",
    "ResourceHookType",
    "ResourcePreFetchPayload",
    "ResourcePostFetchPayload",
    "AgentHookType",
    "AgentPreInvokePayload",
    "AgentPostInvokePayload",
    "RequestExtension",
    "PluginContextTable",
    "PluginResult",
    "GATEWAY_METADATA",
    "TOOL_METADATA",
    "current_trace_id",
    "LEGACY_RUNTIME_AVAILABLE",
    "PluginRuntimeUnavailable",
    "require_legacy_runtime",
    "require_plugin_runtime",
    "PluginViolationError",
    "PluginError",
    "HookPayloadPolicy",
    "Extensions",
    "PluginManager",
    "TenantPluginManager",
    "ObservabilityProvider",
]
