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
import ssl
from typing import Optional, Union

# Third-Party
import httpx

# First-Party
from mcpgateway.config import settings

# Cached loopback client context, keyed by the (cert, key) pair it was built from.
# Building an SSLContext reads and parses PEM files, so it must not happen per
# request. The cache is keyed rather than a bare global so that a changed
# configuration is picked up instead of silently serving a stale context.
_loopback_ssl_context: Optional[ssl.SSLContext] = None
_loopback_ssl_context_key: Optional[tuple] = None


def _is_ssl_enabled() -> bool:
    """Check whether the gateway is running with SSL enabled.

    Returns:
        bool: ``True`` when ``SSL=true`` is set in the environment.
    """
    return os.getenv("SSL", "false") == "true"


def _loopback_client_cert() -> Optional[tuple]:
    """Return the configured loopback client certificate pair, if any.

    Read from the environment rather than :mod:`mcpgateway.config` for
    consistency with :func:`_is_ssl_enabled`: both describe how the *launcher*
    (``run-gunicorn.sh``) started this process, not application configuration.

    Returns:
        Optional[tuple]: ``(cert_path, key_path)`` when both are set, else ``None``.
    """
    cert = os.getenv("LOOPBACK_CLIENT_CERT", "")
    key = os.getenv("LOOPBACK_CLIENT_KEY", "")
    if cert and key:
        return (cert, key)
    return None


def reset_loopback_ssl_context() -> None:
    """Clear the cached loopback SSL context.

    Call from test fixtures that mutate ``LOOPBACK_CLIENT_CERT`` /
    ``LOOPBACK_CLIENT_KEY`` so a later call rebuilds the context.
    """
    global _loopback_ssl_context, _loopback_ssl_context_key  # pylint: disable=global-statement
    _loopback_ssl_context = None
    _loopback_ssl_context_key = None


def internal_loopback_base_url() -> str:
    """Return loopback base URL for gateway self-calls.

    Uses HTTPS when runtime is started with SSL=true, otherwise HTTP.

    Returns:
        str: The base URL string (e.g. ``http://127.0.0.1:4444``).
    """
    scheme = "https" if _is_ssl_enabled() else "http"
    return f"{scheme}://127.0.0.1:{settings.port}"


def internal_loopback_verify() -> Union[bool, ssl.SSLContext]:
    """Return the TLS verification policy for loopback self-calls.

    Loopback HTTPS frequently uses a self-signed local cert, so server-certificate
    verification is disabled for HTTPS loopback self-calls and enabled otherwise.

    When the gateway itself requires client certificates (inbound mTLS, i.e.
    ``CERT_REQS=1`` or ``2`` in ``run-gunicorn.sh``), a bare ``verify=False`` is
    not enough: that only skips *validating* the server, it does not *present* a
    client certificate, so the handshake is rejected before any HTTP is exchanged.
    Configuring ``LOOPBACK_CLIENT_CERT`` / ``LOOPBACK_CLIENT_KEY`` returns an
    ``ssl.SSLContext`` carrying that certificate instead. ``httpx`` accepts an
    ``SSLContext`` wherever it accepts ``verify``, so call sites are unchanged.

    The context deliberately keeps the existing trust posture - ``CERT_NONE`` and
    ``check_hostname=False`` - so enabling a loopback client certificate never
    silently imposes a new server-certificate or SAN requirement on operators who
    bring their own certificates.

    Returns:
        Union[bool, ssl.SSLContext]: ``True`` when the loopback URL is plain HTTP;
        an ``ssl.SSLContext`` when a loopback client certificate is configured for
        an HTTPS loopback; ``False`` otherwise.
    """
    global _loopback_ssl_context, _loopback_ssl_context_key  # pylint: disable=global-statement

    if not _is_ssl_enabled():
        return True

    cert_pair = _loopback_client_cert()
    if cert_pair is None:
        return False

    if _loopback_ssl_context is not None and _loopback_ssl_context_key == cert_pair:
        return _loopback_ssl_context

    cert_path, key_path = cert_pair
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    # Order matters: check_hostname must be disabled before verify_mode is set to
    # CERT_NONE, otherwise Python raises "Cannot set verify_mode to CERT_NONE when
    # check_hostname is enabled."
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    context.load_cert_chain(cert_path, key_path)

    _loopback_ssl_context = context
    _loopback_ssl_context_key = cert_pair
    return context


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
