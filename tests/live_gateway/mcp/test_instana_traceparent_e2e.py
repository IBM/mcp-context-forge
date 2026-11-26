# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/mcp/test_instana_traceparent_e2e.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Black-box regression for Instana AutoTrace 3.12 to 3.19 with an inbound ``traceparent`` header.

Those Instana releases accept ``context=`` but raise
``TypeError: parent_context must be an Instana SpanContext or None.`` when the parent
is a plain OpenTelemetry ``SpanContext``. FastAPI native telemetry builds such a parent
from every ``traceparent`` header, so every request returned HTTP 500.

This test boots an isolated gateway subprocess under the real Instana bootstrap
(``AUTOWRAPT_BOOTSTRAP=instana``), sends each gateway route with a ``traceparent``
header, and asserts that no request returns 500. Instana 3.20 and later convert the
parent themselves and act as the control.

Run (opt-in; fails rather than skips when ``INSTANA_TRACEPARENT_E2E=1``)::

    INSTANA_TRACEPARENT_E2E=1 uv run --extra observability \\
        --with "instana==3.15.0" \\
        pytest tests/live_gateway/mcp/test_instana_traceparent_e2e.py -v
"""

# Standard
import os
import re

# Third-Party
import pytest

# First-Party
from tests.live_gateway.mcp.test_legacy_instana_e2e import boot_instana_gateway, installed_instana_version, upstream_mcp_server  # noqa: F401  # pylint: disable=unused-import

pytestmark = pytest.mark.e2e
_OPT_IN = os.getenv("INSTANA_TRACEPARENT_E2E", "").lower() in {"1", "true", "yes"}
_PARENT_TYPE_ERROR = re.compile(r"TypeError:.*parent_context must be an Instana SpanContext")
TRACEPARENT = {"traceparent": "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"}  # pragma: allowlist secret


@pytest.fixture(scope="module")
def instana_traceparent_gateway(tmp_path_factory, upstream_mcp_server):  # noqa: F811  # pylint: disable=redefined-outer-name
    """Boot a gateway under Instana AutoTrace with a registered upstream."""
    version_tuple = installed_instana_version()
    if version_tuple < (3, 12):
        message = "instana < 3.12 does not reach the parent type check; use test_legacy_instana_e2e.py"
        if _OPT_IN:
            pytest.fail(message)
        pytest.skip(message)
    yield from boot_instana_gateway(tmp_path_factory, upstream_mcp_server)


def _log(gateway):
    """Return the gateway log text."""
    return gateway["log_path"].read_text()


def test_shim_applies_only_below_instana_3_20(instana_traceparent_gateway):
    """The adapter wraps the tracer for 3.12 to 3.19 and leaves 3.20 and later alone."""
    adapted = "Adapted InstanaTracer.start_span to convert OpenTelemetry parent contexts" in _log(instana_traceparent_gateway)
    assert adapted is (installed_instana_version() < (3, 20)), _log(instana_traceparent_gateway)[-3000:]


def test_health_with_traceparent(instana_traceparent_gateway):
    """The minimal reproduction: ``GET /health`` with ``traceparent`` no longer returns 500."""
    response = instana_traceparent_gateway["client"].get("/health", headers=TRACEPARENT)
    assert response.status_code == 200, response.text


def test_gateway_routes_with_traceparent(instana_traceparent_gateway):
    """Every gateway route returns a non-500 status when the request carries ``traceparent``."""
    client = instana_traceparent_gateway["client"]
    gateway_id = instana_traceparent_gateway["gateway_id"]
    upstream_alias_url = f'{instana_traceparent_gateway["upstream_url"]}?alias=traceparent'

    responses = {
        "list": client.get("/gateways", headers=TRACEPARENT),
        "read": client.get(f"/gateways/{gateway_id}", headers=TRACEPARENT),
        "impact-preview": client.get(f"/gateways/{gateway_id}/impact-preview", headers=TRACEPARENT),
        "update": client.put(f"/gateways/{gateway_id}", json={"description": "updated with traceparent"}, headers=TRACEPARENT),
        "state-off": client.post(f"/gateways/{gateway_id}/state", params={"activate": "false"}, headers=TRACEPARENT),
        "state-on": client.post(f"/gateways/{gateway_id}/state", params={"activate": "true"}, headers=TRACEPARENT),
        "tools-refresh": client.post(f"/gateways/{gateway_id}/tools/refresh", headers=TRACEPARENT),
        "create": client.post(
            "/gateways",
            json={"name": "instana-traceparent-created", "url": upstream_alias_url, "transport": "STREAMABLEHTTP", "visibility": "public"},
            headers=TRACEPARENT,
        ),
    }
    created = responses["create"]
    if created.status_code in (200, 201):
        responses["delete"] = client.delete(f"/gateways/{created.json()['id']}", headers=TRACEPARENT)

    server_errors = {name: (response.status_code, response.text[:300]) for name, response in responses.items() if response.status_code >= 500}
    assert not server_errors, server_errors
    assert responses["create"].status_code in (200, 201), responses["create"].text
    assert responses["list"].status_code == 200, responses["list"].text
    assert responses["read"].status_code == 200, responses["read"].text


def test_create_gateway_with_traceparent_when_upstream_is_unreachable(instana_traceparent_gateway):
    """The production symptom: "add MCP server" with ``traceparent`` reaches the route and fails there, not in telemetry."""
    response = instana_traceparent_gateway["client"].post(
        "/gateways",
        json={"name": "instana-traceparent-unreachable", "url": "http://127.0.0.1:9/mcp", "transport": "STREAMABLEHTTP", "visibility": "public"},
        headers=TRACEPARENT,
    )
    assert response.status_code != 500, response.text
    assert not _PARENT_TYPE_ERROR.search(_log(instana_traceparent_gateway)), _log(instana_traceparent_gateway)[-5000:]


def test_log_has_no_parent_type_error(instana_traceparent_gateway):
    """No request in this module raised the Instana parent-type ``TypeError``."""
    assert not _PARENT_TYPE_ERROR.search(_log(instana_traceparent_gateway)), _log(instana_traceparent_gateway)[-5000:]


def test_requests_without_traceparent_still_pass(instana_traceparent_gateway):
    """Control: the same gateway serves requests without the header."""
    client = instana_traceparent_gateway["client"]
    assert client.get("/health").status_code == 200
    assert client.get("/gateways").status_code == 200


def test_unauthenticated_request_with_traceparent_is_rejected(instana_traceparent_gateway):
    """Deny path: ``traceparent`` does not bypass authentication."""
    # Third-Party
    import httpx

    with httpx.Client(base_url=instana_traceparent_gateway["base_url"], timeout=15, trust_env=False) as anonymous:
        response = anonymous.get("/gateways", headers=TRACEPARENT)
    assert response.status_code == 401, response.text
