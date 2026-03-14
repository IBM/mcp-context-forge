# -*- coding: utf-8 -*-
"""Shared benchmark workload catalog and selection helpers."""

from __future__ import annotations

# Standard
from copy import deepcopy
import json
from pathlib import Path
from typing import Any

PAYLOAD_ROOT = Path(__file__).resolve().parent / "payloads"
DEFAULT_FALLBACK_ENDPOINT = "/health"
SUPPORTED_WORKLOAD_SELECTIONS = {"weighted-random"}
DEFAULT_VIRTUAL_SERVER_ID = "9779b6698cbd4b4995ee04a4fab38737"


def _load_payload(group: str, name: str) -> dict[str, Any]:
    return json.loads((PAYLOAD_ROOT / group / name).read_text(encoding="utf-8"))


def benchmark_catalog() -> list[dict[str, Any]]:
    return [
        {
            "name": "/health",
            "group": "health",
            "tags": {"health"},
            "weight": 10,
            "request": {"kind": "get", "path": "/health", "expect_json": True, "auth": False},
        },
        {
            "name": "/ready",
            "group": "health",
            "tags": {"health"},
            "weight": 4,
            "request": {"kind": "get", "path": "/ready", "expect_json": True, "auth": False},
        },
        {
            "name": "/admin/plugins",
            "group": "admin",
            "tags": {"admin", "plugins"},
            "weight": 2,
            "request": {"kind": "get", "path": "/admin/plugins", "expect_json": False, "auth": True},
        },
        {
            "name": "/servers",
            "group": "servers",
            "tags": {"servers", "rest", "discovery"},
            "weight": 5,
            "request": {
                "kind": "get",
                "path": "/servers",
                "expect_json": True,
                "auth": True,
                "expect_list_min_items": 1,
                "expect_list_item_name": "Fast Time Server",
            },
        },
        {
            "name": "/a2a",
            "group": "a2a",
            "tags": {"a2a", "rest", "discovery"},
            "weight": 3,
            "request": {
                "kind": "get",
                "path": "/a2a",
                "expect_json": True,
                "auth": True,
                "expect_list_min_items": 1,
                "expect_list_item_name": "a2a-echo-agent",
            },
        },
        {
            "name": "/a2a/a2a-echo-agent/invoke",
            "group": "a2a",
            "tags": {"a2a", "invoke", "echo"},
            "weight": 8,
            "request": {
                "kind": "post",
                "path": "/a2a/a2a-echo-agent/invoke",
                "auth": True,
                "payload": {
                    "parameters": {
                        "message": {
                            "kind": "message",
                            "role": "user",
                            "messageId": "benchmark-a2a-invoke",
                            "parts": [{"kind": "text", "text": "benchmark ping"}],
                        }
                    },
                    "interaction_type": "query",
                },
                "expect_json": True,
                "expect_result_key": "result",
            },
        },
        {
            "name": "/mcp tools/list",
            "group": "mcp",
            "tags": {"mcp", "tools", "discovery"},
            "weight": 3,
            "request": {
                "kind": "mcp",
                "payload": _load_payload("tools", "list_tools.json"),
                "auth": True,
                "server_id": DEFAULT_VIRTUAL_SERVER_ID,
                "expect_result_key": "tools",
                "expect_result_min_items": 2,
            },
        },
        {
            "name": "/mcp tools/call fast-time-get-system-time",
            "group": "tools",
            "tags": {"tools", "mcp", "plugin-heavy"},
            "weight": 8,
            "request": {
                "kind": "mcp",
                "payload": _load_payload("tools", "get_system_time.json"),
                "auth": True,
                "server_id": DEFAULT_VIRTUAL_SERVER_ID,
                "expect_content_text": True,
            },
        },
        {
            "name": "/mcp tools/call fast-time-convert-time",
            "group": "tools",
            "tags": {"tools", "mcp", "plugin-heavy"},
            "weight": 6,
            "request": {
                "kind": "mcp",
                "payload": _load_payload("tools", "convert_time.json"),
                "auth": True,
                "server_id": DEFAULT_VIRTUAL_SERVER_ID,
                "expect_content_text": True,
            },
        },
        {
            "name": "/resources",
            "group": "resources",
            "tags": {"resources", "rest"},
            "weight": 3,
            "request": {"kind": "get", "path": "/resources", "expect_json": True, "auth": True, "expect_list_min_items": 1},
        },
        {
            "name": "/mcp resources/list",
            "group": "mcp",
            "tags": {"mcp", "resources"},
            "weight": 3,
            "request": {
                "kind": "mcp",
                "payload": _load_payload("resources", "list_resources.json"),
                "auth": True,
                "server_id": DEFAULT_VIRTUAL_SERVER_ID,
                "expect_result_key": "resources",
                "expect_result_min_items": 1,
            },
        },
        {
            "name": "/mcp resources/read timezone://info",
            "group": "resources",
            "tags": {"resources", "mcp", "plugin-heavy"},
            "weight": 5,
            "request": {
                "kind": "mcp",
                "payload": _load_payload("resources", "read_timezone_info.json"),
                "auth": True,
                "server_id": DEFAULT_VIRTUAL_SERVER_ID,
                "expect_result_key": "contents",
                "expect_result_min_items": 1,
            },
        },
        {
            "name": "/mcp resources/read time://current/world",
            "group": "resources",
            "tags": {"resources", "mcp", "plugin-heavy"},
            "weight": 4,
            "request": {
                "kind": "mcp",
                "payload": _load_payload("resources", "read_world_times.json"),
                "auth": True,
                "server_id": DEFAULT_VIRTUAL_SERVER_ID,
                "expect_result_key": "contents",
                "expect_result_min_items": 1,
            },
        },
        {
            "name": "/prompts",
            "group": "prompts",
            "tags": {"prompts", "rest"},
            "weight": 3,
            "request": {"kind": "get", "path": "/prompts", "expect_json": True, "auth": True, "expect_list_min_items": 1},
        },
        {
            "name": "/mcp prompts/list",
            "group": "mcp",
            "tags": {"mcp", "prompts"},
            "weight": 3,
            "request": {
                "kind": "mcp",
                "payload": _load_payload("prompts", "list_prompts.json"),
                "auth": True,
                "server_id": DEFAULT_VIRTUAL_SERVER_ID,
                "expect_result_key": "prompts",
                "expect_result_min_items": 1,
            },
        },
        {
            "name": "/mcp prompts/get fast-time-schedule-meeting",
            "group": "prompts",
            "tags": {"prompts", "mcp", "plugin-heavy"},
            "weight": 5,
            "request": {
                "kind": "mcp",
                "payload": _load_payload("prompts", "get_customer_greeting.json"),
                "auth": True,
                "server_id": DEFAULT_VIRTUAL_SERVER_ID,
                "expect_result_key": "messages",
                "expect_result_min_items": 1,
            },
        },
        {
            "name": "/mcp prompts/get fast-time-compare-timezones",
            "group": "prompts",
            "tags": {"prompts", "mcp", "plugin-heavy"},
            "weight": 4,
            "request": {
                "kind": "mcp",
                "payload": _load_payload("prompts", "get_compare_timezones.json"),
                "auth": True,
                "server_id": DEFAULT_VIRTUAL_SERVER_ID,
                "expect_result_key": "messages",
                "expect_result_min_items": 1,
            },
        },
    ]


def benchmark_request_names() -> set[str]:
    return {request["name"] for request in benchmark_catalog()}


def resolve_requests_from_filters(
    *,
    enabled_groups: set[str] | None = None,
    disabled_groups: set[str] | None = None,
    explicit_endpoints: list[str] | None = None,
    disabled_endpoints: set[str] | None = None,
    enabled_tags: set[str] | None = None,
    disabled_tags: set[str] | None = None,
) -> list[dict[str, Any]]:
    enabled_groups = enabled_groups or set()
    disabled_groups = disabled_groups or set()
    explicit_endpoints = explicit_endpoints or []
    disabled_endpoints = disabled_endpoints or set()
    enabled_tags = enabled_tags or set()
    disabled_tags = disabled_tags or set()

    requests: list[dict[str, Any]] = []
    for request in benchmark_catalog():
        if explicit_endpoints and request["name"] not in explicit_endpoints:
            continue
        if request["name"] in disabled_endpoints:
            continue
        if enabled_groups and request["group"] not in enabled_groups:
            continue
        if request["group"] in disabled_groups:
            continue
        if enabled_tags and not (request["tags"] & enabled_tags):
            continue
        if request["tags"] & disabled_tags:
            continue
        requests.append(request)
    return requests


def resolve_requests_from_workload(workload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not workload:
        return benchmark_catalog()

    endpoint_overrides = workload.get("endpoints")
    if endpoint_overrides is None:
        return benchmark_catalog()
    endpoints = endpoint_overrides or {}
    requests: list[dict[str, Any]] = []
    for request in benchmark_catalog():
        override = endpoints.get(request["name"])
        if override is None:
            continue
        override = override or {}
        enabled = override.get("enabled", True)
        weight = int(override.get("weight", request.get("weight", 1)) or 0)
        if not enabled or weight <= 0:
            continue
        resolved = deepcopy(request)
        resolved["weight"] = weight
        requests.append(resolved)

    if requests:
        return requests

    fallback_name = str(workload.get("fallback_endpoint") or DEFAULT_FALLBACK_ENDPOINT)
    fallback = next((request for request in benchmark_catalog() if request["name"] == fallback_name), None)
    return [deepcopy(fallback)] if fallback else [deepcopy(request) for request in benchmark_catalog() if request["name"] == DEFAULT_FALLBACK_ENDPOINT]
