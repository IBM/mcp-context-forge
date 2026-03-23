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
