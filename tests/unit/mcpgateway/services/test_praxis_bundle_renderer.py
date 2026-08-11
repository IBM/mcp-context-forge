"""Contracts for deterministic native Praxis and CPEX bundle rendering."""

import hashlib
import json
import random

from cpex.framework.models import Config
from pydantic import BaseModel, ValidationError
import pytest

from mcpgateway.services.praxis_bundle_models import PraxisCpexPlugin, PraxisCpexRoute

from mcpgateway.services.praxis_bundle_renderer import (
    PraxisBundleRenderError,
    PraxisBundleRenderErrorCode,
    parse_cpex_document,
    parse_praxis_document,
    render_praxis_bundle,
    validate_bundle_documents,
)
from mcpgateway.services.praxis_config_models import (
    PraxisConfigSourceSnapshot,
    PraxisGatewaySource,
    PraxisPromptSource,
    PraxisRenderedDocument,
    PraxisResourceSource,
    PraxisServerSource,
    PraxisToolSource,
    validate_canonical_archive,
)


def _gateway(gateway_id: str) -> PraxisGatewaySource:
    return PraxisGatewaySource(
        id=gateway_id,
        name=gateway_id,
        url=f"https://{gateway_id}.example.test/mcp",
        transport="STREAMABLEHTTP",
        passthrough_headers=("x-request-id",),
        add_headers={"x-source": gateway_id},
        remove_headers=("x-internal",),
        capabilities={"tools": {"listChanged": True}},
    )


def _tool(tool_id: str, name: str, gateway_id: str) -> PraxisToolSource:
    return PraxisToolSource(id=tool_id, name=name, gateway_id=gateway_id, headers={"x-tool": name}, compiled_config=Config(plugins=[]))


def source_snapshot() -> PraxisConfigSourceSnapshot:
    team_server = PraxisServerSource(
        id="server-a",
        name="Team server",
        scope="team-a",
        gateways=(_gateway("gateway-a"),),
        tools=(_tool("tool-b", "summarize", "gateway-a"), _tool("tool-a", "search", "gateway-a")),
        resources=(PraxisResourceSource(id="resource-a", name="guide", uri="https://docs.example.test/guide", gateway_id="gateway-a"),),
        prompts=(PraxisPromptSource(id="prompt-a", name="brief", gateway_id="gateway-a"),),
    )
    platform_server = PraxisServerSource(
        id="server-z",
        name="Platform server",
        scope="platform",
        gateways=(_gateway("gateway-z"),),
        tools=(_tool("tool-z", "clock", "gateway-z"),),
    )
    return PraxisConfigSourceSnapshot(target_id="target-alpha", source_fingerprint="1" * 64, servers=(team_server, platform_server))


def _payload_documents(archive: bytes) -> tuple[PraxisRenderedDocument, ...]:
    return tuple(document for document in validate_canonical_archive(archive) if document.path != "render-manifest.json")


def _replace(documents: tuple[PraxisRenderedDocument, ...], path: str, content: bytes) -> tuple[PraxisRenderedDocument, ...]:
    return tuple(PraxisRenderedDocument(path=item.path, content=content if item.path == path else item.content) for item in documents)


def _encoded(model: BaseModel) -> bytes:
    payload = model.model_dump(mode="json", by_alias=True, exclude_none=True)
    return (json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode()


def _route_key(route: PraxisCpexRoute) -> tuple[str, str]:
    for kind in ("tool", "resource", "prompt"):
        value = getattr(route, kind)
        if value is not None:
            return kind, value
    raise AssertionError("validated route has no matcher")


def test_renderer_emits_native_documents_and_terminal_wildcards() -> None:
    documents = _payload_documents(render_praxis_bundle(source_snapshot()).archive_bytes)

    assert [document.path for document in documents] == ["cpex/platform--server-z.yaml", "cpex/team-a--server-a.yaml", "praxis.yaml"]
    root = parse_praxis_document(next(document.content for document in documents if document.path == "praxis.yaml"))
    assert root.listeners[0].filter_chains == ("mcp",)
    chain = root.filter_chains[0]
    assert [item.filter for item in chain.filters] == ["mcp", "cpex"]
    assert [mapping.config_path for mapping in chain.filters[1].policies or ()] == ["cpex/platform--server-z.yaml", "cpex/team-a--server-a.yaml"]

    team = parse_cpex_document(next(document.content for document in documents if document.path == "cpex/team-a--server-a.yaml"))
    assert team.plugin_settings.routing_enabled is True
    assert team.plugin_settings.fail_on_plugin_error is True
    assert [_route_key(route) for route in team.routes] == [
        ("prompt", "brief"),
        ("resource", "https://docs.example.test/guide"),
        ("tool", "search"),
        ("tool", "summarize"),
        ("tool", "*"),
        ("resource", "*"),
        ("prompt", "*"),
    ]


@pytest.mark.parametrize("priority", [0, 1001])
def test_plugin_priority_rejects_values_outside_compiler_bounds(priority: int) -> None:
    with pytest.raises(ValidationError):
        PraxisCpexPlugin(
            name="audit",
            kind="audit/logger",
            hooks=("cmf.tool_pre_invoke",),
            mode="sequential",
            priority=priority,
            on_error="fail",
        )


def test_one_hundred_shuffled_source_permutations_are_byte_identical() -> None:
    baseline = render_praxis_bundle(source_snapshot())
    source = source_snapshot()
    outputs: set[tuple[bytes, str, str]] = set()
    for seed in range(100):
        generator = random.Random(seed)
        servers = list(source.servers)
        generator.shuffle(servers)
        shuffled_servers = []
        for server in servers:
            gateways, tools, resources, prompts = map(list, (server.gateways, server.tools, server.resources, server.prompts))
            for collection in (gateways, tools, resources, prompts):
                generator.shuffle(collection)
            shuffled_servers.append(server.model_copy(update={"gateways": tuple(gateways), "tools": tuple(tools), "resources": tuple(resources), "prompts": tuple(prompts)}))
        artifact = render_praxis_bundle(source.model_copy(update={"servers": tuple(shuffled_servers)}))
        outputs.add((artifact.archive_bytes, artifact.payload_hash, artifact.content_hash))
    assert outputs == {(baseline.archive_bytes, baseline.payload_hash, baseline.content_hash)}


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("unknown_filter", PraxisBundleRenderErrorCode.UNKNOWN_FILTER),
        ("dangling_path", PraxisBundleRenderErrorCode.DANGLING_CONFIG_PATH),
        ("empty_route", PraxisBundleRenderErrorCode.EMPTY_ROUTE),
        ("missing_terminal_deny", PraxisBundleRenderErrorCode.MISSING_TERMINAL_DENY),
        ("duplicate_plugin", PraxisBundleRenderErrorCode.DUPLICATE_PLUGIN),
        ("duplicate_route", PraxisBundleRenderErrorCode.DUPLICATE_ROUTE),
        ("unsupported_capability", PraxisBundleRenderErrorCode.UNSUPPORTED_CAPABILITY),
        ("non_fail_security", PraxisBundleRenderErrorCode.NON_FAIL_SECURITY_PLUGIN),
        ("incompatible_output", PraxisBundleRenderErrorCode.INCOMPATIBLE_OUTPUT_MODEL),
    ],
)
def test_exact_invalid_output_cases_fail_before_publication(mutation: str, expected: PraxisBundleRenderErrorCode) -> None:
    documents = _payload_documents(render_praxis_bundle(source_snapshot()).archive_bytes)
    root_path = "praxis.yaml"
    cpex_path = "cpex/team-a--server-a.yaml"
    root_content = next(item.content for item in documents if item.path == root_path)
    root = parse_praxis_document(root_content)
    cpex_content = next(item.content for item in documents if item.path == cpex_path)
    cpex = parse_cpex_document(cpex_content)
    plugin = PraxisCpexPlugin(
        capabilities=("read_headers",),
        hooks=("http_auth_check_permission",),
        kind="audit/logger",
        mode="sequential",
        name="authorization",
        on_error="fail",
        priority=10,
        tags=("security",),
    )
    if mutation == "unknown_filter":
        documents = _replace(documents, root_path, root_content.replace(b'"filter":"mcp"', b'"filter":"unknown"', 1))
    elif mutation == "dangling_path":
        dispatcher = root.filter_chains[0].filters[1]
        mappings = dispatcher.policies or ()
        assert mappings
        changed = mappings[0].model_copy(update={"config_path": "cpex/platform--missing.yaml"})
        filters = (root.filter_chains[0].filters[0], dispatcher.model_copy(update={"policies": (changed, *mappings[1:])}))
        chain = root.filter_chains[0].model_copy(update={"filters": filters})
        documents = _replace(documents, root_path, _encoded(root.model_copy(update={"filter_chains": (chain,)})))
    elif mutation == "empty_route":
        chain = root.filter_chains[0].model_copy(update={"filters": ()})
        documents = _replace(documents, root_path, _encoded(root.model_copy(update={"filter_chains": (chain,)})))
    elif mutation == "missing_terminal_deny":
        documents = _replace(documents, cpex_path, _encoded(cpex.model_copy(update={"routes": cpex.routes[:-1]})))
    elif mutation == "duplicate_plugin":
        documents = _replace(documents, cpex_path, _encoded(cpex.model_copy(update={"plugins": (plugin, plugin)})))
    elif mutation == "duplicate_route":
        documents = _replace(documents, cpex_path, _encoded(cpex.model_copy(update={"routes": (cpex.routes[0], *cpex.routes)})))
    elif mutation == "unsupported_capability":
        changed = plugin.model_copy(update={"capabilities": ("launch_missiles",)})
        documents = _replace(documents, cpex_path, _encoded(cpex.model_copy(update={"plugins": (changed,)})))
    elif mutation == "non_fail_security":
        changed = plugin.model_copy(update={"on_error": "ignore"})
        documents = _replace(documents, cpex_path, _encoded(cpex.model_copy(update={"plugins": (changed,)})))
    else:
        documents = _replace(documents, root_path, root_content.replace(b"{", b'{"schema":"praxis-config/v2",', 1))

    with pytest.raises(PraxisBundleRenderError) as captured:
        validate_bundle_documents(documents)
    assert captured.value.code is expected


def test_renderer_rejects_unavailable_plugin_kind_without_disclosure() -> None:
    source = source_snapshot()
    tool = source.servers[0].tools[0]
    sentinel = "plugins.secret.Sentinel"
    plugin = {
        "name": "secret",
        "kind": sentinel,
        "hooks": ["tool_pre_invoke"],
        "mode": "sequential",
        "on_error": "fail",
        "priority": 10,
    }
    compiled = Config.model_validate({"plugins": [plugin]})
    server = source.servers[0].model_copy(update={"tools": (tool.model_copy(update={"compiled_config": compiled}), *source.servers[0].tools[1:])})
    with pytest.raises(PraxisBundleRenderError) as captured:
        render_praxis_bundle(source.model_copy(update={"servers": (server, source.servers[1])}))
    assert captured.value.code is PraxisBundleRenderErrorCode.INCOMPATIBLE_OUTPUT_MODEL
    assert sentinel not in str(captured.value)


def test_renderer_rejects_secret_bearing_snapshot_without_disclosure() -> None:
    source = source_snapshot()
    sentinel = "credential-sentinel"
    gateway = source.servers[0].gateways[0].model_copy(update={"url": f"https://user:{sentinel}@example.test/mcp"})  # pragma: allowlist secret
    server = source.servers[0].model_copy(update={"gateways": (gateway,)})
    with pytest.raises(PraxisBundleRenderError) as captured:
        render_praxis_bundle(source.model_copy(update={"servers": (server, source.servers[1])}))
    assert sentinel not in str(captured.value)


def test_manifest_hashes_match_final_document_bytes() -> None:
    artifact = render_praxis_bundle(source_snapshot())
    documents = {document.path: document.content for document in validate_canonical_archive(artifact.archive_bytes)}
    for descriptor in artifact.manifest.documents:
        assert hashlib.sha256(documents[descriptor.path]).hexdigest() == descriptor.sha256
