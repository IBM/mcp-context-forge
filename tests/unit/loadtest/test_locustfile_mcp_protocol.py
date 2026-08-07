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
