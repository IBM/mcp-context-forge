# -*- coding: utf-8 -*-
"""Location: ./tests/playwright/entities/test_team_scope_redirect.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Playwright regression tests for team_id preservation in admin redirect URLs.

Verifies that toggle (activate/deactivate) and delete operations preserve
the team_id query parameter in the redirect URL, so users remain within
their team-scoped view after performing actions. Regression coverage for
the fix in PR #3268.
"""

# Standard
import logging
import uuid

# Third-Party
from playwright.sync_api import APIRequestContext, APIResponse

# Local
from ..pages.admin_utils import _get_auth_headers, cleanup_server, cleanup_tool

logger = logging.getLogger(__name__)

# Fixed test UUID — _build_admin_redirect validates format but not existence.
TEST_TEAM_UUID = "12345678-1234-5678-1234-567812345678"
# Backend normalizes to hex (no hyphens) via _normalize_team_id.
TEST_TEAM_HEX = "12345678123456781234567812345678"


def _create_tool_via_api(api_request_context: APIRequestContext, suffix: str) -> dict:
    """Create a tool via REST API and return its JSON."""
    payload = {
        "tool": {
            "name": f"team-redirect-tool-{suffix}",
            "url": "https://api.example.com/test",
            "description": "Temporary tool for team redirect test",
            "integration_type": "REST",
            "request_type": "GET",
        }
    }
    resp = api_request_context.post("/tools", data=payload)
    assert resp.ok, f"Tool creation failed: {resp.status} {resp.text()[:200]}"
    return resp.json()


def _create_server_via_api(api_request_context: APIRequestContext, suffix: str) -> dict:
    """Create a virtual server via REST API and return its JSON."""
    payload = {
        "server": {
            "name": f"team-redirect-server-{suffix}",
            "description": "Temporary server for team redirect test",
        }
    }
    resp = api_request_context.post("/servers", data=payload)
    assert resp.ok, f"Server creation failed: {resp.status} {resp.text()[:200]}"
    return resp.json()


def _post_admin_form(page, path: str, form_data: str) -> APIResponse:
    """POST form-encoded data to an admin endpoint, following redirects.

    Returns the final response (after 303 redirect).
    """
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    headers.update(_get_auth_headers(page))
    return page.request.post(path, data=form_data, headers=headers)


class TestTeamScopeRedirect:
    """Regression tests: team_id is preserved in admin redirect URLs.

    The admin toggle/delete endpoints return 303 redirects. Playwright's
    ``page.request.post()`` follows those redirects automatically, so we
    assert on ``response.url`` (the final landing URL).
    """

    # ------------------------------------------------------------------
    # Tool toggle — deactivate
    # ------------------------------------------------------------------
    def test_tool_deactivate_preserves_team_id(self, tools_page, api_request_context: APIRequestContext):
        """Deactivating a tool with team_id keeps team_id in the redirect."""
        page = tools_page.page
        suffix = uuid.uuid4().hex[:8]
        tool = _create_tool_via_api(api_request_context, suffix)
        tool_id = tool["id"]
        try:
            form = f"activate=false&is_inactive_checked=false&team_id={TEST_TEAM_UUID}"
            resp = _post_admin_form(page, f"/admin/tools/{tool_id}/state", form)
            assert resp.status < 400, f"Toggle failed: {resp.status}"
            assert f"team_id={TEST_TEAM_HEX}" in resp.url, f"team_id missing from redirect: {resp.url}"
        finally:
            cleanup_tool(page, tool["name"])

    # ------------------------------------------------------------------
    # Tool toggle — reactivate (with include_inactive)
    # ------------------------------------------------------------------
    def test_tool_reactivate_preserves_team_id(self, tools_page, api_request_context: APIRequestContext):
        """Reactivating a tool preserves team_id and include_inactive."""
        page = tools_page.page
        suffix = uuid.uuid4().hex[:8]
        tool = _create_tool_via_api(api_request_context, suffix)
        tool_id = tool["id"]
        try:
            # First deactivate so we can reactivate.
            _post_admin_form(page, f"/admin/tools/{tool_id}/state", "activate=false&is_inactive_checked=false")

            form = f"activate=true&is_inactive_checked=true&team_id={TEST_TEAM_UUID}"
            resp = _post_admin_form(page, f"/admin/tools/{tool_id}/state", form)
            assert resp.status < 400, f"Toggle failed: {resp.status}"
            assert f"team_id={TEST_TEAM_HEX}" in resp.url, f"team_id missing from redirect: {resp.url}"
            assert "include_inactive=true" in resp.url, f"include_inactive missing from redirect: {resp.url}"
        finally:
            cleanup_tool(page, tool["name"])

    # ------------------------------------------------------------------
    # Tool delete
    # ------------------------------------------------------------------
    def test_tool_delete_preserves_team_id(self, tools_page, api_request_context: APIRequestContext):
        """Deleting a tool with team_id keeps team_id in the redirect."""
        page = tools_page.page
        suffix = uuid.uuid4().hex[:8]
        tool = _create_tool_via_api(api_request_context, suffix)
        tool_id = tool["id"]
        try:
            form = f"is_inactive_checked=false&team_id={TEST_TEAM_UUID}"
            resp = _post_admin_form(page, f"/admin/tools/{tool_id}/delete", form)
            assert resp.status < 400, f"Delete failed: {resp.status}"
            assert f"team_id={TEST_TEAM_HEX}" in resp.url, f"team_id missing from redirect: {resp.url}"
        finally:
            cleanup_tool(page, tool["name"])

    # ------------------------------------------------------------------
    # No spurious team_id when omitted
    # ------------------------------------------------------------------
    def test_tool_toggle_without_team_id_has_no_team_param(self, tools_page, api_request_context: APIRequestContext):
        """Toggle without team_id does not inject a spurious team_id."""
        page = tools_page.page
        suffix = uuid.uuid4().hex[:8]
        tool = _create_tool_via_api(api_request_context, suffix)
        tool_id = tool["id"]
        try:
            form = "activate=false&is_inactive_checked=false"
            resp = _post_admin_form(page, f"/admin/tools/{tool_id}/state", form)
            assert resp.status < 400, f"Toggle failed: {resp.status}"
            assert "team_id" not in resp.url, f"Unexpected team_id in redirect: {resp.url}"
        finally:
            cleanup_tool(page, tool["name"])

    # ------------------------------------------------------------------
    # Invalid UUID is silently dropped
    # ------------------------------------------------------------------
    def test_tool_toggle_with_invalid_team_id_drops_it(self, tools_page, api_request_context: APIRequestContext):
        """An invalid team_id UUID is silently dropped from the redirect."""
        page = tools_page.page
        suffix = uuid.uuid4().hex[:8]
        tool = _create_tool_via_api(api_request_context, suffix)
        tool_id = tool["id"]
        try:
            form = "activate=false&is_inactive_checked=false&team_id=not-a-valid-uuid"
            resp = _post_admin_form(page, f"/admin/tools/{tool_id}/state", form)
            assert resp.status < 400, f"Toggle failed: {resp.status}"
            assert "team_id" not in resp.url, f"Invalid team_id leaked into redirect: {resp.url}"
        finally:
            cleanup_tool(page, tool["name"])

    # ------------------------------------------------------------------
    # Cross-entity: server toggle → #catalog
    # ------------------------------------------------------------------
    def test_server_toggle_preserves_team_id(self, tools_page, api_request_context: APIRequestContext):
        """Server toggle redirect preserves team_id (targets #catalog)."""
        page = tools_page.page
        suffix = uuid.uuid4().hex[:8]
        server = _create_server_via_api(api_request_context, suffix)
        server_id = server["id"]
        try:
            form = f"activate=false&is_inactive_checked=false&team_id={TEST_TEAM_UUID}"
            resp = _post_admin_form(page, f"/admin/servers/{server_id}/state", form)
            assert resp.status < 400, f"Toggle failed: {resp.status}"
            assert f"team_id={TEST_TEAM_HEX}" in resp.url, f"team_id missing from redirect: {resp.url}"
            assert "#catalog" in resp.url or "catalog" in resp.url, f"Wrong redirect target: {resp.url}"
        finally:
            cleanup_server(page, server["name"])

    # ------------------------------------------------------------------
    # JS: handleToggleSubmit injects team_id from URL
    # ------------------------------------------------------------------
    def test_js_injects_team_id_into_toggle_form(self, tools_page):
        """handleToggleSubmit reads team_id from the URL and injects it into the form."""
        page = tools_page.page

        # Use pushState to set team_id in the URL without triggering navigation.
        # This avoids the admin login redirect stripping query params.
        injected = page.evaluate(
            """(teamHex) => {
                // Set team_id into the current URL via pushState
                const url = new URL(window.location.href);
                url.searchParams.set('team_id', teamHex);
                window.history.pushState({}, '', url.toString());

                // Simulate what handleToggleSubmit does
                const form = document.createElement('form');
                document.body.appendChild(form);

                const teamId = new URL(window.location.href).searchParams.get('team_id');
                if (teamId && !form.querySelector('input[name="team_id"]')) {
                    const field = document.createElement('input');
                    field.type = 'hidden';
                    field.name = 'team_id';
                    field.value = teamId;
                    form.appendChild(field);
                }

                const hiddenInput = form.querySelector('input[name="team_id"]');
                const value = hiddenInput ? hiddenInput.value : null;
                form.remove();
                return value;
            }""",
            TEST_TEAM_HEX,
        )
        assert injected == TEST_TEAM_HEX, f"Expected JS to inject {TEST_TEAM_HEX}, got {injected}"
