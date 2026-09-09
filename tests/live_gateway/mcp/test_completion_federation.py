# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/mcp/test_completion_federation.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Live-gateway black-box test for #6629 completion/complete federation.

Federates a prompt from ``completion_test_server`` (advertises the
``completions`` capability) and asserts the completion suggestions come from
the live upstream call, not the synced (enum-less) ``argument_schema`` --
proving R1-R6 end-to-end against a real running gateway + fixture MCP server.
Also federates a prompt from ``completion_test_server_no_completions`` (same
fixture, no ``completion`` handler registered) and asserts the gateway maps
the upstream's missing capability to JSON-RPC ``-32601`` over ``/rpc``.

R7 (modern-protocol gating) is not implemented on this branch (spec §5.4,
plan Task 9 -- withdrawn) so there is no gate for this test to exercise.

Requires the `testing` compose profile (provides `completion_test_server`
and `completion_test_server_no_completions` alongside the gateway):

    make docker-nuke docker-prod-rust testing-up RUST_MCP_MODE=
    pytest tests/live_gateway/mcp/test_completion_federation.py -v
"""

# Future
from __future__ import annotations

# Standard
from contextlib import suppress
import subprocess
import sys
import time
from typing import Any, Generator
import uuid

# Third-Party
import httpx
import pytest

# Local
from ..helpers.mcp_test_helpers import ADMIN_EMAIL, BASE_URL, JWT_SECRET, skip_no_gateway, TOKEN_EXPIRY

pytestmark = [pytest.mark.e2e, skip_no_gateway]

COMPLETION_TEST_SERVER_URL = "http://completion_test_server:9102/mcp"
COMPLETION_TEST_SERVER_NO_COMPLETIONS_URL = "http://completion_test_server_no_completions:9103/mcp"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def jwt_token() -> str:
    """Mint an admin JWT the same way test_mcp_protocol_e2e.py does (subprocess CLI, no bespoke signing)."""
    result = subprocess.run(
        [sys.executable, "-m", "mcpgateway.utils.create_jwt_token", "--username", ADMIN_EMAIL, "--exp", TOKEN_EXPIRY, "--secret", JWT_SECRET],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, f"JWT generation failed: {result.stderr}"
    return result.stdout.strip().strip('"')


@pytest.fixture(scope="module")
def admin_client(jwt_token: str) -> Generator[httpx.Client, None, None]:
    """Admin-authenticated API client for gateway registration and cleanup."""
    with httpx.Client(base_url=BASE_URL, headers={"Authorization": f"Bearer {jwt_token}"}, timeout=30.0) as client:
        yield client


def _register_gateway_and_get_prompt(admin_client: httpx.Client, *, name: str, url: str, prompt_name: str = "greet") -> Generator[dict[str, Any], None, None]:
    """Register an upstream gateway, wait for its `greet` prompt to sync, and yield {gateway_id, prompt_name}.

    Shared by both fixtures below -- the only difference between the
    "supports completions" and "does not support completions" cases is which
    upstream URL gets registered.
    """
    # Idempotent across reruns: remove any stale gateway of the same name/URL first.
    resp = admin_client.get("/gateways")
    resp.raise_for_status()
    for gw in resp.json():
        if gw.get("name") == name or gw.get("url") == url:
            admin_client.delete(f"/gateways/{gw['id']}")

    resp = admin_client.post("/gateways", json={"name": name, "url": url, "transport": "STREAMABLEHTTP"})
    assert resp.status_code in (200, 201), f"Failed to register {name}: {resp.status_code} {resp.text}"
    gateway_id = resp.json()["id"]

    # Force immediate sync, then poll (compose startup can race the first request).
    with suppress(Exception):
        admin_client.post(f"/gateways/{gateway_id}/tools/refresh?include_resources=true&include_prompts=true")

    federated_prompt_name = None
    for _ in range(30):
        resp = admin_client.get("/prompts")
        resp.raise_for_status()
        for prompt in resp.json():
            if prompt.get("gatewayId") == gateway_id and prompt.get("originalName", prompt.get("name")) == prompt_name:
                federated_prompt_name = prompt["name"]
                break
        if federated_prompt_name:
            break
        time.sleep(1)

    assert federated_prompt_name, f"'{prompt_name}' prompt from gateway '{name}' (id={gateway_id}) did not sync within 30s"

    try:
        yield {"gateway_id": gateway_id, "prompt_name": federated_prompt_name}
    finally:
        with suppress(Exception):
            admin_client.delete(f"/gateways/{gateway_id}")


@pytest.fixture(scope="module")
def federated_prompt(admin_client: httpx.Client) -> Generator[dict[str, Any], None, None]:
    """Register completion_test_server as a gateway and federate its `greet` prompt."""
    unique = uuid.uuid4().hex[:8]
    yield from _register_gateway_and_get_prompt(admin_client, name=f"completion-test-server-{unique}", url=COMPLETION_TEST_SERVER_URL)


@pytest.fixture(scope="module")
def federated_prompt_without_completions(admin_client: httpx.Client) -> Generator[dict[str, Any], None, None]:
    """Register completion_test_server_no_completions as a gateway and federate its `greet` prompt."""
    unique = uuid.uuid4().hex[:8]
    yield from _register_gateway_and_get_prompt(admin_client, name=f"completion-test-server-no-completions-{unique}", url=COMPLETION_TEST_SERVER_NO_COMPLETIONS_URL)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_federated_completion_is_answered_by_upstream(admin_client: httpx.Client, federated_prompt: dict[str, Any]) -> None:
    """A federated prompt's completion/complete is answered by its owning upstream, not a stale synced schema.

    `greet`'s `style` argument has no `enum` in its synced argument_schema at
    all (confirmed by `_register_gateway_and_get_prompt` finding it via
    `/prompts`, whose argument_schema carries only `{"name": "style",
    "required": true}` -- see completion_test_server/server.py's docstring).
    So "formal"/"friendly"/"playful" coming back can only have come from the
    live upstream `completion/complete` call this PR adds, never from a
    local-schema fallback.
    """
    response = admin_client.post(
        "/rpc",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "completion/complete",
            "params": {
                "ref": {"type": "ref/prompt", "name": federated_prompt["prompt_name"]},
                "argument": {"name": "style", "value": "for"},
            },
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert "error" not in body, body
    values = body["result"]["completion"]["values"]
    assert values == ["formal"], f"expected upstream-only completion ['formal'], got {values}"


def test_upstream_without_completions_capability_returns_method_not_found(admin_client: httpx.Client, federated_prompt_without_completions: dict[str, Any]) -> None:
    """A federated prompt owned by an upstream lacking the `completions` capability maps to -32601.

    `completion_test_server_no_completions` is the same fixture image with no
    `completion` handler registered (`COMPLETIONS_ENABLED=false`), so its
    negotiated `server_capabilities` has no `completions` key at all --
    exercising CompletionNotSupportedError's R3 mapping end-to-end. (The
    `greet` prompt here also has no enum in its argument_schema, so there is
    no local-schema fallback available either -- the request must surface
    the upstream-derived error, not a silent empty result.)
    """
    response = admin_client.post(
        "/rpc",
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "completion/complete",
            "params": {
                "ref": {"type": "ref/prompt", "name": federated_prompt_without_completions["prompt_name"]},
                "argument": {"name": "style", "value": "for"},
            },
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body.get("error", {}).get("code") == -32601, body
