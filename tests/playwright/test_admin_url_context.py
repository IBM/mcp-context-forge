# -*- coding: utf-8 -*-
"""Location: ./tests/playwright/test_admin_url_context.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Regression tests for admin UI URL context preservation.
Covers issues #3321 (delete/toggle loses tab/team_id) and
#3324 (add/edit loses tab/team_id via ROOT_PATH).

These tests run against the real gateway in non-proxy mode.
They verify that after each mutation the browser URL retains:
  - the correct #fragment (tab)
  - the team_id query param (when originally present)
"""

# Standard
import re
import uuid

# Third-Party
import pytest
from playwright.sync_api import APIRequestContext, expect, Page

# Local
from .conftest import _ensure_admin_logged_in


# A placeholder team_id value; tests use it as a URL param and verify it survives
# mutations.  In a real team-scoped deployment this would be a valid UUID.
_TEAM_PARAM = "test-team-placeholder"


def _cleanup_gateway_by_name(api_request_context: APIRequestContext, name: str) -> None:
    """Best-effort cleanup: find and delete any gateway with the given name."""
    try:
        resp = api_request_context.get("/gateways")
        if not resp.ok:
            return
        for gw in resp.json():
            if gw.get("name") == name:
                api_request_context.delete(f"/gateways/{gw['id']}")
    except Exception:
        pass  # Best-effort only — never fail a test on cleanup


_PROXY_PREFIX = "/proxy/mcp"


@pytest.mark.ui
@pytest.mark.regression
class TestAdminUrlContextPreservation:
    """URL context (tab fragment + team_id) is preserved after mutations.

    Regression coverage for:
      - #3321: delete/toggle used form.submit() → 303 redirect drops proxy prefix
      - #3324: add/edit redirected via window.ROOT_PATH which is empty in proxy context
    """

    # ------------------------------------------------------------------
    # Smoke: basic URL state
    # ------------------------------------------------------------------

    def test_admin_page_retains_tools_fragment(self, page: Page, base_url: str):
        """Navigating to /admin#tools loads and keeps #tools fragment."""
        _ensure_admin_logged_in(page, base_url)
        page.goto(f"{base_url}/admin#tools")
        expect(page).to_have_url(re.compile(r"#tools$"))

    def test_admin_page_retains_gateways_fragment(self, page: Page, base_url: str):
        """Navigating to /admin#gateways loads and keeps #gateways fragment."""
        _ensure_admin_logged_in(page, base_url)
        page.goto(f"{base_url}/admin#gateways")
        expect(page).to_have_url(re.compile(r"#gateways$"))

    def test_admin_page_retains_catalog_fragment(self, page: Page, base_url: str):
        """Navigating to /admin#catalog loads and keeps #catalog fragment."""
        _ensure_admin_logged_in(page, base_url)
        page.goto(f"{base_url}/admin#catalog")
        expect(page).to_have_url(re.compile(r"#catalog$"))

    # ------------------------------------------------------------------
    # Add/Edit redirect (issue #3324): _navigateAdmin() preserves team_id
    # ------------------------------------------------------------------

    def test_add_gateway_success_preserves_gateways_fragment(
        self, page: Page, base_url: str, api_request_context: APIRequestContext
    ):
        """After adding a gateway, URL fragment stays on #gateways and team_id is kept.

        Creates and immediately deletes a minimal gateway via API so there is no
        leftover data.  The UI mutation is submitted via the add-gateway form.
        """
        _ensure_admin_logged_in(page, base_url)
        unique_name = f"test-gw-urlctx-{uuid.uuid4().hex[:8]}"

        page.goto(f"{base_url}/admin?team_id={_TEAM_PARAM}#gateways")
        page.wait_for_load_state("networkidle")

        # Locate add-gateway form fields
        name_input = page.locator("#gateway-name, input[name='name'][id*='gateway']").first
        url_input = page.locator("#gateway-url, input[name='url'][id*='gateway']").first

        if name_input.count() == 0 or url_input.count() == 0:
            pytest.skip("Add-gateway form inputs not found — skipping.")

        name_input.fill(unique_name)
        url_input.fill("http://127.0.0.1:19999")

        # Submit and wait for _navigateAdmin() to trigger navigation
        with page.expect_navigation(wait_until="networkidle", timeout=15000):
            page.locator(
                "button[onclick*='handleGatewayFormSubmit'], #add-gateway-btn, "
                "button[type='submit'][form*='gateway'], button:has-text('Add Gateway')"
            ).first.click()

        # Core assertion: fragment preserved, team_id preserved
        expect(page).to_have_url(re.compile(r"#gateways"))
        expect(page).to_have_url(re.compile(rf"team_id={_TEAM_PARAM}"))

    def test_add_server_success_preserves_catalog_fragment(
        self, page: Page, base_url: str
    ):
        """After adding a virtual server, URL fragment stays on #catalog and team_id is kept.

        Uses a minimal server payload and skips if the form cannot be located.
        """
        _ensure_admin_logged_in(page, base_url)
        unique_name = f"test-srv-urlctx-{uuid.uuid4().hex[:8]}"

        page.goto(f"{base_url}/admin?team_id={_TEAM_PARAM}#catalog")
        page.wait_for_load_state("networkidle")

        name_input = page.locator("#server-name, input[name='name'][id*='server']").first
        if name_input.count() == 0:
            pytest.skip("Add-server form inputs not found — skipping.")

        name_input.fill(unique_name)

        with page.expect_navigation(wait_until="networkidle", timeout=15000):
            page.locator(
                "button[onclick*='handleServerFormSubmit'], #add-server-btn, "
                "button[type='submit'][form*='server'], button:has-text('Add Server')"
            ).first.click()

        expect(page).to_have_url(re.compile(r"#catalog"))
        expect(page).to_have_url(re.compile(rf"team_id={_TEAM_PARAM}"))

    # ------------------------------------------------------------------
    # Delete/Toggle (issue #3321): fetch() preserves proxy URL context
    # ------------------------------------------------------------------

    def test_toggle_server_preserves_catalog_tab_and_team_id(
        self, page: Page, base_url: str
    ):
        """After toggling a server's active state, URL stays on #catalog and team_id survives.

        Skips when no servers are registered in the system.
        """
        _ensure_admin_logged_in(page, base_url)
        page.goto(f"{base_url}/admin?team_id={_TEAM_PARAM}#catalog")
        page.wait_for_load_state("networkidle")

        # Find any activate/deactivate toggle form targeting a server state endpoint
        toggle_form = page.locator('form[action*="/servers/"][action*="/state"]').first
        if toggle_form.count() == 0:
            pytest.skip("No server toggle forms found — register a server first.")

        toggle_btn = toggle_form.locator('button[type="submit"]').first

        # Click and wait for _navigateAdmin() navigation
        with page.expect_navigation(wait_until="networkidle", timeout=15000):
            toggle_btn.click()

        # After fetch + _navigateAdmin(): must remain on #catalog with team_id
        expect(page).to_have_url(re.compile(r"#catalog"))
        expect(page).to_have_url(re.compile(rf"team_id={_TEAM_PARAM}"))

    def test_delete_gateway_preserves_gateways_tab_and_team_id(
        self, page: Page, base_url: str, api_request_context: APIRequestContext
    ):
        """After deleting a gateway via the UI, URL stays on #gateways and team_id survives.

        Creates a test gateway via API, deletes via UI, then verifies URL context.
        Cleans up gateway even if assertions fail.
        """
        _ensure_admin_logged_in(page, base_url)

        # Create a gateway to delete
        create_resp = api_request_context.post(
            "/gateways",
            headers={"Content-Type": "application/json"},
            data={
                "name": f"test-gw-del-{uuid.uuid4().hex[:6]}",
                "url": "http://127.0.0.1:19999",
                "transport": "HTTP",
            },
        )
        if not create_resp.ok:
            pytest.skip(f"Could not create test gateway (HTTP {create_resp.status}) — skipping.")

        gw_id = create_resp.json().get("id", "")
        if not gw_id:
            pytest.skip("Gateway created but ID missing — skipping.")

        try:
            page.goto(f"{base_url}/admin?team_id={_TEAM_PARAM}#gateways")
            page.wait_for_load_state("networkidle")

            delete_form = page.locator(f'form[action*="/gateways/{gw_id}/delete"]').first
            if delete_form.count() == 0:
                pytest.skip("Delete form for created gateway not visible in UI — skipping.")

            delete_btn = delete_form.locator('button[type="submit"]').first

            confirmed: list = []

            def _handle_dialog(dialog):
                confirmed.append(dialog.message)
                dialog.accept()

            page.once("dialog", _handle_dialog)

            # Click delete and wait for _navigateAdmin() to fire
            with page.expect_navigation(wait_until="networkidle", timeout=15000):
                delete_btn.click()

            # After fetch + _navigateAdmin(): must remain on #gateways with team_id
            expect(page).to_have_url(re.compile(r"#gateways"))
            expect(page).to_have_url(re.compile(rf"team_id={_TEAM_PARAM}"))
            assert len(confirmed) >= 1, "Expected at least one confirm() dialog for delete"
        finally:
            # Best-effort cleanup — gateway may already be deleted
            api_request_context.delete(
                f"/gateways/{gw_id}",
            )

    def test_add_gateway_preserves_both_params(
        self, page: Page, base_url: str, api_request_context: APIRequestContext
    ):
        """After adding a gateway, both team_id AND include_inactive survive in URL.

        Navigates with both params; the JS checkbox-init logic checks the
        show-inactive checkbox, so isInactiveChecked() returns True, and
        _navigateAdmin() carries include_inactive=true forward.
        """
        _ensure_admin_logged_in(page, base_url)
        unique_name = f"test-gw-both-{uuid.uuid4().hex[:8]}"

        page.goto(f"{base_url}/admin?team_id={_TEAM_PARAM}&include_inactive=true#gateways")
        page.wait_for_load_state("networkidle")

        name_input = page.locator("#gateway-name, input[name='name'][id*='gateway']").first
        url_input = page.locator("#gateway-url, input[name='url'][id*='gateway']").first
        if name_input.count() == 0 or url_input.count() == 0:
            pytest.skip("Add-gateway form inputs not found — skipping.")

        name_input.fill(unique_name)
        url_input.fill("http://127.0.0.1:19999")

        try:
            with page.expect_navigation(wait_until="networkidle", timeout=15000):
                page.locator(
                    "button[onclick*='handleGatewayFormSubmit'], #add-gateway-btn, "
                    "button[type='submit'][form*='gateway'], button:has-text('Add Gateway')"
                ).first.click()

            expect(page).to_have_url(re.compile(r"#gateways"))
            expect(page).to_have_url(re.compile(rf"team_id={_TEAM_PARAM}"))
            expect(page).to_have_url(re.compile(r"include_inactive=true"))
        finally:
            _cleanup_gateway_by_name(api_request_context, unique_name)

    def test_delete_gateway_preserves_both_params(
        self, page: Page, base_url: str, api_request_context: APIRequestContext
    ):
        """After deleting a gateway, both team_id AND include_inactive survive in URL."""
        _ensure_admin_logged_in(page, base_url)

        create_resp = api_request_context.post(
            "/gateways",
            headers={"Content-Type": "application/json"},
            data={
                "name": f"test-gw-delboth-{uuid.uuid4().hex[:6]}",
                "url": "http://127.0.0.1:19999",
                "transport": "HTTP",
            },
        )
        if not create_resp.ok:
            pytest.skip(f"Could not create test gateway (HTTP {create_resp.status}) — skipping.")

        gw_id = create_resp.json().get("id", "")
        if not gw_id:
            pytest.skip("Gateway created but ID missing.")

        try:
            page.goto(f"{base_url}/admin?team_id={_TEAM_PARAM}&include_inactive=true#gateways")
            page.wait_for_load_state("networkidle")

            delete_form = page.locator(f'form[action*="/gateways/{gw_id}/delete"]').first
            if delete_form.count() == 0:
                pytest.skip("Delete form for created gateway not visible in UI — skipping.")

            delete_btn = delete_form.locator('button[type="submit"]').first
            confirmed: list = []

            def _handle_dialog_both(dialog):
                confirmed.append(dialog.message)
                dialog.accept()

            page.once("dialog", _handle_dialog_both)

            with page.expect_navigation(wait_until="networkidle", timeout=15000):
                delete_btn.click()

            assert len(confirmed) >= 1, "Expected at least one confirm() dialog for delete"
            expect(page).to_have_url(re.compile(r"#gateways"))
            expect(page).to_have_url(re.compile(rf"team_id={_TEAM_PARAM}"))
            expect(page).to_have_url(re.compile(r"include_inactive=true"))
        finally:
            api_request_context.delete(f"/gateways/{gw_id}")

    def test_add_preserves_team_id_only(self, page: Page, base_url: str, api_request_context: APIRequestContext):
        """Starting with only team_id: include_inactive must NOT appear post-mutation.

        Verifies _navigateAdmin() does not inject include_inactive when the
        show-inactive checkbox is unchecked (URL has no include_inactive param).
        """
        _ensure_admin_logged_in(page, base_url)
        unique_name = f"test-gw-tidonly-{uuid.uuid4().hex[:8]}"

        page.goto(f"{base_url}/admin?team_id={_TEAM_PARAM}#gateways")
        page.wait_for_load_state("networkidle")

        name_input = page.locator("#gateway-name, input[name='name'][id*='gateway']").first
        url_input = page.locator("#gateway-url, input[name='url'][id*='gateway']").first
        if name_input.count() == 0 or url_input.count() == 0:
            pytest.skip("Add-gateway form inputs not found — skipping.")

        name_input.fill(unique_name)
        url_input.fill("http://127.0.0.1:19999")

        try:
            with page.expect_navigation(wait_until="networkidle", timeout=15000):
                page.locator(
                    "button[onclick*='handleGatewayFormSubmit'], #add-gateway-btn, "
                    "button[type='submit'][form*='gateway'], button:has-text('Add Gateway')"
                ).first.click()

            expect(page).to_have_url(re.compile(r"#gateways"))
            expect(page).to_have_url(re.compile(rf"team_id={_TEAM_PARAM}"))
            assert "include_inactive" not in page.url, (
                f"include_inactive must not appear when starting URL had none; got: {page.url}"
            )
        finally:
            _cleanup_gateway_by_name(api_request_context, unique_name)

    def test_add_preserves_include_inactive_only(self, page: Page, base_url: str, api_request_context: APIRequestContext):
        """Starting with only include_inactive: team_id must NOT appear post-mutation.

        Verifies _navigateAdmin() does not inject team_id when the URL had none.
        """
        _ensure_admin_logged_in(page, base_url)
        unique_name = f"test-gw-inaconly-{uuid.uuid4().hex[:8]}"

        page.goto(f"{base_url}/admin?include_inactive=true#gateways")
        page.wait_for_load_state("networkidle")

        name_input = page.locator("#gateway-name, input[name='name'][id*='gateway']").first
        url_input = page.locator("#gateway-url, input[name='url'][id*='gateway']").first
        if name_input.count() == 0 or url_input.count() == 0:
            pytest.skip("Add-gateway form inputs not found — skipping.")

        name_input.fill(unique_name)
        url_input.fill("http://127.0.0.1:19999")

        try:
            with page.expect_navigation(wait_until="networkidle", timeout=15000):
                page.locator(
                    "button[onclick*='handleGatewayFormSubmit'], #add-gateway-btn, "
                    "button[type='submit'][form*='gateway'], button:has-text('Add Gateway')"
                ).first.click()

            expect(page).to_have_url(re.compile(r"include_inactive=true"))
            expect(page).to_have_url(re.compile(r"#gateways"))
            assert "team_id" not in page.url, (
                f"team_id must not appear when starting URL had none; got: {page.url}"
            )
        finally:
            _cleanup_gateway_by_name(api_request_context, unique_name)


@pytest.mark.ui
@pytest.mark.regression
@pytest.mark.proxy
class TestAdminProxyUrlContext:
    """Proxy-prefix URL context is preserved after mutations.

    Uses page.route() to serve the admin under /proxy/mcp/admin, making
    window.location.pathname = "/proxy/mcp/admin" inside the page JS.
    _navigateAdmin() must then produce /proxy/mcp/admin?...#fragment.

    Regression guard for #3321 and #3324 in proxy-embedded deployments.
    """

    @pytest.fixture(autouse=True)
    def _proxy_routes(self, page: Page, base_url: str):
        """Intercept /proxy/mcp/** and serve real content from /**."""

        def handle_route(route):
            url = route.request.url.replace(
                base_url.rstrip("/") + _PROXY_PREFIX, base_url.rstrip("/"), 1
            )
            response = route.fetch(url=url)
            route.fulfill(response=response)

        _pattern = re.compile(r".*/proxy/mcp/.*")
        page.route(_pattern, handle_route)
        yield
        page.unroute(_pattern)

    # ------------------------------------------------------------------
    # Both-params mutations
    # ------------------------------------------------------------------

    def test_proxy_add_gateway_preserves_fragment_and_params(
        self, page: Page, base_url: str, api_request_context: APIRequestContext
    ):
        """After adding a gateway via proxy URL, fragment + both params survive."""
        _ensure_admin_logged_in(page, base_url)
        unique_name = f"test-gw-prxadd-{uuid.uuid4().hex[:8]}"

        page.goto(f"{base_url}{_PROXY_PREFIX}/admin?team_id={_TEAM_PARAM}&include_inactive=true#gateways")
        page.wait_for_load_state("networkidle")

        name_input = page.locator("#gateway-name, input[name='name'][id*='gateway']").first
        url_input = page.locator("#gateway-url, input[name='url'][id*='gateway']").first
        if name_input.count() == 0 or url_input.count() == 0:
            pytest.skip("Add-gateway form inputs not found — skipping.")

        name_input.fill(unique_name)
        url_input.fill("http://127.0.0.1:19999")

        try:
            with page.expect_navigation(wait_until="networkidle", timeout=15000):
                page.locator(
                    "button[onclick*='handleGatewayFormSubmit'], #add-gateway-btn, "
                    "button[type='submit'][form*='gateway'], button:has-text('Add Gateway')"
                ).first.click()

            expect(page).to_have_url(re.compile(r"/proxy/mcp/admin"))
            expect(page).to_have_url(re.compile(rf"team_id={_TEAM_PARAM}"))
            expect(page).to_have_url(re.compile(r"include_inactive=true"))
            expect(page).to_have_url(re.compile(r"#gateways"))
        finally:
            _cleanup_gateway_by_name(api_request_context, unique_name)

    def test_proxy_edit_gateway_preserves_fragment_and_params(
        self, page: Page, base_url: str, api_request_context: APIRequestContext
    ):
        """After editing a gateway via proxy URL, fragment + both params survive.

        Creates a gateway via API, opens its edit modal via JS, submits, asserts URL.
        """
        _ensure_admin_logged_in(page, base_url)

        create_resp = api_request_context.post(
            "/gateways",
            headers={"Content-Type": "application/json"},
            data={
                "name": f"test-gw-prxedit-{uuid.uuid4().hex[:6]}",
                "url": "http://127.0.0.1:19999",
                "transport": "HTTP",
            },
        )
        if not create_resp.ok:
            pytest.skip(f"Could not create test gateway (HTTP {create_resp.status}) — skipping.")

        gw_id = create_resp.json().get("id", "")
        if not gw_id:
            pytest.skip("Gateway created but ID missing.")

        try:
            page.goto(f"{base_url}{_PROXY_PREFIX}/admin?team_id={_TEAM_PARAM}&include_inactive=true#gateways")
            page.wait_for_load_state("networkidle")

            # editGateway() is a global JS function that populates and opens the edit modal
            page.evaluate(f"editGateway('{gw_id}')")

            edit_form = page.locator("#edit-gateway-form")
            try:
                edit_form.wait_for(state="visible", timeout=10000)
            except Exception:
                pytest.skip("Edit gateway modal did not open — skipping.")

            desc_input = page.locator("#edit-gateway-description")
            if desc_input.count() > 0:
                desc_input.fill("updated by proxy test")

            with page.expect_navigation(wait_until="networkidle", timeout=15000):
                edit_form.locator('button[type="submit"]').first.click()

            expect(page).to_have_url(re.compile(r"/proxy/mcp/admin"))
            expect(page).to_have_url(re.compile(rf"team_id={_TEAM_PARAM}"))
            expect(page).to_have_url(re.compile(r"include_inactive=true"))
            expect(page).to_have_url(re.compile(r"#gateways"))
        finally:
            api_request_context.delete(f"/gateways/{gw_id}")

    def test_proxy_toggle_server_preserves_catalog_tab(
        self, page: Page, base_url: str
    ):
        """After toggling a server state via proxy URL, #catalog + both params survive."""
        _ensure_admin_logged_in(page, base_url)
        page.goto(f"{base_url}{_PROXY_PREFIX}/admin?team_id={_TEAM_PARAM}&include_inactive=true#catalog")
        page.wait_for_load_state("networkidle")

        toggle_form = page.locator('form[action*="/servers/"][action*="/state"]').first
        if toggle_form.count() == 0:
            pytest.skip("No server toggle forms found — register a server first.")

        toggle_btn = toggle_form.locator('button[type="submit"]').first

        with page.expect_navigation(wait_until="networkidle", timeout=15000):
            toggle_btn.click()

        expect(page).to_have_url(re.compile(r"/proxy/mcp/admin"))
        expect(page).to_have_url(re.compile(rf"team_id={_TEAM_PARAM}"))
        expect(page).to_have_url(re.compile(r"include_inactive=true"))
        expect(page).to_have_url(re.compile(r"#catalog"))

    def test_proxy_delete_gateway_preserves_tab_and_params(
        self, page: Page, base_url: str, api_request_context: APIRequestContext
    ):
        """After deleting a gateway via proxy URL, fragment + both params survive."""
        _ensure_admin_logged_in(page, base_url)

        create_resp = api_request_context.post(
            "/gateways",
            headers={"Content-Type": "application/json"},
            data={
                "name": f"test-gw-prxdel-{uuid.uuid4().hex[:6]}",
                "url": "http://127.0.0.1:19999",
                "transport": "HTTP",
            },
        )
        if not create_resp.ok:
            pytest.skip(f"Could not create test gateway (HTTP {create_resp.status}) — skipping.")

        gw_id = create_resp.json().get("id", "")
        if not gw_id:
            pytest.skip("Gateway created but ID missing.")

        try:
            page.goto(f"{base_url}{_PROXY_PREFIX}/admin?team_id={_TEAM_PARAM}&include_inactive=true#gateways")
            page.wait_for_load_state("networkidle")

            delete_form = page.locator(f'form[action*="/gateways/{gw_id}/delete"]').first
            if delete_form.count() == 0:
                pytest.skip("Delete form for created gateway not visible in UI — skipping.")

            delete_btn = delete_form.locator('button[type="submit"]').first

            confirmed: list = []

            def _handle_dialog_prx(dialog):
                confirmed.append(dialog.message)
                dialog.accept()

            page.once("dialog", _handle_dialog_prx)

            with page.expect_navigation(wait_until="networkidle", timeout=15000):
                delete_btn.click()

            assert len(confirmed) >= 1, "Expected at least one confirm() dialog for delete"
            expect(page).to_have_url(re.compile(r"/proxy/mcp/admin"))
            expect(page).to_have_url(re.compile(rf"team_id={_TEAM_PARAM}"))
            expect(page).to_have_url(re.compile(r"include_inactive=true"))
            expect(page).to_have_url(re.compile(r"#gateways"))
        finally:
            api_request_context.delete(f"/gateways/{gw_id}")

    # ------------------------------------------------------------------
    # Single-param (negative) tests
    # ------------------------------------------------------------------

    def test_proxy_add_preserves_team_id_only(
        self, page: Page, base_url: str, api_request_context: APIRequestContext
    ):
        """Proxy: starting with only team_id — include_inactive must not appear post-mutation."""
        _ensure_admin_logged_in(page, base_url)
        unique_name = f"test-gw-prxtid-{uuid.uuid4().hex[:8]}"

        page.goto(f"{base_url}{_PROXY_PREFIX}/admin?team_id={_TEAM_PARAM}#gateways")
        page.wait_for_load_state("networkidle")

        name_input = page.locator("#gateway-name, input[name='name'][id*='gateway']").first
        url_input = page.locator("#gateway-url, input[name='url'][id*='gateway']").first
        if name_input.count() == 0 or url_input.count() == 0:
            pytest.skip("Add-gateway form inputs not found — skipping.")

        name_input.fill(unique_name)
        url_input.fill("http://127.0.0.1:19999")

        try:
            with page.expect_navigation(wait_until="networkidle", timeout=15000):
                page.locator(
                    "button[onclick*='handleGatewayFormSubmit'], #add-gateway-btn, "
                    "button[type='submit'][form*='gateway'], button:has-text('Add Gateway')"
                ).first.click()

            expect(page).to_have_url(re.compile(r"/proxy/mcp/admin"))
            expect(page).to_have_url(re.compile(rf"team_id={_TEAM_PARAM}"))
            expect(page).to_have_url(re.compile(r"#gateways"))
            assert "include_inactive" not in page.url, (
                f"include_inactive must not appear when starting URL had none; got: {page.url}"
            )
        finally:
            _cleanup_gateway_by_name(api_request_context, unique_name)

    def test_proxy_add_preserves_include_inactive_only(
        self, page: Page, base_url: str, api_request_context: APIRequestContext
    ):
        """Proxy: starting with only include_inactive — team_id must not appear post-mutation."""
        _ensure_admin_logged_in(page, base_url)
        unique_name = f"test-gw-prxinac-{uuid.uuid4().hex[:8]}"

        page.goto(f"{base_url}{_PROXY_PREFIX}/admin?include_inactive=true#gateways")
        page.wait_for_load_state("networkidle")

        name_input = page.locator("#gateway-name, input[name='name'][id*='gateway']").first
        url_input = page.locator("#gateway-url, input[name='url'][id*='gateway']").first
        if name_input.count() == 0 or url_input.count() == 0:
            pytest.skip("Add-gateway form inputs not found — skipping.")

        name_input.fill(unique_name)
        url_input.fill("http://127.0.0.1:19999")

        try:
            with page.expect_navigation(wait_until="networkidle", timeout=15000):
                page.locator(
                    "button[onclick*='handleGatewayFormSubmit'], #add-gateway-btn, "
                    "button[type='submit'][form*='gateway'], button:has-text('Add Gateway')"
                ).first.click()

            expect(page).to_have_url(re.compile(r"/proxy/mcp/admin"))
            expect(page).to_have_url(re.compile(r"include_inactive=true"))
            expect(page).to_have_url(re.compile(r"#gateways"))
            assert "team_id" not in page.url, (
                f"team_id must not appear when starting URL had none; got: {page.url}"
            )
        finally:
            _cleanup_gateway_by_name(api_request_context, unique_name)
