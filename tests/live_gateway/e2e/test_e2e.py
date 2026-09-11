# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/e2e/test_e2e.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

End-to-end coverage of observable gateway flows against a live stack.

``TestVirtualServerLifecycle`` (issue #6519) exercises the virtual server as a
complete flow rather than as test scaffolding: creation contract, discovery via
REST, tool and resource associations reachable through the per-server MCP
endpoint, deletion, and the endpoint's disappearance afterwards.

Requirements:
    - ContextForge running with docker-compose (default: http://localhost:8080)
    - fast_time_server auto-registered as the ``fast_time`` gateway
    - playwright installed: pip install playwright

Usage:
    make test-e2e
    make test-e2e K=TestVirtualServerLifecycle
"""

# Future
from __future__ import annotations

# Standard
from typing import Any, Callable

# Third-Party
import httpx
import pytest
from playwright.sync_api import APIRequestContext, APIResponse

# Local
from ..helpers.mcp_test_helpers import BASE_URL, build_initialize, skip_no_gateway
from .conftest import json_or_fail, list_all_servers

pytestmark = [pytest.mark.e2e, skip_no_gateway]

# Direct HTTP probe timeout — independent of the MCP client timeout so a hung
# gateway fails the test rather than hanging the run.
_PROBE_TIMEOUT = 10.0


def _server_mcp_base(server_id: str) -> str:
    """Return the MCP base URL for a virtual server.

    Args:
        server_id: Virtual server id.

    Returns:
        The ``{BASE_URL}/servers/{id}`` base the MCP helpers append ``/mcp/`` to.
    """
    return f"{BASE_URL}/servers/{server_id}"


class TestVirtualServerLifecycle:
    """Admin creates a virtual server, associates tools and resources, reaches them over MCP, deletes it."""

    def test_create_server_returns_id_and_name(self, create_server: Callable[..., APIResponse], shared_gateway: dict[str, Any]) -> None:
        """Creation returns 201 and echoes the requested identity and associations.

        Args:
            create_server: Factory returning the raw ``POST /servers`` response.
            shared_gateway: The stack's read-only ``fast_time`` gateway and catalog.
        """
        tool_ids = [tool["id"] for tool in shared_gateway["tools"]]
        expected_names = {tool["name"] for tool in shared_gateway["tools"]}
        assert tool_ids, "shared gateway fixture must supply at least one tool"

        name = "e2e-lifecycle-create-check"
        resp = create_server(tool_ids=tool_ids, name=name)

        assert resp.status == 201, f"POST /servers returned {resp.status}: {resp.text()[:500]}"
        server = json_or_fail(resp, "POST /servers")

        assert server.get("id"), f"created server has no id: {server}"
        assert server["name"] == name

        # The request takes tool IDs; the response splits them: associatedToolIds
        # carries the IDs, associatedTools carries the tool names.
        assert set(server["associatedToolIds"]) == set(tool_ids)
        assert set(server["associatedTools"]) == expected_names

    def test_created_server_in_list(self, admin_api: APIRequestContext, create_server: Callable[..., APIResponse], shared_gateway: dict[str, Any]) -> None:
        """A created server is discoverable in the paginated list and by id.

        Args:
            admin_api: Authenticated admin API context.
            create_server: Factory returning the raw ``POST /servers`` response.
            shared_gateway: The stack's read-only ``fast_time`` gateway and catalog.
        """
        tool_ids = [tool["id"] for tool in shared_gateway["tools"]]
        resp = create_server(tool_ids=tool_ids)
        assert resp.status == 201, f"POST /servers returned {resp.status}: {resp.text()[:500]}"
        server = json_or_fail(resp, "POST /servers")
        server_id = server["id"]

        listed = {entry["id"] for entry in list_all_servers(admin_api)}
        assert server_id in listed, f"server {server_id} missing from GET /servers ({len(listed)} servers listed)"

        detail = admin_api.get(f"/servers/{server_id}")
        assert detail.status == 200, f"GET /servers/{server_id} returned {detail.status}: {detail.text()[:500]}"
        assert json_or_fail(detail, f"GET /servers/{server_id}")["id"] == server_id

    def test_associated_tools_reachable_via_mcp(
        self,
        admin_api: APIRequestContext,
        create_server: Callable[..., APIResponse],
        shared_gateway: dict[str, Any],
        mcp: Any,
    ) -> None:
        """Associated tools are listed per server via REST and reachable over MCP.

        Args:
            admin_api: Authenticated admin API context.
            create_server: Factory returning the raw ``POST /servers`` response.
            shared_gateway: The stack's read-only ``fast_time`` gateway and catalog.
            mcp: MCP probe bound to the admin identity.
        """
        tool_ids = [tool["id"] for tool in shared_gateway["tools"]]
        resp = create_server(tool_ids=tool_ids)
        assert resp.status == 201, f"POST /servers returned {resp.status}: {resp.text()[:500]}"
        server_id = json_or_fail(resp, "POST /servers")["id"]

        rest = admin_api.get(f"/servers/{server_id}/tools")
        assert rest.status == 200, f"GET /servers/{server_id}/tools returned {rest.status}: {rest.text()[:500]}"
        rest_tools = json_or_fail(rest, f"GET /servers/{server_id}/tools")

        rest_ids = {tool["id"] for tool in rest_tools}
        expected_names = {tool["name"] for tool in rest_tools}
        assert rest_ids, "per-server tool listing is empty"
        assert rest_ids == set(tool_ids)

        observed = mcp.tool_names_when_ready(_server_mcp_base(server_id), expected_names)
        assert observed == expected_names, f"MCP tools/list mismatch: missing={sorted(expected_names - observed)} unexpected={sorted(observed - expected_names)}"

    def test_associated_resources_reachable_via_mcp(
        self,
        admin_api: APIRequestContext,
        create_server: Callable[..., APIResponse],
        create_resource: Callable[..., APIResponse],
        mcp: Any,
    ) -> None:
        """Associated resources are listed per server via REST and reachable over MCP.

        Args:
            admin_api: Authenticated admin API context.
            create_server: Factory returning the raw ``POST /servers`` response.
            create_resource: Factory returning the raw ``POST /resources`` response.
            mcp: MCP probe bound to the admin identity.
        """
        resource_resp = create_resource()
        assert resource_resp.status in (200, 201), f"POST /resources returned {resource_resp.status}: {resource_resp.text()[:500]}"
        resource = json_or_fail(resource_resp, "POST /resources")
        resource_id = resource["id"]

        resp = create_server(resource_ids=[resource_id])
        assert resp.status == 201, f"POST /servers returned {resp.status}: {resp.text()[:500]}"
        server_id = json_or_fail(resp, "POST /servers")["id"]

        rest = admin_api.get(f"/servers/{server_id}/resources")
        assert rest.status == 200, f"GET /servers/{server_id}/resources returned {rest.status}: {rest.text()[:500]}"
        rest_resources = json_or_fail(rest, f"GET /servers/{server_id}/resources")

        # The association is by id, but MCP exposes resources by URI only, so the
        # comparison has to go through the per-server REST records.
        rest_ids = {str(entry["id"]) for entry in rest_resources}
        expected_uris = {entry["uri"] for entry in rest_resources}
        assert rest_ids, "per-server resource listing is empty"
        assert rest_ids == {str(resource_id)}

        observed = mcp.resource_uris_when_ready(_server_mcp_base(server_id), expected_uris)
        assert observed == expected_uris, f"MCP resources/list mismatch: missing={sorted(expected_uris - observed)} unexpected={sorted(observed - expected_uris)}"

    def test_delete_removes_from_list(self, admin_api: APIRequestContext, create_server: Callable[..., APIResponse], shared_gateway: dict[str, Any]) -> None:
        """Deletion removes the server from the list and from detail lookup.

        Args:
            admin_api: Authenticated admin API context.
            create_server: Factory returning the raw ``POST /servers`` response.
            shared_gateway: The stack's read-only ``fast_time`` gateway and catalog.
        """
        tool_ids = [tool["id"] for tool in shared_gateway["tools"]]
        resp = create_server(tool_ids=tool_ids)
        assert resp.status == 201, f"POST /servers returned {resp.status}: {resp.text()[:500]}"
        server_id = json_or_fail(resp, "POST /servers")["id"]

        assert server_id in {entry["id"] for entry in list_all_servers(admin_api)}, "server absent from GET /servers before deletion"

        deleted = admin_api.delete(f"/servers/{server_id}")
        assert deleted.status == 200, f"DELETE /servers/{server_id} returned {deleted.status}: {deleted.text()[:500]}"
        assert json_or_fail(deleted, f"DELETE /servers/{server_id}")["status"] == "success"

        assert server_id not in {entry["id"] for entry in list_all_servers(admin_api)}, "server still present in GET /servers after deletion"

        detail = admin_api.get(f"/servers/{server_id}")
        assert detail.status == 404, f"GET /servers/{server_id} returned {detail.status} after deletion, expected 404"

    def test_mcp_endpoint_gone_after_delete(
        self,
        admin_api: APIRequestContext,
        create_server: Callable[..., APIResponse],
        shared_gateway: dict[str, Any],
        admin_token: str,
        mcp: Any,
    ) -> None:
        """The per-server MCP endpoint stops serving once the server is deleted.

        Server existence is an uncached ``EXISTS`` check made after the delete has
        committed, so the 404 is immediate and is asserted without convergence
        retries. The exact status is scoped to this admin identity and the Python
        transport: the ``servers.use`` check runs before existence validation, so a
        narrowed or non-admin token would see 403 instead.

        Args:
            admin_api: Authenticated admin API context.
            create_server: Factory returning the raw ``POST /servers`` response.
            shared_gateway: The stack's read-only ``fast_time`` gateway and catalog.
            admin_token: Un-narrowed platform-admin JWT.
            mcp: MCP probe bound to the admin identity.
        """
        tool_ids = [tool["id"] for tool in shared_gateway["tools"]]
        expected_names = {tool["name"] for tool in shared_gateway["tools"]}
        resp = create_server(tool_ids=tool_ids)
        assert resp.status == 201, f"POST /servers returned {resp.status}: {resp.text()[:500]}"
        server_id = json_or_fail(resp, "POST /servers")["id"]

        observed = mcp.tool_names_when_ready(_server_mcp_base(server_id), expected_names)
        assert observed == expected_names, f"MCP endpoint not serving expected tools before deletion: {sorted(observed)}"

        deleted = admin_api.delete(f"/servers/{server_id}")
        assert deleted.status == 200, f"DELETE /servers/{server_id} returned {deleted.status}: {deleted.text()[:500]}"

        # A timeout or connection error propagates and fails the test: an
        # unreachable gateway must not read as a successfully removed endpoint.
        with httpx.Client(timeout=_PROBE_TIMEOUT) as client:
            probe = client.post(
                f"{_server_mcp_base(server_id)}/mcp/",
                headers={
                    "Authorization": f"Bearer {admin_token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                },
                json=build_initialize(1),
            )

        assert probe.status_code == 404, f"initialize against deleted server returned {probe.status_code}, expected 404: {probe.text[:500]}"
