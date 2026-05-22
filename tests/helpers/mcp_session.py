# -*- coding: utf-8 -*-
"""Location: ./tests/helpers/mcp_session.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Shared MCP session-handshake helper for integration and load tests.

Centralizes the streamable-HTTP ``POST /servers/<id>/mcp`` initialize +
``notifications/initialized`` handshake that the gateway requires before any
non-initialize call. Replaces the near-identical helpers that lived in
``tests/integration/test_rate_limiter_dynamic_behavior.py`` and
``tests/integration/test_rate_limiter_multi_tenant.py``.

For ``httpx``-based callers (e.g. ``tests/live_gateway/mcp/...`` and
``tests/live_gateway/e2e_rust/...``) see the helpers in those files. This
module uses ``requests`` to match the integration-test convention.
"""

# Standard
import logging

# Third-Party
import requests

logger = logging.getLogger(__name__)

# Canonical MCP protocol version for the gateway's streamable-HTTP transport.
# Mirrors the constant in tests/live_gateway/mcp/test_mcp_plugin_parity.py
# and tests/loadtest/locustfile_echo_delay.py — keep these in sync if the
# gateway's supported version changes.
MCP_PROTOCOL_VERSION = "2025-11-25"


def initialize_mcp_session(
    gateway_url: str,
    server_id: str,
    headers: dict,
    *,
    client_name: str = "test-client",
    client_version: str = "0",
    protocol_version: str = MCP_PROTOCOL_VERSION,
    init_timeout: float = 10.0,
    notify_timeout: float = 5.0,
) -> str | None:
    """Run the MCP streamable-HTTP initialize + initialized handshake.

    The gateway's session-aware MCP transport requires an ``Mcp-Session-Id``
    header on every ``POST /servers/<id>/mcp`` non-initialize call. This
    helper performs the handshake and returns the allocated session id, or
    ``None`` on failure (with a ``logger.warning`` describing which step
    failed so the caller's test output explains the failure mode).

    Args:
        gateway_url: Base URL of the gateway (e.g. ``http://localhost:8080``).
        server_id: Target virtual server id.
        headers: Pre-built auth / content headers (typically a Bearer-token
            header dict from the caller's ``_fresh_headers()``).
        client_name: ``clientInfo.name`` reported in the initialize body.
            Pass a test-specific name so it shows up in server logs.
        client_version: ``clientInfo.version`` reported in the initialize body.
        protocol_version: MCP protocol version. Defaults to the canonical
            ``MCP_PROTOCOL_VERSION``.
        init_timeout: Seconds to wait for the initialize POST.
        notify_timeout: Seconds to wait for the notifications/initialized POST.

    Returns:
        The allocated session id when the handshake succeeds, otherwise
        ``None``. A non-``None`` return guarantees the initialize step
        succeeded; the notifications/initialized step is best-effort and
        a failure there is logged but does not invalidate the session id.
    """
    sse_headers = {**headers, "Accept": "application/json, text/event-stream"}
    init_body = {
        "jsonrpc": "2.0",
        "id": "init",
        "method": "initialize",
        "params": {
            "protocolVersion": protocol_version,
            "capabilities": {},
            "clientInfo": {"name": client_name, "version": client_version},
        },
    }
    try:
        resp = requests.post(
            f"{gateway_url}/servers/{server_id}/mcp",
            json=init_body,
            headers=sse_headers,
            timeout=init_timeout,
        )
    except requests.RequestException as exc:
        logger.warning(
            "MCP initialize POST failed for server %s (transport): %s",
            server_id, exc,
        )
        return None
    if resp.status_code != 200:
        logger.warning(
            "MCP initialize returned HTTP %s for server %s: %s",
            resp.status_code, server_id, resp.text[:200],
        )
        return None
    sid = resp.headers.get("mcp-session-id")
    if not sid:
        logger.warning(
            "MCP initialize response for server %s missing mcp-session-id header",
            server_id,
        )
        return None
    try:
        requests.post(
            f"{gateway_url}/servers/{server_id}/mcp",
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            headers={**sse_headers, "Mcp-Session-Id": sid},
            timeout=notify_timeout,
        )
    except requests.RequestException as exc:
        # Best-effort: the session id is already valid for non-initialize
        # calls. Log so the caller can see the failure mode in test output.
        logger.warning(
            "MCP notifications/initialized failed for server %s session %s: %s",
            server_id, sid, exc,
        )
    return sid
