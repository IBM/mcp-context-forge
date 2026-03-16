"""Helpers for gateway-internal loopback HTTP calls.

These helpers centralize protocol and TLS verification behavior for
self-calls to local endpoints like /rpc.
"""

import os
from mcpgateway.config import settings


_SSL_TRUE_VALUES = {"true"}


def internal_loopback_base_url() -> str:
    """Return loopback base URL for gateway self-calls.

    Uses HTTPS when runtime is started with SSL=true, otherwise HTTP.
    """
    ssl_env = os.getenv("SSL", "false").strip().lower()
    scheme = "https" if ssl_env in _SSL_TRUE_VALUES else "http"
    return f"{scheme}://127.0.0.1:{settings.port}"


def internal_loopback_verify() -> bool:
    """Return TLS verification policy for loopback self-calls.

    Loopback HTTPS frequently uses a self-signed local cert, so verification
    is disabled for HTTPS loopback self-calls and enabled otherwise.
    """
    return not internal_loopback_base_url().startswith("https://")
