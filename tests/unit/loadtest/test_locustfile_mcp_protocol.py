# -*- coding: utf-8 -*-
"""Location: ./tests/unit/loadtest/test_locustfile_mcp_protocol.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for the pure helpers in tests/loadtest/locustfile_mcp_protocol.py.

These cover argument synthesis and tool-pool selection only; they never start a
Locust runner and never touch the network.
"""

# Standard
import os

# Belt and braces: conftest.py in this package sets the same variable, but this
# keeps the module importable on its own (pytest path args, IDE runners).
# Importing locust without it runs gevent.monkey.patch_all() and hangs pytest.
os.environ.setdefault("LOCUST_SKIP_MONKEY_PATCH", "1")

# Third-Party
import pytest  # noqa: E402

# First-Party
from tests.loadtest import locustfile_mcp_protocol as lf  # noqa: E402

# Real schemas as returned by ghcr.io/ibm/cfex-mcp-fast-time-server tools/list.
ECHO_SCHEMA = {
    "type": "object",
    "required": ["message"],
    "properties": {
        "message": {"type": "string"},
        "delay": {"type": "integer"},
        "delay_stddev": {"type": "number"},
    },
}
FLAKY_SCHEMA = {
    "type": "object",
    "required": ["key"],
    "properties": {"key": {"type": "string"}, "fail_times": {"type": "integer"}},
}
CONVERT_SCHEMA = {
    "type": "object",
    "required": ["time", "source_timezone", "target_timezone"],
    "properties": {
        "time": {"type": "string"},
        "source_timezone": {"type": "string"},
        "target_timezone": {"type": "string"},
    },
}
GET_STATS_SCHEMA = {"type": "object", "properties": {}}


def test_args_from_schema_only_includes_required_properties():
    """Optional properties are omitted so payloads stay minimal."""
    args = lf._args_from_schema(ECHO_SCHEMA)
    assert set(args) == {"message"}
    assert isinstance(args["message"], str)


def test_args_from_schema_handles_multiple_required_strings():
    """Every required property gets a value of the declared type."""
    args = lf._args_from_schema(CONVERT_SCHEMA)
    assert set(args) == {"time", "source_timezone", "target_timezone"}
    assert all(isinstance(v, str) for v in args.values())
    assert args["source_timezone"] in lf.TIMEZONES
    assert args["target_timezone"] in lf.TIMEZONES


def test_args_from_schema_empty_schema_returns_empty_dict():
    """A tool with no required properties is called with no arguments."""
    assert lf._args_from_schema(GET_STATS_SCHEMA) == {}


@pytest.mark.parametrize(
    "spec,expected_type",
    [
        ({"type": "string"}, str),
        ({"type": "integer"}, int),
        ({"type": "number"}, float),
        ({"type": "boolean"}, bool),
        ({"type": "array"}, list),
        ({"type": "object"}, dict),
    ],
)
def test_synth_value_respects_declared_type(spec, expected_type):
    """Each JSON Schema scalar/container type maps to a matching Python value."""
    assert isinstance(lf._synth_value("field", spec), expected_type)


def test_synth_value_prefers_enum_then_default():
    """Enum wins over type guessing; default wins when no enum is present."""
    assert lf._synth_value("mode", {"type": "string", "enum": ["alpha", "beta"]}) == "alpha"
    assert lf._synth_value("mode", {"type": "string", "default": "preset"}) == "preset"


def test_synth_value_nullable_union_type_uses_first_non_null():
    """A ["string", "null"] union synthesizes a string, not None."""
    assert isinstance(lf._synth_value("field", {"type": ["string", "null"]}), str)


def test_build_tool_args_uses_schema_for_gateway_prefixed_echo():
    """Regression for #6082: 'fast-time-echo' must not receive a timezone."""
    args = lf._build_tool_args("fast-time-echo", ECHO_SCHEMA)
    assert set(args) == {"message"}


def test_build_tool_args_uses_schema_for_unknown_tool_name():
    """A tool whose name matches no keyword still gets valid required args."""
    args = lf._build_tool_args("fast-time-flaky", FLAKY_SCHEMA)
    assert set(args) == {"key"}
    assert isinstance(args["key"], str) and args["key"]


def test_build_tool_args_reads_registered_schema_when_none_passed(monkeypatch):
    """Module-level schema registry is consulted when no schema is supplied."""
    monkeypatch.setattr(lf, "_tool_schemas", {"fast-time-echo": ECHO_SCHEMA})
    assert set(lf._build_tool_args("fast-time-echo")) == {"message"}


def test_build_tool_args_falls_back_to_name_heuristic_without_schema(monkeypatch):
    """MCP_TOOL_NAMES override path has no schemas; echo must beat the time branch."""
    monkeypatch.setattr(lf, "_tool_schemas", {})
    assert set(lf._build_tool_args("fast-time-echo")) == {"message"}
    assert set(lf._build_tool_args("fast-time-get-system-time")) == {"timezone"}
    assert set(lf._build_tool_args("fast-time-convert-time")) == {"time", "source_timezone", "target_timezone"}


def test_build_tool_args_respects_empty_schema_over_name_heuristic():
    """A genuinely zero-argument schema must win even when the tool name matches a heuristic.

    Regression for a narrower #6082 variant: a schema with `properties: {}` and no
    `required` list is falsy on both counts, so a truthiness check on its contents
    would mistake it for "no schema" and fall through to the name heuristic. A
    heuristic-matching name (contains "timezone") must not override an explicitly
    declared empty schema.
    """
    schema = {"type": "object", "properties": {}}
    args = lf._build_tool_args("fast-time-timezone-lookup", schema)
    assert args == {}


class _FakeResponse:
    """Minimal stand-in for a requests.Response."""

    def __init__(self, payload, headers=None):
        self._payload = payload
        self.headers = headers or {}

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


@pytest.fixture()
def fake_gateway(monkeypatch):
    """Stub the `requests` module that _auto_detect imports, serving a fixed inventory."""
    # Standard
    import sys
    import types

    tools = [
        {"name": "fast-time-echo", "inputSchema": ECHO_SCHEMA},
        {"name": "fast-time-flaky", "inputSchema": FLAKY_SCHEMA},
        {"name": "fast-time-convert-time", "inputSchema": CONVERT_SCHEMA},
        {"name": "fast-time-get-stats", "inputSchema": GET_STATS_SCHEMA},
        {"name": "fast-time-schema-error", "inputSchema": GET_STATS_SCHEMA},
        {"name": "fast-time-verify-protocol"},  # no inputSchema at all
    ]

    def fake_get(url, headers=None, timeout=None):
        return _FakeResponse([{"id": "srv-1", "enabled": True, "associatedTools": ["a"]}])

    def fake_post(url, json=None, headers=None, timeout=None):
        method = json.get("method")
        if method == "initialize":
            return _FakeResponse({"result": {"serverInfo": {"name": "fast-time"}}}, {"Mcp-Session-Id": "sid-1"})
        if method == "tools/list":
            return _FakeResponse({"result": {"tools": tools}})
        return _FakeResponse({"result": {}})

    module = types.ModuleType("requests")
    module.get = fake_get
    module.post = fake_post
    monkeypatch.setitem(sys.modules, "requests", module)
    monkeypatch.setattr(lf, "_server_targets", [])
    monkeypatch.setattr(lf, "_tool_schemas", {})
    monkeypatch.setattr(lf, "MCP_TOOL_NAMES_STR", "")
    return tools


def test_auto_detect_captures_input_schemas(fake_gateway, monkeypatch):
    """Discovery stores each tool's inputSchema on the target and in the module registry."""
    # raising=False: MCP_TOOL_DENYLIST does not exist until Task 2. Pinning it to
    # an empty set keeps this test independent of the denylist default either way.
    monkeypatch.setattr(lf, "MCP_TOOL_DENYLIST", set(), raising=False)
    lf._auto_detect("http://gateway.test")
    target = lf._server_targets[0]
    assert target.tool_schemas["fast-time-echo"]["required"] == ["message"]
    assert lf._tool_schemas == target.tool_schemas
    assert "fast-time-verify-protocol" not in target.tool_schemas  # no schema published for it


def test_auto_detect_warns_about_tools_without_schema(fake_gateway, monkeypatch, caplog):
    """A schema-less tool is reported, not silently called with guessed args."""
    # Standard
    import logging

    monkeypatch.setattr(lf, "MCP_TOOL_DENYLIST", set(), raising=False)  # attribute arrives in Task 2
    with caplog.at_level(logging.WARNING, logger=lf.logger.name):
        lf._auto_detect("http://gateway.test")
    assert "fast-time-verify-protocol" in caplog.text


def test_server_target_carries_tool_schemas():
    """ServerTarget exposes the discovered per-tool inputSchema map."""
    target = lf.ServerTarget(
        server_id="s1",
        server_name="fast-time",
        tool_names=["fast-time-echo"],
        resource_uris=[],
        prompt_targets=[],
        tool_schemas={"fast-time-echo": ECHO_SCHEMA},
    )
    assert target.tool_schemas["fast-time-echo"]["required"] == ["message"]


def test_is_denied_matches_gateway_prefixed_names(monkeypatch):
    """Denylist entries match the trailing segment of a gateway-prefixed name."""
    monkeypatch.setattr(lf, "MCP_TOOL_DENYLIST", {"schema_error", "flaky"})
    assert lf._is_denied("fast-time-schema-error") is True
    assert lf._is_denied("fast-time-flaky") is True
    assert lf._is_denied("flaky") is True


def test_is_denied_does_not_match_unrelated_tools(monkeypatch):
    """Tools that merely contain a denied substring are not excluded."""
    monkeypatch.setattr(lf, "MCP_TOOL_DENYLIST", {"schema_error", "flaky"})
    assert lf._is_denied("fast-time-echo") is False
    assert lf._is_denied("fast-time-get-system-time") is False
    assert lf._is_denied("fast-time-schema-success") is False
    assert lf._is_denied("flakiness-report") is False


def test_is_denied_empty_denylist_allows_everything(monkeypatch):
    """An empty MCP_BENCHMARK_TOOL_DENYLIST disables filtering."""
    monkeypatch.setattr(lf, "MCP_TOOL_DENYLIST", set())
    assert lf._is_denied("fast-time-schema-error") is False


def test_empty_denylist_env_var_disables_filtering(monkeypatch):
    """MCP_BENCHMARK_TOOL_DENYLIST="" must actually disable filtering, not fall through to the default.

    Regression for the final review of #6082: ``_cfg()`` resolves via
    ``os.environ.get(key) or default``, so an explicitly empty env var is falsy and
    silently loses to the default. The other denylist tests in this file only
    monkeypatch the already-parsed ``MCP_TOOL_DENYLIST`` set, which can't catch a bug
    in the parsing itself — this test reloads the module so the env var is actually
    re-parsed.
    """
    # Standard
    import importlib

    monkeypatch.setenv("MCP_BENCHMARK_TOOL_DENYLIST", "")
    try:
        importlib.reload(lf)
        assert lf.MCP_TOOL_DENYLIST == set()
    finally:
        monkeypatch.delenv("MCP_BENCHMARK_TOOL_DENYLIST", raising=False)
        importlib.reload(lf)  # restore default state for subsequent tests


def test_missing_denylist_env_var_keeps_default(monkeypatch):
    """Without the env var set at all, the default schema_error,flaky denylist still applies."""
    # Standard
    import importlib

    monkeypatch.delenv("MCP_BENCHMARK_TOOL_DENYLIST", raising=False)
    try:
        importlib.reload(lf)
        assert lf.MCP_TOOL_DENYLIST == {"schema_error", "flaky"}
    finally:
        importlib.reload(lf)  # restore default state for subsequent tests


def test_auto_detect_drops_denylisted_tools(fake_gateway, monkeypatch, caplog):
    """Discovery removes denylisted tools from the pool and logs the exclusion once."""
    # Standard
    import logging

    monkeypatch.setattr(lf, "MCP_TOOL_DENYLIST", {"schema_error", "flaky"})
    with caplog.at_level(logging.INFO, logger=lf.logger.name):
        lf._auto_detect("http://gateway.test")

    target = lf._server_targets[0]
    assert "fast-time-flaky" not in target.tool_names
    assert "fast-time-schema-error" not in target.tool_names
    assert "fast-time-verify-protocol" in target.tool_names
    assert "excluded 2 denylisted" in caplog.text


SEVEN_TOOLS = [
    "fast-time-echo",
    "fast-time-get-system-time",
    "fast-time-convert-time",
    "fast-time-get-stats",
    "fast-time-schema-success",
    "fast-time-tool-six",
    "fast-time-tool-seven",
]


def test_limit_pool_returns_every_tool_by_default(monkeypatch):
    """Regression for #6082: no tool is excluded by position."""
    monkeypatch.setattr(lf, "MCP_TOOL_POOL_SIZE", 0)
    assert lf._limit_pool(SEVEN_TOOLS) == SEVEN_TOOLS


def test_limit_pool_applies_configured_ceiling(monkeypatch):
    """MCP_BENCHMARK_TOOL_POOL_SIZE=6 reproduces the 6-tool agent scenario."""
    monkeypatch.setattr(lf, "MCP_TOOL_POOL_SIZE", 6)
    assert lf._limit_pool(SEVEN_TOOLS) == SEVEN_TOOLS[:6]


def test_limit_pool_ceiling_larger_than_pool_is_a_noop(monkeypatch):
    """A ceiling above the tool count returns the full pool."""
    monkeypatch.setattr(lf, "MCP_TOOL_POOL_SIZE", 50)
    assert lf._limit_pool(SEVEN_TOOLS) == SEVEN_TOOLS


def test_user_tool_pool_uses_all_assigned_tools(monkeypatch):
    """BaseMCPUser._tool_pool exposes every tool on the assigned target."""
    monkeypatch.setattr(lf, "MCP_TOOL_POOL_SIZE", 0)
    user = lf.MCPToolCallerUser.__new__(lf.MCPToolCallerUser)
    user._tool_names = list(SEVEN_TOOLS)
    assert user._tool_pool() == SEVEN_TOOLS


def test_source_has_no_hardcoded_six_tool_cap():
    """Guard: the literal [:6] slice must not reappear in the benchmark script."""
    # Standard
    from pathlib import Path

    source = Path(lf.__file__).read_text(encoding="utf-8")
    assert "[:6]" not in source


def _make_user(cls, tool_names, monkeypatch):
    """Build a user instance without Locust's environment, recording MCP calls."""
    monkeypatch.setattr(lf, "MCP_TOOL_POOL_SIZE", 0)
    user = cls.__new__(cls)
    user._tool_names = list(tool_names)
    user._tool_schemas = {"fast-time-echo": ECHO_SCHEMA, "fast-time-flaky": FLAKY_SCHEMA}
    user._mcp_session_id = "session-1"
    user._initialized = True
    user.calls = []
    user._mcp_request = lambda method, params, name: user.calls.append((method, params, name))
    return user


def test_tool_caller_calls_a_tool_from_the_full_pool(monkeypatch):
    """MCPToolCallerUser can select any discovered tool, not just the first six."""
    user = _make_user(lf.MCPToolCallerUser, SEVEN_TOOLS + ["fast-time-verify-protocol"], monkeypatch)
    for _ in range(200):
        user.call_tool()
    selected = {params["name"] for method, params, _ in user.calls if method == "tools/call"}
    assert "fast-time-verify-protocol" in selected


def test_stress_user_calls_a_tool_from_the_full_pool(monkeypatch):
    """MCPStressUser uses the same unbounded pool."""
    user = _make_user(lf.MCPStressUser, SEVEN_TOOLS + ["fast-time-verify-protocol"], monkeypatch)
    for _ in range(200):
        user.stress_call_tool()
    selected = {params["name"] for method, params, _ in user.calls if method == "tools/call"}
    assert "fast-time-verify-protocol" in selected


def test_churn_user_runs_full_lifecycle_and_calls_a_tool(monkeypatch):
    """MCPSessionChurnUser re-initializes and then calls a tool from the full pool."""
    user = _make_user(lf.MCPSessionChurnUser, SEVEN_TOOLS, monkeypatch)
    user.full_lifecycle()
    methods = [method for method, _, _ in user.calls]
    assert methods == ["initialize", "tools/list", "tools/call"]


def test_agent_user_calls_tools_with_schema_derived_args(monkeypatch):
    """MCPAgentUser sends schema-derived arguments, not name-guessed ones."""
    user = _make_user(lf.MCPAgentUser, ["fast-time-echo"], monkeypatch)
    user.agent_call_tool()
    user.agent_multi_tool_turn()
    for method, params, _ in user.calls:
        assert method == "tools/call"
        assert set(params["arguments"]) == {"message"}


def test_call_sites_no_op_when_no_tools_discovered(monkeypatch):
    """Every tool-calling task exits quietly when discovery returned nothing."""
    for cls, method_name in (
        (lf.MCPToolCallerUser, "call_tool"),
        (lf.MCPStressUser, "stress_call_tool"),
        (lf.MCPAgentUser, "agent_call_tool"),
    ):
        user = _make_user(cls, [], monkeypatch)
        getattr(user, method_name)()
        assert user.calls == []


def test_rest_baseline_uses_module_level_pool(monkeypatch):
    """RESTBaselineUser reads the module-level pool through _limit_pool."""
    monkeypatch.setattr(lf, "MCP_TOOL_POOL_SIZE", 0)
    monkeypatch.setattr(lf, "_tool_names", SEVEN_TOOLS + ["fast-time-verify-protocol"])
    assert "fast-time-verify-protocol" in lf._limit_pool(lf._tool_names)
