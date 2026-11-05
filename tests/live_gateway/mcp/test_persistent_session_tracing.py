# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/mcp/test_persistent_session_tracing.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Verify stateful upstream reuse and metadata tracing through a running gateway.
"""

# Standard
import asyncio
import json
import secrets
from typing import Any

# Third-Party
import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
import pytest

# Local
from tests.live_gateway.mcp.test_request_trace_policy import _spans, _wait

pytest_plugins = ["tests.live_gateway.mcp.test_request_trace_policy"]

pytestmark = pytest.mark.e2e

_UPSTREAM = '''
import json
from pathlib import Path
import sys
import time
from mcp.server.mcpserver import MCPServer, Context
from opentelemetry import propagate, trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
import uvicorn
provider = TracerProvider()
provider.add_span_processor(SimpleSpanProcessor(OTLPSpanExporter(endpoint=sys.argv[3] + "/v1/traces")))
tracer = provider.get_tracer("upstream-test")
mcp = MCPServer("session-tracing")
counters = {}
@mcp.tool()
def echo(value: str, ctx: Context) -> str:
    """Increment this session's counter or return a controlled error."""
    meta = ctx.request_context.meta
    carrier = dict(meta or {})
    with tracer.start_as_current_span("upstream.tool", context=propagate.extract(carrier)) as span:
        time.sleep(0.01)
        if value == "fail":
            raise ValueError("controlled upstream error")
        request = ctx.request_context.request
        key = request.headers.get("mcp-session-id") or request.query_params.get("session_id")
        assert key is not None
        counters[key] = counters.get(key, 0) + 1
        return json.dumps({"counter": counters[key], "meta": carrier})
class Capture(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        body = await request.body()
        with Path(sys.argv[2]).open("a") as output:
            output.write(json.dumps({"method": request.method, "body": body.decode(), "headers": dict(request.headers)}) + "\\n")
        if body and request.url.path == "/mcp":
            message = json.loads(body)
            if message.get("method") == "server/discover":
                return JSONResponse({"jsonrpc": "2.0", "id": message["id"], "error": {"code": -32022, "message": "Legacy stateful upstream", "data": {"supported": ["2025-11-25"]}}})
        return await call_next(request)
app = mcp.sse_app() if "--sse" in sys.argv else mcp.streamable_http_app(stateless_http=False, json_response=True)
app.add_middleware(Capture)
uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[1]), log_level="error")
'''


def _configuration(transport: str, mode: str, enabled: bool = True) -> dict[str, Any]:
    """Configure the live fixture for one upstream transport and tracing mode."""
    source = _UPSTREAM.replace('"--sse" in sys.argv', str(transport == "SSE"))
    return {
        "transport": transport,
        "upstream": source,
        "env": {
            "MCP_CLIENT_CONNECT_MODE": mode,
            "USE_STATEFUL_SESSIONS": "true",
            "COMPRESSION_ENABLED": "false",
            "OTEL_ENABLE_OBSERVABILITY": str(enabled).lower(),
            "OTEL_HTTPX_INSTRUMENTATION_ENABLED": "false",
            "OTEL_CAPTURE_IDENTITY_ATTRIBUTES": "true",
            "OTEL_BAGGAGE_PROPAGATE_TO_EXTERNAL": "true",
            "HEALTH_CHECK_INTERVAL": "3600",
        },
    }


@pytest.mark.parametrize(
    "traced_gateway",
    [_configuration(transport, mode) for transport in ("SSE", "STREAMABLEHTTP") for mode in ("legacy", "auto")],
    ids=["sse-legacy", "sse-auto", "http-legacy", "http-auto"],
    indirect=True,
)
def test_reused_sessions_have_independent_traces(traced_gateway: Any) -> None:
    """Preserve state and upstream IDs while exporting fresh parents and baggage for every call."""
    client, server_id, tool_name, snapshot, events, _, _ = traced_gateway
    traces = [secrets.token_hex(16) for _ in range(4)]

    async def exercise() -> None:
        headers = {**dict(client.headers), "Accept-Encoding": "identity"}
        async with httpx2.AsyncClient(headers=headers, timeout=30, trust_env=False) as http_client:
            async with streamable_http_client(f"{str(client.base_url).rstrip('/')}/servers/{server_id}/mcp", http_client=http_client) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    for index, trace_id in enumerate(traces):
                        http_client.headers["traceparent"] = f"00-{trace_id}-0123456789abcdef-01"
                        http_client.headers["X-Tenant-ID"] = f"tenant-{index}"
                        http_client.headers["tracestate"] = f"vendor=call{index}"
                        result = await session.call_tool(tool_name, {"value": "fail" if index == 2 else "increment"})
                        if index == 2:
                            assert result.is_error
                        else:
                            assert not result.is_error, result
                            payload = json.loads(next(item.text for item in result.content if hasattr(item, "text")))
                            assert payload["counter"] == (index + 1 if index < 2 else 3)
                            assert payload["meta"]["traceparent"].split("-")[1] == trace_id
                            assert payload["meta"]["tracestate"] == f"vendor=call{index}"
                            assert f"tenant.id=tenant-{index}" in payload["meta"]["baggage"]

    asyncio.run(exercise())
    _wait(lambda: all(any(span["name"] == "tool.invoke" and span["trace_id"] == trace_id for span in _spans(snapshot)) for trace_id in traces), "tool trace exports")
    _wait(lambda: len([span for span in _spans(snapshot) if span["name"] == "upstream.tool" and span["trace_id"] in traces]) == 4, "upstream trace exports")
    ids = set()
    for index, trace_id in enumerate(traces):
        spans = [span for span in _spans(snapshot) if span["trace_id"] == trace_id]
        by_name = {span["name"]: span for span in spans}
        for name in ("tool.invoke", "mcp.client.call", "mcp.client.request", "mcp.client.response"):
            span = by_name[name]
            ids.add(span["attributes"]["gateway.upstream.session_id"])
            assert span["status"] == (2 if index == 2 else 1)
            assert span["duration_ns"] > 0
        parent = next(span for span in spans if span["span_id"] == by_name["upstream.tool"]["parent_span_id"])
        assert parent["name"] == "MCP send tools/call echo"
        assert parent["parent_span_id"] == by_name["mcp.client.request"]["span_id"]
        assert by_name["tool.invoke"]["attributes"]["user.email"] == "admin@example.com"
        assert by_name["mcp.client.request"]["attributes"]["baggage.tenant.id"] == f"tenant-{index}"
        assert ("mcp.client.initialize" in by_name) == (index == 0)
    assert len(ids) == 1
    calls = []
    for line in events.read_text().splitlines():
        event = json.loads(line)
        if event["body"]:
            body = json.loads(event["body"])
            if body.get("method") == "tools/call":
                calls.append(event)
    assert len(calls) == 4
    assert all(not {"traceparent", "tracestate", "baggage", "x-correlation-id"} & event["headers"].keys() for event in calls)


@pytest.mark.parametrize("traced_gateway", [_configuration("STREAMABLEHTTP", "legacy", False)], indirect=True)
def test_session_reuse_without_gateway_tracing(traced_gateway: Any) -> None:
    """Retain state with gateway tracing disabled and remove stale metadata propagation fields."""
    client, server_id, tool_name, snapshot, _, _, _ = traced_gateway

    async def exercise() -> None:
        async with httpx2.AsyncClient(headers={**dict(client.headers), "Accept-Encoding": "identity"}, timeout=30, trust_env=False) as http_client:
            async with streamable_http_client(f"{str(client.base_url).rstrip('/')}/servers/{server_id}/mcp", http_client=http_client) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    for counter in (1, 2):
                        result = await session.call_tool(tool_name, {"value": "increment"}, meta={"traceparent": "stale", "baggage": "tenant.id=stale"})
                        assert not result.is_error
                        payload = json.loads(next(item.text for item in result.content if hasattr(item, "text")))
                        assert payload["counter"] == counter
                        assert "traceparent" not in payload["meta"]
                        assert "baggage" not in payload["meta"]

    asyncio.run(exercise())
    assert not any(span["name"] == "tool.invoke" for span in _spans(snapshot))


@pytest.mark.parametrize("traced_gateway", [_configuration(transport, "legacy") for transport in ("SSE", "STREAMABLEHTTP")], ids=["sse", "http"], indirect=True)
def test_concurrent_downstream_sessions_keep_state_and_context_private(traced_gateway: Any) -> None:
    """Keep independent counters, upstream IDs, and trace metadata across concurrent downstream sessions."""
    client, server_id, tool_name, snapshot, _, _, _ = traced_gateway
    traces = [secrets.token_hex(16), secrets.token_hex(16)]

    async def run_session(index: int) -> None:
        headers = {**dict(client.headers), "traceparent": f"00-{traces[index]}-0123456789abcdef-01", "X-Tenant-ID": f"tenant-{index}"}
        async with httpx2.AsyncClient(headers=headers, timeout=30, trust_env=False) as http_client:
            async with streamable_http_client(f"{str(client.base_url).rstrip('/')}/servers/{server_id}/mcp", http_client=http_client) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    for expected in (1, 2):
                        result = await session.call_tool(tool_name, {"value": "increment"})
                        assert not result.is_error
                        payload = json.loads(next(item.text for item in result.content if hasattr(item, "text")))
                        assert payload["counter"] == expected
                        assert payload["meta"]["traceparent"].split("-")[1] == traces[index]
                        assert f"tenant.id=tenant-{index}" in payload["meta"]["baggage"]

    async def exercise() -> None:
        await asyncio.gather(run_session(0), run_session(1))

    asyncio.run(exercise())
    _wait(lambda: all(len([span for span in _spans(snapshot) if span["name"] == "tool.invoke" and span["trace_id"] == trace]) == 2 for trace in traces), "concurrent tool traces")
    ids = [{span["attributes"]["gateway.upstream.session_id"] for span in _spans(snapshot) if span["name"] == "tool.invoke" and span["trace_id"] == trace} for trace in traces]
    assert len(ids[0]) == len(ids[1]) == 1
    assert ids[0].isdisjoint(ids[1])


@pytest.mark.parametrize("traced_gateway", [_configuration("STREAMABLEHTTP", "legacy")], indirect=True)
def test_denied_requests_do_not_reach_upstream(traced_gateway: Any) -> None:
    """Reject unauthenticated, wrong-team, and insufficient-permission calls before upstream invocation."""
    # Third-Party
    import httpx

    # Local
    from tests.helpers.auth import make_auth_headers

    client, server_id, tool_name, _, events, options, _ = traced_gateway
    payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool_name, "arguments": {"value": "increment"}}}

    def upstream_call_count() -> int:
        return sum('"tools/call"' in json.loads(line).get("body", "") for line in events.read_text().splitlines())

    initial = upstream_call_count()
    url = f"{str(client.base_url).rstrip('/')}/servers/{server_id}/mcp"
    response = httpx.post(url, json=payload, headers={"Accept": "application/json, text/event-stream"}, trust_env=False)
    assert response.status_code == 401
    restricted = options["token_factory"](email="admin@example.com", is_admin=True, teams=None, scopes={"permissions": ["tools.read"]})

    async def denied_call() -> None:
        headers = dict(client.headers)
        statuses = []

        async def capture_status(response: httpx2.Response) -> None:
            statuses.append(response.status_code)

        async with httpx2.AsyncClient(headers=headers, timeout=30, trust_env=False, event_hooks={"response": [capture_status]}) as http_client:
            async with streamable_http_client(url, http_client=http_client) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    http_client.headers.update(make_auth_headers(restricted))
                    # Third-Party
                    from mcp.shared.exceptions import MCPError

                    try:
                        result = await session.call_tool(tool_name, {"value": "increment"})
                    except MCPError as exc:
                        assert 403 in statuses, (str(exc), statuses)
                    else:
                        assert result.is_error, result
                        assert any(word in str(result).lower() for word in ("permission", "forbidden", "denied")), result
                    finally:
                        http_client.headers.update(headers)

    asyncio.run(denied_call())
    team = client.post("/teams/", json={"name": "session-trace-private", "visibility": "private"})
    assert team.status_code in (200, 201), team.text
    team_server = client.post("/servers", json={"server": {"name": "team-server", "associated_tools": []}, "team_id": team.json()["id"], "visibility": "team"})
    assert team_server.status_code in (200, 201), team_server.text
    wrong_team = options["token_factory"](email="admin@example.com", is_admin=True, teams=["other-team"])
    response = httpx.post(
        f"{str(client.base_url).rstrip('/')}/servers/{team_server.json()['id']}/mcp",
        json=payload,
        headers={**make_auth_headers(wrong_team), "Accept": "application/json, text/event-stream"},
        trust_env=False,
    )
    assert response.status_code in (403, 404), response.text
    assert upstream_call_count() == initial
