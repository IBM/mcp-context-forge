# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/internal_http.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Helpers for gateway-internal loopback HTTP calls.

These helpers centralize protocol and TLS verification behavior for
self-calls to local endpoints like /rpc.
"""

# Standard
import os
from typing import Dict, Optional

# Third-Party
import httpx

# First-Party
from mcpgateway.config import settings


def _is_ssl_enabled() -> bool:
    """Check whether the gateway is running with SSL enabled.

    Returns:
        bool: ``True`` when ``SSL=true`` is set in the environment.
    """
    return os.getenv("SSL", "false") == "true"


def internal_loopback_base_url() -> str:
    """Return loopback base URL for gateway self-calls.

    Uses HTTPS when runtime is started with SSL=true, otherwise HTTP.

    Returns:
        str: The base URL string (e.g. ``http://127.0.0.1:4444``).
    """
    scheme = "https" if _is_ssl_enabled() else "http"
    return f"{scheme}://127.0.0.1:{settings.port}"


def internal_loopback_verify() -> bool:
    """Return TLS verification policy for loopback self-calls.

    Loopback HTTPS frequently uses a self-signed local cert, so verification
    is disabled for HTTPS loopback self-calls and enabled otherwise.

    Returns:
        bool: ``False`` when the loopback URL is HTTPS, ``True`` otherwise.
    """
    return not _is_ssl_enabled()


async def _post_in_process(path: str, *, content: bytes, headers: Dict[str, str], timeout: float) -> httpx.Response:
    """POST to a local route via an in-process ASGI transport.

    Affinity-owned requests must execute on the worker that actually holds the
    bound upstream session. A real loopback to ``127.0.0.1`` hits the shared
    gunicorn socket, and the kernel routes it to an arbitrary worker that does
    not hold the session — which breaks upstream-session reuse (and the #4205
    isolation invariant for stateful upstreams). ``httpx.ASGITransport`` invokes
    the FastAPI app in *this* process instead, so the route resolves the session
    from this worker's ``UpstreamSessionRegistry``.

    The explicit ``client=("127.0.0.1", 0)`` sets ``scope["client"]`` to a
    loopback address, which both the trusted-internal gate
    (``_is_trusted_internal_mcp_runtime_request``) and the public ``/rpc``
    loop guard require. ``app`` is imported lazily to avoid a circular import at
    module load.

    Args:
        path: Local route to dispatch to (``/rpc`` or ``/_internal/mcp/rpc``).
        content: Serialized JSON-RPC request body.
        headers: Fully-built request headers (caller owns the trust/loop contract).
        timeout: Per-call timeout in seconds.

    Returns:
        httpx.Response: The response from the in-process dispatch.
    """
    # First-Party
    from mcpgateway.main import app  # pylint: disable=import-outside-toplevel,cyclic-import

    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 0))
    async with httpx.AsyncClient(transport=transport, base_url=internal_loopback_base_url()) as client:
        return await client.post(path, content=content, headers=headers, timeout=timeout)


async def post_rpc_in_process(*, content: bytes, headers: Dict[str, str], timeout: float) -> httpx.Response:
    """Dispatch a generic JSON-RPC body in-process to the public ``/rpc`` route.

    Used by the generic RPC affinity path (``_execute_forwarded_request``), which
    authenticates from the forwarded ``Authorization`` header rather than an
    encoded auth-context. The caller MUST include ``x-forwarded-internally: true``
    so the re-entered ``/rpc`` handler does not forward again.

    Args:
        content: Serialized JSON-RPC request body.
        headers: Request headers; must include ``x-forwarded-internally: true``.
        timeout: Per-call timeout in seconds.

    Returns:
        httpx.Response: The response from the in-process ``/rpc`` dispatch.
    """
    return await _post_in_process("/rpc", content=content, headers=headers, timeout=timeout)


async def post_internal_mcp_rpc_in_process(
    *,
    content: bytes,
    timeout: float,
    session_id: Optional[str] = None,
    auth_context: str = "",
    original_headers: Optional[Dict[str, str]] = None,
    extra_headers: Optional[Dict[str, str]] = None,
) -> httpx.Response:
    """Dispatch a Streamable HTTP affinity forward in-process to ``/_internal/mcp/rpc``.

    Targets the **trusted internal** endpoint rather than public ``/rpc`` so the
    owner does not re-authenticate: the originating worker already ran
    ``streamable_http_auth()`` (the only place that handles virtual-server OAuth
    verifiers and ``MCP_REQUIRE_AUTH=false`` public-only mode), packaged the
    result into ``auth_context``, and ships it here. The trust contract is built
    once, here, so every streamable affinity dispatch site is guaranteed
    consistent:

    - ``x-contextforge-mcp-runtime: affinity`` — marker accepted by
      ``_is_trusted_internal_mcp_runtime_request``.
    - ``x-contextforge-mcp-runtime-auth`` — shared-secret HMAC.
    - ``x-contextforge-auth-context`` — the encoded edge auth context.

    The original ``Authorization`` header is preserved (when present) so the CSRF
    middleware short-circuits on its bearer exemption; the endpoint itself does
    not re-authenticate from it. Passthrough headers destined for upstream MCP
    servers (#3640) are re-extracted from ``original_headers``.

    Args:
        content: Serialized JSON-RPC request body.
        timeout: Per-call timeout in seconds.
        session_id: Downstream MCP session id (``x-mcp-session-id``).
        auth_context: Encoded ``x-contextforge-auth-context`` value from the
            originating worker (empty string falls back to the endpoint's
            existing visibility rules).
        original_headers: Original request headers (lowercased keys) used to
            recover the ``Authorization`` header and upstream passthrough headers.
        extra_headers: Optional headers merged last; override the defaults above.

    Returns:
        httpx.Response: The response from the in-process ``/_internal/mcp/rpc`` dispatch.
    """
    # First-Party
    from mcpgateway.auth_context import _expected_internal_mcp_runtime_auth_header  # pylint: disable=import-outside-toplevel,protected-access
    from mcpgateway.utils.passthrough_headers import safe_extract_and_filter_for_loopback  # pylint: disable=import-outside-toplevel

    rpc_headers = {
        "content-type": "application/json",
        "x-mcp-session-id": session_id or "",
        "x-contextforge-mcp-runtime": "affinity",
        "x-contextforge-mcp-runtime-auth": _expected_internal_mcp_runtime_auth_header(),
        "x-contextforge-auth-context": auth_context,
    }
    if original_headers:
        original_auth = original_headers.get("authorization") or original_headers.get("Authorization")
        if original_auth:
            rpc_headers["authorization"] = original_auth
        # Preserve passthrough headers destined for upstream MCP servers (#3640).
        rpc_headers.update(safe_extract_and_filter_for_loopback(original_headers))
    if extra_headers:
        rpc_headers.update(extra_headers)

    return await _post_in_process("/_internal/mcp/rpc", content=content, headers=rpc_headers, timeout=timeout)
