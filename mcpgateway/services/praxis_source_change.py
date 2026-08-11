"""Conservative typed source-diff classification for Praxis rollback policy."""

from __future__ import annotations

from collections.abc import Callable
from typing import assert_never, TypeVar

from cpex.framework.models import PluginConfig

from mcpgateway.services._praxis_reconciliation import SourceChange
from mcpgateway.services.praxis_bundle_models import AUTHORIZATION_HOOKS, FAIL_CLOSED_TAGS
from mcpgateway.services.praxis_config_models import PraxisConfigSourceSnapshot, PraxisGatewaySource, PraxisPromptSource, PraxisResourceSource, PraxisServerSource, PraxisSourceErrorCode, PraxisToolSource

SourceT = TypeVar("SourceT")


def _by_id(items: tuple[SourceT, ...], identifier: Callable[[SourceT], str]) -> dict[str, SourceT]:
    return {identifier(item): item for item in items}


def _members(before: dict[str, SourceT], after: dict[str, SourceT], changes: set[SourceChange]) -> tuple[str, ...]:
    added = after.keys() - before.keys()
    removed = before.keys() - after.keys()
    if added:
        changes.add(SourceChange.ADDITIVE)
    if removed:
        changes.add(SourceChange.REMOVAL)
    return tuple(sorted(before.keys() & after.keys()))


def _plugin_is_security(plugin: PluginConfig) -> bool:
    return not {tag.casefold() for tag in plugin.tags}.isdisjoint(FAIL_CLOSED_TAGS) or not set(plugin.hooks).isdisjoint(AUTHORIZATION_HOOKS)


def _plugins(before: PraxisToolSource, after: PraxisToolSource, changes: set[SourceChange]) -> None:
    before_plugins = {plugin.name: plugin for plugin in before.compiled_config.plugins or ()}
    after_plugins = {plugin.name: plugin for plugin in after.compiled_config.plugins or ()}
    added = after_plugins.keys() - before_plugins.keys()
    if added:
        changes.add(SourceChange.PLUGIN_POLICY if any(_plugin_is_security(after_plugins[name]) for name in added) else SourceChange.ADDITIVE)
    if before_plugins.keys() - after_plugins.keys() or any(before_plugins[name] != after_plugins[name] for name in before_plugins.keys() & after_plugins.keys()):
        changes.add(SourceChange.PLUGIN_POLICY)
    if before.compiled_config != after.compiled_config and not added and SourceChange.PLUGIN_POLICY not in changes:
        changes.add(SourceChange.UNKNOWN)


def _gateways(before: tuple[PraxisGatewaySource, ...], after: tuple[PraxisGatewaySource, ...], changes: set[SourceChange]) -> None:
    before_map, after_map = _by_id(before, lambda item: item.id), _by_id(after, lambda item: item.id)
    for gateway_id in _members(before_map, after_map, changes):
        old, new = before_map[gateway_id], after_map[gateway_id]
        if old.name != new.name:
            changes.add(SourceChange.DESCRIPTIVE)
        if (old.url, old.transport, old.passthrough_headers, old.add_headers, old.remove_headers) != (new.url, new.transport, new.passthrough_headers, new.add_headers, new.remove_headers):
            changes.add(SourceChange.GATEWAY_ENDPOINT)
        if old.capabilities != new.capabilities:
            changes.add(SourceChange.UNKNOWN)


def _tools(before: tuple[PraxisToolSource, ...], after: tuple[PraxisToolSource, ...], changes: set[SourceChange]) -> None:
    before_map, after_map = _by_id(before, lambda item: item.id), _by_id(after, lambda item: item.id)
    for tool_id in _members(before_map, after_map, changes):
        old, new = before_map[tool_id], after_map[tool_id]
        if old.gateway_id != new.gateway_id:
            changes.add(SourceChange.REASSIGNMENT)
        if old.name != new.name:
            changes.add(SourceChange.UNKNOWN)
        if old.headers != new.headers:
            changes.add(SourceChange.AUTHORIZATION)
        _plugins(old, new, changes)


def _resources(before: tuple[PraxisResourceSource, ...], after: tuple[PraxisResourceSource, ...], changes: set[SourceChange]) -> None:
    before_map, after_map = _by_id(before, lambda item: item.id), _by_id(after, lambda item: item.id)
    for resource_id in _members(before_map, after_map, changes):
        old, new = before_map[resource_id], after_map[resource_id]
        if old.gateway_id != new.gateway_id:
            changes.add(SourceChange.REASSIGNMENT)
        if old.name != new.name:
            changes.add(SourceChange.DESCRIPTIVE)
        if old.uri != new.uri:
            changes.add(SourceChange.UNKNOWN)


def _prompts(before: tuple[PraxisPromptSource, ...], after: tuple[PraxisPromptSource, ...], changes: set[SourceChange]) -> None:
    before_map, after_map = _by_id(before, lambda item: item.id), _by_id(after, lambda item: item.id)
    for prompt_id in _members(before_map, after_map, changes):
        old, new = before_map[prompt_id], after_map[prompt_id]
        if old.gateway_id != new.gateway_id:
            changes.add(SourceChange.REASSIGNMENT)
        if old.name != new.name:
            changes.add(SourceChange.UNKNOWN)


def _server(old: PraxisServerSource, new: PraxisServerSource, changes: set[SourceChange]) -> None:
    if old.name != new.name:
        changes.add(SourceChange.DESCRIPTIVE)
    if old.scope != new.scope:
        changes.add(SourceChange.AUTHORIZATION)
    _gateways(old.gateways, new.gateways, changes)
    _tools(old.tools, new.tools, changes)
    _resources(old.resources, new.resources, changes)
    _prompts(old.prompts, new.prompts, changes)


def classify_source_changes(before: PraxisConfigSourceSnapshot, after: PraxisConfigSourceSnapshot) -> frozenset[SourceChange]:
    """Classify all observable source changes, failing closed for unclassified drift."""
    if before.target_id != after.target_id:
        return frozenset({SourceChange.UNKNOWN})
    changes: set[SourceChange] = set()
    before_servers, after_servers = _by_id(before.servers, lambda item: item.id), _by_id(after.servers, lambda item: item.id)
    for server_id in _members(before_servers, after_servers, changes):
        _server(before_servers[server_id], after_servers[server_id], changes)
    if before.source_fingerprint != after.source_fingerprint and not changes:
        changes.add(SourceChange.UNKNOWN)
    return frozenset(changes)


def classify_source_refusal(code: PraxisSourceErrorCode) -> SourceChange:
    """Map an unrepresentable source refusal to its fail-closed policy class."""
    match code:
        case PraxisSourceErrorCode.OWNER_PRIVATE | PraxisSourceErrorCode.SCOPE_MISMATCH:
            return SourceChange.AUTHORIZATION
        case PraxisSourceErrorCode.URL_USERINFO | PraxisSourceErrorCode.CREDENTIAL_QUERY | PraxisSourceErrorCode.AUTH_MATERIAL | PraxisSourceErrorCode.OAUTH_MATERIAL | PraxisSourceErrorCode.KEY_MATERIAL | PraxisSourceErrorCode.SECRET_HEADER:
            return SourceChange.SECRET_CLASSIFICATION
        case PraxisSourceErrorCode.RUNTIME_OVERRIDE | PraxisSourceErrorCode.INVALID_BINDING:
            return SourceChange.PLUGIN_POLICY
        case PraxisSourceErrorCode.TARGET_NOT_FOUND | PraxisSourceErrorCode.DANGLING_ASSOCIATION | PraxisSourceErrorCode.INVALID_SOURCE:
            return SourceChange.UNKNOWN
        case unreachable:
            assert_never(unreachable)


__all__ = ("classify_source_changes", "classify_source_refusal")
