# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/reverse_proxy/test_reverse_proxy_e2e.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Live maintained-client verification for distributed reverse-proxy routing.
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import time
from urllib.error import HTTPError

import pytest
import websockets

from mcpgateway.services.reverse_proxy_protocol import JsonObject
from tests.live_gateway.reverse_proxy.helpers.live_helpers import (
    AUTH_CLIENT_PID,
    AUTH_SERVER_NAME,
    AUTH_TOOL_NAME,
    AUTHORITY_SERVER_NAME,
    BASE_URL,
    COMPLIANCE_PROMPT_NAME,
    COMPOSE_PROJECT,
    FAST_CLIENT_PID,
    FAST_SERVER_NAME,
    FAST_TOOL_NAME,
    RESTRICTED_TOKEN,
    TOKEN,
    json_request as _json_request,
    post as _post,
    put as _put,
    rpc as _rpc,
    rpc_text as _rpc_text,
    wait_for_gateway as _wait_for_gateway,
    wait_for_tool as _wait_for_tool,
)


def _session_ids_for_server(response: JsonObject | list[JsonObject], server_name: str) -> set[str]:
    """Extract live connection IDs for one registered server."""
    assert isinstance(response, dict)
    sessions = response.get("sessions")
    assert isinstance(sessions, list)
    session_ids: set[str] = set()
    for session in sessions:
        assert isinstance(session, dict)
        server_info = session.get("server_info")
        if not isinstance(server_info, dict) or server_info.get("name") != server_name:
            continue
        session_id = session.get("session_id")
        assert isinstance(session_id, str)
        session_ids.add(session_id)
    return session_ids


@pytest.mark.e2e
def test_websocket_auth_denials_preserve_http_status() -> None:
    async def verify() -> None:
        for suffix in ("", "?token=forbidden"):
            with pytest.raises(websockets.InvalidStatus) as rejected:
                async with websockets.connect(f"{BASE_URL.replace('http', 'ws', 1)}/reverse-proxy/ws{suffix}"):
                    pytest.fail("unauthenticated WebSocket was accepted")
            assert rejected.value.response.status_code == 401

    import anyio

    anyio.run(verify)


@pytest.mark.e2e
def test_websocket_insufficient_token_scope_returns_403() -> None:
    async def verify() -> None:
        with pytest.raises(websockets.InvalidStatus) as rejected:
            async with websockets.connect(
                f"{BASE_URL.replace('http', 'ws', 1)}/reverse-proxy/ws",
                additional_headers={"Authorization": f"Bearer {RESTRICTED_TOKEN}"},
            ):
                pytest.fail("scope-restricted WebSocket was accepted")
        assert rejected.value.response.status_code == 403

    import anyio

    anyio.run(verify)


@pytest.mark.e2e
def test_peer_registration_cannot_override_authenticated_authority() -> None:
    async def verify() -> None:
        async with websockets.connect(
            f"{BASE_URL.replace('http', 'ws', 1)}/reverse-proxy/ws",
            additional_headers={"Authorization": f"Bearer {TOKEN}"},
        ) as websocket:
            await websocket.send(
                json.dumps(
                    {
                        "type": "register",
                        "server": {
                            "name": AUTHORITY_SERVER_NAME,
                            "ownerEmail": "attacker@example.com",
                            "teamId": "attacker-team",
                            "visibility": "private",
                        },
                    }
                )
            )
            while True:
                frame = json.loads(await websocket.recv())
                if frame.get("type") == "request" and frame["payload"].get("method") == "initialize":
                    await websocket.send(
                        json.dumps(
                            {
                                "type": "response",
                                "payload": {
                                    "jsonrpc": "2.0",
                                    "id": frame["payload"]["id"],
                                    "result": {"protocolVersion": "2025-11-25", "capabilities": {}, "serverInfo": {"name": "authority-probe", "version": "1.0"}},
                                },
                            }
                        )
                    )
                if frame.get("type") == "register_complete":
                    assert frame.get("status") == "success"
                    break
            gateway = _wait_for_gateway(AUTHORITY_SERVER_NAME, True)
            assert gateway["ownerEmail"] == "admin@example.com"
            assert gateway["visibility"] == "public"
            assert gateway.get("teamId") is None

    import anyio

    anyio.run(verify)


@pytest.mark.e2e
def test_resource_and_prompt_round_trip_through_maintained_client() -> None:
    deadline = time.monotonic() + 60
    resources: list[JsonObject] = []
    prompts: list[JsonObject] = []
    while time.monotonic() < deadline:
        resource_response = _json_request("/resources")
        prompt_response = _json_request("/prompts")
        assert isinstance(resource_response, list)
        assert isinstance(prompt_response, list)
        resources = resource_response
        prompts = prompt_response
        resource_uris = {str(item.get("uri")) for item in resources}
        if {"reference://static/greeting", "reference://static/blob"} <= resource_uris and any(item.get("name") == COMPLIANCE_PROMPT_NAME for item in prompts):
            break
        time.sleep(1)
    else:
        pytest.fail("compliance resource and prompt were not discovered")

    resource_id = next(item["id"] for item in resources if str(item.get("uri")) == "reference://static/greeting")
    blob_resource_id = next(item["id"] for item in resources if str(item.get("uri")) == "reference://static/blob")
    prompt_id = next(item["id"] for item in prompts if item.get("name") == COMPLIANCE_PROMPT_NAME)
    resource = _json_request(f"/resources/{resource_id}")
    assert isinstance(resource, dict)
    assert isinstance(resource["text"], str)
    assert "hello from compliance-reference-server" in resource["text"]
    blob_resource = _json_request(f"/resources/{blob_resource_id}")
    assert isinstance(blob_resource, dict)
    assert blob_resource["blob"] == "dDgtYmluYXJ5"
    assert blob_resource["mimeType"] == "application/x-t8-binary"
    prompt = _post(f"/prompts/{prompt_id}", {"name": "T8"})
    assert prompt["messages"]


@pytest.mark.e2e
def test_tool_call_crosses_redis_worker_relay(tmp_path) -> None:
    _wait_for_tool()
    monitor_log = tmp_path / "redis-monitor.log"
    with monitor_log.open("wb") as output:
        monitor = subprocess.Popen(["docker", "exec", f"{COMPOSE_PROJECT}-redis-1", "redis-cli", "MONITOR"], stdout=output, stderr=subprocess.STDOUT)
        try:
            for request_id in range(1, 21):
                payload = json.dumps({"jsonrpc": "2.0", "id": request_id, "method": "tools/call", "params": {"name": FAST_TOOL_NAME, "arguments": {"message": f"relay-{request_id}"}}}).encode()
                response = _json_request("/rpc", payload=payload)
                assert isinstance(response, dict)
                assert _rpc_text(response) == f"relay-{request_id}"
        finally:
            monitor.terminate()
            monitor.wait(timeout=10)
    evidence = monitor_log.read_text(encoding="utf-8")
    assert '\\"type\\":\\"rp_request\\"' in evidence
    assert '\\"forward_sig\\"' in evidence
    assert '\\"origin_worker_id\\"' in evidence
    relayed_workers = re.findall(r'"PUBLISH"\s+"mcpgw:pool_rp:([^"]+)".*?\\"origin_worker_id\\":\\"([^"\\]+)', evidence)
    assert any(target_worker != origin_worker for target_worker, origin_worker in relayed_workers)


@pytest.mark.e2e
def test_discovered_gateway_retains_only_server_owned_authority() -> None:
    gateway = _wait_for_gateway(FAST_SERVER_NAME, True)
    assert gateway["transport"] == "PROXIED"
    assert isinstance(gateway["url"], str)
    assert gateway["url"].startswith("reverse-proxy://")
    assert gateway["ownerEmail"] == "admin@example.com"
    assert gateway["visibility"] == "public"
    assert gateway["authType"] is None


@pytest.mark.e2e
def test_stored_bearer_auth_is_forwarded_without_exposure() -> None:
    gateway = _wait_for_gateway(AUTH_SERVER_NAME, True, timeout=60)
    updated = _put(f"/gateways/{gateway['id']}", {"auth_type": "bearer", "auth_token": "t8-forwarded-token"})
    assert updated["authType"] == "bearer"
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        response = _rpc("tools/call", {"name": AUTH_TOOL_NAME, "arguments": {}}, request_id="auth")
        if _rpc_text(response) == "authorized":
            return
        time.sleep(1)
    pytest.fail("stored bearer authorization did not reach downstream probe")


@pytest.mark.e2e
def test_downstream_restart_recovers_after_client_reregistration() -> None:
    original_session_ids = _session_ids_for_server(_json_request("/reverse-proxy/sessions"), FAST_SERVER_NAME)
    assert len(original_session_ids) == 1
    original_session_id = next(iter(original_session_ids))
    subprocess.run(["docker", "stop", f"{COMPOSE_PROJECT}-fast_test_server-1"], check=True, capture_output=True, text=True)
    subprocess.run(["docker", "start", f"{COMPOSE_PROJECT}-fast_test_server-1"], check=True, capture_output=True, text=True)
    _wait_for_tool()
    deadline = time.monotonic() + 30
    recovered_session_ids: set[str] = set()
    while time.monotonic() < deadline:
        recovered_session_ids = _session_ids_for_server(_json_request("/reverse-proxy/sessions"), FAST_SERVER_NAME)
        if recovered_session_ids - {original_session_id}:
            break
        time.sleep(1)
    else:
        pytest.fail(f"downstream restart did not create a fresh reverse-proxy session: {recovered_session_ids}")


@pytest.mark.e2e
def test_redis_outage_fails_closed_and_recovers() -> None:
    redis_container = f"{COMPOSE_PROJECT}-redis-1"
    subprocess.run(["docker", "stop", redis_container], check=True, capture_output=True, text=True)
    failures = 0
    try:
        for request_id in range(20):
            try:
                response = _rpc("tools/call", {"name": FAST_TOOL_NAME, "arguments": {"message": "redis-outage"}}, request_id=f"redis-outage-{request_id}")
            except HTTPError:
                failures += 1
            else:
                failures += int("error" in response)
        assert failures > 0
    finally:
        subprocess.run(["docker", "start", redis_container], check=True, capture_output=True, text=True)

    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        ping = subprocess.run(["docker", "exec", redis_container, "redis-cli", "PING"], check=False, capture_output=True, text=True)
        if ping.returncode == 0 and ping.stdout.strip() == "PONG":
            break
        time.sleep(1)
    else:
        pytest.fail("Redis did not recover")
    _wait_for_tool()


@pytest.mark.e2e
def test_client_stop_marks_gateway_unreachable_and_invocation_fails_closed() -> None:
    os.kill(FAST_CLIENT_PID, signal.SIGTERM)
    _wait_for_gateway(FAST_SERVER_NAME, False)
    response = _rpc("tools/call", {"name": FAST_TOOL_NAME, "arguments": {"message": "must-fail"}}, request_id="stopped")
    assert "error" in response


@pytest.mark.e2e
def test_heartbeat_timeout_evicts_paused_client() -> None:
    _wait_for_gateway(AUTH_SERVER_NAME, True)
    children = subprocess.run(["pgrep", "-P", str(AUTH_CLIENT_PID)], check=True, capture_output=True, text=True).stdout.split()
    assert children
    for child in children:
        os.kill(int(child), signal.SIGSTOP)
    _wait_for_gateway(AUTH_SERVER_NAME, False, timeout=15)
