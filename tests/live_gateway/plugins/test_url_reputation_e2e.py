# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/plugins/test_url_reputation_e2e.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

End-to-end gateway test for the cpex-url-reputation plugin.

Boots against a live gateway that was started with a single-plugin enforce
config derived from ``plugins/config.yaml`` (URLReputationPlugin in ``enforce``
mode, all other plugins disabled). Unlike the secrets / encoded-exfil suites,
URL reputation hooks ``resource_pre_fetch`` (a resource hook, not a tool hook),
so it is driven by registering a resource and reading it back: the gateway runs
the pre-fetch hook on the resource URI *before* any network fetch, so the test
is fully deterministic and never touches the network.

It asserts:

* reading a resource whose URI is on a blocked domain is **blocked** with the
  exact plugin-violation envelope, and
* reading a resource on a clean (non-blocked, https) domain returns its content
  unchanged.

The cpex plugin is never imported here — the gateway loads it from
``PLUGINS_CONFIG_FILE``. ``assert_plugin_active`` confirms the wheel actually
imported and registered, so a broken build fails loudly instead of skipping.

Note: URL reputation is a *resource-hook* plugin, so it is enforced only via
the static ``plugins/config.yaml`` path; the tool plugin-bindings API does not
govern resource hooks.
"""

from __future__ import annotations

# Standard
from contextlib import suppress

# Third-Party
import httpx
import pytest

# First-Party
from tests.live_gateway.helpers.mcp_test_helpers import skip_no_gateway
from tests.live_gateway.plugins import _helpers

pytestmark = [pytest.mark.e2e, skip_no_gateway]

PLUGIN_NAME = "URLReputationPlugin"

# ``malicious.example.com`` is the blocked domain configured for
# URLReputationPlugin in plugins/config.yaml.
BLOCKED_DOMAIN = "malicious.example.com"
BLOCKED_URI = f"https://{BLOCKED_DOMAIN}/exfil/data"

# A clean resource on a non-blocked domain. https is required because the
# detector blocks plain http (``block_non_secure_http`` defaults to True).
CLEAN_URI = "https://safe.example.com/report/data"
CLEAN_CONTENT = "Quarterly revenue is up 12% year over year."

# Exact JSON-RPC error envelope the gateway surfaces when URLReputationPlugin
# blocks a resource read. The global PluginViolationError handler wraps the
# cpex violation (reason / code / description are constants for a blocked
# domain) into this stable structure, so the whole body is deterministic.
EXPECTED_BLOCK_ERROR = {
    "code": -32602,
    "message": f"Plugin Violation: Domain '{BLOCKED_DOMAIN}' in blocked set",
    "data": {
        "description": f"Domain '{BLOCKED_DOMAIN}' in blocked set",
        "details": {"domain": BLOCKED_DOMAIN},
        "plugin_error_code": "URL_REPUTATION_BLOCK",
        "plugin_name": PLUGIN_NAME,
    },
}


@pytest.fixture(scope="module", autouse=True)
def _require_plugin_active(admin_client: httpx.Client) -> None:
    """Fail fast unless URLReputationPlugin loaded in enforce mode.

    Args:
        admin_client: Authenticated admin HTTP client.
    """
    _helpers.assert_plugin_active(admin_client, PLUGIN_NAME, expected_mode="enforce")


def _register_then_read(admin_client: httpx.Client, *, uri: str, content: str) -> tuple[str, httpx.Response]:
    """Register a local resource and read it back, cleaning up afterwards.

    Args:
        admin_client: Authenticated admin HTTP client.
        uri: Resource URI to register (drives the ``resource_pre_fetch`` hook).
        content: Inline resource content.

    Returns:
        A ``(resource_id, response)`` tuple, where ``response`` is the raw read
        response (a content envelope or a violation envelope).
    """
    resource = _helpers.register_resource(
        admin_client,
        uri=uri,
        name=f"urlrep_e2e_{_helpers.unique_suffix()}",
        content=content,
    )
    resource_id = resource["id"]
    try:
        return resource_id, _helpers.read_resource(admin_client, resource_id=resource_id)
    finally:
        with suppress(Exception):
            _helpers.delete_resource(admin_client, resource_id=resource_id)


def test_blocked_domain_resource_is_blocked(admin_client: httpx.Client) -> None:
    """Reading a resource on a blocked domain is rejected by URLReputationPlugin.

    Args:
        admin_client: Authenticated admin HTTP client.
    """
    _resource_id, response = _register_then_read(admin_client, uri=BLOCKED_URI, content="payload")

    assert response.status_code == 200
    assert response.json() == {"error": EXPECTED_BLOCK_ERROR}


def test_clean_domain_resource_passes_through(admin_client: httpx.Client) -> None:
    """Reading a resource on a non-blocked domain returns its content unchanged.

    Args:
        admin_client: Authenticated admin HTTP client.
    """
    resource_id, response = _register_then_read(admin_client, uri=CLEAN_URI, content=CLEAN_CONTENT)

    assert response.status_code == 200
    assert response.json() == {
        "type": "resource",
        "id": resource_id,
        "uri": CLEAN_URI,
        "mime_type": "text/plain",
        "text": CLEAN_CONTENT,
        "blob": None,
    }
