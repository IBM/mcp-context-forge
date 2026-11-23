# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/sso/test_sso_seed_audience_e2e.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

E2E test for ``make compose-sso-seed-audience``.

Requirements:
    - ContextForge running from the sso compose profile (``make compose-sso``)
      with SSO_KEYCLOAK_ENABLED=true, so the ``keycloak`` provider exists
    - ``make``, ``jq`` and ``docker compose`` on the host
    - ``JWT_SECRET_KEY`` exported in the shell, equal to the gateway's value
    - playwright installed; pass ``-p playwright`` to pytest

Usage:
    pytest -p playwright tests/live_gateway/sso/test_sso_seed_audience_e2e.py -v -rs
"""

# Future
from __future__ import annotations

# Standard
from contextlib import suppress
import logging
from pathlib import Path
import shutil
import subprocess  # nosec B404
from typing import Generator

# Third-Party
import pytest

pw = pytest.importorskip("playwright", reason="playwright is not installed – pip install playwright")
# Third-Party
from playwright.sync_api import APIRequestContext, Playwright  # noqa: E402

# Local
from ..helpers.mcp_test_helpers import BASE_URL, JWT_SECRET, skip_no_gateway  # noqa: E402
from tests.helpers.auth import make_playwright_api_context, make_test_jwt  # noqa: E402

logger = logging.getLogger(__name__)

pytestmark = [pytest.mark.e2e, skip_no_gateway]

REPO_ROOT = Path(__file__).resolve().parents[3]
PROVIDER_ID = "keycloak"
SEED_AUDIENCE = "mcp-gateway-api"
skip_no_tooling = pytest.mark.skipif(not all(shutil.which(tool) for tool in ("make", "jq", "docker")), reason="make, jq and docker are required")


@pytest.fixture(scope="module")
def admin_api(playwright: Playwright) -> Generator[APIRequestContext, None, None]:
    """Admin API context using a ContextForge-issued JWT."""
    token = make_test_jwt("admin@example.com", is_admin=True, teams=None, secret=JWT_SECRET)
    ctx = make_playwright_api_context(playwright, BASE_URL, token)
    yield ctx
    ctx.dispose()


@pytest.fixture
def restore_provider(admin_api: APIRequestContext) -> Generator[None, None, None]:
    """Restore the provider's trust settings after the seed target changes them."""
    original = admin_api.get(f"/auth/sso/admin/providers/{PROVIDER_ID}")
    assert original.status == 200, f"keycloak SSOProvider not found (401 means JWT_SECRET_KEY does not match the gateway): {original.status} {original.text()}"
    body = original.json()
    yield
    with suppress(Exception):
        admin_api.put(
            f"/auth/sso/admin/providers/{PROVIDER_ID}",
            data={"trusted_for_api_auth": bool(body.get("trusted_for_api_auth")), "api_audience": body.get("api_audience") or ""},
        )


@skip_no_tooling
def test_seed_target_trusts_provider_and_is_idempotent(admin_api: APIRequestContext, restore_provider: None) -> None:
    """The seed target sets trusted_for_api_auth and api_audience, and a second run succeeds."""
    for _ in range(2):
        result = subprocess.run(  # nosec B603 B607
            ["make", "compose-sso-seed-audience", f"SSO_SEED_GATEWAY_URL={BASE_URL}"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"

    resp = admin_api.get(f"/auth/sso/admin/providers/{PROVIDER_ID}")
    assert resp.status == 200, resp.text()
    provider = resp.json()
    assert provider["trusted_for_api_auth"] is True
    assert provider["api_audience"] == SEED_AUDIENCE
