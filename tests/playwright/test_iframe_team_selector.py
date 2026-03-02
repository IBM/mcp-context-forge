# -*- coding: utf-8 -*-
"""Regression test: team selector dropdown works inside an iframe.

The innerHTML sanitizer guard strips inline onclick attributes. This test
verifies the event delegation fix makes team selection work in iframe mode.
"""

# Standard
import re
import uuid

# Third-Party
import pytest
from playwright.sync_api import expect
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError


_PROXY_PREFIX = "/proxy/mcp"


class TestIframeTeamSelector:
    """Team selector dropdown inside an iframe-embedded admin UI."""

    def test_team_selector_click_navigates_in_iframe(self, team_page):
        """Clicking a team in the header dropdown inside an iframe should navigate with ?team_id=."""
        page = team_page.page
        base_url = page.url.split("/admin")[0]
        team_name = f"iframe-test-{uuid.uuid4().hex[:8]}"

        # Create a team via UI (same as existing test)
        team_page.navigate_to_teams_tab()
        with page.expect_response(lambda r: "/admin/teams" in r.url and r.request.method == "POST"):
            team_page.create_team(team_name)
        page.wait_for_load_state("domcontentloaded")

        # Set up proxy route for iframe
        def handle_route(route):
            try:
                url = route.request.url.replace(
                    _PROXY_PREFIX, "", 1
                )
                response = route.fetch(url=url)
                headers = dict(response.headers)
                headers.pop("x-frame-options", None)
                if "content-security-policy" in headers:
                    headers["content-security-policy"] = headers[
                        "content-security-policy"
                    ].replace("frame-ancestors 'none'", "frame-ancestors 'self'")
                route.fulfill(status=response.status, headers=headers, body=response.body())
            except Exception:
                pass

        pattern = re.compile(r".*/proxy/mcp/.*")
        page.route(pattern, handle_route)

        try:
            # Load admin inside an iframe
            proxy_admin_url = f"{base_url}{_PROXY_PREFIX}/admin#gateways"
            page.set_content(
                f'<!DOCTYPE html><html><body style="margin:0">'
                f'<iframe id="af" src="{proxy_admin_url}" '
                f'style="width:100%;height:100vh;border:none" '
                f'sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-modals">'
                f'</iframe></body></html>'
            )

            frame = page.frame_locator("#af")
            frame_obj = page.frames[-1]

            # Wait for admin JS init
            frame_obj.wait_for_function(
                "typeof window.selectTeamFromSelector === 'function'",
                timeout=20000,
            )

            # Open team selector dropdown
            selector_btn = frame.locator("#team-selector-button")
            expect(selector_btn).to_be_visible(timeout=10000)
            selector_btn.click()

            # Wait for items loaded via fetch + innerHTML
            frame_obj.wait_for_function(
                "() => document.querySelectorAll('#team-selector-items .team-selector-item').length > 0",
                timeout=15000,
            )

            # PROOF 1: onclick stripped, data-team-id survives
            check = frame_obj.evaluate("""
                () => {
                    const btn = document.querySelector('#team-selector-items .team-selector-item');
                    return btn ? {
                        hasOnclick: btn.hasAttribute('onclick'),
                        hasDataTeamId: btn.hasAttribute('data-team-id'),
                    } : null;
                }
            """)
            assert check, "No team-selector-item found in iframe"
            assert check["hasOnclick"] is False, "innerHTML guard should strip onclick"
            assert check["hasDataTeamId"] is True, "data-team-id should survive guard"

            # PROOF 2: Click team → navigation with ?team_id=
            team_item = frame.locator(f".team-selector-item:has-text('{team_name}')")
            expect(team_item).to_be_visible(timeout=10000)

            with frame_obj.expect_navigation(timeout=15000):
                team_item.click()

            assert "team_id=" in frame_obj.url, (
                f"Expected team_id in iframe URL, got: {frame_obj.url}"
            )
        finally:
            page.unroute(pattern)
            # Cleanup: go back to normal admin, delete team
            page.goto(f"{base_url}/admin")
            page.wait_for_load_state("domcontentloaded")
            team_page.navigate_to_teams_tab()
            team_search = page.locator("#team-search")
            team_search.wait_for(state="visible", timeout=30000)
            team_search.fill(team_name)
            team_page.wait_for_team_visible(team_name)
            team_page.delete_team(team_name)
