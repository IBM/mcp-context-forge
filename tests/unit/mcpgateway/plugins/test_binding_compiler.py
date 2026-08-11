# -*- coding: utf-8 -*-
"""Characterization and contract tests for CPEX tool-binding compilation."""

import random
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from cpex.framework import OnError, PluginMode
from cpex.framework.models import Config, PluginConfig
from pydantic import ValidationError
import pytest

from mcpgateway.plugins.binding_compiler import (
    BindingCompilationError,
    BindingCompilationErrorCode,
    BindingCompilationInput,
    BindingSource,
    RuntimeModeOverride,
    ToolBinding,
    compile_tool_bindings,
)
from mcpgateway.plugins.gateway_plugin_manager import TenantPluginManagerFactory


@pytest.mark.asyncio
async def test_runtime_config_characterization_when_bindings_are_representable() -> None:
    """Pin the observable runtime config before extracting binding compilation."""
    # Given
    operator_config = Config(
        plugins=[
            PluginConfig(
                name="RateLimiterPlugin",
                kind="plugins.rate_limiter.RateLimiterPlugin",
                hooks=["tool_pre_invoke"],
                tags=["limits"],
                mode=PluginMode.DISABLED,
                on_error=OnError.FAIL,
                priority=90,
                config={"backend": "memory", "by_user": None},
            ),
            PluginConfig(
                name="OutputLengthGuardPlugin",
                kind="plugins.output_length_guard.OutputLengthGuardPlugin",
                hooks=["tool_post_invoke"],
                tags=["limits"],
                mode=PluginMode.DISABLED,
                on_error=OnError.FAIL,
                priority=80,
                config={"max_chars": 999, "strategy": "block"},
            ),
        ]
    )
    bindings = [
        SimpleNamespace(
            plugin_id="RateLimiterPlugin",
            tool_name="*",
            mode="permissive",
            priority=20,
            config={"backend": "memory", "by_user": "60/m"},
            on_error=None,
        ),
        SimpleNamespace(
            plugin_id="OutputLengthGuardPlugin",
            tool_name="summarize",
            mode="enforce",
            priority=42,
            config={"max_chars": 500, "strategy": "truncate"},
            on_error="ignore",
        ),
    ]
    session = MagicMock()
    factory = TenantPluginManagerFactory.__new__(TenantPluginManagerFactory)
    factory._base_config = operator_config
    factory._db_factory = MagicMock(return_value=session)

    # When
    with patch("mcpgateway.plugins.gateway_plugin_manager.get_bindings_for_tool", return_value=bindings):
        overrides = await factory.get_config_from_db("team-a::summarize")
    effective = factory._merge_tenant_config(overrides)

    # Then
    assert operator_config.plugins is not None
    assert effective.model_dump(mode="json")["plugins"] == [
        {
            **operator_config.plugins[0].model_dump(mode="json"),
            "config": {"backend": "memory", "by_user": "60/m"},
            "mode": "transform",
            "priority": 20,
        },
        {
            **operator_config.plugins[1].model_dump(mode="json"),
            "config": {"max_chars": 500, "strategy": "truncate"},
            "mode": "sequential",
            "on_error": "ignore",
            "priority": 42,
        },
    ]
    session.close.assert_called_once_with()


def test_runtime_config_characterization_when_no_bindings_exist() -> None:
    """The runtime normalizes mandatory operator plugins without DB bindings."""
    # Given
    operator_config = Config(plugins=[PluginConfig(name="GlobalAuthPlugin", kind="plugins.auth.GlobalAuthPlugin", hooks=["http_auth_check_permission"], on_error=OnError.IGNORE)])
    factory = TenantPluginManagerFactory.__new__(TenantPluginManagerFactory)
    factory._base_config = operator_config

    # When
    effective = factory._merge_tenant_config(None)

    # Then
    assert effective.plugins is not None
    assert effective.plugins[0].on_error is OnError.FAIL


def _operator_config() -> Config:
    return Config(
        plugins=[
            PluginConfig(
                name="AlphaPlugin",
                kind="plugins.alpha.AlphaPlugin",
                hooks=["tool_pre_invoke"],
                tags=["transform"],
                mode=PluginMode.DISABLED,
                on_error=OnError.FAIL,
                priority=80,
                config={"operator_only": True, "threshold": 1},
            ),
            PluginConfig(
                name="SecurityPlugin",
                kind="plugins.security.SecurityPlugin",
                hooks=["tool_pre_invoke"],
                tags=["security"],
                mode=PluginMode.DISABLED,
                on_error=OnError.IGNORE,
                priority=90,
                config={"operator_only": True},
            ),
            PluginConfig(
                name="AuthorizationPlugin",
                kind="plugins.authorization.AuthorizationPlugin",
                hooks=["http_auth_check_permission"],
                tags=["auth"],
                mode=PluginMode.SEQUENTIAL,
                on_error=OnError.IGNORE,
                priority=30,
                config={"operator_only": True},
            ),
        ]
    )


def _binding(
    plugin_id: str = "AlphaPlugin",
    *,
    tool_name: str = "summarize",
    mode: str = "sequential",
    priority: int = 50,
    on_error: str | None = None,
    source: BindingSource = BindingSource.TOOL,
) -> ToolBinding:
    return ToolBinding(
        plugin_id=plugin_id,
        tool_name=tool_name,
        mode=mode,
        priority=priority,
        config={"binding": plugin_id},
        on_error=on_error,
        source=source,
    )


def _compile(*bindings: ToolBinding, runtime_overrides: tuple[RuntimeModeOverride, ...] = ()) -> Config:
    return compile_tool_bindings(
        BindingCompilationInput(
            operator_config=_operator_config(),
            tool_name="summarize",
            bindings=bindings,
            runtime_overrides=runtime_overrides,
        )
    )


def test_compilation_is_stable_when_exact_and_wildcard_rows_are_shuffled() -> None:
    """Exact precedence and effective ordering do not depend on DB row order."""
    # Given
    rows = [
        _binding(tool_name="*", mode="permissive", priority=1),
        _binding(mode="concurrent", priority=30, on_error="disable"),
        _binding("SecurityPlugin", mode="audit", priority=10, on_error="ignore"),
    ]

    # When
    outputs = []
    for seed in range(20):
        shuffled = rows.copy()
        random.Random(seed).shuffle(shuffled)
        outputs.append(_compile(*shuffled).model_dump_json())

    # Then
    assert len(set(outputs)) == 1
    plugins = _compile(*rows).plugins
    assert plugins is not None
    assert [plugin.name for plugin in plugins] == ["SecurityPlugin", "AlphaPlugin", "AuthorizationPlugin"]
    assert plugins[1].mode is PluginMode.CONCURRENT
    assert plugins[1].config == {"binding": "AlphaPlugin"}
    assert plugins[1].on_error is OnError.DISABLE


def test_explicit_on_error_is_preserved_for_non_security_plugin() -> None:
    """A binding-level error policy overrides the operator default."""
    # Given / When
    plugins = _compile(_binding(on_error="ignore")).plugins

    # Then
    assert plugins is not None
    assert next(plugin for plugin in plugins if plugin.name == "AlphaPlugin").on_error is OnError.IGNORE


@pytest.mark.parametrize("plugin_id", ["SecurityPlugin", "AuthorizationPlugin"])
def test_mandatory_security_plugin_forces_fail_when_binding_requests_ignore(plugin_id: str) -> None:
    """Security and authorization controls fail closed on execution errors."""
    # Given / When
    plugins = _compile(_binding(plugin_id, on_error="ignore")).plugins

    # Then
    assert plugins is not None
    assert next(plugin for plugin in plugins if plugin.name == plugin_id).on_error is OnError.FAIL


@pytest.mark.parametrize("plugin_id", ["SecurityPlugin", "AuthorizationPlugin"])
def test_global_mandatory_plugin_forces_fail_without_binding(plugin_id: str) -> None:
    """Unbound mandatory controls also deny when plugin execution fails."""
    # Given / When
    plugins = _compile().plugins

    # Then
    assert plugins is not None
    assert next(plugin for plugin in plugins if plugin.name == plugin_id).on_error is OnError.FAIL


def test_unknown_plugin_is_rejected() -> None:
    """A binding cannot name a plugin absent from operator configuration."""
    # Given / When
    with pytest.raises(BindingCompilationError) as captured:
        _compile(_binding("UnknownPlugin"))

    # Then
    assert captured.value.code is BindingCompilationErrorCode.UNKNOWN_PLUGIN


def test_duplicate_effective_plugin_is_rejected() -> None:
    """Two exact rows cannot resolve to the same effective plugin."""
    # Given / When
    with pytest.raises(BindingCompilationError) as captured:
        _compile(_binding(priority=10), _binding(priority=20))

    # Then
    assert captured.value.code is BindingCompilationErrorCode.DUPLICATE_PLUGIN


@pytest.mark.parametrize("mode", ["legacy_strict", "modern_stream"])
def test_unsupported_modern_or_legacy_mode_is_rejected_without_echoing_value(mode: str) -> None:
    """Unsupported persisted modes fail with a typed, sanitized error."""
    # Given / When
    with pytest.raises(BindingCompilationError) as captured:
        _compile(_binding(mode=mode))

    # Then
    assert captured.value.code is BindingCompilationErrorCode.UNSUPPORTED_MODE
    assert mode not in str(captured.value)


def test_unsupported_on_error_is_rejected_without_echoing_value() -> None:
    """Malformed persisted error behavior fails with a sanitized category."""
    # Given / When
    with pytest.raises(BindingCompilationError) as captured:
        _compile(_binding(on_error="secret-error-policy"))

    # Then
    assert captured.value.code is BindingCompilationErrorCode.UNSUPPORTED_ON_ERROR
    assert "secret-error-policy" not in str(captured.value)


def test_malformed_binding_config_is_rejected_at_the_typed_boundary() -> None:
    """Non-JSON DB config cannot enter deterministic compilation."""
    # Given / When / Then
    with pytest.raises(ValidationError):
        ToolBinding.model_validate(
            {
                "plugin_id": "AlphaPlugin",
                "tool_name": "summarize",
                "mode": "sequential",
                "priority": 50,
                "config": {"malformed": b"\xff"},
            }
        )


def test_a2a_binding_is_excluded_from_tool_compilation() -> None:
    """A2A rows cannot alter tool runtime CPEX configuration."""
    # Given / When
    compiled = _compile(_binding("UnknownA2APlugin", source=BindingSource.A2A))

    # Then
    assert compiled == _compile()


def test_redis_and_local_override_mismatch_is_rejected() -> None:
    """Node-local mode drift is not a deterministic renderer input."""
    # Given
    override = RuntimeModeOverride(plugin_id="AlphaPlugin", redis_mode="sequential", local_mode="disabled")

    # When
    with pytest.raises(BindingCompilationError) as captured:
        _compile(_binding(), runtime_overrides=(override,))

    # Then
    assert captured.value.code is BindingCompilationErrorCode.RUNTIME_OVERRIDE_MISMATCH


@pytest.mark.parametrize(
    ("redis_mode", "local_mode"),
    [("enforce_ignore_error", None), (None, "enforce_ignore_error"), ("enforce_ignore_error", "enforce_ignore_error")],
)
def test_representable_runtime_override_cannot_weaken_mandatory_security_plugin(redis_mode: str | None, local_mode: str | None) -> None:
    """Single-source or aligned overrides preserve deny-on-error."""
    # Given
    override = RuntimeModeOverride(plugin_id="SecurityPlugin", redis_mode=redis_mode, local_mode=local_mode)

    # When
    plugins = _compile(_binding("SecurityPlugin"), runtime_overrides=(override,)).plugins

    # Then
    assert plugins is not None
    assert next(plugin for plugin in plugins if plugin.name == "SecurityPlugin").on_error is OnError.FAIL
