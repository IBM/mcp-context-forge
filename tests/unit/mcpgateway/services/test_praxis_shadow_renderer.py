"""Read-only deterministic Praxis shadow comparison contracts."""

from unittest.mock import MagicMock

import anyio
from cpex.framework.models import Config
import pytest

from mcpgateway.services.praxis_bundle_renderer import render_praxis_bundle
from mcpgateway.services.praxis_config_models import PraxisConfigSourceSnapshot, PraxisGatewaySource, PraxisServerSource, PraxisSourceError, PraxisSourceErrorCode, PraxisToolSource
from mcpgateway.services.praxis_shadow_renderer import PraxisReconcilerLifecycleService, PraxisShadowMismatchKind, PraxisShadowRendererService, compare_shadow_routes


def _snapshot() -> PraxisConfigSourceSnapshot:
    gateway = PraxisGatewaySource(id="gateway-a", name="Gateway", url="https://gateway.example.test/mcp", transport="STREAMABLEHTTP")
    tool = PraxisToolSource(id="tool-a", name="search", gateway_id="gateway-a", compiled_config=Config(plugins=[]))
    server = PraxisServerSource(id="server-a", name="Server", scope="team-a", gateways=(gateway,), tools=(tool,))
    return PraxisConfigSourceSnapshot(target_id="target-a", source_fingerprint="1" * 64, servers=(server,))


def test_matching_routes_have_deterministic_zero_diff() -> None:
    snapshot = _snapshot()
    artifact = render_praxis_bundle(snapshot)

    assert compare_shadow_routes(snapshot, artifact) == ()
    assert compare_shadow_routes(snapshot, artifact) == compare_shadow_routes(snapshot, artifact)


def test_representable_route_change_is_redacted_and_reported() -> None:
    snapshot = _snapshot()
    artifact = render_praxis_bundle(snapshot)
    renamed_tool = snapshot.servers[0].tools[0].model_copy(update={"name": "renamed-private-sentinel"})
    changed_server = snapshot.servers[0].model_copy(update={"tools": (renamed_tool,)})
    changed = snapshot.model_copy(update={"servers": (changed_server,)})

    diffs = compare_shadow_routes(changed, artifact)

    assert [diff.kind for diff in diffs] == [PraxisShadowMismatchKind.MISSING_ROUTE, PraxisShadowMismatchKind.UNEXPECTED_ROUTE]
    assert all(len(diff.route_digest) == 64 for diff in diffs)
    assert "renamed-private-sentinel" not in repr(diffs)


def test_plugin_route_change_is_reported_without_plugin_content() -> None:
    snapshot = _snapshot()
    artifact = render_praxis_bundle(snapshot)
    plugin = Config.model_validate(
        {
            "plugins": [
                {
                    "name": "audit-sentinel",
                    "kind": "audit/logger",
                    "hooks": ["cmf.tool_pre_invoke"],
                    "mode": "sequential",
                    "on_error": "fail",
                    "priority": 10,
                }
            ]
        }
    )
    changed_tool = snapshot.servers[0].tools[0].model_copy(update={"compiled_config": plugin})
    changed_server = snapshot.servers[0].model_copy(update={"tools": (changed_tool,)})
    changed = snapshot.model_copy(update={"servers": (changed_server,)})

    diffs = compare_shadow_routes(changed, artifact)

    assert len(diffs) == 1
    assert diffs[0].kind is PraxisShadowMismatchKind.PLUGIN_MISMATCH
    assert "audit-sentinel" not in repr(diffs)


def test_owner_private_state_is_explicitly_nonrepresentable() -> None:
    source = MagicMock()
    source.snapshot.side_effect = PraxisSourceError(PraxisSourceErrorCode.OWNER_PRIVATE)
    service = PraxisShadowRendererService(MagicMock(), source)

    result = service.compare("target-a")

    assert result.representable is False
    assert result.reason == PraxisSourceErrorCode.OWNER_PRIVATE.value
    assert result.diffs == ()


@pytest.mark.asyncio
async def test_reconciler_lifecycle_start_is_process_idempotent() -> None:
    reconciler = MagicMock()
    reconciler.fallback_scan = MagicMock()
    service = PraxisReconcilerLifecycleService(reconciler, interval_seconds=60)

    await service.start()
    await service.start()
    await anyio.sleep(0.05)
    await service.shutdown()

    reconciler.fallback_scan.assert_called_once_with()
