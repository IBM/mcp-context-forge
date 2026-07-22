# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/plugins/_helpers.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Shared helpers for the live-gateway cpex plugin E2E suites.

These helpers talk plain HTTP to a running gateway (started by the
plugin-integration.yml workflow with a single-plugin enforce config). They
cover three concerns shared by every plugin suite:

* minting an admin JWT and building API / MCP headers,
* registering the ``fast-time-server`` gateway and provisioning a virtual
  server that exposes its tools, and
* the streamable-HTTP ``initialize`` handshake plus ``tools/call`` round-trip.

The suites never import the cpex plugin package — the gateway loads it from
``PLUGINS_CONFIG_FILE`` — so a broken wheel surfaces as a failing E2E rather
than a silently skipped import.
"""

from __future__ import annotations

# Standard
from contextlib import contextmanager, suppress
import os
from pathlib import Path
import time
from typing import Any, Iterator
import uuid

# Third-Party
import httpx
import yaml

# First-Party
from tests.helpers.auth import make_auth_headers, make_test_jwt

# Canonical MCP protocol version for the gateway's streamable-HTTP transport.
# Keep in sync with tests/helpers/mcp_session.py and the parity suite.
MCP_PROTOCOL_VERSION = "2025-11-25"

# Which enforcement path the suite exercises this run, set by the workflow
# matrix. ``"static"`` boots the plugin in ``enforce`` mode via the derived
# config; ``"binding"`` boots it disabled and a runtime DB tool-plugin-binding
# flips it to ``enforce`` for the test's team+tool. Both paths must surface the
# identical block behaviour.
PLUGIN_ENFORCEMENT = os.getenv("PLUGIN_ENFORCEMENT", "static")

# The committed plugin config (single source of truth). Used by the bindings
# path to reuse each plugin's real ``config`` block when creating the binding,
# so the binding exercises production's actual detector settings.
STATIC_CONFIG_PATH = Path(__file__).resolve().parents[3] / "plugins" / "config.yaml"

# JWT secret the gateway is booted with in CI. The default matches the shared
# test secret used across the live-gateway suites; the workflow overrides it
# via JWT_SECRET_KEY so the minted admin token validates against the gateway.
JWT_SECRET = os.getenv("JWT_SECRET_KEY", "my-test-key-but-now-longer-than-32-bytes")  # pragma: allowlist secret

# Where fast-time-server is reachable for federation registration.
# The cfex-mcp-fast-time-server image listens on port 9080; override via
# FAST_TIME_SERVER_URL or run run_plugin_tests.sh which exports it automatically.
FAST_TIME_URL = os.getenv("FAST_TIME_SERVER_URL", "http://localhost:9080/mcp")

# Bounded polling budget for asynchronous tool federation sync.
_TOOL_SYNC_ATTEMPTS = 30
_TOOL_SYNC_INTERVAL_S = 2.0


def make_admin_jwt() -> str:
    """Mint a platform-admin JWT signed with the gateway's test secret.

    Returns:
        A signed admin JWT valid for the live-gateway test stack.
    """
    return make_test_jwt(
        "admin@example.com",
        is_admin=True,
        teams=None,
        secret=JWT_SECRET,
    )


def api_headers(token: str) -> dict[str, str]:
    """Build JSON API headers for a bearer token.

    Args:
        token: Bearer token to send.

    Returns:
        Standard JSON API headers.
    """
    return make_auth_headers(token)


def mcp_headers(token: str, *, session_id: str | None = None) -> dict[str, str]:
    """Build MCP JSON-RPC headers for a bearer token.

    Args:
        token: Bearer token to send.
        session_id: Optional MCP session identifier to attach.

    Returns:
        Standard MCP streamable-HTTP headers.
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
    }
    if session_id:
        headers["mcp-session-id"] = session_id
    return headers


def request_json(
    client: httpx.Client,
    method: str,
    path: str,
    *,
    expected: tuple[int, ...] = (200, 201),
    **kwargs: Any,
) -> Any:
    """Send a JSON API request and return the parsed body.

    Args:
        client: Configured HTTP client.
        method: HTTP method.
        path: Relative API path.
        expected: Allowed status codes.
        **kwargs: Request options forwarded to ``httpx``.

    Returns:
        Parsed JSON response body, or ``None`` for an empty body.
    """
    response = client.request(method, path, **kwargs)
    assert response.status_code in expected, f"{method} {path} expected {expected}, got {response.status_code}: {response.text}"
    return response.json() if response.content else None


def assert_plugin_active(client: httpx.Client, name: str, *, expected_mode: str = "enforce") -> dict[str, Any]:
    """Assert that a named plugin is loaded and active on the gateway.

    Queries the admin plugin registry so a misconfigured or unloadable plugin
    fails the test before any behavioral assertion runs. This is what proves
    the cpex wheel actually imported and registered inside the product.

    Args:
        client: Authenticated admin HTTP client.
        name: Plugin name as it appears in the enforce config (e.g.
            ``"SecretsDetection"``).
        expected_mode: Mode the plugin must report (defaults to ``"enforce"``).

    Returns:
        The matching plugin summary dict.
    """
    payload = request_json(client, "GET", "/admin/plugins", params={"search": name})
    plugins = payload["plugins"] if isinstance(payload, dict) else payload
    match = next((p for p in plugins if p["name"] == name), None)
    assert match is not None, f"plugin {name!r} not found in registry: {[p['name'] for p in plugins]}"
    assert match["mode"] == expected_mode, f"plugin {name!r} mode={match['mode']!r}, expected {expected_mode!r}"
    return match


def register_fast_time_gateway(client: httpx.Client, *, name: str, team_id: str | None = None, visibility: str = "public") -> str:
    """Register the fast-time-server federation gateway (idempotently).

    When ``team_id`` is supplied the gateway (and the tools it federates) are
    scoped to that team. This is required by the tool-plugin-bindings path: a
    binding keys on ``(team_id, tool_name)``, and the invoke path falls back to
    the bare server id when a tool has no team \u2014 in which case a binding never
    matches.

    Args:
        client: Authenticated admin HTTP client.
        name: Unique gateway name to register under.
        team_id: Optional team to scope the gateway to.
        visibility: Visibility to register under when ``team_id`` is set
            (defaults to ``"public"`` for the team-less static path).

    Returns:
        The gateway id (newly created or pre-existing).
    """
    body: dict[str, Any] = {"name": name, "url": FAST_TIME_URL, "transport": "STREAMABLEHTTP"}
    if team_id:
        body["team_id"] = team_id
        body["visibility"] = visibility
    response = client.post("/gateways", json=body)
    if response.status_code in (200, 201):
        return response.json()["id"]
    if response.status_code == 409 or "already exists" in response.text:
        gateways = request_json(client, "GET", "/gateways")
        existing = next(g for g in gateways if g["name"] == name)
        return existing["id"]
    raise AssertionError(f"gateway registration failed: HTTP {response.status_code}: {response.text}")


def wait_for_gateway_tools(client: httpx.Client, gateway_id: str) -> list[dict[str, Any]]:
    """Poll until the gateway has synced at least one tool from fast-time.

    Args:
        client: Authenticated admin HTTP client.
        gateway_id: Federation gateway id to filter tools by.

    Returns:
        The list of synced tool dicts belonging to the gateway.

    Raises:
        AssertionError: If no tools sync within the polling budget.
    """
    for _ in range(_TOOL_SYNC_ATTEMPTS):
        tools = request_json(client, "GET", "/tools")
        owned = [t for t in tools if t.get("gatewayId") == gateway_id]
        if owned:
            return owned
        time.sleep(_TOOL_SYNC_INTERVAL_S)
    raise AssertionError(f"no tools synced from gateway {gateway_id} within {_TOOL_SYNC_ATTEMPTS * _TOOL_SYNC_INTERVAL_S:.0f}s")


def find_echo_tool(tools: list[dict[str, Any]]) -> dict[str, Any]:
    """Locate the fast-time ``echo`` tool among synced tools.

    The gateway prefixes federated tool names with the gateway slug, so the
    echo tool surfaces as e.g. ``fast-time-echo``. Match on suffix rather than
    a hardcoded prefix so the suite is robust to the registered gateway name.

    Args:
        tools: Synced tool dicts (already filtered to one gateway).

    Returns:
        The echo tool dict.

    Raises:
        AssertionError: If no echo tool is present.
    """
    echo = next((t for t in tools if t["name"].endswith("echo") or t.get("originalName") == "echo"), None)
    assert echo is not None, f"no echo tool synced; available: {[t['name'] for t in tools]}"
    return echo


def find_flaky_tool(tools: list[dict[str, Any]]) -> dict[str, Any]:
    """Locate the fast-time ``flaky`` tool among synced tools.

    The gateway prefixes federated tool names with the gateway slug, so the
    flaky tool surfaces as e.g. ``fast-time-flaky``. Match on suffix rather than
    a hardcoded prefix so the suite is robust to the registered gateway name.

    Args:
        tools: Synced tool dicts (already filtered to one gateway).

    Returns:
        The flaky tool dict.

    Raises:
        AssertionError: If no flaky tool is present.
    """
    flaky = next((t for t in tools if t["name"].endswith("flaky") or t.get("originalName") == "flaky"), None)
    assert flaky is not None, (
        f"no 'flaky' tool synced from fast-time-server; available tools: {[t['name'] for t in tools]}. "
        "Ensure the image referenced by FAST_TIME_IMAGE exposes the 'flaky' tool "
        "(ghcr.io/ibm/cfex-mcp-fast-time-server:latest should include it)."
    )
    return flaky


def create_virtual_server(client: httpx.Client, *, name: str, tool_ids: list[str], prompt_ids: list[str] | None = None) -> str:
    """Create a virtual server exposing the given tools (and optional prompts).

    Args:
        client: Authenticated admin HTTP client.
        name: Virtual server name.
        tool_ids: Tool ids to associate with the server.
        prompt_ids: Optional prompt ids to associate with the server, so the
            suite can drive the prompt hooks via ``prompts/get`` on the same
            virtual server (the gateway scopes prompt rendering to the server).

    Returns:
        The created virtual server id.
    """
    server = request_json(
        client,
        "POST",
        "/servers",
        json={
            "server": {
                "name": name,
                "description": "Virtual server for cpex plugin E2E",
                "associated_tools": tool_ids,
                "associated_resources": [],
                "associated_prompts": prompt_ids or [],
            }
        },
    )
    return server["id"]


def create_team(client: httpx.Client, *, name: str) -> str:
    """Create a private team and return its id.

    The bindings path needs a real team to scope its tool-plugin-binding to;
    each suite creates a throwaway team rather than depending on the
    bootstrapped personal team (whose id is generated per gateway boot).

    Args:
        client: Authenticated admin HTTP client.
        name: Unique team name.

    Returns:
        The created team id.
    """
    # Trailing slash avoids the router's 307 redirect (the admin client does
    # not follow redirects).
    team = request_json(client, "POST", "/teams/", json={"name": name, "description": "cpex plugin E2E team", "visibility": "private"})
    return team["id"]


def delete_team(client: httpx.Client, *, team_id: str) -> None:
    """Delete a team by id (best-effort teardown helper).

    Args:
        client: Authenticated admin HTTP client.
        team_id: Id of the team to delete.
    """
    client.delete(f"/teams/{team_id}")


def load_plugin_config_block(plugin_name: str) -> dict[str, Any]:
    """Return a plugin's block from the committed ``plugins/config.yaml``.

    The bindings path reuses the plugin's real ``config`` (detector settings)
    and ``priority`` so the runtime binding exercises production's actual plugin
    shape, keeping ``plugins/config.yaml`` the single source of truth.

    Args:
        plugin_name: ``name`` of the plugin to look up.

    Returns:
        The plugin's config block (includes ``config`` and ``priority``).

    Raises:
        AssertionError: If the plugin is not present in the config.
    """
    with open(STATIC_CONFIG_PATH, "r", encoding="utf-8") as handle:
        document = yaml.safe_load(handle)
    for plugin in document.get("plugins") or []:
        if plugin.get("name") == plugin_name:
            return plugin
    raise AssertionError(f"plugin {plugin_name!r} not found in {STATIC_CONFIG_PATH}")


def create_tool_plugin_binding(
    client: httpx.Client,
    *,
    team_id: str,
    tool_name: str,
    plugin_id: str,
    config: dict[str, Any],
    mode: str = "enforce",
    priority: int = 50,
) -> dict[str, Any]:
    """Create a tool-plugin-binding and return the created record.

    Args:
        client: Authenticated admin HTTP client.
        team_id: Team the binding applies to (must match the tool's team).
        tool_name: Gateway-prefixed tool name the policy binds to.
        plugin_id: Plugin config name to bind (e.g. ``"SecretsDetection"``).
        config: Plugin-specific configuration (fully replaces stored config).
        mode: Binding execution mode (``"enforce"``, ``"disabled"``, ...).
        priority: Execution priority (lower runs first).

    Returns:
        The created binding record (includes ``id``).
    """
    body = {
        "teams": {
            team_id: {
                "policies": [
                    {
                        "tool_names": [tool_name],
                        "plugin_id": plugin_id,
                        "mode": mode,
                        "priority": priority,
                        "config": config,
                    }
                ]
            }
        }
    }
    payload = request_json(client, "POST", "/v1/tools/plugin_bindings/", json=body)
    bindings = payload["bindings"] if isinstance(payload, dict) else payload
    assert bindings, f"binding upsert returned no rows: {payload}"
    return bindings[0]


def delete_tool_plugin_binding(client: httpx.Client, *, binding_id: str) -> None:
    """Delete a tool-plugin-binding by id (best-effort teardown helper).

    Args:
        client: Authenticated admin HTTP client.
        binding_id: Id of the binding to delete.
    """
    client.delete(f"/v1/tools/plugin_bindings/{binding_id}")


@contextmanager
def plugin_enforcement(
    client: httpx.Client,
    *,
    fast_time_server: dict[str, str],
    plugin_name: str,
    enforcement: str | None = None,
    config_overrides: dict[str, Any] | None = None,
    tool_name: str | None = None,
) -> Iterator[None]:
    """Activate one of the two enforcement paths for a tool-hook plugin suite.

    Both paths must produce identical block/clean behaviour, so a single test
    body asserts against both. The path is selected by ``PLUGIN_ENFORCEMENT``
    (overridable via ``enforcement``):

    * ``"static"``: the gateway was booted with the plugin in ``enforce`` mode;
      this asserts it loaded active and yields. No binding is created.
    * ``"binding"``: the gateway was booted with the plugin ``disabled``; this
      asserts it loaded inert, then creates a runtime tool-plugin-binding in
      ``enforce`` mode scoped to the suite's team+echo-tool, and removes it on
      exit.

    Args:
        client: Authenticated admin HTTP client.
        fast_time_server: Provisioned virtual server fixture value (must carry
            ``team_id`` and ``echo_tool``).
        plugin_name: Plugin config name (e.g. ``"SecretsDetection"``).
        enforcement: Optional explicit path; defaults to ``PLUGIN_ENFORCEMENT``.
        config_overrides: Optional ``config`` keys merged over the plugin's
            committed block on the ``binding`` path only (ignored on
            ``static``). The bindings API stores config verbatim and does not
            render the ``{{ env.* }}`` Jinja templates that the static-config
            loader expands, so plugins whose config references env-templated
            values (e.g. the rate limiter's ``redis_url``) must supply the
            resolved value here to match the static path's effective config.
        tool_name: Optional gateway-prefixed tool the binding targets; defaults
            to the suite's ``echo_tool``. Suites that drive a different tool
            (e.g. the retry suite's ``flaky_tool``) must pass it so the binding
            applies to the tool they actually invoke.

    Yields:
        ``None`` once the selected enforcement path is active.

    Raises:
        ValueError: If the resolved enforcement path is unknown.
    """
    mode = enforcement or PLUGIN_ENFORCEMENT
    if mode == "static":
        assert_plugin_active(client, plugin_name, expected_mode="enforce")
        yield
        return
    if mode == "binding":
        assert_plugin_active(client, plugin_name, expected_mode="disabled")
        block = load_plugin_config_block(plugin_name)
        binding_config = dict(block.get("config") or {})
        if config_overrides:
            binding_config.update(config_overrides)
        binding = create_tool_plugin_binding(
            client,
            team_id=fast_time_server["team_id"],
            tool_name=tool_name or fast_time_server["echo_tool"],
            plugin_id=plugin_name,
            config=binding_config,
            priority=block.get("priority", 50),
        )
        try:
            yield
        finally:
            with suppress(Exception):
                delete_tool_plugin_binding(client, binding_id=binding["id"])
        return
    raise ValueError(f"unknown PLUGIN_ENFORCEMENT={mode!r}; expected 'static' or 'binding'")


def register_resource(
    client: httpx.Client,
    *,
    uri: str,
    name: str,
    content: str,
    mime_type: str = "text/plain",
) -> dict[str, Any]:
    """Register a local resource and return its created record.

    Used by resource-hook plugin suites (e.g. URL reputation) to drive the
    gateway's ``resource_pre_fetch`` hook: the resource is stored locally, so
    reading it back exercises the hook on its URI without any network fetch.

    Args:
        client: Authenticated admin HTTP client.
        uri: Resource URI (must contain ``://`` so the pre-fetch hook runs).
        name: Human-readable resource name.
        content: Inline resource content stored in the gateway.
        mime_type: Resource MIME type.

    Returns:
        The created resource record (includes ``id`` and ``uri``).
    """
    return request_json(
        client,
        "POST",
        "/resources",
        json={"resource": {"uri": uri, "name": name, "content": content, "mimeType": mime_type}, "visibility": "public"},
    )


def register_prompt(
    client: httpx.Client,
    *,
    name: str,
    template: str,
    arguments: list[dict[str, Any]],
    team_id: str | None = None,
    visibility: str = "public",
) -> dict[str, Any]:
    """Register a prompt template and return its created record.

    Used by prompt-hook plugin suites (e.g. PII filter) to drive the gateway's
    ``prompt_pre_fetch`` / ``prompt_post_fetch`` hooks: rendering the prompt via
    ``prompts/get`` runs both hooks over the supplied arguments and the rendered
    messages.

    Args:
        client: Authenticated admin HTTP client.
        name: Prompt name (the gateway slugifies it; the slug is what
            ``prompts/get`` addresses).
        template: Jinja prompt template (e.g. ``"User said: {{ text }}"``).
        arguments: Argument definitions (each a ``{name, description, required}``
            dict).
        team_id: Optional team to scope the prompt to.
        visibility: Visibility to register under (defaults to ``"public"`` so the
            admin token can render it).

    Returns:
        The created prompt record (includes ``id`` and slugified ``name``).
    """
    body: dict[str, Any] = {
        "prompt": {"name": name, "description": "cpex plugin E2E prompt", "template": template, "arguments": arguments},
        "visibility": visibility,
    }
    if team_id:
        body["team_id"] = team_id
    return request_json(client, "POST", "/prompts", json=body)


def delete_prompt(client: httpx.Client, *, prompt_id: str) -> None:
    """Delete a prompt by id (best-effort teardown helper).

    Args:
        client: Authenticated admin HTTP client.
        prompt_id: Id of the prompt to delete.
    """
    client.delete(f"/prompts/{prompt_id}")


def read_resource(client: httpx.Client, *, resource_id: str) -> httpx.Response:
    """Read a resource by id, triggering the ``resource_pre_fetch`` hook.

    Returns the raw response so callers can inspect both a normal content
    envelope and a plugin-violation error envelope (the gateway surfaces plugin
    blocks as a JSON-RPC error body, not via the HTTP status).

    Args:
        client: Authenticated admin HTTP client.
        resource_id: Id of the resource to read.

    Returns:
        The raw HTTP response.
    """
    return client.get(f"/resources/{resource_id}")


def delete_resource(client: httpx.Client, *, resource_id: str) -> None:
    """Delete a resource by id (best-effort teardown helper).

    Args:
        client: Authenticated admin HTTP client.
        resource_id: Id of the resource to delete.
    """
    client.delete(f"/resources/{resource_id}")


def initialize_session(client: httpx.Client, *, server_id: str, token: str) -> str | None:
    """Run the MCP initialize handshake and return the session id, if any.

    Args:
        client: Configured HTTP client.
        server_id: Target virtual server id.
        token: Bearer token to send.

    Returns:
        The allocated MCP session id when the runtime exposes one, else
        ``None``.
    """
    response = client.post(
        f"/servers/{server_id}/mcp/",
        headers=mcp_headers(token),
        json={
            "jsonrpc": "2.0",
            "id": "init",
            "method": "initialize",
            "params": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "cpex-plugin-e2e", "version": "1.0.0"},
            },
        },
    )
    assert response.status_code == 200, f"initialize failed: HTTP {response.status_code}: {response.text}"
    payload = response.json()
    assert "result" in payload, payload
    return response.headers.get("mcp-session-id")


def call_tool(
    client: httpx.Client,
    *,
    server_id: str,
    token: str,
    tool_name: str,
    arguments: dict[str, Any],
    session_id: str | None = None,
    request_id: int = 1,
) -> dict[str, Any]:
    """Invoke a tool over MCP and return the JSON-RPC ``result`` payload.

    The gateway returns HTTP 200 with an ``isError`` result both for normal
    output and for plugin blocks, so callers inspect ``result["isError"]`` and
    ``result["content"]`` rather than relying on the HTTP status.

    Args:
        client: Configured HTTP client.
        server_id: Target virtual server id.
        token: Bearer token to send.
        tool_name: Gateway-prefixed tool name (e.g. ``fast-time-echo``).
        arguments: Tool arguments.
        session_id: Optional MCP session id from ``initialize_session``.
        request_id: JSON-RPC request id.

    Returns:
        The JSON-RPC ``result`` payload.
    """
    response = client.post(
        f"/servers/{server_id}/mcp/",
        headers=mcp_headers(token, session_id=session_id),
        json={
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        },
    )
    assert response.status_code == 200, f"tools/call failed: HTTP {response.status_code}: {response.text}"
    payload = response.json()
    assert "result" in payload, payload
    return payload["result"]


def get_prompt(
    client: httpx.Client,
    *,
    server_id: str,
    token: str,
    prompt_name: str,
    arguments: dict[str, Any],
    session_id: str | None = None,
    request_id: int = 1,
) -> dict[str, Any]:
    """Render a prompt over MCP and return the JSON-RPC ``result`` payload.

    Drives the ``prompt_pre_fetch`` (over ``arguments``) and ``prompt_post_fetch``
    (over the rendered messages) hooks. The gateway scopes prompt rendering to
    the virtual server, so the prompt must be associated with ``server_id``.

    Args:
        client: Configured HTTP client.
        server_id: Target virtual server id.
        token: Bearer token to send.
        prompt_name: Slugified prompt name (as returned by ``register_prompt``).
        arguments: Prompt arguments to interpolate.
        session_id: Optional MCP session id from ``initialize_session``.
        request_id: JSON-RPC request id.

    Returns:
        The JSON-RPC ``result`` payload (includes ``messages``).
    """
    response = client.post(
        f"/servers/{server_id}/mcp/",
        headers=mcp_headers(token, session_id=session_id),
        json={
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "prompts/get",
            "params": {"name": prompt_name, "arguments": arguments},
        },
    )
    assert response.status_code == 200, f"prompts/get failed: HTTP {response.status_code}: {response.text}"
    payload = response.json()
    assert "result" in payload, payload
    return payload["result"]


def prompt_text(result: dict[str, Any]) -> str:
    """Concatenate the text content of a rendered prompt's messages.

    Args:
        result: JSON-RPC ``result`` payload from ``get_prompt``.

    Returns:
        The joined text of all message ``text`` content blocks.
    """
    texts: list[str] = []
    for message in result.get("messages") or []:
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, dict) and content.get("type") == "text":
            texts.append(content.get("text", ""))
    return "\n".join(texts)


def result_text(result: dict[str, Any]) -> str:
    """Concatenate the text content blocks of a tool result.

    Args:
        result: JSON-RPC ``result`` payload from ``call_tool``.

    Returns:
        The joined text of all ``type == "text"`` content blocks (empty when
        none are present).
    """
    blocks = result.get("content") or []
    return "\n".join(block.get("text", "") for block in blocks if isinstance(block, dict) and block.get("type") == "text")


def unique_suffix() -> str:
    """Return a short unique suffix for naming federated resources.

    Returns:
        An 8-character hex suffix.
    """
    return uuid.uuid4().hex[:8]
