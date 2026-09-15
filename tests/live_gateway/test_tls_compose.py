# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/test_tls_compose.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Black-box smoke test for the end-to-end Compose TLS path.
"""

from __future__ import annotations

import os
import socket
import ssl
from urllib.parse import urlparse
from urllib.request import urlopen

import pytest


BASE_URL = os.environ.get("TLS_BASE_URL", "https://localhost:8443").rstrip("/")


def test_end_to_end_tls_health() -> None:
    """Verify nginx TLS can reach the gateway's HTTPS health endpoint."""
    parsed = urlparse(BASE_URL)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((parsed.hostname, port), timeout=2):
            pass
    except OSError:
        pytest.skip(f"TLS gateway is not reachable at {BASE_URL}")

    context = ssl._create_unverified_context()
    with urlopen(f"{BASE_URL}/health", context=context, timeout=5) as response:
        assert response.status == 200
