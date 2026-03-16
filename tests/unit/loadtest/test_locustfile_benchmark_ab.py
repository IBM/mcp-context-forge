# -*- coding: utf-8 -*-
"""Tests for benchmark Locust request selection."""

# Standard
import importlib
import json
import sys
import types


class _DummyEventHook:
    def add_listener(self, fn):
        return fn


def _install_locust_stub():
    module = types.ModuleType("locust")
    module.task = lambda fn: fn
    module.events = types.SimpleNamespace(request=_DummyEventHook(), init=_DummyEventHook())
    sys.modules["locust"] = module

    contrib = types.ModuleType("locust.contrib")
    fasthttp = types.ModuleType("locust.contrib.fasthttp")
    fasthttp.FastHttpUser = type("FastHttpUser", (), {})
    contrib.fasthttp = fasthttp
    sys.modules["locust.contrib"] = contrib
    sys.modules["locust.contrib.fasthttp"] = fasthttp


def test_resolve_requests_filters_plugin_heavy_tool_mix(monkeypatch):
    _install_locust_stub()
    monkeypatch.delenv("BENCH_WORKLOAD", raising=False)
    monkeypatch.setenv("BENCH_ENABLED_GROUPS", '["tools"]')
    monkeypatch.setenv("BENCH_DISABLED_GROUPS", "[]")
    monkeypatch.setenv("BENCH_ENABLED_ENDPOINTS", "[]")
    monkeypatch.setenv("BENCH_DISABLED_ENDPOINTS", "[]")
    monkeypatch.setenv("BENCH_ENABLED_TAGS", '["plugin-heavy"]')
    monkeypatch.setenv("BENCH_DISABLED_TAGS", "[]")
    monkeypatch.setenv("BENCH_SEED", "7")

    module = importlib.import_module("benchmarks.contextforge.locust.locustfile_benchmark_ab")
    module = importlib.reload(module)

    names = [request["name"] for request in module.ACTIVE_REQUESTS]
    assert "/mcp tools/call fast-time-get-system-time" in names
    assert "/mcp tools/call fast-time-convert-time" in names
    assert "/health" not in names


def test_include_flags_map_to_real_request_groups(monkeypatch):
    _install_locust_stub()
    monkeypatch.delenv("BENCH_WORKLOAD", raising=False)
    monkeypatch.setenv("BENCH_ENABLED_GROUPS", "[]")
    monkeypatch.setenv("BENCH_DISABLED_GROUPS", "[]")
    monkeypatch.setenv("BENCH_ENABLED_ENDPOINTS", "[]")
    monkeypatch.setenv("BENCH_DISABLED_ENDPOINTS", "[]")
    monkeypatch.setenv("BENCH_ENABLED_TAGS", "[]")
    monkeypatch.setenv("BENCH_DISABLED_TAGS", "[]")
    monkeypatch.setenv("BENCH_INCLUDE_RESOURCE_ENDPOINTS", "true")
    monkeypatch.setenv("BENCH_INCLUDE_PROMPT_ENDPOINTS", "true")
    monkeypatch.setenv("BENCH_INCLUDE_TOOL_ENDPOINTS", "true")
    monkeypatch.setenv("BENCH_INCLUDE_MCP_ENDPOINTS", "true")
    monkeypatch.delenv("BENCH_SEED", raising=False)

    module = importlib.import_module("benchmarks.contextforge.locust.locustfile_benchmark_ab")
    module = importlib.reload(module)

    names = {request["name"] for request in module.ACTIVE_REQUESTS}
    assert "/mcp resources/read timezone://info" in names
    assert "/mcp prompts/get fast-time-schedule-meeting" in names
    assert "/mcp tools/call fast-time-get-system-time" in names
    assert "/mcp tools/list" in names


def test_resolve_requests_falls_back_to_health_when_empty(monkeypatch):
    _install_locust_stub()
    monkeypatch.delenv("BENCH_WORKLOAD", raising=False)
    monkeypatch.setenv("BENCH_ENABLED_GROUPS", '["admin"]')
    monkeypatch.setenv("BENCH_DISABLED_GROUPS", '["admin"]')
    monkeypatch.setenv("BENCH_ENABLED_ENDPOINTS", "[]")
    monkeypatch.setenv("BENCH_DISABLED_ENDPOINTS", "[]")
    monkeypatch.setenv("BENCH_ENABLED_TAGS", "[]")
    monkeypatch.setenv("BENCH_DISABLED_TAGS", "[]")

    module = importlib.import_module("benchmarks.contextforge.locust.locustfile_benchmark_ab")
    module = importlib.reload(module)

    assert [request["name"] for request in module.ACTIVE_REQUESTS] == ["/health"]


def test_resolve_requests_prefers_toml_workload_over_legacy_filters(monkeypatch):
    _install_locust_stub()
    monkeypatch.setenv(
        "BENCH_WORKLOAD",
        json.dumps(
            {
                "fallback_endpoint": "/health",
                "endpoints": {
                    "/health": {"enabled": False},
                    "/mcp tools/call fast-time-get-system-time": {"enabled": True, "weight": 11},
                    "/mcp prompts/get fast-time-schedule-meeting": {"enabled": True, "weight": 7},
                },
            }
        ),
    )
    monkeypatch.setenv("BENCH_ENABLED_GROUPS", '["health"]')
    monkeypatch.setenv("BENCH_DISABLED_GROUPS", "[]")
    monkeypatch.setenv("BENCH_ENABLED_ENDPOINTS", "[]")
    monkeypatch.setenv("BENCH_DISABLED_ENDPOINTS", "[]")
    monkeypatch.setenv("BENCH_ENABLED_TAGS", "[]")
    monkeypatch.setenv("BENCH_DISABLED_TAGS", "[]")

    module = importlib.import_module("benchmarks.contextforge.locust.locustfile_benchmark_ab")
    module = importlib.reload(module)

    names = {request["name"] for request in module.ACTIVE_REQUESTS}
    weights = {request["name"]: request["weight"] for request in module.ACTIVE_REQUESTS}
    assert names == {
        "/mcp tools/call fast-time-get-system-time",
        "/mcp prompts/get fast-time-schedule-meeting",
    }
    assert weights["/mcp tools/call fast-time-get-system-time"] == 11
    assert weights["/mcp prompts/get fast-time-schedule-meeting"] == 7


def test_response_header_handles_missing_headers(monkeypatch):
    _install_locust_stub()
    monkeypatch.delenv("BENCH_WORKLOAD", raising=False)

    module = importlib.import_module("benchmarks.contextforge.locust.locustfile_benchmark_ab")
    module = importlib.reload(module)

    response = types.SimpleNamespace(headers=None)
    assert module.BenchmarkScenarioUser._response_header(response, "Mcp-Session-Id") == ""


def test_session_mode_env_is_loaded(monkeypatch):
    _install_locust_stub()
    monkeypatch.setenv("BENCH_MCP_SESSION_MODE", "ephemeral")

    module = importlib.import_module("benchmarks.contextforge.locust.locustfile_benchmark_ab")
    module = importlib.reload(module)

    assert module.MCP_SESSION_MODE == "ephemeral"


def test_resolve_requests_supports_a2a_invoke_workload(monkeypatch):
    _install_locust_stub()
    monkeypatch.setenv(
        "BENCH_WORKLOAD",
        json.dumps(
            {
                "fallback_endpoint": "/a2a/a2a-echo-agent/invoke",
                "endpoints": {
                    "/a2a": {"enabled": False},
                    "/a2a/a2a-echo-agent/invoke": {"enabled": True, "weight": 1},
                },
            }
        ),
    )

    module = importlib.import_module("benchmarks.contextforge.locust.locustfile_benchmark_ab")
    module = importlib.reload(module)

    assert [request["name"] for request in module.ACTIVE_REQUESTS] == ["/a2a/a2a-echo-agent/invoke"]
    definition = module.ACTIVE_REQUESTS[0]["request"]
    assert definition["kind"] == "post"
    assert definition["path"] == "/a2a/a2a-echo-agent/invoke"
