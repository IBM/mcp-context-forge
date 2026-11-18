# SPDX-License-Identifier: Apache-2.0
"""Run the output length guard through native CPEX gateway hooks."""

from __future__ import annotations

import asyncio
from pathlib import Path
import tempfile
import time
from typing import Any, Callable, Literal
from uuid import uuid4

from cpex import PolicyEngine
from pydantic import BaseModel, ConfigDict, Field
import yaml  # type: ignore[import-untyped]

from mcpgateway.common.models import ToolResult
from mcpgateway.plugins._state import active_local_mode_overrides, prune_expired_local_overrides
from mcpgateway.plugins.contracts import (
    Extensions,
    GlobalContext,
    PluginError,
    PluginErrorModel,
    PluginResult,
    PluginRuntimeUnavailable,
    PluginViolation,
    PluginViolationError,
    ToolHookType,
    ToolPostInvokePayload,
)


class _StrictConfig(BaseModel):
    """Reject unsupported configuration fields."""

    model_config = ConfigDict(extra="forbid")


class _HookDispatch(_StrictConfig):
    """Select dispatch through declared plugin hooks."""

    dispatch: Literal["hooks"]


class _OutputLengthGuardConfig(_StrictConfig):
    """Configure the output guard and its isolated worker."""

    class_name: Literal["cpex_output_length_guard.output_length_guard.OutputLengthGuardPlugin"]
    requirements_file: str = Field(min_length=1)
    max_chars: int = Field(default=15000, ge=0)
    min_chars: int = Field(default=0, ge=0)
    strategy: Literal["truncate", "block"] = "truncate"
    ellipsis: str = "…"
    word_boundary: bool = False
    timeout_secs: int = Field(default=30, gt=0)


class _OutputLengthGuard(_StrictConfig):
    """Permit the output guard post-tool hook in enforce mode."""

    name: str = Field(min_length=1)
    kind: Literal["isolated_venv"]
    hooks: list[Literal["cmf.tool_post_invoke"]] = Field(min_length=1, max_length=1)
    mode: Literal["enforce"] = "enforce"
    config: _OutputLengthGuardConfig


class _PluginDocument(_StrictConfig):
    """Restrict native execution to one output guard."""

    engine_settings: _HookDispatch
    plugins: list[_OutputLengthGuard] = Field(min_length=1, max_length=1)


class NativeToolManager:
    """Translate tool results and preserve gateway control decisions."""

    supports_plugin_management = False
    supports_preview = False

    def __init__(self, policy_path: str, timeout: int) -> None:
        """Validate and snapshot native configuration before loading its engine."""
        if timeout <= 0:
            raise ValueError("Native plugin timeout must be positive")
        document_text = Path(policy_path).read_text(encoding="utf-8")
        document = _PluginDocument.model_validate(yaml.safe_load(document_text))
        self.plugin_count = len(document.plugins)
        self._snapshot = tempfile.TemporaryDirectory(prefix="contextforge-native-plugin-")
        try:
            snapshot_path = Path(self._snapshot.name) / "config.yaml"
            snapshot_path.write_text(document_text, encoding="utf-8")
            self._engine = PolicyEngine(str(snapshot_path))
        except BaseException:
            self._snapshot.cleanup()
            raise
        self._timeout = timeout
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        """Initialize plugin workers before gateway execution."""
        async with self._lock:
            await asyncio.wait_for(self._engine.initialize(), timeout=self._timeout)

    async def shutdown(self) -> None:
        """Drain the engine and remove its configuration snapshot."""
        async with self._lock:
            try:
                await self._engine.shutdown()
            finally:
                self._snapshot.cleanup()

    def has_hooks_for(self, hook: str) -> bool:
        """Advertise only the supported post-tool hook."""
        return hook == ToolHookType.TOOL_POST_INVOKE

    async def invoke_hook(
        self,
        hook: str,
        *,
        payload: ToolPostInvokePayload,
        global_context: GlobalContext | None = None,
        local_contexts: dict[str, Any] | None = None,
        violations_as_exceptions: bool = True,
        extensions: Extensions | None = None,
    ) -> tuple[PluginResult[Any], dict[str, Any]]:
        """Run a post-tool hook and translate native results into gateway contracts.

        Args:
            hook: Gateway hook name.
            payload: Complete MCP tool result.
            global_context: Request context for call correlation.
            local_contexts: Native per-plugin context table.
            violations_as_exceptions: Raise structured gateway denials when true.
            extensions: Gateway request telemetry.

        Returns:
            Gateway plugin result and native context table.

        Raises:
            PluginRuntimeUnavailable: The hook or payload is unsupported.
            PluginError: Execution fails or a mutation changes the tool boundary.
            PluginViolationError: A plugin denies output and exceptions are enabled.
        """
        if not self.has_hooks_for(hook) or not isinstance(payload, ToolPostInvokePayload):
            raise PluginRuntimeUnavailable("Native execution supports the output guard post-tool hook only")
        call_id = global_context.request_id if global_context else str(uuid4())
        try:
            result = ToolResult.model_validate(payload.result)
            content = {"tool_call_id": call_id, "tool_name": payload.name, "content": result.model_dump(mode="json", by_alias=True), "is_error": bool(result.is_error)}
            message = {"message": {"role": "tool", "content": [{"content_type": "tool_result", "content": content}]}}
            native_extensions = extensions.model_dump(exclude_none=True) if extensions else {}
            native_extensions["meta"] = {"entity_type": "tool", "entity_name": payload.name}
            async with self._lock:
                native = await asyncio.wait_for(self._engine.invoke_hook("cmf.tool_post_invoke", message, native_extensions, local_contexts), timeout=self._timeout)
            if native.errors:
                raise ValueError("Native tool execution reported errors")
            violation = None
            if not native.continue_processing:
                details = native.violation or {}
                violation = PluginViolation(
                    reason=details.get("reason") or "Native plugin denied tool output",
                    description=details.get("description") or "Native plugin denied tool output",
                    code=details.get("code") or "native_tool_denied",
                    details=details.get("details") or {},
                    mcp_error_code=details.get("proto_error_code"),
                )
            modified = None
            if native.continue_processing and native.payload_modified:
                if native.modified_payload is None:
                    raise ValueError("Native execution reported a mutation without a payload")
                returned = native.modified_payload["message"]
                parts = returned["content"]
                if returned["role"] != "tool" or len(parts) != 1 or parts[0]["content_type"] != "tool_result":
                    raise ValueError("Native mutation changed the tool message boundary")
                part = parts[0]["content"]
                if part["tool_name"] != payload.name or part["tool_call_id"] != call_id or part.get("namespace") is not None:
                    raise ValueError("Native mutation attempted to retarget the tool")
                restored = ToolResult.model_validate(part["content"])
                if bool(restored.is_error) != part["is_error"]:
                    raise ValueError("Native mutation produced inconsistent error flags")
                modified = payload.model_copy(update={"result": restored.model_dump(mode="json", by_alias=True)})
            gateway_result: PluginResult[Any] = PluginResult(continue_processing=native.continue_processing, modified_payload=modified, violation=violation, metadata=native.metadata)
        except (TimeoutError, RuntimeError, ValueError, KeyError, TypeError, IndexError) as exc:
            raise PluginError(PluginErrorModel(message="Native tool execution failed", plugin_name="native_runtime", code="native_tool_error")) from exc
        if violation is not None and violations_as_exceptions:
            raise PluginViolationError(violation.reason, violation=violation)
        return gateway_result, native.context_table


class NativeToolManagerFactory:
    """Manage one global plugin while rejecting unsupported tenant overrides."""

    def __init__(self, policy_path: str, timeout: int, db_factory: Callable[[], Any] | None = None, observability: Any = None) -> None:
        """Construct the manager and retain gateway dependencies."""
        self._manager = NativeToolManager(policy_path, timeout)
        self._db_factory = db_factory
        self.observability = observability
        self._initialized = False
        self._lock = asyncio.Lock()

    @property
    def plugin_names(self) -> list[str]:
        """Return no manageable plugin instances for native execution."""
        return []

    async def get_manager(self, context_id: str | None = None) -> NativeToolManager:
        """Reject unsupported overrides and initialize the engine once."""
        prune_expired_local_overrides(time.monotonic())
        if active_local_mode_overrides(time.monotonic()):
            raise PluginRuntimeUnavailable("Native plugins do not support mode overrides")
        if context_id and "::" in context_id and self._db_factory:
            from mcpgateway.services.tool_plugin_binding_service import get_bindings_for_tool

            team_id, tool_name = context_id.split("::", 1)
            db = self._db_factory()
            try:
                if get_bindings_for_tool(db, team_id, tool_name):
                    raise PluginRuntimeUnavailable("Native plugins do not support team/tool bindings")
            finally:
                db.close()
        async with self._lock:
            if not self._initialized:
                try:
                    await self._manager.initialize()
                except BaseException:
                    await self._manager.shutdown()
                    raise
                self._initialized = True
            return self._manager

    async def invalidate_all(self) -> None:
        """Reject reload until native configuration reload is supported."""
        raise PluginRuntimeUnavailable("Native plugin configuration changes require a gateway restart")

    async def invalidate_team(self, team_id: str) -> None:
        """Reject unsupported tenant invalidation."""
        raise PluginRuntimeUnavailable("Native plugins do not support tenant configuration")

    async def reload_tenant(self, context_id: str) -> NativeToolManager:
        """Reject unsupported tenant reload."""
        raise PluginRuntimeUnavailable("Native plugins do not support tenant configuration")

    async def shutdown(self) -> None:
        """Close the manager when the gateway stops."""
        async with self._lock:
            await self._manager.shutdown()
