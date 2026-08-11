# -*- coding: utf-8 -*-
"""Pure deterministic compilation of tool plugin bindings into CPEX config."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Final, assert_never

from cpex.framework import OnError, PluginMode
from cpex.framework.models import Config, PluginConfig
from pydantic import BaseModel, ConfigDict, Field, JsonValue


class BindingSource(StrEnum):
    """Persisted binding domain."""

    TOOL = "tool"
    A2A = "a2a"


class BindingCompilationErrorCode(StrEnum):
    """Stable machine-readable compiler failure categories."""

    UNKNOWN_PLUGIN = "unknown_plugin"
    DUPLICATE_PLUGIN = "duplicate_plugin"
    UNSUPPORTED_MODE = "unsupported_mode"
    UNSUPPORTED_ON_ERROR = "unsupported_on_error"
    RUNTIME_OVERRIDE_MISMATCH = "runtime_override_mismatch"


class BindingCompilationError(Exception):
    """Sanitized failure raised when binding state is not representable."""

    __slots__ = ("code", "plugin_id")

    def __init__(self, code: BindingCompilationErrorCode, plugin_id: str | None = None) -> None:
        """Store only the stable category and sanitized plugin identifier."""
        super().__init__(code.value, plugin_id)
        self.code = code
        self.plugin_id = plugin_id

    def __str__(self) -> str:
        """Return a sanitized operator-facing failure reason."""
        plugin = f" for plugin {self.plugin_id}" if self.plugin_id is not None else ""
        return f"tool binding compilation failed: {self.code.value}{plugin}"


class ToolBinding(BaseModel):
    """Validated persistence-neutral input for one plugin binding row."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    plugin_id: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    mode: str = Field(min_length=1)
    priority: int = Field(ge=1, le=1000)
    config: dict[str, JsonValue]
    on_error: str | None = None
    source: BindingSource = BindingSource.TOOL


class RuntimeModeOverride(BaseModel):
    """Redis and process-local observations for one runtime mode override."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    plugin_id: str = Field(min_length=1)
    redis_mode: str | None = None
    local_mode: str | None = None


@dataclass(frozen=True, slots=True)
class BindingCompilationInput:
    """All state needed to compile one tool's effective CPEX configuration."""

    operator_config: Config
    tool_name: str
    bindings: tuple[ToolBinding, ...]
    runtime_overrides: tuple[RuntimeModeOverride, ...] = ()


@dataclass(frozen=True, slots=True)
class ResolvedBindingMode:
    """Canonical CPEX mode and any error behavior implied by a legacy mode."""

    mode: PluginMode
    implied_on_error: OnError | None


_LEGACY_MODES: Final[dict[str, ResolvedBindingMode]] = {
    "enforce": ResolvedBindingMode(PluginMode.SEQUENTIAL, None),
    "enforce_ignore_error": ResolvedBindingMode(PluginMode.SEQUENTIAL, OnError.IGNORE),
    "permissive": ResolvedBindingMode(PluginMode.TRANSFORM, None),
    "disabled": ResolvedBindingMode(PluginMode.DISABLED, None),
}
_FAIL_CLOSED_TAGS: Final[frozenset[str]] = frozenset({"security", "auth", "authorization", "access-control", "rbac", "abac", "pdp", "mac"})
_AUTHORIZATION_HOOKS: Final[frozenset[str]] = frozenset({"http_auth_resolve_user", "http_auth_check_permission"})


def resolve_binding_mode(raw_mode: str, plugin_id: str | None = None) -> ResolvedBindingMode:
    """Resolve legacy and modern mode names into canonical CPEX semantics."""
    legacy = _LEGACY_MODES.get(raw_mode)
    if legacy is not None:
        return legacy
    try:
        return ResolvedBindingMode(PluginMode(raw_mode), None)
    except ValueError:
        raise BindingCompilationError(BindingCompilationErrorCode.UNSUPPORTED_MODE, _safe_plugin_id(plugin_id)) from None


def compile_tool_bindings(source: BindingCompilationInput) -> Config:
    """Compile operator definitions and persisted tool bindings deterministically."""
    operator_plugins = source.operator_config.plugins or []
    operator_by_id: dict[str, PluginConfig] = {}
    for plugin in operator_plugins:
        if plugin.name in operator_by_id:
            raise BindingCompilationError(BindingCompilationErrorCode.DUPLICATE_PLUGIN, _safe_plugin_id(plugin.name))
        operator_by_id[plugin.name] = _force_fail_closed(plugin)

    candidates: dict[str, list[ToolBinding]] = {}
    for binding in source.bindings:
        match binding.source:
            case BindingSource.TOOL:
                if binding.tool_name not in {source.tool_name, "*"}:
                    continue
                if binding.plugin_id not in operator_by_id:
                    raise BindingCompilationError(BindingCompilationErrorCode.UNKNOWN_PLUGIN, _safe_plugin_id(binding.plugin_id))
                candidates.setdefault(binding.plugin_id, []).append(binding)
            case BindingSource.A2A:
                continue
            case unreachable:
                assert_never(unreachable)

    effective = dict(operator_by_id)
    for plugin_id in sorted(candidates):
        rows = candidates[plugin_id]
        exact = [binding for binding in rows if binding.tool_name == source.tool_name]
        wildcard = [binding for binding in rows if binding.tool_name == "*"]
        if len(exact) > 1 or len(wildcard) > 1:
            raise BindingCompilationError(BindingCompilationErrorCode.DUPLICATE_PLUGIN, _safe_plugin_id(plugin_id))
        binding = exact[0] if exact else wildcard[0]
        effective[plugin_id] = _apply_binding(operator_by_id[plugin_id], binding)

    seen_runtime_plugins: set[str] = set()
    for override in source.runtime_overrides:
        if override.plugin_id not in effective:
            raise BindingCompilationError(BindingCompilationErrorCode.UNKNOWN_PLUGIN, _safe_plugin_id(override.plugin_id))
        if override.plugin_id in seen_runtime_plugins:
            raise BindingCompilationError(BindingCompilationErrorCode.DUPLICATE_PLUGIN, _safe_plugin_id(override.plugin_id))
        seen_runtime_plugins.add(override.plugin_id)
        redis_mode = resolve_binding_mode(override.redis_mode, override.plugin_id) if override.redis_mode is not None else None
        local_mode = resolve_binding_mode(override.local_mode, override.plugin_id) if override.local_mode is not None else None
        if redis_mode is None and local_mode is None:
            raise BindingCompilationError(BindingCompilationErrorCode.RUNTIME_OVERRIDE_MISMATCH, _safe_plugin_id(override.plugin_id))
        if redis_mode is not None and local_mode is not None and redis_mode != local_mode:
            raise BindingCompilationError(BindingCompilationErrorCode.RUNTIME_OVERRIDE_MISMATCH, _safe_plugin_id(override.plugin_id))
        raw_mode = override.redis_mode if override.redis_mode is not None else override.local_mode
        if raw_mode is None:
            raise BindingCompilationError(BindingCompilationErrorCode.RUNTIME_OVERRIDE_MISMATCH, _safe_plugin_id(override.plugin_id))
        effective[override.plugin_id] = apply_runtime_mode_override(effective[override.plugin_id], raw_mode)

    ordered = sorted(effective.values(), key=lambda plugin: (plugin.priority, plugin.name))
    return source.operator_config.model_copy(update={"plugins": ordered}, deep=True)


def apply_runtime_mode_override(plugin: PluginConfig, raw_mode: str) -> PluginConfig:
    """Apply one runtime mode value without weakening mandatory controls."""
    resolved = resolve_binding_mode(raw_mode, plugin.name)
    update: dict[str, PluginMode | OnError] = {"mode": resolved.mode}
    if resolved.implied_on_error is not None:
        update["on_error"] = resolved.implied_on_error
    return _force_fail_closed(plugin.model_copy(update=update))


def _apply_binding(operator_plugin: PluginConfig, binding: ToolBinding) -> PluginConfig:
    resolved = resolve_binding_mode(binding.mode, binding.plugin_id)
    on_error = operator_plugin.on_error
    if resolved.implied_on_error is not None:
        on_error = resolved.implied_on_error
    if binding.on_error is not None:
        try:
            on_error = OnError(binding.on_error)
        except ValueError:
            raise BindingCompilationError(BindingCompilationErrorCode.UNSUPPORTED_ON_ERROR, _safe_plugin_id(binding.plugin_id)) from None
    plugin = operator_plugin.model_copy(
        update={
            "config": dict(binding.config),
            "mode": resolved.mode,
            "on_error": on_error,
            "priority": binding.priority,
        }
    )
    return _force_fail_closed(plugin)


def _force_fail_closed(plugin: PluginConfig) -> PluginConfig:
    tags = {tag.casefold() for tag in plugin.tags}
    if tags.isdisjoint(_FAIL_CLOSED_TAGS) and set(plugin.hooks).isdisjoint(_AUTHORIZATION_HOOKS):
        return plugin
    return plugin.model_copy(update={"on_error": OnError.FAIL})


def _safe_plugin_id(plugin_id: str | None) -> str | None:
    if plugin_id is None or len(plugin_id) > 64 or not all(character.isalnum() or character in "._-" for character in plugin_id):
        return None
    return plugin_id
