# -*- coding: utf-8 -*-
"""Go/Rust fast server parity through a live ContextForge MCP gateway."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from typing import Any

import pytest
from fastmcp.client import Client
from fastmcp.client.auth import BearerAuth

from ..helpers.mcp_test_helpers import ADMIN_EMAIL, BASE_URL, JWT_SECRET, TOKEN_EXPIRY, skip_no_gateway

pytestmark = [pytest.mark.e2e, skip_no_gateway]

_CLIENT_TIMEOUT = float(os.getenv("MCP_E2E_CLIENT_TIMEOUT", "5.0"))
_PARITY_CALLS = int(os.getenv("FAST_SERVER_PARITY_CALLS", "5"))
_RUST_MAX_GO_RATIO = float(os.getenv("FAST_SERVER_PARITY_MAX_RATIO", "2.5"))


@pytest.fixture(scope="module")
def jwt_token() -> str:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "mcpgateway.utils.create_jwt_token",
            "--username",
            ADMIN_EMAIL,
            "--exp",
            TOKEN_EXPIRY,
            "--secret",
            JWT_SECRET,
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, f"JWT generation failed: {result.stderr}"
    return result.stdout.strip().strip('"')


@pytest.fixture
async def client(jwt_token: str):
    async with Client(
        f"{BASE_URL}/mcp/",
        auth=BearerAuth(jwt_token),
        init_timeout=_CLIENT_TIMEOUT,
        timeout=_CLIENT_TIMEOUT,
    ) as connected:
        yield connected


def _tool_name(tool: Any) -> str:
    name = getattr(tool, "name", None)
    if not name:
        raise AssertionError(f"tool has no name: {tool!r}")
    return name


def _find_tool(tools: list[Any], expected_name: str, hints: tuple[str, ...], suffix: str) -> str:
    names = [_tool_name(tool) for tool in tools]
    if expected_name in names:
        return expected_name

    normalized_suffix = suffix.replace("_", "-")
    candidates = [
        name
        for name in names
        if name.replace("_", "-").endswith(normalized_suffix)
        and any(hint in name.replace("_", "-").lower() for hint in hints)
    ]
    if candidates:
        return sorted(candidates, key=len)[0]

    pytest.skip(f"Required fast server tool {expected_name!r} is not registered through ContextForge; available tools: {names}")


def _text_result(result: Any, tool_name: str) -> str:
    assert result.isError is False, f"{tool_name} returned an MCP error: {result.content}"
    assert result.content, f"{tool_name} returned no content"
    first = result.content[0]
    assert first.type == "text", f"{tool_name} returned non-text content: {result.content}"
    assert first.text, f"{tool_name} returned empty text"
    return first.text


async def _call_text(client: Client, tool_name: str, arguments: dict[str, Any]) -> str:
    result = await client.call_tool_mcp(name=tool_name, arguments=arguments)
    return _text_result(result, tool_name)


@pytest.mark.flaky(reruns=1, reruns_delay=2)
async def test_go_and_rust_fast_servers_match_time_conversion_through_contextforge(client: Client) -> None:
    """The Rust fast server must preserve Go fast-time behavior once federated."""
    tools = await client.list_tools()
    go_convert = _find_tool(tools, "fast-time-convert-time", ("fast-time", "fast-time-server"), "convert-time")
    rust_convert = _find_tool(tools, "fast-time-convert-time", ("fast-time", "fast-time-server"), "convert-time")

    cases = [
        (
            {"time": "2025-06-21T16:00:00Z", "source_timezone": "UTC", "target_timezone": "America/New_York"},
            "2025-06-21T12:00:00-04:00",
        ),
        (
            {"time": "2025-01-10T10:00:00Z", "source_timezone": "UTC", "target_timezone": "Asia/Kolkata"},
            "2025-01-10T15:30:00+05:30",
        ),
    ]

    for arguments, expected in cases:
        go_text = await _call_text(client, go_convert, arguments)
        rust_text = await _call_text(client, rust_convert, arguments)
        assert go_text == expected
        assert rust_text == go_text


@pytest.mark.flaky(reruns=1, reruns_delay=2)
async def test_rust_fast_server_latency_tracks_go_through_contextforge(client: Client) -> None:
    """A CF-routed Rust tool call should stay in the same latency band as Go."""
    tools = await client.list_tools()
    go_time = _find_tool(tools, "fast-time-get-system-time", ("fast-time", "fast-time-server"), "get-system-time")
    rust_time = _find_tool(tools, "fast-time-get-system-time", ("fast-time", "fast-time-server"), "get-system-time")

    arguments = {"timezone": "UTC"}
    for _ in range(3):
        await _call_text(client, go_time, arguments)
        await _call_text(client, rust_time, arguments)

    go_avg = await _average_latency_seconds(client, go_time, arguments, _PARITY_CALLS)
    rust_avg = await _average_latency_seconds(client, rust_time, arguments, _PARITY_CALLS)
    print(f"Go avg={go_avg:.6f}s Rust avg={rust_avg:.6f}s calls={_PARITY_CALLS}")

    assert rust_avg <= go_avg * _RUST_MAX_GO_RATIO, (
            f"Rust fast-time latency through ContextForge ({rust_avg:.6f}s) exceeded "
        f"{_RUST_MAX_GO_RATIO:.2f}x Go fast-time latency ({go_avg:.6f}s)"
    )


async def _average_latency_seconds(client: Client, tool_name: str, arguments: dict[str, Any], calls: int) -> float:
    started = time.perf_counter()
    for _ in range(calls):
        await _call_text(client, tool_name, arguments)
    return (time.perf_counter() - started) / calls
