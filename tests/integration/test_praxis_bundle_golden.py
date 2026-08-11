"""Golden multi-scope Praxis/CPEX canonical archive verification."""

import json
from pathlib import Path

from cpex.framework import OnError, PluginMode
from cpex.framework.models import Config, PluginConfig

from mcpgateway.services.praxis_bundle_renderer import DEFAULT_PRAXIS_COMPATIBILITY, parse_cpex_document, render_praxis_bundle
from mcpgateway.services.praxis_config_models import PraxisBundleBuildRequest, PraxisConfigSourceSnapshot, PraxisGatewaySource, PraxisRenderedDocument
from mcpgateway.services.praxis_config_models import PraxisServerSource, PraxisSourceSnapshot, PraxisToolSource, build_praxis_bundle, validate_canonical_archive


FIXTURE = Path(__file__).parents[1] / "fixtures" / "praxis_config" / "bundle-render-v1.json"


def _source() -> PraxisConfigSourceSnapshot:
    audit = PluginConfig(
        name="native-audit",
        kind="audit/logger",
        hooks=["cmf.tool_pre_invoke"],
        mode=PluginMode.SEQUENTIAL,
        on_error=OnError.FAIL,
        priority=10,
        config={"destination": "tracing", "source": "task5-golden"},
    )
    servers = tuple(
        PraxisServerSource(
            id=server_id,
            name=server_id,
            scope=scope,
            gateways=(PraxisGatewaySource(id=gateway_id, name=gateway_id, url=f"https://{gateway_id}.example.test/mcp", transport="STREAMABLEHTTP", capabilities={"tools": {}}),),
            tools=(PraxisToolSource(id=tool_id, name=tool_name, gateway_id=gateway_id, compiled_config=Config(plugins=[audit] if scope == "platform" else [])),),
        )
        for scope, server_id, gateway_id, tool_id, tool_name in (
            ("platform", "server-public", "gateway-public", "tool-public", "clock"),
            ("team-red", "server-team", "gateway-team", "tool-team", "search"),
        )
    )
    return PraxisConfigSourceSnapshot(target_id="target-golden", source_fingerprint="a" * 64, servers=servers)


def test_complete_canonical_archive_matches_committed_golden_bytes() -> None:
    expected = json.loads(FIXTURE.read_text(encoding="utf-8"))
    artifact = render_praxis_bundle(_source())
    expected_documents = tuple(PraxisRenderedDocument(path=item["path"], content=item["content_utf8"].encode()) for item in expected["documents"])
    expected_artifact = build_praxis_bundle(
        PraxisBundleBuildRequest(
            snapshot=PraxisSourceSnapshot(target_id="target-golden", source_fingerprint="a" * 64),
            compatibility=DEFAULT_PRAXIS_COMPATIBILITY,
            documents=expected_documents,
        )
    )

    assert artifact.archive_bytes == expected_artifact.archive_bytes
    assert artifact.generation_id == expected["generation_id"]
    assert artifact.payload_hash == expected["payload_hash"]
    assert artifact.content_hash == expected["content_hash"]
    documents = validate_canonical_archive(artifact.archive_bytes)
    cpex_documents = [document for document in documents if document.path.startswith("cpex/")]
    assert len(cpex_documents) == 2
    assert all(parse_cpex_document(document.content).routes[-3].tool == "*" for document in cpex_documents)
    platform = parse_cpex_document(next(document.content for document in cpex_documents if document.path == "cpex/platform--server-public.yaml"))
    assert [(plugin.name, plugin.kind) for plugin in platform.plugins] == [("native-audit", "audit/logger")]
    assert platform.routes[0].plugins == ("native-audit",)
