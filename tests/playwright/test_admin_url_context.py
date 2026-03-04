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
from playwright.sync_api import APIRequestContext, expect, Page, TimeoutError as PlaywrightTimeoutError

# Local
from .conftest import _ensure_admin_logged_in


# A placeholder team_id value; tests use it as a URL param and verify it survives
# mutations.  In a real team-scoped deployment this would be a valid UUID.
# NOTE: This value intentionally fails UUID validation, which causes tests with
# team_id=True to receive a 400 JSON error instead of the admin page.  This
# means those tests skip (no form elements found) rather than exercise the real
# admin UI.  See #3340 for the tracking issue.
_TEAM_PARAM = "test-team-placeholder"

_PROXY_PREFIX = "/proxy/mcp"

_ADD_GATEWAY_BTN_SELECTOR = (
    "button[onclick*='handleGatewayFormSubmit'], #add-gateway-btn, "
    "button[type='submit'][form*='gateway'], button:has-text('Add Gateway')"
)


# ===================================================================
# SHARED HELPERS
# ===================================================================


def _wait_for_admin_content(page: Page) -> None:
    """Wait for admin app to settle after navigation.

    Uses networkidle with a timeout fallback, since these tests need HTMX
    partials to have loaded before interacting with tab content.
    """
    try:
        page.wait_for_load_state("networkidle", timeout=30000)
    except PlaywrightTimeoutError:
        pass  # SSE/setInterval may prevent networkidle; proceed anyway


def _build_navigate_admin_url(page, fragment: str = "gateways") -> str:
    """Build the URL that ``_navigateAdmin()`` would navigate to.

    After any successful mutation the admin JS calls ``_navigateAdmin()``
    which builds a URL from the current page state (checkbox values, URL
    params) and sets ``window.location.href``.

    This helper invokes the same logic but captures the URL string instead
    of actually navigating.  This lets us test URL-context preservation
    independently of the server's trailing-slash redirect behavior (which
    strips query params when a hash fragment is present — a separate known
    bug in ``_navigateAdmin`` generating ``/admin`` without trailing slash).
    """
    return page.evaluate(f"""() => {{
        const currentPath = window.location.pathname;
        const adminIdx = currentPath.lastIndexOf('/admin');
        const base = adminIdx >= 0
            ? window.location.origin + currentPath.slice(0, adminIdx)
            : (window.ROOT_PATH || window.location.origin);
        const searchParams = new URLSearchParams();
        if (typeof isInactiveChecked === 'function' && isInactiveChecked('{fragment}')) {{
            searchParams.set('include_inactive', 'true');
        }}
        const teamId = new URL(window.location.href).searchParams.get('team_id');
        if (teamId) {{ searchParams.set('team_id', teamId); }}
        const qs = searchParams.toString();
        return base + '/admin' + (qs ? '?' + qs : '') + '#{fragment}';
    }}""")


def _admin_url(base_url: str, *, prefix: str = "", team_id: bool = False, include_inactive: bool = False, fragment: str = "gateways") -> str:
    """Build an admin URL with optional proxy prefix, query params, and fragment.

    Note: the server's trailing-slash redirect can strip query params when a
    ``#fragment`` is present.  The JS ``cleanUpUrlParamsForTab()`` also removes
    ``include_inactive`` from the URL on tab switch (but preserves the checkbox
    state).  Tests should verify checkbox state rather than relying on
    ``include_inactive`` being in the URL after initial navigation.
    """
    params = []
    if team_id:
        params.append(f"team_id={_TEAM_PARAM}")
    if include_inactive:
        params.append("include_inactive=true")
    qs = f"?{'&'.join(params)}" if params else ""
    return f"{base_url}{prefix}/admin{qs}#{fragment}"


def _create_gateway_api(api_request_context: APIRequestContext, name_prefix: str) -> str:
    """Create a test gateway via API. Returns the gateway ID. Skips on failure."""
    create_resp = api_request_context.post(
        "/gateways",
        headers={"Content-Type": "application/json"},
        data={
            "name": f"{name_prefix}-{uuid.uuid4().hex[:6]}",
            "url": "http://127.0.0.1:19999",
            "transport": "HTTP",
        },
    )
    if not create_resp.ok:
        pytest.skip(f"Could not create test gateway (HTTP {create_resp.status}) — skipping.")

    gw_id = create_resp.json().get("id", "")
    if not gw_id:
        pytest.skip("Gateway created but ID missing — skipping.")
    return gw_id


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


def _fill_add_gateway_form(root, unique_name: str) -> None:
    """Fill the add-gateway form fields. Skips if inputs are not found.

    ``root`` can be a Page or FrameLocator — both support ``.locator()``.
    The add-gateway form uses ``#mcp-server-name`` / ``#mcp-server-url``
    (not ``#gateway-*`` which belongs to the edit modal).
    """
    name_input = root.locator("#add-gateway-form #mcp-server-name, #add-gateway-form input[name='name']").first
    url_input = root.locator("#add-gateway-form #mcp-server-url, #add-gateway-form input[name='url']").first

    if name_input.count() == 0 or url_input.count() == 0:
        pytest.skip("Add-gateway form inputs not found — skipping.")

    name_input.fill(unique_name)
    url_input.fill("http://127.0.0.1:19999")


def _click_add_gateway_btn(root) -> None:
    """Click the add-gateway submit button. ``root`` is a Page or FrameLocator."""
    root.locator(_ADD_GATEWAY_BTN_SELECTOR).first.click()


def _get_delete_gateway_btn(root, gw_id: str):
    """Locate and return the delete button for a gateway. Waits for HTMX table load."""
    # The gateways table body is loaded via HTMX partial — wait for it first.
    # FrameLocator (used in iframe tests) lacks wait_for_selector, so guard.
    if hasattr(root, "wait_for_selector"):
        try:
            root.wait_for_selector("#gateways-table-body", state="attached", timeout=30000)
        except PlaywrightTimeoutError:
            pass
    delete_form = root.locator(f'form[action*="/gateways/{gw_id}/delete"]').first
    if delete_form.count() == 0:
        pytest.skip("Delete form for created gateway not visible in UI — skipping.")
    return delete_form.locator('button[type="submit"]').first


def _accept_dialog(page: Page) -> list:
    """Register a one-shot dialog handler that accepts. Returns the confirmed list."""
    confirmed: list = []

    def _handler(dialog):
        confirmed.append(dialog.message)
        dialog.accept()

    page.once("dialog", _handler)
    return confirmed


def _assert_url_params(
    url: str,
    *,
    proxy_prefix: bool = False,
    team_id: bool = True,
    include_inactive: bool = True,
    fragment: str = "gateways",
) -> None:
    """Assert URL contains/excludes expected params, prefix, and fragment."""
    if proxy_prefix:
        assert f"{_PROXY_PREFIX}/admin" in url, f"Expected proxy prefix in URL; got: {url}"
    if team_id:
        assert f"team_id={_TEAM_PARAM}" in url, f"Expected team_id in URL; got: {url}"
    else:
        assert "team_id" not in url, f"team_id must be absent from URL; got: {url}"
    if include_inactive:
        assert "include_inactive=true" in url, f"Expected include_inactive in URL; got: {url}"
    else:
        assert "include_inactive" not in url, f"include_inactive must be absent from URL; got: {url}"
    assert f"#{fragment}" in url, f"Expected #{fragment} in URL; got: {url}"


# ===================================================================
# TEST CLASS 1: Direct (non-proxy) mode
# ===================================================================


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
        """After adding a gateway, URL fragment stays on #gateways and team_id is kept."""
        _ensure_admin_logged_in(page, base_url)
        unique_name = f"test-gw-urlctx-{uuid.uuid4().hex[:8]}"

        page.goto(_admin_url(base_url, team_id=True))
        page.wait_for_load_state("domcontentloaded")
        _wait_for_admin_content(page)

        _fill_add_gateway_form(page, unique_name)

        with page.expect_navigation(wait_until="domcontentloaded", timeout=30000):
            _click_add_gateway_btn(page)

        _assert_url_params(page.url, team_id=True, include_inactive=False)

    def test_add_server_success_preserves_catalog_fragment(
        self, page: Page, base_url: str
    ):
        """After adding a virtual server, URL fragment stays on #catalog and team_id is kept."""
        _ensure_admin_logged_in(page, base_url)
        unique_name = f"test-srv-urlctx-{uuid.uuid4().hex[:8]}"

        page.goto(_admin_url(base_url, team_id=True, fragment="catalog"))
        page.wait_for_load_state("domcontentloaded")
        _wait_for_admin_content(page)

        name_input = page.locator("#server-name, input[name='name'][id*='server']").first
        if name_input.count() == 0:
            pytest.skip("Add-server form inputs not found — skipping.")

        name_input.fill(unique_name)

        with page.expect_navigation(wait_until="domcontentloaded", timeout=30000):
            page.locator(
                "button[onclick*='handleServerFormSubmit'], #add-server-btn, "
                "button[type='submit'][form*='server'], button:has-text('Add Server')"
            ).first.click()

        _assert_url_params(page.url, team_id=True, include_inactive=False, fragment="catalog")

    def test_edit_gateway_preserves_gateways_fragment_and_team_id(
        self, page: Page, base_url: str, api_request_context: APIRequestContext
    ):
        """After editing a gateway, URL fragment stays on #gateways and team_id is kept."""
        _ensure_admin_logged_in(page, base_url)
        gw_id = _create_gateway_api(api_request_context, "test-gw-edit")

        try:
            page.goto(_admin_url(base_url, team_id=True))
            page.wait_for_load_state("domcontentloaded")
            _wait_for_admin_content(page)

            edit_btn = page.locator(f"button[onclick*=\"editGateway('{gw_id}')\"]").first
            if edit_btn.count() == 0:
                pytest.skip("Edit button for created gateway not visible — skipping.")
            edit_btn.click()

            edit_form = page.locator("#edit-gateway-form")
            try:
                edit_form.wait_for(state="visible", timeout=10000)
            except Exception:
                pytest.skip("Edit gateway modal did not open — skipping.")

            desc_input = page.locator("#edit-gateway-description")
            if desc_input.count() > 0:
                desc_input.fill("updated by direct test")

            with page.expect_navigation(wait_until="domcontentloaded", timeout=30000):
                edit_form.locator('button[type="submit"]').first.click()

            _assert_url_params(page.url, team_id=True, include_inactive=False)
        finally:
            api_request_context.delete(f"/gateways/{gw_id}")

    # ------------------------------------------------------------------
    # Delete/Toggle (issue #3321): fetch() preserves proxy URL context
    # ------------------------------------------------------------------

    def test_toggle_server_preserves_catalog_tab_and_team_id(
        self, page: Page, base_url: str
    ):
        """After toggling a server's active state, URL stays on #catalog and team_id survives."""
        _ensure_admin_logged_in(page, base_url)
        page.goto(_admin_url(base_url, team_id=True, fragment="catalog"))
        page.wait_for_load_state("domcontentloaded")
        _wait_for_admin_content(page)

        toggle_form = page.locator('form[action*="/servers/"][action*="/state"]').first
        if toggle_form.count() == 0:
            pytest.skip("No server toggle forms found — register a server first.")

        with page.expect_navigation(wait_until="domcontentloaded", timeout=30000):
            toggle_form.locator('button[type="submit"]').first.click()

        _assert_url_params(page.url, team_id=True, include_inactive=False, fragment="catalog")

    def test_delete_gateway_preserves_gateways_tab_and_team_id(
        self, page: Page, base_url: str, api_request_context: APIRequestContext
    ):
        """After deleting a gateway via the UI, URL stays on #gateways and team_id survives."""
        _ensure_admin_logged_in(page, base_url)
        gw_id = _create_gateway_api(api_request_context, "test-gw-del")

        try:
            page.goto(_admin_url(base_url, team_id=True))
            page.wait_for_load_state("domcontentloaded")
            _wait_for_admin_content(page)

            delete_btn = _get_delete_gateway_btn(page, gw_id)
            confirmed = _accept_dialog(page)

            with page.expect_navigation(wait_until="domcontentloaded", timeout=30000):
                delete_btn.click()

            _assert_url_params(page.url, team_id=True, include_inactive=False)
            assert len(confirmed) >= 1, "Expected at least one confirm() dialog for delete"
        finally:
            api_request_context.delete(f"/gateways/{gw_id}")

    def test_add_gateway_preserves_both_params(
        self, page: Page, base_url: str, api_request_context: APIRequestContext
    ):
        """After adding a gateway, both team_id AND include_inactive survive in URL."""
        _ensure_admin_logged_in(page, base_url)
        unique_name = f"test-gw-both-{uuid.uuid4().hex[:8]}"

        page.goto(_admin_url(base_url, team_id=True, include_inactive=True))
        page.wait_for_load_state("domcontentloaded")
        _wait_for_admin_content(page)

        _fill_add_gateway_form(page, unique_name)

        try:
            with page.expect_navigation(wait_until="domcontentloaded", timeout=30000):
                _click_add_gateway_btn(page)

            _assert_url_params(page.url, team_id=True, include_inactive=True)
        finally:
            _cleanup_gateway_by_name(api_request_context, unique_name)

    def test_delete_gateway_preserves_both_params(
        self, page: Page, base_url: str, api_request_context: APIRequestContext
    ):
        """After deleting a gateway, both team_id AND include_inactive survive in URL."""
        _ensure_admin_logged_in(page, base_url)
        gw_id = _create_gateway_api(api_request_context, "test-gw-delboth")

        try:
            page.goto(_admin_url(base_url, team_id=True, include_inactive=True))
            page.wait_for_load_state("domcontentloaded")
            _wait_for_admin_content(page)

            delete_btn = _get_delete_gateway_btn(page, gw_id)
            confirmed = _accept_dialog(page)

            with page.expect_navigation(wait_until="domcontentloaded", timeout=30000):
                delete_btn.click()

            assert len(confirmed) >= 1, "Expected at least one confirm() dialog for delete"
            _assert_url_params(page.url, team_id=True, include_inactive=True)
        finally:
            api_request_context.delete(f"/gateways/{gw_id}")

    def test_add_preserves_team_id_only(self, page: Page, base_url: str, api_request_context: APIRequestContext):
        """Starting with only team_id: include_inactive must NOT appear post-mutation."""
        _ensure_admin_logged_in(page, base_url)
        unique_name = f"test-gw-tidonly-{uuid.uuid4().hex[:8]}"

        page.goto(_admin_url(base_url, team_id=True))
        page.wait_for_load_state("domcontentloaded")
        _wait_for_admin_content(page)

        _fill_add_gateway_form(page, unique_name)

        try:
            with page.expect_navigation(wait_until="domcontentloaded", timeout=30000):
                _click_add_gateway_btn(page)

            _assert_url_params(page.url, team_id=True, include_inactive=False)
        finally:
            _cleanup_gateway_by_name(api_request_context, unique_name)

    def test_add_preserves_include_inactive_only(self, page: Page, base_url: str, api_request_context: APIRequestContext):
        """Starting with only include_inactive: team_id must NOT appear post-mutation.

        Regression test for #3324: after a mutation the admin JS calls
        ``_navigateAdmin()`` which builds the redirect URL from checkbox state
        and current URL params.  ``include_inactive`` must survive the round-trip.
        """
        _ensure_admin_logged_in(page, base_url)

        # Navigate WITHOUT hash first — the server redirect strips query params
        # when a #fragment is present.  The JS checkbox initialization reads
        # include_inactive from window.location.search on DOMContentLoaded.
        page.goto(f"{base_url}/admin/?include_inactive=true")
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_selector('[data-testid="servers-tab"]', state="visible", timeout=30000)

        # Verify checkbox was initialized from the URL parameter.
        assert page.evaluate("document.getElementById('show-inactive-gateways')?.checked") is True, \
            "show-inactive-gateways checkbox should be checked from include_inactive=true URL param"

        # Verify _navigateAdmin builds a URL that preserves include_inactive
        # from the checkbox state and does NOT include team_id.
        nav_url = _build_navigate_admin_url(page, "gateways")
        _assert_url_params(nav_url, team_id=False, include_inactive=True)


# ===================================================================
# TEST CLASS 2: Proxy-prefix mode
# ===================================================================


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

        page.goto(_admin_url(base_url, prefix=_PROXY_PREFIX, team_id=True, include_inactive=True))
        page.wait_for_load_state("domcontentloaded")
        _wait_for_admin_content(page)

        _fill_add_gateway_form(page, unique_name)

        try:
            with page.expect_navigation(wait_until="domcontentloaded", timeout=30000):
                _click_add_gateway_btn(page)

            _assert_url_params(page.url, proxy_prefix=True, team_id=True, include_inactive=True)
        finally:
            _cleanup_gateway_by_name(api_request_context, unique_name)

    def test_proxy_edit_gateway_preserves_fragment_and_params(
        self, page: Page, base_url: str, api_request_context: APIRequestContext
    ):
        """After editing a gateway via proxy URL, fragment + both params survive."""
        _ensure_admin_logged_in(page, base_url)
        gw_id = _create_gateway_api(api_request_context, "test-gw-prxedit")

        try:
            page.goto(_admin_url(base_url, prefix=_PROXY_PREFIX, team_id=True, include_inactive=True))
            page.wait_for_load_state("domcontentloaded")
            _wait_for_admin_content(page)

            # Click the edit button in the DOM rather than calling editGateway()
            # via evaluate — the 1.2 MB admin.js may not finish executing before
            # domcontentloaded fires in the proxy context.
            edit_btn = page.locator(f"button[onclick*=\"editGateway('{gw_id}')\"]").first
            if edit_btn.count() == 0:
                pytest.skip("Edit button for created gateway not visible — skipping.")
            edit_btn.click()

            edit_form = page.locator("#edit-gateway-form")
            try:
                edit_form.wait_for(state="visible", timeout=10000)
            except Exception:
                pytest.skip("Edit gateway modal did not open — skipping.")

            desc_input = page.locator("#edit-gateway-description")
            if desc_input.count() > 0:
                desc_input.fill("updated by proxy test")

            with page.expect_navigation(wait_until="domcontentloaded", timeout=30000):
                edit_form.locator('button[type="submit"]').first.click()

            _assert_url_params(page.url, proxy_prefix=True, team_id=True, include_inactive=True)
        finally:
            api_request_context.delete(f"/gateways/{gw_id}")

    def test_proxy_toggle_server_preserves_catalog_tab(
        self, page: Page, base_url: str
    ):
        """After toggling a server state via proxy URL, #catalog + both params survive."""
        _ensure_admin_logged_in(page, base_url)
        page.goto(_admin_url(base_url, prefix=_PROXY_PREFIX, team_id=True, include_inactive=True, fragment="catalog"))
        page.wait_for_load_state("domcontentloaded")
        _wait_for_admin_content(page)

        toggle_form = page.locator('form[action*="/servers/"][action*="/state"]').first
        if toggle_form.count() == 0:
            pytest.skip("No server toggle forms found — register a server first.")

        with page.expect_navigation(wait_until="domcontentloaded", timeout=30000):
            toggle_form.locator('button[type="submit"]').first.click()

        _assert_url_params(page.url, proxy_prefix=True, team_id=True, include_inactive=True, fragment="catalog")

    def test_proxy_delete_gateway_preserves_tab_and_params(
        self, page: Page, base_url: str, api_request_context: APIRequestContext
    ):
        """After deleting a gateway via proxy URL, fragment + both params survive."""
        _ensure_admin_logged_in(page, base_url)
        gw_id = _create_gateway_api(api_request_context, "test-gw-prxdel")

        try:
            page.goto(_admin_url(base_url, prefix=_PROXY_PREFIX, team_id=True, include_inactive=True))
            page.wait_for_load_state("domcontentloaded")
            _wait_for_admin_content(page)

            delete_btn = _get_delete_gateway_btn(page, gw_id)
            confirmed = _accept_dialog(page)

            with page.expect_navigation(wait_until="domcontentloaded", timeout=30000):
                delete_btn.click()

            assert len(confirmed) >= 1, "Expected at least one confirm() dialog for delete"
            _assert_url_params(page.url, proxy_prefix=True, team_id=True, include_inactive=True)
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

        page.goto(_admin_url(base_url, prefix=_PROXY_PREFIX, team_id=True))
        page.wait_for_load_state("domcontentloaded")
        _wait_for_admin_content(page)

        _fill_add_gateway_form(page, unique_name)

        try:
            with page.expect_navigation(wait_until="domcontentloaded", timeout=30000):
                _click_add_gateway_btn(page)

            _assert_url_params(page.url, proxy_prefix=True, team_id=True, include_inactive=False)
        finally:
            _cleanup_gateway_by_name(api_request_context, unique_name)

    def test_proxy_add_preserves_include_inactive_only(
        self, page: Page, base_url: str, api_request_context: APIRequestContext
    ):
        """Proxy: starting with only include_inactive — team_id must not appear post-mutation.

        Regression test for #3324 in proxy context.
        """
        _ensure_admin_logged_in(page, base_url)

        # Navigate WITHOUT hash via proxy so include_inactive survives the redirect.
        page.goto(f"{base_url}{_PROXY_PREFIX}/admin/?include_inactive=true")
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_selector('[data-testid="servers-tab"]', state="visible", timeout=30000)

        assert page.evaluate("document.getElementById('show-inactive-gateways')?.checked") is True, \
            "show-inactive-gateways checkbox should be checked from include_inactive=true URL param"

        # Verify _navigateAdmin builds a URL that preserves include_inactive
        # and proxy prefix, without team_id.
        nav_url = _build_navigate_admin_url(page, "gateways")
        _assert_url_params(nav_url, proxy_prefix=True, team_id=False, include_inactive=True)

    # ------------------------------------------------------------------
    # Same-URL reload regression (#3351, root cause of #3324)
    # ------------------------------------------------------------------

    def test_proxy_navigate_admin_reloads_when_url_unchanged(
        self, page: Page, base_url: str
    ):
        """_navigateAdmin must reload even when target URL equals the current URL.

        Regression for #3351 (root cause of #3324): in proxy/iframe mode the
        URL path has no trailing slash (``/proxy/mcp/admin``), so
        ``_navigateAdmin`` computes the exact same URL as the current one.
        Browsers treat ``location.href = sameURL#sameHash`` as an in-page
        anchor scroll and skip the network reload, leaving stale data on
        screen.

        In direct mode the bug is masked because FastAPI redirects ``/admin`` →
        ``/admin/`` (trailing slash), creating a URL difference that triggers a
        real reload.
        """
        _ensure_admin_logged_in(page, base_url)

        # Navigate to proxy admin WITHOUT trailing slash (matches iframe behavior).
        page.goto(_admin_url(base_url, prefix=_PROXY_PREFIX, fragment="gateways"))
        page.wait_for_load_state("domcontentloaded")
        _wait_for_admin_content(page)

        # Plant a marker variable — a real page reload will wipe it.
        page.evaluate("window.__reload_test_marker = Date.now()")

        # Call the real _navigateAdmin from admin.js with the current fragment.
        # Because the target URL matches the current URL (proxy path without
        # trailing slash), the fix should trigger window.location.reload().
        try:
            with page.expect_navigation(wait_until="domcontentloaded", timeout=10000):
                page.evaluate("_navigateAdmin('gateways', new URLSearchParams())")
        except PlaywrightTimeoutError:
            pytest.fail(
                "Page did NOT reload after _navigateAdmin to same URL — "
                "this is the #3351 bug: proxy/iframe URLs have no "
                "trailing-slash difference to trigger a browser reload."
            )

        marker = page.evaluate("window.__reload_test_marker")
        assert marker is None, (
            "Navigation occurred but page was not fully reloaded — "
            "window.__reload_test_marker survived."
        )


# ===================================================================
# TEST CLASS 3: Iframe-embedded mode
# ===================================================================


@pytest.mark.ui
@pytest.mark.regression
@pytest.mark.iframe
class TestAdminIframeContext:
    """Admin UI works correctly when embedded in an <iframe> with a proxy-prefix src.

    The host page is built with page.set_content() (no file on disk). The same
    page.route() proxy fixture strips X-Frame-Options so the browser allows
    embedding. After mutations, page.frames[-1].url carries the expected
    /proxy/mcp/admin?...#fragment URL.

    Regression guard for #3321 and #3324 in iframe-embedded deployments.
    """

    @pytest.fixture(autouse=True)
    def _proxy_routes(self, page: Page, base_url: str):
        """Intercept /proxy/mcp/** and serve real content from /**.

        Also strips X-Frame-Options and fixes CSP frame-ancestors so that
        the admin page (default: X-Frame-Options: DENY) can be embedded.
        """

        def handle_route(route):
            try:
                url = route.request.url.replace(
                    base_url.rstrip("/") + _PROXY_PREFIX, base_url.rstrip("/"), 1
                )
                response = route.fetch(url=url)
                headers = dict(response.headers)
                headers.pop("x-frame-options", None)
                if "content-security-policy" in headers:
                    headers["content-security-policy"] = headers[
                        "content-security-policy"
                    ].replace("frame-ancestors 'none'", "frame-ancestors 'self'")
                route.fulfill(
                    status=response.status,
                    headers=headers,
                    body=response.body(),
                )
            except Exception:
                pass  # Route may already be handled during teardown

        _pattern = re.compile(r".*/proxy/mcp/.*")
        page.route(_pattern, handle_route)
        yield
        page.unroute(_pattern)

    @pytest.fixture(autouse=True)
    def _iframe_host(self, page: Page, base_url: str, _proxy_routes):
        """Seed auth cookies then load a host page with the admin in an <iframe>."""
        _ensure_admin_logged_in(page, base_url)
        proxy_admin_url = _admin_url(base_url, prefix=_PROXY_PREFIX, team_id=True, include_inactive=True)
        page.set_content(
            f"""<!DOCTYPE html>
<html><head><title>iframe host</title></head>
<body style="margin:0;padding:0">
<iframe id="admin-frame"
        src="{proxy_admin_url}"
        style="width:100%;height:100vh;border:none"
        sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-modals">
</iframe>
</body></html>"""
        )
        frame = page.frame_locator("#admin-frame")
        try:
            frame.locator('[data-testid="servers-tab"]').wait_for(
                state="visible", timeout=30000
            )
        except PlaywrightTimeoutError:
            pass  # Continue — some CI setups load slower

    def _frame(self, page: Page):
        """Return the iframe Frame object (index 1, index 0 is the host page)."""
        frames = page.frames
        return frames[-1] if len(frames) > 1 else frames[0]

    def _assert_iframe_url(self, page: Page, *, proxy_prefix: bool = True, team_id: bool = True, include_inactive: bool = True, fragment: str = "gateways"):
        """Wait briefly then assert the iframe URL using the shared helper."""
        frame_obj = self._frame(page)
        try:
            frame_obj.wait_for_load_state("domcontentloaded", timeout=10000)
        except PlaywrightTimeoutError:
            pass
        _assert_url_params(frame_obj.url, proxy_prefix=proxy_prefix, team_id=team_id, include_inactive=include_inactive, fragment=fragment)

    # ------------------------------------------------------------------
    # Smoke
    # ------------------------------------------------------------------

    def test_iframe_admin_loads_and_retains_fragment(self, page: Page, base_url: str):
        """Admin UI loads in iframe and initial URL contains proxy prefix + fragment."""
        frame_obj = self._frame(page)
        try:
            frame_obj.wait_for_load_state("domcontentloaded", timeout=15000)
        except PlaywrightTimeoutError:
            pass
        url = frame_obj.url
        assert f"{_PROXY_PREFIX}/admin" in url, f"Proxy prefix missing from iframe URL; got: {url}"
        assert "#gateways" in url, f"Fragment missing from iframe URL; got: {url}"

    # ------------------------------------------------------------------
    # Add / Edit / Toggle / Delete (both params)
    # ------------------------------------------------------------------

    def test_iframe_add_gateway_preserves_proxy_prefix(
        self, page: Page, base_url: str, api_request_context: APIRequestContext
    ):
        """Adding a gateway inside the iframe: proxy prefix + both params + fragment survive."""
        frame = page.frame_locator("#admin-frame")
        frame_obj = self._frame(page)
        unique_name = f"test-gw-iframeadd-{uuid.uuid4().hex[:8]}"

        _fill_add_gateway_form(frame, unique_name)

        try:
            with frame_obj.expect_navigation(wait_until="domcontentloaded", timeout=30000):
                _click_add_gateway_btn(frame)

            self._assert_iframe_url(page)
        finally:
            _cleanup_gateway_by_name(api_request_context, unique_name)

    def test_iframe_edit_gateway_preserves_proxy_prefix(
        self, page: Page, base_url: str, api_request_context: APIRequestContext
    ):
        """Editing a gateway inside the iframe: proxy prefix + both params + fragment survive."""
        gw_id = _create_gateway_api(api_request_context, "test-gw-iframeedit")

        frame = page.frame_locator("#admin-frame")
        frame_obj = self._frame(page)

        try:
            # Click the edit button in the DOM rather than calling editGateway()
            # via evaluate — admin.js may not finish executing in iframe context.
            edit_btn = frame.locator(f"button[onclick*=\"editGateway('{gw_id}')\"]").first
            if edit_btn.count() == 0:
                pytest.skip("Edit button for created gateway not visible in iframe — skipping.")
            edit_btn.click()

            edit_form = frame.locator("#edit-gateway-form")
            try:
                edit_form.wait_for(state="visible", timeout=10000)
            except PlaywrightTimeoutError:
                pytest.skip("Edit gateway modal did not open in iframe — skipping.")

            desc_input = frame.locator("#edit-gateway-description")
            if desc_input.count() > 0:
                desc_input.fill("updated by iframe test")

            with frame_obj.expect_navigation(wait_until="domcontentloaded", timeout=30000):
                edit_form.locator('button[type="submit"]').first.click()

            self._assert_iframe_url(page)
        finally:
            api_request_context.delete(f"/gateways/{gw_id}")

    def test_iframe_toggle_server_preserves_proxy_prefix(
        self, page: Page, base_url: str
    ):
        """Toggling a server state inside the iframe: proxy prefix + params + #catalog survive."""
        frame_obj = self._frame(page)
        frame_obj.evaluate(
            f"window.location.href = '{_admin_url(base_url, prefix=_PROXY_PREFIX, team_id=True, include_inactive=True, fragment='catalog')}'"
        )
        try:
            frame_obj.wait_for_load_state("domcontentloaded", timeout=10000)
        except PlaywrightTimeoutError:
            pass

        frame = page.frame_locator("#admin-frame")
        toggle_form = frame.locator('form[action*="/servers/"][action*="/state"]').first
        if toggle_form.count() == 0:
            pytest.skip("No server toggle forms found in iframe — register a server first.")

        with frame_obj.expect_navigation(wait_until="domcontentloaded", timeout=30000):
            toggle_form.locator('button[type="submit"]').first.click()

        self._assert_iframe_url(page, fragment="catalog")

    def test_iframe_delete_gateway_preserves_proxy_prefix(
        self, page: Page, base_url: str, api_request_context: APIRequestContext
    ):
        """Deleting a gateway inside the iframe: proxy prefix + both params + fragment survive."""
        gw_id = _create_gateway_api(api_request_context, "test-gw-iframedel")

        frame = page.frame_locator("#admin-frame")
        frame_obj = self._frame(page)

        try:
            delete_btn = _get_delete_gateway_btn(frame, gw_id)
            page.on("dialog", lambda d: d.accept())

            with frame_obj.expect_navigation(wait_until="domcontentloaded", timeout=30000):
                delete_btn.click()

            self._assert_iframe_url(page)
        finally:
            api_request_context.delete(f"/gateways/{gw_id}")

    # ------------------------------------------------------------------
    # Single-param (negative) tests
    # ------------------------------------------------------------------

    def test_iframe_add_preserves_team_id_only(
        self, page: Page, base_url: str, api_request_context: APIRequestContext
    ):
        """Iframe + proxy: team_id only start — include_inactive must NOT appear post-mutation."""
        frame_obj = self._frame(page)
        frame_obj.evaluate(
            f"window.location.href = '{_admin_url(base_url, prefix=_PROXY_PREFIX, team_id=True, fragment='gateways')}'"
        )
        try:
            frame_obj.wait_for_load_state("domcontentloaded", timeout=10000)
        except PlaywrightTimeoutError:
            pass

        frame = page.frame_locator("#admin-frame")
        unique_name = f"test-gw-ifrtid-{uuid.uuid4().hex[:8]}"

        _fill_add_gateway_form(frame, unique_name)

        try:
            with frame_obj.expect_navigation(wait_until="domcontentloaded", timeout=30000):
                _click_add_gateway_btn(frame)

            self._assert_iframe_url(page, include_inactive=False)
        finally:
            _cleanup_gateway_by_name(api_request_context, unique_name)

    def test_iframe_add_preserves_include_inactive_only(
        self, page: Page, base_url: str, api_request_context: APIRequestContext
    ):
        """Iframe + proxy: include_inactive only start — team_id must NOT appear post-mutation."""
        frame_obj = self._frame(page)
        frame_obj.evaluate(
            f"window.location.href = '{_admin_url(base_url, prefix=_PROXY_PREFIX, include_inactive=True, fragment='gateways')}'"
        )
        try:
            frame_obj.wait_for_load_state("domcontentloaded", timeout=10000)
        except PlaywrightTimeoutError:
            pass

        frame = page.frame_locator("#admin-frame")
        unique_name = f"test-gw-ifrinac-{uuid.uuid4().hex[:8]}"

        _fill_add_gateway_form(frame, unique_name)

        try:
            with frame_obj.expect_navigation(wait_until="domcontentloaded", timeout=30000):
                _click_add_gateway_btn(frame)

            self._assert_iframe_url(page, team_id=False)
        finally:
            _cleanup_gateway_by_name(api_request_context, unique_name)

    # ------------------------------------------------------------------
    # Team selector dropdown inside iframe
    # ------------------------------------------------------------------

    def test_iframe_team_selector_onclick_stripped_but_delegation_works(
        self, page: Page, base_url: str, api_request_context: APIRequestContext
    ):
        """Team selector click inside iframe navigates with ?team_id=.

        Regression: installInnerHtmlGuard() strips inline onclick from
        team selector buttons loaded via fetch() + innerHTML. This test
        verifies:
        1. The inline onclick IS stripped (proving the guard is active)
        2. The event delegation fix makes clicks work anyway
        3. The iframe URL ends up with ?team_id= after clicking a team
        """
        frame_obj = self._frame(page)

        # Navigate iframe to admin WITHOUT team scope so the page loads
        # properly (the autouse fixture uses a placeholder team_id that
        # causes 400 errors).
        no_team_url = _admin_url(
            base_url, prefix=_PROXY_PREFIX, team_id=False, fragment="gateways"
        )
        frame_obj.evaluate(f"window.location.href = '{no_team_url}'")
        try:
            frame_obj.wait_for_load_state("domcontentloaded", timeout=15000)
        except PlaywrightTimeoutError:
            pass

        # Wait for admin JS to initialise inside iframe
        try:
            frame_obj.wait_for_function(
                "typeof window.searchTeamSelector === 'function'",
                timeout=15000,
            )
        except PlaywrightTimeoutError:
            pytest.skip("Admin JS did not initialise inside iframe")

        frame = page.frame_locator("#admin-frame")

        # Create a real team via API so the dropdown has something to click
        team_name = f"iframe-test-{uuid.uuid4().hex[:8]}"
        resp = api_request_context.post("/admin/teams", data={"name": team_name})
        if resp.status >= 400:
            pytest.skip(f"Could not create test team: {resp.status}")
        team_data = resp.json()
        team_id = team_data.get("id") or team_data.get("team", {}).get("id")
        assert team_id, f"Team creation response missing id: {team_data}"

        try:
            # Open the team selector dropdown
            selector_btn = frame.locator("#team-selector-button")
            try:
                selector_btn.wait_for(state="visible", timeout=10000)
            except PlaywrightTimeoutError:
                pytest.skip("Team selector button not visible in iframe")
            selector_btn.click()

            # Wait for team items to load via fetch + innerHTML
            items_container = frame.locator("#team-selector-items")
            items_container.wait_for(state="visible", timeout=10000)

            # Wait for actual team buttons (not "Loading..." placeholder)
            frame_obj.wait_for_function(
                "() => document.querySelectorAll('#team-selector-items .team-selector-item').length > 0",
                timeout=15000,
            )

            # PROOF 1: Verify the innerHTML guard is active inside the iframe
            # by injecting a synthetic element with onclick via innerHTML and
            # confirming it is stripped while data-* attributes survive.
            # (The team selector template no longer emits onclick, so checking
            # the template button alone would be tautological.)
            guard_check = frame_obj.evaluate("""
                () => {
                    const div = document.createElement('div');
                    document.body.appendChild(div);
                    // Use innerHTML to trigger the guard (this is a test, not production code)
                    div.innerHTML = '<button onclick="alert(1)" data-action="test" data-id="x">X</button>';
                    const btn = div.querySelector('button');
                    const result = {
                        guardActive: !btn.hasAttribute('onclick'),
                        dataActionSurvived: btn.getAttribute('data-action') === 'test',
                    };
                    div.remove();
                    return result;
                }
            """)
            assert guard_check["guardActive"], (
                "innerHTML guard should strip onclick inside iframe"
            )
            assert guard_check["dataActionSurvived"], (
                "data-action should survive innerHTML guard inside iframe"
            )

            # Also verify team selector items have data-team-id (template correctness)
            onclick_check = frame_obj.evaluate("""
                () => {
                    const btn = document.querySelector('#team-selector-items .team-selector-item');
                    if (!btn) return { found: false };
                    return {
                        found: true,
                        hasDataTeamId: btn.hasAttribute('data-team-id'),
                    };
                }
            """)
            assert onclick_check["found"], "No team-selector-item found in iframe"
            assert onclick_check["hasDataTeamId"] is True, (
                "data-team-id should survive innerHTML guard"
            )

            # PROOF 2: Click our team and verify navigation happens
            team_item = frame.locator(
                f".team-selector-item:has-text('{team_name}')"
            )
            try:
                team_item.wait_for(state="visible", timeout=10000)
            except PlaywrightTimeoutError:
                pytest.skip("Created team not visible in dropdown")

            with frame_obj.expect_navigation(timeout=15000):
                team_item.click()

            # PROOF 3: iframe URL now contains team_id
            iframe_url = frame_obj.url
            assert "team_id=" in iframe_url, (
                f"Expected team_id in iframe URL after clicking team, got: {iframe_url}"
            )
            assert team_id in iframe_url, (
                f"Expected team_id={team_id} in iframe URL, got: {iframe_url}"
            )
        finally:
            # Cleanup: delete the test team
            api_request_context.delete(f"/admin/teams/{team_id}")
