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


async def post_rpc_in_process(*, content: bytes, headers: dict, timeout: float) -> httpx.Response:
    """POST to the local ``/rpc`` route via an in-process ASGI transport.

    Affinity-owned requests must execute on the worker that actually holds the
    bound upstream session. A real loopback to ``127.0.0.1`` hits the shared
    gunicorn socket, and the kernel routes it to an arbitrary worker that does
    not hold the session — which breaks upstream-session reuse (and the #4205
    isolation invariant for stateful upstreams). ``httpx.ASGITransport`` invokes
    the FastAPI app in *this* process instead, so ``/rpc`` resolves the session
    from this worker's ``UpstreamSessionRegistry``.

    ``app`` is imported lazily to avoid a circular import at module load.

    Args:
        content: Serialized JSON-RPC request body.
        headers: Request headers. Must include ``x-forwarded-internally: true``
            so the re-entered handler does not forward again.
        timeout: Per-call timeout in seconds.

    Returns:
        httpx.Response: The response from the in-process ``/rpc`` dispatch.
    """
    # First-Party
    from mcpgateway.main import app  # pylint: disable=import-outside-toplevel,cyclic-import

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=internal_loopback_base_url()) as client:
        return await client.post("/rpc", content=content, headers=headers, timeout=timeout)
