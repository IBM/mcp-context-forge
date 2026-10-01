# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/mcp_a2a/conftest.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Shared fixtures for the live-gateway MCP/A2A invocation-path E2E suites.

Provides an authenticated admin HTTP client and a vault-tagged registration
of the fast-time-server federation gateway, exposed through a virtual server.
The fixture pattern mirrors ``tests/live_gateway/plugins/conftest.py`` and
reuses the plugins suite helper toolkit (``tests/live_gateway/plugins/_helpers.py``).
The gateway under test is started out-of-band by ``make testing-up``; these
fixtures only set up the request path the tests exercise.
"""

from __future__ import annotations

# Standard
import os
from contextlib import suppress
from typing import Generator

# Third-Party
import httpx
import pytest

# First-Party
from tests.live_gateway.helpers.mcp_test_helpers import BASE_URL
from tests.live_gateway.plugins import _helpers

# Vault system key the test tokens are filed under. The gateway registration
# carries the matching ``system:<key>`` tag so the Vault plugin resolves it.
VAULT_SYSTEM = "echo.local"
SYSTEM_TAG = f"system:{VAULT_SYSTEM}"

# Boot recipe the skip reason points at. The committed plugins/config.yaml
# keeps VaultPlugin in ``mode: disabled``, so a default ``make testing-up``
# stack cannot run this suite.
VAULT_BOOT_HINT = (
    "VaultPlugin is not enabled on the gateway under test. Boot a vault-enabled stack with: "
    "ENABLE_HEADER_PASSTHROUGH=true ENABLE_SENSITIVE_HEADER_PASSTHROUGH=true "
    "PLUGINS_CONFIG_FILE=plugins/vault/config_vault_e2e.yaml make testing-up"
)

# Upstream URL the gateway container uses to reach fast-time-server. The
# compose testing stack resolves the docker-network service name. Host-run
# gateways override via FAST_TIME_SERVER_URL.
FAST_TIME_UPSTREAM_URL = os.getenv("FAST_TIME_SERVER_URL", "http://fast_time_server:9080/mcp")


@pytest.fixture(scope="session")
def admin_token() -> str:
    """Session-scoped admin JWT for the live-gateway test stack.

    Returns:
        A signed admin JWT.
    """
    return _helpers.make_admin_jwt()


@pytest.fixture(scope="session")
def admin_client(admin_token: str) -> Generator[httpx.Client, None, None]:
    """Session-scoped authenticated admin HTTP client.

    Args:
        admin_token: Admin bearer token.

    Yields:
        An ``httpx.Client`` bound to the gateway base URL.
    """
    # The live-gateway suites only talk to a local plain-HTTP stack; verify is
    # disabled to avoid TLS env leakage from other tests in the session.
    with httpx.Client(base_url=BASE_URL, headers=_helpers.api_headers(admin_token), timeout=30.0, verify=False) as client:
        yield client


@pytest.fixture(scope="module", autouse=True)
def _require_vault_plugin(admin_client: httpx.Client) -> None:
    """Skip the module unless VaultPlugin is enabled on the gateway under test.

    Probes the plugin discovery API (``enable_plugin_api: true`` in both the
    committed and the E2E plugin configs). A default ``make testing-up`` stack
    loads VaultPlugin in ``mode: disabled``, so the suite self-skips instead of
    producing false failures.

    Args:
        admin_client: Authenticated admin HTTP client.
    """
    payload = _helpers.request_json(admin_client, "GET", "/v1/plugins", params={"search": "Vault"})
    plugins = payload.get("plugins", []) if isinstance(payload, dict) else []
    vault = next((p for p in plugins if p.get("name") == "VaultPlugin"), None)
    if vault is None or vault.get("status") != "enabled":
        pytest.skip(VAULT_BOOT_HINT)


@pytest.fixture(scope="module")
def vault_echo_server(admin_client: httpx.Client, admin_token: str, _require_vault_plugin: None) -> Generator[dict[str, str], None, None]:
    """Expose the fast-time ``whoami`` tool through a vault-tagged registration.

    Creates a throwaway team and registers the fast-time-server federation
    gateway scoped to it: the gateway uniqueness rule rejects a second public
    no-auth registration of the boot-registered ``fast_time`` URL. The
    registration carries the ``system:echo.local`` tag (Vault plugin system
    resolution) and an ``X-Vault-Tokens``-only passthrough whitelist. Dropping
    ``Authorization`` from the whitelist attributes the injected Bearer solely
    to the plugin. Creates a virtual server over the synced ``whoami`` tool
    and tears everything down on exit.

    Args:
        admin_client: Authenticated admin HTTP client.
        admin_token: Admin bearer token (for MCP calls).
        _require_vault_plugin: Module gate; skips when VaultPlugin is disabled.

    Yields:
        Mapping with ``server_id``, ``whoami_tool`` (gateway-prefixed name),
        and ``token``.
    """
    suffix = _helpers.unique_suffix()
    team_id = _helpers.create_team(admin_client, name=f"vault_echo_e2e_team_{suffix}")
    gateway_id = _helpers.register_fast_time_gateway(
        admin_client,
        name=f"vault_echo_e2e_{suffix}",
        team_id=team_id,
        visibility="team",
        tags=[SYSTEM_TAG],
        passthrough_headers=["X-Vault-Tokens"],
        url=FAST_TIME_UPSTREAM_URL,
    )

    tools = _helpers.wait_for_gateway_tools(admin_client, gateway_id)
    whoami_tool = _helpers.find_whoami_tool(tools)
    server_id = _helpers.create_virtual_server(
        admin_client,
        name=f"vault_echo_e2e_server_{suffix}",
        tool_ids=[whoami_tool["id"]],
    )

    try:
        yield {"server_id": server_id, "whoami_tool": whoami_tool["name"], "token": admin_token}
    finally:
        with suppress(Exception):
            admin_client.delete(f"/servers/{server_id}")
        with suppress(Exception):
            admin_client.delete(f"/gateways/{gateway_id}")
        with suppress(Exception):
            _helpers.delete_team(admin_client, team_id=team_id)
