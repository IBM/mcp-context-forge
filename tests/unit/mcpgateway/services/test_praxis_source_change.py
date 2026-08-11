# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_praxis_source_change.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for conservative Praxis source-diff classification.
"""

from __future__ import annotations

from typing import cast

import pytest
from cpex.framework.models import Config, PluginConfig

from mcpgateway.services._praxis_reconciliation import SourceChange
from mcpgateway.services.praxis_config_models import (
    PraxisConfigSourceSnapshot,
    PraxisGatewaySource,
    PraxisPromptSource,
    PraxisResourceSource,
    PraxisServerSource,
    PraxisSourceErrorCode,
    PraxisToolSource,
)
from mcpgateway.services.praxis_source_change import classify_source_changes, classify_source_refusal

FINGERPRINT_BEFORE = "a" * 64
FINGERPRINT_AFTER = "b" * 64


def _gateway(**overrides: object) -> PraxisGatewaySource:
    values: dict[str, object] = {"id": "gw-1", "name": "Gateway", "url": "https://gw.example.test/mcp", "transport": "STREAMABLEHTTP"}
    values.update(overrides)
    return PraxisGatewaySource(**values)  # type: ignore[arg-type]


def _tool(config: Config | None = None, **overrides: object) -> PraxisToolSource:
    values: dict[str, object] = {"id": "tool-1", "name": "tool", "gateway_id": "gw-1", "compiled_config": config or Config()}
    values.update(overrides)
    return PraxisToolSource(**values)  # type: ignore[arg-type]


def _resource(**overrides: object) -> PraxisResourceSource:
    values: dict[str, object] = {"id": "res-1", "name": "resource", "uri": "resource://one", "gateway_id": "gw-1"}
    values.update(overrides)
    return PraxisResourceSource(**values)  # type: ignore[arg-type]


def _prompt(**overrides: object) -> PraxisPromptSource:
    values: dict[str, object] = {"id": "prompt-1", "name": "prompt", "gateway_id": "gw-1"}
    values.update(overrides)
    return PraxisPromptSource(**values)  # type: ignore[arg-type]


def _snapshot(
    *,
    target_id: str = "target-a",
    fingerprint: str = FINGERPRINT_BEFORE,
    servers: tuple[PraxisServerSource, ...] = (),
) -> PraxisConfigSourceSnapshot:
    return PraxisConfigSourceSnapshot(target_id=target_id, source_fingerprint=cast("str", fingerprint), servers=servers)


def _server(**overrides: object) -> PraxisServerSource:
    values: dict[str, object] = {"id": "server-1", "name": "Server", "scope": "team"}
    values.update(overrides)
    return PraxisServerSource(**values)  # type: ignore[arg-type]


def test_target_mismatch_fails_closed_unknown() -> None:
    before = _snapshot(target_id="target-a")
    after = _snapshot(target_id="target-b")

    assert classify_source_changes(before, after) == frozenset({SourceChange.UNKNOWN})


def test_fingerprint_drift_without_classified_change_is_unknown() -> None:
    before = _snapshot(fingerprint=FINGERPRINT_BEFORE)
    after = _snapshot(fingerprint=FINGERPRINT_AFTER)

    assert classify_source_changes(before, after) == frozenset({SourceChange.UNKNOWN})


def test_gateway_rename_is_descriptive_and_capability_drift_is_unknown() -> None:
    before = _snapshot(servers=(_server(gateways=(_gateway(),)),))
    renamed = _snapshot(servers=(_server(gateways=(_gateway(name="Renamed"),)),))
    capabilities = _snapshot(servers=(_server(gateways=(_gateway(capabilities={"experimental": True}),)),))

    assert classify_source_changes(before, renamed) == frozenset({SourceChange.DESCRIPTIVE})
    assert classify_source_changes(before, capabilities) == frozenset({SourceChange.UNKNOWN})


def test_gateway_endpoint_change_is_classified() -> None:
    before = _snapshot(servers=(_server(gateways=(_gateway(),)),))
    after = _snapshot(servers=(_server(gateways=(_gateway(url="https://other.example.test/mcp"),)),))

    assert classify_source_changes(before, after) == frozenset({SourceChange.GATEWAY_ENDPOINT})


def test_tool_reassignment_rename_and_header_changes_are_conservative() -> None:
    reassigned = classify_source_changes(
        _snapshot(servers=(_server(tools=(_tool(),)),)),
        _snapshot(servers=(_server(tools=(_tool(gateway_id="gw-2"),)),)),
    )
    renamed = classify_source_changes(
        _snapshot(servers=(_server(tools=(_tool(),)),)),
        _snapshot(servers=(_server(tools=(_tool(name="renamed"),)),)),
    )
    headers = classify_source_changes(
        _snapshot(servers=(_server(tools=(_tool(),)),)),
        _snapshot(servers=(_server(tools=(_tool(headers={"Authorization": "Bearer x"}),)),)),
    )

    assert reassigned == frozenset({SourceChange.REASSIGNMENT})
    assert renamed == frozenset({SourceChange.UNKNOWN})
    assert headers == frozenset({SourceChange.AUTHORIZATION})


def test_added_security_plugin_is_policy_but_plain_plugin_is_additive() -> None:
    security = Config(plugins=[PluginConfig(name="guard", kind="builtin", hooks=["http_auth_check_permission"], tags=[])])
    tagged = Config(plugins=[PluginConfig(name="guard", kind="builtin", hooks=["tool_post_invoke"], tags=["rbac"])])
    plain = Config(plugins=[PluginConfig(name="metrics", kind="builtin", hooks=["tool_post_invoke"], tags=["observability"])])

    assert classify_source_changes(
        _snapshot(servers=(_server(tools=(_tool(),)),)),
        _snapshot(servers=(_server(tools=(_tool(security),)),)),
    ) == frozenset({SourceChange.PLUGIN_POLICY})
    assert classify_source_changes(
        _snapshot(servers=(_server(tools=(_tool(),)),)),
        _snapshot(servers=(_server(tools=(_tool(tagged),)),)),
    ) == frozenset({SourceChange.PLUGIN_POLICY})
    assert classify_source_changes(
        _snapshot(servers=(_server(tools=(_tool(),)),)),
        _snapshot(servers=(_server(tools=(_tool(plain),)),)),
    ) == frozenset({SourceChange.ADDITIVE})


def test_removed_or_reconfigured_plugin_is_policy() -> None:
    secured = _tool(Config(plugins=[PluginConfig(name="guard", kind="builtin", hooks=["tool_post_invoke"], tags=[])]))
    removed = classify_source_changes(
        _snapshot(servers=(_server(tools=(secured,)),)),
        _snapshot(servers=(_server(tools=(_tool(),)),)),
    )
    reconfigured = classify_source_changes(
        _snapshot(servers=(_server(tools=(secured,)),)),
        _snapshot(servers=(_server(tools=(_tool(Config(plugins=[PluginConfig(name="guard", kind="builtin", hooks=["resource_post_fetch"], tags=[])])),)),)),
    )

    assert removed == frozenset({SourceChange.PLUGIN_POLICY})
    assert reconfigured == frozenset({SourceChange.PLUGIN_POLICY})


def test_non_plugin_config_drift_is_unknown() -> None:
    before = _tool(Config(server_settings={"port": 8000}))
    after = _tool(Config(server_settings={"port": 9000}))

    assert classify_source_changes(
        _snapshot(servers=(_server(tools=(before,)),)),
        _snapshot(servers=(_server(tools=(after,)),)),
    ) == frozenset({SourceChange.UNKNOWN})


def test_resource_and_prompt_changes_are_classified() -> None:
    cases = [
        (_resource(gateway_id="gw-2"), SourceChange.REASSIGNMENT, "resources"),
        (_resource(name="renamed"), SourceChange.DESCRIPTIVE, "resources"),
        (_resource(uri="resource://two"), SourceChange.UNKNOWN, "resources"),
        (_prompt(gateway_id="gw-2"), SourceChange.REASSIGNMENT, "prompts"),
        (_prompt(name="renamed"), SourceChange.UNKNOWN, "prompts"),
    ]
    for replacement, expected, field in cases:
        result = classify_source_changes(
            _snapshot(servers=(_server(**{field: (_resource() if field == "resources" else _prompt(),)}),)),
            _snapshot(servers=(_server(**{field: (replacement,)}),)),
        )
        assert result == frozenset({expected}), field


def test_server_scope_change_is_authorization() -> None:
    result = classify_source_changes(
        _snapshot(servers=(_server(scope="team"),)),
        _snapshot(servers=(_server(scope="public"),)),
    )

    assert result == frozenset({SourceChange.AUTHORIZATION})


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (PraxisSourceErrorCode.OWNER_PRIVATE, SourceChange.AUTHORIZATION),
        (PraxisSourceErrorCode.SCOPE_MISMATCH, SourceChange.AUTHORIZATION),
        (PraxisSourceErrorCode.URL_USERINFO, SourceChange.SECRET_CLASSIFICATION),
        (PraxisSourceErrorCode.SECRET_HEADER, SourceChange.SECRET_CLASSIFICATION),
        (PraxisSourceErrorCode.RUNTIME_OVERRIDE, SourceChange.PLUGIN_POLICY),
        (PraxisSourceErrorCode.INVALID_BINDING, SourceChange.PLUGIN_POLICY),
        (PraxisSourceErrorCode.TARGET_NOT_FOUND, SourceChange.UNKNOWN),
        (PraxisSourceErrorCode.DANGLING_ASSOCIATION, SourceChange.UNKNOWN),
        (PraxisSourceErrorCode.INVALID_SOURCE, SourceChange.UNKNOWN),
    ],
)
def test_refusal_codes_map_to_fail_closed_policy(code: PraxisSourceErrorCode, expected: SourceChange) -> None:
    assert classify_source_refusal(code) is expected


def test_unrecognized_refusal_code_fails_closed_by_raising() -> None:
    bogus = cast(PraxisSourceErrorCode, "unenumerated_refusal")

    with pytest.raises(AssertionError):
        classify_source_refusal(bogus)
