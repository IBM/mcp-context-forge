# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/internal_http.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Helpers for gateway-internal loopback HTTP calls.

These helpers centralize protocol and TLS verification behavior for
self-calls to local endpoints like /rpc.
"""

# Standard
import os

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


async def post_rpc_in_process(*, content: bytes, headers: dict, timeout: float, auth_context: str) -> httpx.Response:
    """POST to the trusted-internal ``/_internal/mcp/rpc`` route via an in-process ASGI transport.

    Affinity-owned requests must execute on the worker that actually holds the
    bound upstream session. A real loopback to ``127.0.0.1`` hits the shared
    gunicorn socket, and the kernel routes it to an arbitrary worker that does
    not hold the session, which breaks upstream-session reuse (and the #4205
    isolation invariant for stateful upstreams). ``httpx.ASGITransport`` invokes
    the FastAPI app in *this* process instead, so the dispatch resolves the
    session from this worker's ``UpstreamSessionRegistry``.

    Targets the trusted-internal endpoint rather than the public ``/rpc`` so that
    OAuth and ``MCP_REQUIRE_AUTH=false`` public-only sessions are not
    re-authenticated (and 401'd) at the public route boundary. The already
    validated edge identity rides in ``auth_context``; this helper attaches the
    runtime-auth trust headers and the encoded context, and pins the ASGI client
    to loopback so the trust gate accepts the call. It is trust-agnostic: a
    Redis-forwarded request MUST have had its signature verified by the caller
    before reaching here.

    ``app`` is imported lazily to avoid a circular import at module load.

    Args:
        content: Serialized JSON-RPC request body.
        headers: Request headers. Must include ``x-forwarded-internally: true``
            so the re-entered handler does not forward again.
        timeout: Per-call timeout in seconds.
        auth_context: Encoded ``x-contextforge-auth-context`` value (required,
            non-empty) carrying the edge-validated identity. Attached verbatim;
            this helper does not verify it.

    Returns:
        httpx.Response: The response from the in-process ``/_internal/mcp/rpc`` dispatch.

    Raises:
        ValueError: If ``auth_context`` is empty (internal dispatch must always carry one).
    """
    if not auth_context:
        raise ValueError("post_rpc_in_process requires a non-empty auth_context for trusted-internal dispatch")

    # First-Party
    from mcpgateway.auth_context import _expected_internal_mcp_runtime_auth_header  # pylint: disable=import-outside-toplevel,protected-access
    from mcpgateway.main import app  # pylint: disable=import-outside-toplevel,cyclic-import

    # Trust headers for the internal endpoint: the "affinity" runtime marker, the
    # shared-secret HMAC, and the encoded edge auth context (so the endpoint
    # reconstructs the caller without re-authenticating).
    rpc_headers = dict(headers)
    rpc_headers["x-contextforge-mcp-runtime"] = "affinity"
    rpc_headers["x-contextforge-mcp-runtime-auth"] = _expected_internal_mcp_runtime_auth_header()
    rpc_headers["x-contextforge-auth-context"] = auth_context

    # client=("127.0.0.1", 0) sets scope["client"] to a loopback address so the
    # trust gate's defense-in-depth loopback check accepts the in-process call.
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 0))
    async with httpx.AsyncClient(transport=transport, base_url=internal_loopback_base_url()) as client:
        return await client.post("/_internal/mcp/rpc", content=content, headers=rpc_headers, timeout=timeout)
