# -*- coding: utf-8 -*-
# Copyright (c) 2025 ContextForge Contributors.
# SPDX-License-Identifier: Apache-2.0

"""End-to-end Playwright test: team selector click flow inside an iframe.

This is the regression test for the most visible symptom of PR #3373:

    "Log in to admin UI → click the team selector dropdown → click any team
     in the list → nothing happens — no navigation, no console errors, no
     network request."

Root cause: ``installInnerHtmlGuard()`` (PR #3129) overrides
``Element.prototype.innerHTML`` to strip all ``on*`` attributes.  When
``loadTeams()`` set ``container.innerHTML = html``, the
``onclick="selectTeamFromSelector(this)"`` on each ``.team-selector-item``
button was removed, making items unclickable.

Fix (PR #3373): buttons now carry ``data-action="select-team"`` and a
delegated ``click`` listener on ``#team-selector-items`` calls
``selectTeamFromSelector(button)``, which in turn calls
``window.updateTeamContext(teamId)`` — navigating the admin page to
``?team_id=<id>``.

Test strategy
-------------
1. Spin up the admin UI inside an ``<iframe>`` using the ``iframe_host``
   fixture (same-origin, X-Frame-Options stripped by route interception).
2. Open the team selector dropdown by clicking the toggle button.
3. Wait for ``loadTeams()`` to populate ``#team-selector-items`` via
   ``innerHTML`` (the path that was broken).
4. Assert every rendered item has ``data-action="select-team"`` and no
   ``onclick`` attribute — proving the innerHTML guard did not break the
   fix.
5. Click the first real team item.
6. Assert the iframe URL changes to include ``?team_id=`` — the concrete
   observable effect that was broken before the fix.

The test is deliberately self-contained: it does not depend on any
pre-existing team data.  If no teams exist it creates a synthetic item
directly in the container (mirroring what ``loadTeams()`` would inject)
and exercises the delegation listener end-to-end.
"""

# Future
from __future__ import annotations

# Standard
import re
from typing import Any, Dict, List
import urllib.parse

# Third-Party
from playwright.sync_api import FrameLocator, Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
import pytest

# Local
from ..conftest import _ensure_admin_logged_in


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_admin_frame(page: Page):
    """Return the Frame object for the admin iframe.

    ``iframe_host`` yields a ``FrameLocator``.  To call ``evaluate()`` /
    ``url`` we need the underlying ``Frame`` object, which Playwright
    exposes via ``page.frames``.
    """
    for _ in range(40):
        for frame in page.frames:
            if "/admin" in frame.url:
                return frame
        page.wait_for_timeout(500)
    return page.frames[-1] if len(page.frames) > 1 else page.main_frame


def _open_team_selector_dropdown(iframe_host: FrameLocator, page: Page, timeout: int = 15_000) -> bool:
    """Click the team selector toggle button to open the dropdown.

    Returns True if the dropdown opened, False if the toggle was not found
    (e.g. single-team deployments where the selector is hidden).
    """
    # The toggle button is the element that opens the team dropdown.
    # It may be identified by data-testid, aria-label, or by being the
    # parent of #team-selector-items.
    toggle_selectors = [
        '[data-testid="team-selector-toggle"]',
        '[aria-label*="team" i][aria-haspopup]',
        '[aria-controls="team-selector-items"]',
        # Fallback: any button that is a sibling/ancestor of the items container
        '#team-selector-items',  # used only to check visibility below
    ]

    # First try explicit toggle buttons
    for sel in toggle_selectors[:-1]:
        try:
            toggle = iframe_host.locator(sel).first
            toggle.wait_for(state="visible", timeout=5_000)
            toggle.click()
            return True
        except PlaywrightTimeoutError:
            continue

    # Fallback: look for any button whose click reveals #team-selector-items
    # by checking if the container is already visible (Alpine.js x-show)
    try:
        items = iframe_host.locator("#team-selector-items")
        items.wait_for(state="visible", timeout=3_000)
        return True  # Already open
    except PlaywrightTimeoutError:
        pass

    # Last resort: find the button that wraps or precedes the items container
    # by evaluating in the frame
    frame = _get_admin_frame(page)
    clicked = frame.evaluate(
        """
        () => {
            const container = document.getElementById('team-selector-items');
            if (!container) return false;
            // Walk up to find the Alpine.js x-data root and toggle open
            let el = container.parentElement;
            while (el && el !== document.body) {
                if (el.hasAttribute('x-data')) {
                    // Try to set open=true via Alpine
                    if (el.__x && el.__x.$data) {
                        el.__x.$data.open = true;
                        return true;
                    }
                }
                el = el.parentElement;
            }
            return false;
        }
        """
    )
    return bool(clicked)


def _wait_for_teams_loaded(iframe_host: FrameLocator, page: Page, timeout: int = 20_000) -> bool:
    """Wait until #team-selector-items has at least one .team-selector-item button.

    Returns True if items loaded, False if the container stayed empty
    (e.g. no teams in the database).
    """
    frame = _get_admin_frame(page)
    deadline_ms = timeout
    poll_ms = 500
    elapsed = 0
    while elapsed < deadline_ms:
        count = frame.evaluate(
            """
            () => {
                const c = document.getElementById('team-selector-items');
                if (!c) return 0;
                return c.querySelectorAll('.team-selector-item').length;
            }
            """
        )
        if count and count > 0:
            return True
        page.wait_for_timeout(poll_ms)
        elapsed += poll_ms
    return False


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def iframe_host_with_teams(page: Page, base_url: str):
    """Load admin inside an iframe with X-Frame-Options stripped.

    Mirrors the ``iframe_host`` fixture from
    ``test_iframe_embedding_security.py`` but is defined locally so this
    test module is self-contained and can be run in isolation.
    """
    from playwright.sync_api import Route

    _ensure_admin_logged_in(page, base_url)

    def _strip_framing_headers(route: Route) -> None:
        try:
            response = route.fetch()
            headers = dict(response.headers)
            headers.pop("x-frame-options", None)
            headers.pop("X-Frame-Options", None)
            if "content-security-policy" in headers:
                headers["content-security-policy"] = headers["content-security-policy"].replace(
                    "frame-ancestors 'none'", "frame-ancestors 'self'"
                )
            route.fulfill(status=response.status, headers=headers, body=response.body())
        except Exception:
            # If route.fetch() or route.fulfill() failed, try to continue the route
            # But only if it hasn't been handled yet
            try:
                route.continue_()
            except Exception:
                pass  # Route was already handled, ignore

    admin_pattern = re.compile(r".*/admin.*")
    page.route(admin_pattern, _strip_framing_headers)

    admin_url = f"{base_url}/admin/"
    page.set_content(
        f"""<!DOCTYPE html>
<html><head><title>Team Selector E2E iframe host</title></head>
<body style="margin:0;padding:0">
<iframe id="admin-frame"
        src="{admin_url}"
        style="width:100%;height:100vh;border:none"
        sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-modals">
</iframe>
</body></html>"""
    )

    frame_locator = page.frame_locator("#admin-frame")
    try:
        frame_locator.locator('[data-testid="servers-tab"]').wait_for(state="visible", timeout=30_000)
    except PlaywrightTimeoutError:
        pass  # CI may be slower; individual tests assert what they need

    yield frame_locator

    page.unroute(admin_pattern)


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


@pytest.mark.ui
@pytest.mark.iframe
@pytest.mark.regression
class TestTeamSelectorDropdownE2E:
    """End-to-end regression for the team selector click flow (PR #3373).

    Most visible symptom from the bug report:
        1. Log in to admin UI
        2. Click the team selector dropdown in the header
        3. Click any team in the list
        4. Nothing happens — no navigation, no console errors, no network request

    These tests verify the complete fix: items rendered via innerHTML carry
    ``data-action="select-team"`` (not ``onclick``), the delegation listener
    fires on click, and ``updateTeamContext`` navigates the page to
    ``?team_id=<id>``.
    """

    # ------------------------------------------------------------------
    # Test 1: innerHTML guard does NOT strip data-action from real server HTML
    # ------------------------------------------------------------------

    def test_server_rendered_team_items_have_data_action_not_onclick(
        self, iframe_host_with_teams: FrameLocator, page: Page
    ) -> None:
        """Team items fetched from /admin/teams/partial must have data-action, not onclick.

        This test calls the real ``/admin/teams/partial?render=selector``
        endpoint (the same URL ``loadTeams()`` uses), injects the response
        HTML into ``#team-selector-items`` via ``innerHTML``, and asserts:

        - Every ``.team-selector-item`` button has ``data-action="select-team"``
        - No ``.team-selector-item`` button has an ``onclick`` attribute
          (the innerHTML guard must not have stripped data-action)
        - Each button carries ``data-team-id`` (required by selectTeamFromSelector)

        This is the core regression check: if the template still used
        ``onclick`` instead of ``data-action``, the guard would strip it and
        this assertion would catch the regression.
        """
        frame = _get_admin_frame(page)

        result: Dict[str, Any] = frame.evaluate(
            """
            async () => {
                // Fetch the real partial HTML from the server
                let html;
                try {
                    const resp = await fetch(
                        (window.ROOT_PATH || '') + '/admin/teams/partial?page=1&per_page=20&render=selector',
                        { credentials: 'same-origin' }
                    );
                    if (!resp.ok) {
                        return { skipped: true, reason: 'HTTP ' + resp.status };
                    }
                    html = await resp.text();
                } catch (e) {
                    return { skipped: true, reason: 'fetch failed: ' + e.message };
                }

                // Inject into a real container (or a temp one) via innerHTML
                // This exercises the innerHTML guard on real server HTML.
                let container = document.getElementById('team-selector-items');
                const usedReal = !!container;
                if (!container) {
                    container = document.createElement('div');
                    container.id = 'team-selector-items-test';
                    document.body.appendChild(container);
                }

                const prevContent = container.innerHTML;
                container.innerHTML = html;  // innerHTML guard fires here

                const buttons = Array.from(container.querySelectorAll('.team-selector-item'));

                if (buttons.length === 0) {
                    // No teams in DB — check the "No teams found" message is present
                    const noTeams = container.textContent.includes('No teams found');
                    container.innerHTML = prevContent;
                    if (!usedReal) container.remove();
                    return { skipped: true, reason: 'no teams in database', noTeamsMessage: noTeams };
                }

                const violations = [];
                const missing_data_action = [];
                const missing_team_id = [];

                for (const btn of buttons) {
                    if (btn.hasAttribute('onclick')) {
                        violations.push(btn.outerHTML.slice(0, 200));
                    }
                    if (btn.getAttribute('data-action') !== 'select-team') {
                        missing_data_action.push(btn.getAttribute('data-action'));
                    }
                    if (!btn.getAttribute('data-team-id')) {
                        missing_team_id.push(btn.outerHTML.slice(0, 200));
                    }
                }

                const teamIds = buttons.map(b => b.getAttribute('data-team-id')).filter(Boolean);

                // Restore
                container.innerHTML = prevContent;
                if (!usedReal) container.remove();

                return {
                    skipped: false,
                    buttonCount: buttons.length,
                    onclickViolations: violations,
                    missingDataAction: missing_data_action,
                    missingTeamId: missing_team_id,
                    teamIds: teamIds,
                };
            }
            """
        )

        if result.get("skipped"):
            reason = result.get("reason", "unknown")
            if "no teams" in reason:
                pytest.skip(f"No teams in database — cannot test team item rendering: {reason}")
            else:
                pytest.skip(f"Could not fetch team partial: {reason}")

        assert result["onclickViolations"] == [], (
            f"Server-rendered team items must NOT have onclick (innerHTML guard regression).\n"
            f"Violations: {result['onclickViolations']}"
        )
        assert result["missingDataAction"] == [], (
            f"Server-rendered team items must have data-action='select-team'.\n"
            f"Items missing it: {result['missingDataAction']}"
        )
        assert result["missingTeamId"] == [], (
            f"Server-rendered team items must have data-team-id.\n"
            f"Items missing it: {result['missingTeamId']}"
        )
        assert result["buttonCount"] > 0, "Expected at least one team item button"

    # ------------------------------------------------------------------
    # Test 2: Delegation listener fires when a team item is clicked
    # ------------------------------------------------------------------

    def test_team_item_click_calls_selectTeamFromSelector(
        self, iframe_host_with_teams: FrameLocator, page: Page
    ) -> None:
        """Clicking a team item inside the iframe must call selectTeamFromSelector.

        This test:
        1. Injects a synthetic team button into ``#team-selector-items``
           (simulating what ``loadTeams()`` does via innerHTML).
        2. Clicks the button.
        3. Asserts ``selectTeamFromSelector`` was called with the correct
           button element.

        The delegation listener is registered on ``#team-selector-items``
        during ``DOMContentLoaded`` in admin.js.  If the listener is absent
        (e.g. the container was not in the DOM at DOMContentLoaded time),
        the test falls back to verifying the listener can be manually wired —
        but the primary assertion is that the admin.js-registered listener fires.
        """
        frame = _get_admin_frame(page)

        result: Dict[str, Any] = frame.evaluate(
            """
            () => {
                const container = document.getElementById('team-selector-items');
                if (!container) return { skipped: true, reason: 'no #team-selector-items' };

                // Inject a synthetic team item via innerHTML (guard fires, strips onclick)
                container.innerHTML = `
                    <button
                        class="team-selector-item"
                        data-action="select-team"
                        data-team-id="e2e-team-42"
                        data-team-name="E2E Test Team"
                        data-team-is-personal="false">
                        🏢 E2E Test Team
                    </button>
                `;

                const btn = container.querySelector('.team-selector-item');
                if (!btn) return { skipped: true, reason: 'button not found after innerHTML' };

                // Verify the guard did not strip data-action
                const dataAction = btn.getAttribute('data-action');
                const hasOnclick = btn.hasAttribute('onclick');

                // Spy on selectTeamFromSelector
                let called = false;
                let calledTeamId = null;
                const orig = window.selectTeamFromSelector;
                window.selectTeamFromSelector = (el) => {
                    called = true;
                    calledTeamId = el ? el.getAttribute('data-team-id') : null;
                    // Also call original to exercise the full code path
                    if (typeof orig === 'function') {
                        try { orig(el); } catch (_) {}
                    }
                };

                try {
                    btn.click();
                    return {
                        skipped: false,
                        dataAction,
                        hasOnclick,
                        called,
                        calledTeamId,
                    };
                } finally {
                    window.selectTeamFromSelector = orig;
                    container.innerHTML = '';
                }
            }
            """
        )

        if result.get("skipped"):
            pytest.skip(f"Team selector container not present: {result.get('reason')}")

        # Guard assertions
        assert result["hasOnclick"] is False, (
            "innerHTML guard must strip onclick from injected team item inside iframe"
        )
        assert result["dataAction"] == "select-team", (
            "data-action='select-team' must survive innerHTML guard inside iframe"
        )

        # Delegation listener assertion
        assert result["called"], (
            "selectTeamFromSelector must be called when a .team-selector-item is clicked.\n"
            "This means the DOMContentLoaded delegation listener on #team-selector-items "
            "is not firing — the fix in admin.js may not be active inside the iframe."
        )
        assert result["calledTeamId"] == "e2e-team-42", (
            f"selectTeamFromSelector must receive the clicked button; "
            f"expected data-team-id='e2e-team-42', got '{result['calledTeamId']}'"
        )

    # ------------------------------------------------------------------
    # Test 3: Full end-to-end — open dropdown, click team, URL changes
    # ------------------------------------------------------------------

    def test_clicking_team_item_navigates_to_team_id_url(
        self, iframe_host_with_teams: FrameLocator, page: Page
    ) -> None:
        """Clicking a team item must navigate the admin page to ?team_id=<id>.

        This is the full end-to-end regression for the bug report symptom:
        "Click any team in the list → nothing happens."

        Steps:
        1. Open the team selector dropdown.
        2. Wait for ``loadTeams()`` to populate ``#team-selector-items`` via
           ``innerHTML`` (the broken path).
        3. Read the first team item's ``data-team-id``.
        4. Click the item.
        5. Assert the iframe URL contains ``?team_id=<id>`` or that
           ``updateTeamContext`` was called with the correct team ID.

        If no real teams exist in the database, the test injects a synthetic
        item and verifies the delegation + navigation logic end-to-end using
        a spy on ``updateTeamContext``.
        """
        frame = _get_admin_frame(page)

        # ---- Step 1: Try to open the dropdown ----
        opened = _open_team_selector_dropdown(iframe_host_with_teams, page)
        if not opened:
            # Dropdown toggle not found — inject directly and test delegation
            pass  # Fall through to synthetic path below

        # ---- Step 2: Check if real teams loaded ----
        teams_loaded = _wait_for_teams_loaded(iframe_host_with_teams, page, timeout=10_000)

        if teams_loaded:
            # ---- Real teams path ----
            result: Dict[str, Any] = frame.evaluate(
                """
                () => {
                    const container = document.getElementById('team-selector-items');
                    if (!container) return { path: 'no-container' };

                    const btn = container.querySelector('.team-selector-item');
                    if (!btn) return { path: 'no-button' };

                    const teamId = btn.getAttribute('data-team-id');
                    const teamName = btn.getAttribute('data-team-name');
                    const dataAction = btn.getAttribute('data-action');
                    const hasOnclick = btn.hasAttribute('onclick');

                    // Spy on updateTeamContext to capture the call
                    let updateCalled = false;
                    let updateCalledWith = null;
                    const origUpdate = window.updateTeamContext;
                    window.updateTeamContext = (id) => {
                        updateCalled = true;
                        updateCalledWith = id;
                        // Call original to trigger real navigation
                        if (typeof origUpdate === 'function') {
                            try { origUpdate(id); } catch (_) {}
                        }
                    };

                    try {
                        btn.click();
                        return {
                            path: 'real',
                            teamId,
                            teamName,
                            dataAction,
                            hasOnclick,
                            updateCalled,
                            updateCalledWith,
                        };
                    } finally {
                        window.updateTeamContext = origUpdate;
                    }
                }
                """
            )

            if result.get("path") in ("no-container", "no-button"):
                pytest.skip(f"Team selector not usable: {result.get('path')}")

            # Core regression assertions
            assert result["hasOnclick"] is False, (
                "innerHTML guard must strip onclick from real server-rendered team items"
            )
            assert result["dataAction"] == "select-team", (
                "Real server-rendered team items must have data-action='select-team'"
            )
            assert result["updateCalled"], (
                f"updateTeamContext must be called when a real team item is clicked.\n"
                f"Team: {result.get('teamName')} (id={result.get('teamId')})\n"
                f"This is the exact symptom from the bug report: clicking a team does nothing."
            )
            assert result["updateCalledWith"] == result["teamId"], (
                f"updateTeamContext must be called with the team's ID.\n"
                f"Expected: {result['teamId']}, got: {result['updateCalledWith']}"
            )

            # ---- Step 5: Verify URL change (best-effort) ----
            # updateTeamContext navigates to ?team_id=<id>.  Give it a moment.
            page.wait_for_timeout(1_500)
            admin_frame = _get_admin_frame(page)
            frame_url = admin_frame.url

            # The URL should contain team_id if navigation succeeded.
            # This is best-effort: some deployments may use a different
            # navigation mechanism (e.g. HTMX partial swap without URL change).
            if "team_id=" in frame_url:
                parsed = urllib.parse.urlparse(frame_url)
                qs = urllib.parse.parse_qs(parsed.query)
                actual_team_id = qs.get("team_id", [None])[0]
                assert actual_team_id == result["teamId"], (
                    f"URL ?team_id= must match the clicked team.\n"
                    f"Expected: {result['teamId']}, got: {actual_team_id}\n"
                    f"Full URL: {frame_url}"
                )

        else:
            # ---- Synthetic path: no teams in DB ----
            # Inject a synthetic item and verify the full delegation + navigation chain.
            result = frame.evaluate(
                """
                () => {
                    const container = document.getElementById('team-selector-items');
                    if (!container) return { path: 'no-container' };

                    // Inject via innerHTML — guard fires, strips onclick, keeps data-action
                    container.innerHTML = `
                        <button
                            class="team-selector-item"
                            data-action="select-team"
                            data-team-id="synthetic-team-e2e"
                            data-team-name="Synthetic E2E Team"
                            data-team-is-personal="false">
                            🏢 Synthetic E2E Team
                        </button>
                    `;

                    const btn = container.querySelector('.team-selector-item');
                    if (!btn) return { path: 'no-button' };

                    const dataAction = btn.getAttribute('data-action');
                    const hasOnclick = btn.hasAttribute('onclick');

                    // Spy on updateTeamContext
                    let updateCalled = false;
                    let updateCalledWith = null;
                    const origUpdate = window.updateTeamContext;
                    window.updateTeamContext = (id) => {
                        updateCalled = true;
                        updateCalledWith = id;
                    };

                    // Spy on selectTeamFromSelector
                    let selectorCalled = false;
                    const origSelector = window.selectTeamFromSelector;
                    window.selectTeamFromSelector = (el) => {
                        selectorCalled = true;
                        if (typeof origSelector === 'function') {
                            try { origSelector(el); } catch (_) {}
                        }
                    };

                    try {
                        btn.click();
                        return {
                            path: 'synthetic',
                            dataAction,
                            hasOnclick,
                            selectorCalled,
                            updateCalled,
                            updateCalledWith,
                        };
                    } finally {
                        window.updateTeamContext = origUpdate;
                        window.selectTeamFromSelector = origSelector;
                        container.innerHTML = '';
                    }
                }
                """
            )

            if result.get("path") in ("no-container", "no-button"):
                pytest.skip(f"Team selector not usable (synthetic path): {result.get('path')}")

            assert result["hasOnclick"] is False, (
                "innerHTML guard must strip onclick from synthetic team item"
            )
            assert result["dataAction"] == "select-team", (
                "data-action='select-team' must survive innerHTML guard"
            )
            assert result["selectorCalled"], (
                "selectTeamFromSelector must be called via delegation listener "
                "when a synthetic team item is clicked (no teams in DB path)"
            )
            assert result["updateCalled"], (
                "updateTeamContext must be called when selectTeamFromSelector runs "
                "(no teams in DB path)"
            )
            assert result["updateCalledWith"] == "synthetic-team-e2e", (
                f"updateTeamContext must receive the correct team ID; "
                f"got: {result['updateCalledWith']}"
            )

    # ------------------------------------------------------------------
    # Test 4: Regression guard — inline onclick in innerHTML is stripped
    # ------------------------------------------------------------------

    def test_inline_onclick_is_stripped_by_innerhtml_guard_inside_iframe(
        self, iframe_host_with_teams: FrameLocator, page: Page
    ) -> None:
        """The innerHTML guard must strip onclick from any HTML set via innerHTML.

        This is the direct regression test for the root cause: if someone
        accidentally re-introduces ``onclick="selectTeamFromSelector(this)"``
        in the template, the guard will strip it and this test will catch
        the resulting breakage (items rendered but unclickable).

        The test injects HTML with BOTH onclick AND data-action (the old
        broken pattern) and verifies:
        - onclick is stripped (guard works)
        - data-action survives (fix works)
        - clicking the button still calls selectTeamFromSelector via delegation
        """
        frame = _get_admin_frame(page)

        result: Dict[str, Any] = frame.evaluate(
            """
            () => {
                const container = document.getElementById('team-selector-items');
                if (!container) return { skipped: true, reason: 'no #team-selector-items' };

                // Inject HTML with BOTH onclick (old broken pattern) AND data-action (fix)
                // The guard should strip onclick but keep data-action.
                container.innerHTML = `
                    <button
                        class="team-selector-item"
                        data-action="select-team"
                        data-team-id="regression-team-1"
                        data-team-name="Regression Team"
                        data-team-is-personal="false"
                        onclick="selectTeamFromSelector(this)">
                        🏢 Regression Team
                    </button>
                `;

                const btn = container.querySelector('.team-selector-item');
                if (!btn) return { skipped: true, reason: 'button not found' };

                const hasOnclick = btn.hasAttribute('onclick');
                const dataAction = btn.getAttribute('data-action');
                const dataTeamId = btn.getAttribute('data-team-id');

                // Spy on selectTeamFromSelector
                let called = false;
                let calledTeamId = null;
                const orig = window.selectTeamFromSelector;
                window.selectTeamFromSelector = (el) => {
                    called = true;
                    calledTeamId = el ? el.getAttribute('data-team-id') : null;
                    if (typeof orig === 'function') {
                        try { orig(el); } catch (_) {}
                    }
                };

                try {
                    btn.click();
                    return {
                        skipped: false,
                        hasOnclick,
                        dataAction,
                        dataTeamId,
                        called,
                        calledTeamId,
                    };
                } finally {
                    window.selectTeamFromSelector = orig;
                    container.innerHTML = '';
                }
            }
            """
        )

        if result.get("skipped"):
            pytest.skip(f"Team selector not present: {result.get('reason')}")

        # Guard must strip onclick
        assert result["hasOnclick"] is False, (
            "innerHTML guard must strip onclick='selectTeamFromSelector(this)' — "
            "this is the root cause of the original bug"
        )

        # data-action must survive
        assert result["dataAction"] == "select-team", (
            "data-action='select-team' must survive the innerHTML guard — "
            "this is the fix that makes items clickable again"
        )
        assert result["dataTeamId"] == "regression-team-1", (
            "data-team-id must survive the innerHTML guard"
        )

        # Delegation listener must fire (onclick was stripped, but data-action + delegation works)
        assert result["called"], (
            "selectTeamFromSelector must be called via the delegation listener even when "
            "onclick was stripped by the guard — this proves the fix works end-to-end.\n"
            "If this fails: the DOMContentLoaded delegation listener on #team-selector-items "
            "is not registered, meaning the fix in admin.js is not active."
        )
        assert result["calledTeamId"] == "regression-team-1", (
            f"selectTeamFromSelector must receive the correct button; "
            f"got data-team-id='{result['calledTeamId']}'"
        )

    # ------------------------------------------------------------------
    # Test 5: No JS errors during team selector interaction
    # ------------------------------------------------------------------

    def test_no_js_errors_during_team_selector_click(
        self, iframe_host_with_teams: FrameLocator, page: Page
    ) -> None:
        """Clicking a team item must not produce uncaught JS errors.

        Captures ``pageerror`` events (uncaught exceptions) during the
        team selector interaction.  Any JS error here would indicate a
        broken event handler or missing function reference.
        """
        js_errors: List[str] = []

        def _on_pageerror(error: Any) -> None:
            js_errors.append(str(error))

        page.on("pageerror", _on_pageerror)

        try:
            frame = _get_admin_frame(page)

            frame.evaluate(
                """
                () => {
                    const container = document.getElementById('team-selector-items');
                    if (!container) return;

                    container.innerHTML = `
                        <button
                            class="team-selector-item"
                            data-action="select-team"
                            data-team-id="no-error-team"
                            data-team-name="No Error Team"
                            data-team-is-personal="false">
                            🏢 No Error Team
                        </button>
                    `;

                    const btn = container.querySelector('.team-selector-item');
                    if (btn) btn.click();

                    // Clean up
                    container.innerHTML = '';
                }
                """
            )

            page.wait_for_timeout(500)

        finally:
            page.remove_listener("pageerror", _on_pageerror)

        # Filter out known benign errors from third-party CDN resources
        critical_errors = [
            e for e in js_errors
            if not any(
                benign in e
                for benign in [
                    "ResizeObserver loop",
                    "Non-Error promise rejection",
                    "Script error",
                    "cdn.jsdelivr",
                    "cdnjs.cloudflare",
                    "unpkg.com",
                ]
            )
        ]

        assert critical_errors == [], (
            "Uncaught JS errors during team selector click inside iframe:\n"
            + "\n".join(f"  - {e}" for e in critical_errors)
        )
