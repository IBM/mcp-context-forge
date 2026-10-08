# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/e2e/test_admin_csp_inline_handlers.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Live-gateway check that the admin UI CSP forbids inline event handler attributes.

``script-src-attr 'none'`` stops injected markup (for example a mutation-XSS
payload in a crafted ``/admin?error=`` link) from executing ``on*`` handlers.
"""

# Future
from __future__ import annotations

# Standard
import os

# Third-Party
import httpx
import pytest

BASE_URL = os.getenv("MCP_CLI_BASE_URL", "http://127.0.0.1:8080").replace("//localhost", "//127.0.0.1")


def _gateway_reachable() -> bool:
    try:
        return httpx.get(f"{BASE_URL}/health", timeout=5).status_code == 200
    except Exception:
        return False


skip_no_gateway = pytest.mark.skipif(not _gateway_reachable(), reason=f"Gateway not reachable at {BASE_URL}")


@skip_no_gateway
def test_admin_login_csp_forbids_inline_event_handlers() -> None:
    """The admin login page CSP blocks inline on* handlers and never allows them via 'unsafe-inline'."""
    response = httpx.get(f"{BASE_URL}/admin/login", timeout=10, follow_redirects=True)
    if response.status_code == 404:
        pytest.skip("Admin UI is disabled on this gateway")

    directives = [d.strip() for d in response.headers.get("content-security-policy", "").split(";")]
    assert "script-src-attr 'none'" in directives
    assert not any(d.startswith("script-src-attr") and "'unsafe-inline'" in d for d in directives)
