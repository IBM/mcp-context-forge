# -*- coding: utf-8 -*-
"""Benchmark locustfile for realistic scenario-based A/B runs."""

from __future__ import annotations

# Standard
import json
import os
from pathlib import Path
import random
import sys
from typing import Any

# Third-Party
from locust import events, task
from locust.contrib.fasthttp import FastHttpUser

# Make the bundled workload module importable when Locust loads this file directly.
_LOCUST_DIR = Path(__file__).resolve().parent
_CONTEXTFORGE_DIR = _LOCUST_DIR.parent
_REPO_ROOT = _CONTEXTFORGE_DIR.parent.parent
for _path in (str(_REPO_ROOT), str(_CONTEXTFORGE_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

# First-Party
try:
    from benchmarks.contextforge.workload import DEFAULT_VIRTUAL_SERVER_ID, resolve_requests_from_filters, resolve_requests_from_workload
except ModuleNotFoundError:  # pragma: no cover - used by standalone Locust container execution
    from workload import DEFAULT_VIRTUAL_SERVER_ID, resolve_requests_from_filters, resolve_requests_from_workload

REQUEST_COUNT_LIMIT = int(os.getenv("BENCH_REQUEST_COUNT", "0") or "0")
REQUEST_COUNTER = 0
BENCH_SEED = os.getenv("BENCH_SEED", "").strip()
TIMEOUT = 30
MCP_PROTOCOL_VERSION = os.getenv("BENCH_MCP_PROTOCOL_VERSION", "2024-11-05").strip() or "2024-11-05"
MCP_VIRTUAL_SERVER_ID = os.getenv("BENCH_VIRTUAL_SERVER_ID", DEFAULT_VIRTUAL_SERVER_ID).strip() or DEFAULT_VIRTUAL_SERVER_ID
MCP_SESSION_MODE = os.getenv("BENCH_MCP_SESSION_MODE", "reuse").strip().lower() or "reuse"

if BENCH_SEED:
    random.seed(BENCH_SEED)


def _json_env(name: str) -> list[str]:
    raw = os.getenv(name, "[]")
    try:
        loaded = json.loads(raw)
        if isinstance(loaded, list):
            return [str(item) for item in loaded]
    except json.JSONDecodeError:
        pass
    return []


def _bool_env(name: str) -> bool:
    return os.getenv(name, "false").lower() == "true"


def _resolve_requests() -> list[dict[str, Any]]:
    workload_raw = os.getenv("BENCH_WORKLOAD", "").strip()
    if workload_raw:
        try:
            workload = json.loads(workload_raw)
        except json.JSONDecodeError:
            workload = {}
        return resolve_requests_from_workload(workload)

    enabled_groups = set(_json_env("BENCH_ENABLED_GROUPS"))
    disabled_groups = set(_json_env("BENCH_DISABLED_GROUPS"))
    explicit_endpoints = _json_env("BENCH_ENABLED_ENDPOINTS")
    disabled_endpoints = set(_json_env("BENCH_DISABLED_ENDPOINTS"))
    enabled_tags = set(_json_env("BENCH_ENABLED_TAGS"))
    disabled_tags = set(_json_env("BENCH_DISABLED_TAGS"))

    if _bool_env("BENCH_INCLUDE_ADMIN_ENDPOINTS"):
        enabled_groups.add("admin")
    if _bool_env("BENCH_INCLUDE_MCP_ENDPOINTS"):
        enabled_groups.add("mcp")
    if _bool_env("BENCH_INCLUDE_RESOURCE_ENDPOINTS"):
        enabled_groups.add("resources")
    if _bool_env("BENCH_INCLUDE_PROMPT_ENDPOINTS"):
        enabled_groups.add("prompts")
    if _bool_env("BENCH_INCLUDE_TOOL_ENDPOINTS"):
        enabled_groups.add("tools")

    requests = resolve_requests_from_filters(
        enabled_groups=enabled_groups,
        disabled_groups=disabled_groups,
        explicit_endpoints=explicit_endpoints,
        disabled_endpoints=disabled_endpoints,
        enabled_tags=enabled_tags,
        disabled_tags=disabled_tags,
    )
    return requests or resolve_requests_from_workload({"fallback_endpoint": "/health", "endpoints": {}})


def _weighted_choice(requests: list[dict[str, Any]]) -> dict[str, Any]:
    total = sum(int(request.get("weight", 1)) for request in requests)
    needle = random.uniform(0, total)
    running = 0.0
    for request in requests:
        running += int(request.get("weight", 1))
        if needle <= running:
            return request
    return requests[-1]


ACTIVE_REQUESTS = _resolve_requests()


@events.request.add_listener
def count_requests(exception=None, **_kwargs):
    """Stop the test after the configured request count."""
    global REQUEST_COUNTER  # pylint: disable=global-statement
    if exception:
        return
    REQUEST_COUNTER += 1
    if REQUEST_COUNT_LIMIT and REQUEST_COUNTER >= REQUEST_COUNT_LIMIT:
        runner = getattr(events.request, "_environment_runner", None)
        if runner:
            runner.quit()


@events.init.add_listener
def capture_environment(environment, **_kwargs):
    """Store runner reference for request-count termination."""
    setattr(events.request, "_environment_runner", environment.runner)


class BenchmarkScenarioUser(FastHttpUser):
    """Generic benchmark user driven by env-configured request groups."""

    network_timeout = TIMEOUT
    connection_timeout = TIMEOUT

    def on_start(self) -> None:
        token = os.getenv("MCPGATEWAY_BEARER_TOKEN", "").strip()
        self._auth_headers = {"Authorization": f"Bearer {token}"} if token else {}
        self._mcp_session_id = ""
        self._mcp_initialized = False
        self._mcp_session_mode = MCP_SESSION_MODE

    def _headers_for(self, request: dict[str, Any]) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if request.get("auth"):
            headers.update(self._auth_headers)
        if request["kind"] in {"rpc", "mcp", "post"}:
            headers["Content-Type"] = "application/json"
        return headers

    @staticmethod
    def _response_json(response):
        try:
            return response.json()
        except Exception as exc:  # pragma: no cover - Locust response object behavior
            raise ValueError(f"Invalid JSON: {exc}") from exc

    @staticmethod
    def _response_header(response, name: str) -> str:
        headers = getattr(response, "headers", None) or {}
        value = headers.get(name, "") if hasattr(headers, "get") else ""
        return str(value).strip()

    def _reset_mcp_session(self) -> None:
        self._mcp_session_id = ""
        self._mcp_initialized = False

    def _session_mode_for(self, definition: dict[str, Any]) -> str:
        value = str(definition.get("session_mode") or self._mcp_session_mode or "reuse").strip().lower()
        return value if value in {"reuse", "ephemeral"} else "reuse"

    @classmethod
    def _mark_success(cls, response, definition: dict[str, Any], expect_jsonrpc: bool = False) -> None:
        if response.status_code < 200 or response.status_code >= 300:
            response.failure(f"HTTP {response.status_code}")
            return
        expect_json = definition.get("expect_json", False) or expect_jsonrpc
        if not expect_json:
            response.success()
            return
        try:
            payload = cls._response_json(response)
        except ValueError as exc:
            response.failure(str(exc))
            return
        if expect_jsonrpc and "error" in payload:
            response.failure(f"JSON-RPC error: {payload['error']}")
            return
        if expect_jsonrpc and "result" not in payload:
            response.failure("JSON-RPC response missing result")
            return
        validated_payload = payload.get("result") if expect_jsonrpc else payload
        if "expect_list_min_items" in definition:
            if not isinstance(validated_payload, list) or len(validated_payload) < int(definition["expect_list_min_items"]):
                response.failure(f"Expected at least {definition['expect_list_min_items']} list items")
                return
        if "expect_list_item_name" in definition:
            if not isinstance(validated_payload, list) or not any(isinstance(item, dict) and item.get("name") == definition["expect_list_item_name"] for item in validated_payload):
                response.failure(f"Expected item named {definition['expect_list_item_name']}")
                return
        if "expect_result_key" in definition:
            expected = str(definition["expect_result_key"])
            if not isinstance(validated_payload, dict) or expected not in validated_payload:
                response.failure(f"Expected result key '{expected}'")
                return
            if "expect_result_min_items" in definition:
                items = validated_payload.get(expected)
                if not isinstance(items, list) or len(items) < int(definition["expect_result_min_items"]):
                    response.failure(f"Expected at least {definition['expect_result_min_items']} items in result.{expected}")
                    return
        if definition.get("expect_content_text"):
            if not isinstance(validated_payload, dict):
                response.failure("Expected dict result payload with content")
                return
            content = validated_payload.get("content")
            if not isinstance(content, list) or not content or "text" not in (content[0] or {}):
                response.failure("Expected text content in result payload")
                return
        response.success()

    def _mcp_path_for(self, definition: dict[str, Any]) -> str:
        server_id = str(definition.get("server_id") or MCP_VIRTUAL_SERVER_ID)
        return f"/servers/{server_id}/mcp"

    def _ensure_mcp_initialized(self, definition: dict[str, Any]) -> bool:
        if self._mcp_initialized:
            return True
        headers = self._headers_for({"kind": "mcp", "auth": definition.get("auth", True)})
        if self._mcp_session_id:
            headers["Mcp-Session-Id"] = self._mcp_session_id
        payload = {
            "jsonrpc": "2.0",
            "id": "benchmark-init",
            "method": "initialize",
            "params": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "benchmark-locust", "version": "1.0"},
            },
        }
        with self.client.post(self._mcp_path_for(definition), json=payload, name="/mcp initialize [setup]", headers=headers, catch_response=True) as response:
            if response.status_code < 200 or response.status_code >= 300:
                self._reset_mcp_session()
                response.failure(f"HTTP {response.status_code}")
                return False
            session_id = self._response_header(response, "Mcp-Session-Id")
            if session_id:
                self._mcp_session_id = session_id
            try:
                body = self._response_json(response)
            except ValueError as exc:
                self._reset_mcp_session()
                response.failure(str(exc))
                return False
            if "error" in body or "result" not in body:
                self._reset_mcp_session()
                response.failure("MCP initialize failed")
                return False
            self._mcp_initialized = True
            response.success()
            return True

    @task
    def hit_configured_endpoint(self):
        request = _weighted_choice(ACTIVE_REQUESTS)
        definition = request["request"]
        headers = self._headers_for(definition)
        if definition["kind"] == "get":
            with self.client.get(definition["path"], name=request["name"], headers=headers, catch_response=True) as response:
                self._mark_success(response, definition)
            return
        if definition["kind"] == "rpc":
            with self.client.post("/rpc", json=definition["payload"], name=request["name"], headers=headers, catch_response=True) as response:
                self._mark_success(response, definition, expect_jsonrpc=True)
            return
        if definition["kind"] == "post":
            with self.client.post(definition["path"], json=definition["payload"], name=request["name"], headers=headers, catch_response=True) as response:
                self._mark_success(response, definition)
            return
        session_mode = self._session_mode_for(definition)
        if session_mode == "ephemeral":
            self._reset_mcp_session()
        if not self._ensure_mcp_initialized(definition):
            return
        if self._mcp_session_id:
            headers["Mcp-Session-Id"] = self._mcp_session_id
        with self.client.post(self._mcp_path_for(definition), json=definition["payload"], name=request["name"], headers=headers, catch_response=True) as response:
            session_id = self._response_header(response, "Mcp-Session-Id")
            if session_id and session_mode != "ephemeral":
                self._mcp_session_id = session_id
            if response.status_code < 200 or response.status_code >= 300:
                self._reset_mcp_session()
            self._mark_success(response, definition, expect_jsonrpc=True)
            if session_mode == "ephemeral":
                self._reset_mcp_session()
