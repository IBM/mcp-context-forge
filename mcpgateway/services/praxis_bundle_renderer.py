"""Deterministic renderer for immutable Praxis/CPEX full bundles."""

from __future__ import annotations

import hashlib
import json
from typing import Final, assert_never
from urllib.parse import parse_qsl, urlsplit

from cpex.framework.models import PluginCondition, PluginConfig
from pydantic import ConfigDict, JsonValue, TypeAdapter, ValidationError

from mcpgateway.services.praxis_bundle_models import (
    PraxisBundleDocument,
    PraxisCpexDocument,
    PraxisCpexPlugin,
    PraxisCpexPluginCondition,
    PraxisCpexPluginSettings,
    PraxisCpexRoute,
    PraxisFilter,
    PraxisFilterChain,
    PraxisListener,
    PraxisPolicyMapping,
)
from mcpgateway.services.praxis_config_models import (
    PraxisBundleArtifact,
    PraxisBundleBuildRequest,
    PraxisCompatibilityContract,
    PraxisConfigSourceSnapshot,
    PraxisGatewaySource,
    PraxisRenderedDocument,
    PraxisServerSource,
    PraxisSourceSnapshot,
    PraxisToolSource,
    build_praxis_bundle,
    validate_canonical_archive,
)
from mcpgateway.services.praxis_bundle_validation import (
    PraxisBundleRenderError,
    PraxisBundleRenderErrorCode,
    _validation_code,
    parse_cpex_document,
    parse_praxis_document,
    validate_bundle_documents,
)
from mcpgateway.utils.header_filtering import filter_sensitive_headers
from mcpgateway.utils.url_auth import STATIC_SENSITIVE_PARAMS

DEFAULT_PRAXIS_COMPATIBILITY: Final = PraxisCompatibilityContract(
    bundle_schema="praxis-bundle/v1",
    renderer_version="1.0.0",
    praxis_revision="ed46eb5",
    cpex_contract_version="cpex/v1",
    mcp_protocol_version="2025-11-25",
    minimum_launcher_version="0.1.0",
)
_CONFIG_ADAPTER: Final = TypeAdapter(dict[str, JsonValue], config=ConfigDict(strict=True))
_SENSITIVE_CONFIG_KEYS: Final = frozenset((*STATIC_SENSITIVE_PARAMS, "authorization", "client_secret", "private_key", "password"))


def _contains_secret(value: JsonValue, key: str | None = None) -> bool:
    if key is not None and key.casefold() in _SENSITIVE_CONFIG_KEYS and value not in (None, "", [], {}):
        return True
    match value:
        case dict():
            return any(_contains_secret(nested, nested_key) for nested_key, nested in value.items())
        case list():
            return any(_contains_secret(nested) for nested in value)
        case str() | int() | float() | bool() | None:
            return False
        case unreachable:
            assert_never(unreachable)


def _condition(source: PluginCondition) -> PraxisCpexPluginCondition:
    def ordered(values: set[str] | list[str] | None) -> tuple[str, ...] | None:
        return None if values is None else tuple(sorted(values))

    return PraxisCpexPluginCondition(
        server_ids=ordered(source.server_ids),
        tenant_ids=ordered(source.tenant_ids),
        tools=ordered(source.tools),
        prompts=ordered(source.prompts),
        resources=ordered(source.resources),
        agents=ordered(source.agents),
        user_patterns=ordered(source.user_patterns),
        content_types=ordered(source.content_types),
    )


def _plugin(source: PluginConfig) -> PraxisCpexPlugin:
    if source.mcp is not None or source.grpc is not None or source.unix_socket is not None or source.applied_to is not None:
        raise PraxisBundleRenderError(PraxisBundleRenderErrorCode.INCOMPATIBLE_OUTPUT_MODEL)
    config = _CONFIG_ADAPTER.validate_python(source.config or {})
    if _contains_secret(config):
        raise PraxisBundleRenderError(PraxisBundleRenderErrorCode.CREDENTIAL_MATERIAL)
    return PraxisCpexPlugin(
        name=source.name,
        kind=source.kind,
        hooks=tuple(sorted(source.hooks)),
        tags=tuple(sorted(source.tags)),
        mode=source.mode.value,
        on_error=source.on_error.value,
        priority=source.priority,
        capabilities=tuple(sorted(source.capabilities)),
        conditions=tuple(sorted((_condition(item) for item in source.conditions), key=lambda item: item.model_dump_json())),
        config=config,
    )


def _validate_gateway(source: PraxisGatewaySource) -> None:
    parsed = urlsplit(source.url)
    sensitive_query = any(name.casefold() in STATIC_SENSITIVE_PARAMS for name, _ in parse_qsl(parsed.query, keep_blank_values=True))
    named_headers = {name: "" for name in (*source.passthrough_headers, *source.remove_headers)}
    if parsed.username is not None or parsed.password is not None or sensitive_query or filter_sensitive_headers(source.add_headers) != source.add_headers or filter_sensitive_headers(named_headers) != named_headers:
        raise PraxisBundleRenderError(PraxisBundleRenderErrorCode.CREDENTIAL_MATERIAL)
    if source.transport != "STREAMABLEHTTP":
        raise PraxisBundleRenderError(PraxisBundleRenderErrorCode.INCOMPATIBLE_OUTPUT_MODEL)


def _tool_plugins(source: PraxisToolSource) -> tuple[PraxisCpexPlugin, ...]:
    if filter_sensitive_headers(source.headers) != source.headers:
        raise PraxisBundleRenderError(PraxisBundleRenderErrorCode.CREDENTIAL_MATERIAL)
    plugins = source.compiled_config.plugins or []
    rendered_plugins = tuple(sorted((_plugin(plugin) for plugin in plugins), key=lambda plugin: (plugin.priority, plugin.name)))
    return rendered_plugins


def _cpex_document(server: PraxisServerSource) -> PraxisCpexDocument:
    for gateway in server.gateways:
        _validate_gateway(gateway)
    declared: dict[str, PraxisCpexPlugin] = {}
    routes: list[PraxisCpexRoute] = []
    for tool in server.tools:
        plugins = _tool_plugins(tool)
        for plugin in plugins:
            previous = declared.setdefault(plugin.name, plugin)
            if previous != plugin:
                raise PraxisBundleRenderError(PraxisBundleRenderErrorCode.DUPLICATE_PLUGIN)
        routes.append(PraxisCpexRoute(tool=tool.name, plugins=tuple(plugin.name for plugin in plugins)))
    routes.extend(PraxisCpexRoute(resource=item.uri) for item in server.resources)
    routes.extend(PraxisCpexRoute(prompt=item.name) for item in server.prompts)
    routes.sort(key=lambda route: next((kind, value) for kind in ("tool", "resource", "prompt") if (value := getattr(route, kind)) is not None))
    routes.extend((PraxisCpexRoute(tool="*"), PraxisCpexRoute(resource="*"), PraxisCpexRoute(prompt="*")))
    return PraxisCpexDocument(
        plugin_settings=PraxisCpexPluginSettings(),
        plugins=tuple(sorted(declared.values(), key=lambda plugin: plugin.name)),
        routes=tuple(routes),
    )


def _encode(model: PraxisBundleDocument | PraxisCpexDocument) -> bytes:
    payload = model.model_dump(mode="json", by_alias=True, exclude_none=True)
    return (json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")


def render_praxis_bundle(snapshot: PraxisConfigSourceSnapshot) -> PraxisBundleArtifact:
    """Render, reparse, archive, and hash one complete typed source snapshot."""
    try:
        cpex_pairs = tuple((f"cpex/{server.scope}--{server.id}.yaml", _cpex_document(server)) for server in sorted(snapshot.servers, key=lambda item: (item.scope, item.id)))
        policies = tuple(
            PraxisPolicyMapping(server_id=server.id, config_path=path)
            for server, (path, _) in zip(sorted(snapshot.servers, key=lambda item: (item.scope, item.id)), cpex_pairs, strict=True)
        )
        root = PraxisBundleDocument(
            listeners=(PraxisListener(),),
            filter_chains=(
                PraxisFilterChain(
                    filters=(
                        PraxisFilter(filter="mcp", max_body_bytes=1_048_576),
                        PraxisFilter(filter="cpex", policies=policies),
                    )
                ),
            ),
        )
    except ValidationError as error:
        code = _validation_code(error)
    else:
        rendered = tuple(PraxisRenderedDocument(path=path, content=_encode(document)) for path, document in cpex_pairs) + (PraxisRenderedDocument(path="praxis.yaml", content=_encode(root)),)
        documents = validate_bundle_documents(tuple(sorted(rendered, key=lambda document: document.path)))
        request = PraxisBundleBuildRequest(
            snapshot=PraxisSourceSnapshot(target_id=snapshot.target_id, source_fingerprint=snapshot.source_fingerprint),
            compatibility=DEFAULT_PRAXIS_COMPATIBILITY,
            documents=documents,
        )
        artifact = build_praxis_bundle(request)
        archived = validate_canonical_archive(artifact.archive_bytes)
        by_path = {document.path: document.content for document in archived}
        if any(hashlib.sha256(by_path[descriptor.path]).hexdigest() != descriptor.sha256 for descriptor in artifact.manifest.documents):
            raise PraxisBundleRenderError(PraxisBundleRenderErrorCode.INVALID_DOCUMENT)
        return artifact
    raise PraxisBundleRenderError(code) from None


__all__ = ("DEFAULT_PRAXIS_COMPATIBILITY", "PraxisBundleRenderError", "PraxisBundleRenderErrorCode", "parse_cpex_document", "parse_praxis_document", "render_praxis_bundle", "validate_bundle_documents")
