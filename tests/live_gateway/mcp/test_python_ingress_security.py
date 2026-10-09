# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/mcp/test_python_ingress_security.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Black-box Python MCP ingress checks for a gateway with explicit allowlists.
"""

# Standard
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
import threading
import time
import uuid

# Third-Party
import httpx
import pytest
import orjson
from redis import Redis

# Local
from mcpgateway.auth_context import encode_internal_mcp_auth_context, sign_redis_forward_envelope
from tests.helpers.auth import make_test_jwt
from tests.live_gateway.helpers.mcp_test_helpers import ADMIN_EMAIL, BASE_URL, build_initialize, JWT_SECRET, skip_no_gateway


@skip_no_gateway
@pytest.mark.parametrize(
    "headers,detail",
    [
        ({"origin": "https://denied.invalid"}, "Forbidden: Origin not allowed"),
        ({"host": "denied.invalid"}, "Forbidden: Host not allowed"),
    ],
)
def test_python_ingress_rejects_disallowed_headers(headers, detail):
    """Configured public allowlists reject requests through the running gateway mount."""
    if os.getenv("MCP_INGRESS_ALLOWLIST_TESTS") != "true":
        pytest.skip("Requires gateway allowlists excluding denied.invalid and optional MCP_INGRESS_TEST_TOKEN")
    request_headers = {"accept": "application/json, text/event-stream"}
    token = os.getenv("MCP_INGRESS_TEST_TOKEN")
    if token:
        request_headers["authorization"] = f"Bearer {token}"
    request_headers.update(headers)
    response = httpx.post(f"{BASE_URL}/mcp/", headers=request_headers, json=build_initialize(), timeout=10)
    assert response.status_code == 403
    assert response.json()["detail"] == detail


@skip_no_gateway
@pytest.mark.parametrize("signature", [None, "forged"])
def test_running_gateway_rejects_untrusted_affinity_dispatch(signature):
    """Missing or forged runtime authentication cannot invoke internal tools over HTTP."""
    headers = {"x-contextforge-mcp-runtime": "affinity", "x-forwarded-internally": "true", "x-contextforge-auth-context": "forged"}
    if signature is not None:
        headers["x-contextforge-mcp-runtime-auth"] = signature
    response = httpx.post(f"{BASE_URL}/_internal/mcp/rpc", headers=headers, json={"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "protected"}, "id": 1}, timeout=10)
    assert response.status_code in (401, 403)


def _rpc_payload(response):
    """Decode a JSON or SSE JSON-RPC response from the running transport."""
    if "text/event-stream" in response.headers.get("content-type", ""):
        return orjson.loads(next(line[5:].strip() for line in response.text.splitlines() if line.startswith("data:")))
    return response.json()


@skip_no_gateway
def test_stateful_python_session_crosses_workers():
    """A stateful Python session retains successful dispatch across a real Redis affinity hop."""
    redis_url = os.getenv("MCP_AFFINITY_TEST_REDIS_URL")
    token = os.getenv("MCP_INGRESS_TEST_TOKEN")
    if not redis_url or not token:
        pytest.skip("Requires two stateful affinity-enabled workers, MCP_AFFINITY_TEST_REDIS_URL, and MCP_INGRESS_TEST_TOKEN")
    headers = {"accept": "application/json, text/event-stream", "authorization": f"Bearer {token}"}
    with Redis.from_url(redis_url) as redis:
        assert len(redis.pubsub_channels("mcpgw:pool_http:*")) >= 2
        with redis.pubsub() as forwarded:
            forwarded.psubscribe("mcpgw:pool_http:*")
            forwarded.get_message(timeout=2)
            response = httpx.post(f"{BASE_URL}/mcp/", headers=headers, json=build_initialize(), timeout=10)
            assert response.status_code == 200
            assert "result" in _rpc_payload(response)
            session_id = response.headers["mcp-session-id"]
            assert redis.get(f"mcpgw:pool_owner:{session_id}")
            headers.update({"mcp-session-id": session_id, "mcp-protocol-version": "2025-11-25"})
            try:
                response = httpx.post(f"{BASE_URL}/mcp/", headers=headers, json={"jsonrpc": "2.0", "method": "notifications/initialized"}, timeout=10)
                assert response.status_code == 202
                observed = False
                for request_id in range(2, 22):
                    response = httpx.post(f"{BASE_URL}/mcp/", headers=headers, json={"jsonrpc": "2.0", "method": "ping", "id": request_id}, timeout=10)
                    assert response.status_code == 200
                    payload = _rpc_payload(response)
                    assert payload.get("result") == {}, payload
                    message = forwarded.get_message(ignore_subscribe_messages=True, timeout=0.2)
                    if message and orjson.loads(message["data"]).get("mcp_session_id") == session_id:
                        observed = True
                        break
                assert observed, "No Redis affinity hop observed across fresh HTTP connections"
            finally:
                httpx.delete(f"{BASE_URL}/mcp/", headers=headers, timeout=10)


@skip_no_gateway
@pytest.mark.parametrize("signature", [None, "forged"])
def test_running_affinity_consumer_rejects_untrusted_envelope(signature):
    """A real worker rejects an unsigned or forged Redis request before internal dispatch."""
    redis_url = os.getenv("MCP_AFFINITY_TEST_REDIS_URL")
    if not redis_url:
        pytest.skip("Requires affinity-enabled workers and MCP_AFFINITY_TEST_REDIS_URL")
    with Redis.from_url(redis_url) as redis:
        channels = redis.pubsub_channels("mcpgw:pool_http:*")
        assert channels
        response_channel = f"mcpgw:5818_test_response:{uuid.uuid4().hex}"
        with redis.pubsub() as responses:
            responses.subscribe(response_channel)
            responses.get_message(timeout=2)
            envelope = {
                "type": "http_forward",
                "method": "POST",
                "path": "/mcp/",
                "mcp_session_id": uuid.uuid4().hex,
                "response_channel": response_channel,
                "headers": {},
                "auth_context": "forged",
                "body": orjson.dumps({"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "protected"}, "id": 1}).hex(),
            }
            if signature is not None:
                envelope["forward_sig"] = signature
            redis.publish(channels[0], orjson.dumps(envelope))
            message = responses.get_message(ignore_subscribe_messages=True, timeout=10)
            assert message is not None
            response = orjson.loads(message["data"])
            assert response["status"] == 403
            assert orjson.loads(bytes.fromhex(response["body"]))["error"]["code"] == -32003


@skip_no_gateway
def test_cross_worker_protected_tool_denial_preserves_execution_sentinel():
    """Public-only scope cannot execute a team tool through a real worker hop."""
    redis_url = os.getenv("MCP_AFFINITY_TEST_REDIS_URL")
    admin_token = os.getenv("MCP_INGRESS_TEST_TOKEN")
    if os.getenv("MCP_AFFINITY_SENTINEL_TESTS") != "true" or not redis_url or not admin_token:
        pytest.skip("Requires isolated gateway allowing localhost tools, test JWT signing key, Redis URL, and admin token")
    calls = []

    class SentinelHandler(BaseHTTPRequestHandler):
        """Count actual protected backend requests."""

        def do_POST(self):
            """Return a successful tool response and record execution."""
            self.rfile.read(int(self.headers.get("content-length", "0")))
            calls.append(self.path)
            body = b'{"sentinel":"executed"}'
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            """Suppress HTTP server access logs in the test."""

    backend = ThreadingHTTPServer(("127.0.0.1", 0), SentinelHandler)
    thread = threading.Thread(target=backend.serve_forever, daemon=True)
    thread.start()
    rest_headers = {"authorization": f"Bearer {admin_token}"}
    team_id = tool_id = server_id = session_id = None
    mcp_headers = {**rest_headers, "accept": "application/json, text/event-stream"}
    suffix = uuid.uuid4().hex
    try:
        response = httpx.post(f"{BASE_URL}/teams/", headers=rest_headers, json={"name": f"affinity-sentinel-{suffix}"}, timeout=20)
        assert response.status_code in (200, 201), response.text
        team_id = response.json()["id"]
        response = httpx.post(
            f"{BASE_URL}/tools",
            headers=rest_headers,
            json={
                "team_id": team_id,
                "tool": {
                    "name": f"affinity-sentinel-{suffix}",
                    "url": f"http://127.0.0.1:{backend.server_port}/probe",
                    "integration_type": "REST",
                    "request_type": "POST",
                    "input_schema": {"type": "object"},
                    "visibility": "team",
                },
            },
            timeout=20,
        )
        assert response.status_code in (200, 201), response.text
        tool_id = response.json()["id"]
        tool_name = response.json()["name"]
        response = httpx.post(f"{BASE_URL}/servers", headers=rest_headers, json={"server": {"name": f"affinity-sentinel-{suffix}", "associated_tools": [tool_id]}, "visibility": "public"}, timeout=20)
        assert response.status_code in (200, 201), response.text
        server_id = response.json()["id"]
        url = f"{BASE_URL}/servers/{server_id}/mcp/"
        response = httpx.post(url, headers=mcp_headers, json=build_initialize(), timeout=10)
        assert response.status_code == 200, response.text
        session_id = response.headers["mcp-session-id"]
        mcp_headers.update({"mcp-session-id": session_id, "mcp-protocol-version": "2025-11-25"})
        response = httpx.post(url, headers=mcp_headers, json={"jsonrpc": "2.0", "method": "notifications/initialized"}, timeout=10)
        assert response.status_code == 202
        body = {"jsonrpc": "2.0", "method": "tools/call", "params": {"name": tool_name, "arguments": {}}, "id": 2}
        response = httpx.post(url, headers=mcp_headers, json=body, timeout=20)
        assert response.status_code == 200, response.text
        positive = _rpc_payload(response)
        assert "result" in positive and not positive["result"].get("isError"), positive
        assert len(calls) == 1, positive
        restricted = make_test_jwt(ADMIN_EMAIL, is_admin=True, teams=[], secret=JWT_SECRET)
        denied_headers = {**mcp_headers, "authorization": f"Bearer {restricted}"}
        response = httpx.post(url, headers=denied_headers, json=body, timeout=20)
        assert response.status_code == 200, response.text
        payload = _rpc_payload(response)
        assert "error" in payload or payload.get("result", {}).get("isError") is True, payload
        with Redis.from_url(redis_url) as redis, redis.pubsub() as responses:
            assert len(redis.pubsub_channels("mcpgw:pool_http:*")) >= 2
            owner = redis.get(f"mcpgw:pool_owner:{session_id}").decode()
            response_channel = f"mcpgw:5818_test_response:{uuid.uuid4().hex}"
            responses.subscribe(response_channel)
            responses.get_message(timeout=2)
            context = encode_internal_mcp_auth_context({"email": ADMIN_EMAIL, "teams": [], "is_authenticated": True, "is_admin": True, "permission_is_admin": True})
            envelope = {
                "type": "http_forward",
                "timestamp": time.time(),
                "method": "POST",
                "path": f"/servers/{server_id}/mcp/",
                "mcp_session_id": session_id,
                "response_channel": response_channel,
                "headers": {},
                "auth_context": context,
                "body": orjson.dumps(body).hex(),
            }
            envelope["forward_sig"] = sign_redis_forward_envelope(envelope)
            redis.publish(f"mcpgw:pool_http:{owner}", orjson.dumps(envelope))
            message = responses.get_message(ignore_subscribe_messages=True, timeout=10)
            assert message is not None
            forwarded = orjson.loads(message["data"])
            assert forwarded["status"] == 200, forwarded
            payload = orjson.loads(bytes.fromhex(forwarded["body"]))
            assert payload["error"]["code"] == -32601, payload
            assert len(calls) == 1, "Denied requests must never reach the backend"
    finally:
        if session_id and server_id:
            httpx.delete(f"{BASE_URL}/servers/{server_id}/mcp/", headers=mcp_headers, timeout=10)
        if server_id:
            httpx.delete(f"{BASE_URL}/servers/{server_id}", headers=rest_headers, timeout=10)
        if tool_id:
            httpx.delete(f"{BASE_URL}/tools/{tool_id}", headers=rest_headers, timeout=10)
        if team_id:
            httpx.delete(f"{BASE_URL}/teams/{team_id}", headers=rest_headers, timeout=10)
        backend.shutdown()
        backend.server_close()
        thread.join(timeout=5)
