# -*- coding: utf-8 -*-
"""Location: ./tests/playwright/test_oauth_callback_fetch_tools.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Browser regression tests for the OAuth callback popup flow.

Three tests cover the entire surface:

1. **Success** – clicking "Fetch Tools" completes the flow: the popup closes,
   ``window.opener.postMessage`` is called once with the correct payload, and
   ``/mcp-auth`` shows "✅ Tools Fetched!".

2. **Failure + user closes popup** – ``fetch-tools`` fails, the error panel
   appears in the popup, and the user manually closes it.  ``_watchPopup()``
   on ``/mcp-auth`` detects the closed popup and resets the page back to
   "⏳ Pending Authorization…" with the "Authorize via OAuth" button re-enabled,
   so the user can start a fresh OAuth flow.

3. **Failure + popup stays open** – ``fetch-tools`` fails but the user leaves
   the popup open and switches focus back to ``/mcp-auth``.  The ``focus``
   listener on ``/mcp-auth`` detects the return and re-enables the
   "Authorize via OAuth" button immediately — no popup close required — so the
   user can open a new OAuth popup and retry from the opener page.

No running gateway is required.  Both the callback HTML and the
``/oauth/fetch-tools`` API are served by ``context.route`` stubs.

Run with:
    TEST_BASE_URL=http://localhost:8080 pytest -p playwright \\
        tests/playwright/test_oauth_callback_fetch_tools.py -v
"""

# Standard
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import os
from unittest.mock import AsyncMock, Mock, patch

# Third-Party
from playwright.sync_api import BrowserContext, expect, Page
import pytest
from sqlalchemy.orm import Session

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ORIGIN = "http://oauth-callback-test.local"
_OPENER_URL = f"{_ORIGIN}/mcp-auth"
_CALLBACK_URL = f"{_ORIGIN}/oauth/callback"
_FETCH_TOOLS_URL = f"{_ORIGIN}/oauth/fetch-tools/test-gateway"
_GATEWAY_ID = "test-gateway"
_GATEWAY_NAME = "Test Gateway"
_SUCCESS_MESSAGE = {
    "type": "oauth_callback",
    "status": "success",
    "gatewayId": _GATEWAY_ID,
    "gatewayName": _GATEWAY_NAME,
}

# Milliseconds to pause between steps when running headed.
# Set OAUTH_TEST_DELAY=1200 (or any value) to slow things down for observation.
# Defaults to 0 so CI runs are unaffected.
_STEP_DELAY_MS: int = int(os.getenv("OAUTH_TEST_DELAY", "0"))

# ---------------------------------------------------------------------------
# Opener page HTML  (/mcp-auth)
# ---------------------------------------------------------------------------
# Simulates the admin UI waiting for the OAuth popup to complete.
# - Shows "Pending Authorization…" initially.
# - Switches to "Tools Fetched!" when it receives a postMessage with
#   status == "success".
# - Resets back to "Pending Authorization…" when the popup closes without
#   sending a success message (_watchPopup interval).
# - Re-enables "Authorize via OAuth" immediately when the window regains
#   focus and the flow is not yet complete (window focus listener), so the
#   user can open a new OAuth popup without closing the old one.
# Exposed DOM ids used by tests:
#   #auth-status   — visible status heading
#   #auth-detail   — detail line (gateway name on success)
#   #auth-step     — secondary hint line
#   #open-btn      — button that opens the OAuth callback popup
_OPENER_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>MCP Auth</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 60px auto; max-width: 520px; text-align: center; }
    h1   { font-size: 1.4rem; }
    #auth-status { margin: 24px 0 8px; font-size: 1.6rem; font-weight: bold; }
    #auth-detail { color: #555; min-height: 1.6em; font-size: 0.95rem; }
    #auth-step   { margin-top: 6px; font-size: 0.85rem; color: #888; min-height: 1.2em; }
    .pending     { color: #b45309; }
    .redirecting { color: #2563eb; }
    .success     { color: #059669; }
    button {
      margin-top: 28px; padding: 10px 24px; font-size: 1rem;
      background: #3b82f6; color: #fff; border: none;
      border-radius: 6px; cursor: pointer; transition: background 0.2s;
    }
    button:hover    { background: #2563eb; }
    button:disabled { opacity: 0.55; cursor: not-allowed; }
  </style>
</head>
<body>
  <h1>MCP Gateway Authorization</h1>
  <div id="auth-status" class="pending">⏳ Pending Authorization…</div>
  <div id="auth-detail">Click the button below to start OAuth and fetch tools.</div>
  <div id="auth-step"></div>
  <button id="open-btn" onclick="openPopup()">Authorize via OAuth</button>

  <script>
    window.__messages = [];
    var _popupRef = null;
    var _pollTimer = null;
    var _completed = false;

    // Reset /mcp-auth back to pending so the user can retry.
    function _resetToPending(hint) {
      var s = document.getElementById('auth-status');
      var d = document.getElementById('auth-detail');
      var t = document.getElementById('auth-step');
      var b = document.getElementById('open-btn');
      s.textContent = '⏳ Pending Authorization…';
      s.className = 'pending';
      d.textContent = 'Click the button below to start OAuth and fetch tools.';
      t.textContent = hint || 'The popup was closed before tools were fetched. Try again.';
      b.disabled = false;
      b.textContent = 'Authorize via OAuth';
    }

    // Poll every 300 ms to detect when the popup closes without sending success.
    function _watchPopup() {
      _pollTimer = setInterval(function() {
        if (_popupRef && _popupRef.closed) {
          clearInterval(_pollTimer);
          _pollTimer = null;
          if (!_completed) {
            _resetToPending('The popup was closed before tools were fetched. Try again.');
          }
        }
      }, 300);
    }

    // When this window regains focus and the flow is not yet complete,
    // re-enable the button so the user can start a new OAuth popup.
    window.addEventListener('focus', function() {
      if (!_completed) {
        _resetToPending('Focus returned — click the button to start a new OAuth flow.');
      }
    });

    window.addEventListener('message', function(event) {
      window.__messages.push(event.data);
      if (event.data && event.data.status === 'success') {
        _completed = true;
        if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; }
        var s = document.getElementById('auth-status');
        var d = document.getElementById('auth-detail');
        var t = document.getElementById('auth-step');
        var b = document.getElementById('open-btn');
        s.textContent = '✅ Tools Fetched!';
        s.className = 'success';
        d.textContent = 'Gateway: ' + (event.data.gatewayName || '') +
                        ' — authorization complete.';
        t.textContent = 'OAuth popup closed. Tools are now available.';
        b.disabled = true;
        b.textContent = '✅ Done';
      }
    });

    function openPopup() {
      var s = document.getElementById('auth-status');
      var d = document.getElementById('auth-detail');
      var t = document.getElementById('auth-step');
      var b = document.getElementById('open-btn');
      _completed = false;
      s.textContent = '🔄 Redirecting to OAuth provider…';
      s.className = 'redirecting';
      d.textContent = 'A popup window will open to complete authorization.';
      t.textContent = 'Step 1 of 2 — Complete sign-in in the popup, then fetch tools.';
      b.disabled = true;
      b.textContent = 'Waiting for popup…';
      _popupRef = window.open('""" + _CALLBACK_URL + """', '_blank', 'width=820,height=640');
      _watchPopup();
    }
  </script>
</body>
</html>"""

# ---------------------------------------------------------------------------
# Helpers rendered once per module
# ---------------------------------------------------------------------------


def _render_callback_html() -> str:
    """Render the legacy callback page by calling ``oauth_callback`` with mocked collaborators.

    Runs the async handler in a background thread so the sync Playwright event
    loop is not blocked.

    Returns:
        Decoded HTML body of the legacy admin UI success page.
    """
    # First-Party
    from mcpgateway.routers.oauth_router import oauth_callback

    gateway = Mock()
    gateway.id = _GATEWAY_ID
    gateway.name = _GATEWAY_NAME
    gateway.url = "https://mcp.example.com"
    gateway.oauth_config = {
        "client_id": "test-client",
        "authorization_url": "https://oauth.example.com/authorize",
        "token_url": "https://oauth.example.com/token",
    }
    gateway.ca_certificate = None
    gateway.client_cert = None
    gateway.client_key = None

    db = Mock(spec=Session)
    db.execute.return_value.scalar_one_or_none.return_value = gateway

    request = Mock()
    request.state = Mock()
    request.state.csp_nonce = "test-nonce"
    request.url = Mock()
    request.url.path = "/oauth/callback"
    request.headers = {}
    request.cookies = {}

    async def _run() -> str:
        with patch("mcpgateway.routers.oauth_router.OAuthManager") as manager_class:
            manager = Mock()
            manager.resolve_gateway_id_from_state = AsyncMock(return_value=_GATEWAY_ID)
            manager.complete_authorization_code_flow = AsyncMock(
                return_value={
                    "user_id": "user@example.com",
                    "expires_at": "2026-12-31T23:59:59Z",
                    "state_data": {"app_user_email": "user@example.com", "team_id": None},
                }
            )
            manager_class.return_value = manager
            with (
                patch("mcpgateway.routers.oauth_router.TokenStorageService"),
                patch("mcpgateway.routers.oauth_router._persist_learned_audience", new_callable=AsyncMock),
                patch("mcpgateway.utils.paths.resolve_root_path", return_value=""),
            ):
                response = await oauth_callback(
                    code="auth-code-123",
                    state="regular-state-abc123",
                    request=request,
                    db=db,
                )
        return response.body.decode()

    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(asyncio.run, _run()).result()


@pytest.fixture(scope="module")
def callback_html() -> str:
    """Rendered legacy callback page, shared by all tests in this module."""
    return _render_callback_html()


# ---------------------------------------------------------------------------
# Route stubs
# ---------------------------------------------------------------------------


class _RouteStub:
    """Registers context-level routes and controls ``fetch-tools`` behaviour.

    Attributes:
        calls: Number of POST requests received at ``/oauth/fetch-tools/<id>``.
    """

    def __init__(self, context: BrowserContext, html: str) -> None:
        self.calls: int = 0
        self._held: list = []
        self.behaviour = self._succeed
        self._html = html
        context.route(f"{_ORIGIN}/**", self._handle)

    def _handle(self, route) -> None:
        url = route.request.url
        if url == _OPENER_URL:
            route.fulfill(
                status=200,
                content_type="text/html; charset=utf-8",
                body=_OPENER_HTML.encode("utf-8"),
            )
        elif url == _CALLBACK_URL:
            # charset=utf-8 is required: emoji in the server-rendered HTML (✅, ⏳)
            # are encoded as UTF-8 bytes and must be decoded that way by Chromium.
            route.fulfill(status=200, content_type="text/html; charset=utf-8", body=self._html.encode("utf-8"))
        elif url == _FETCH_TOOLS_URL and route.request.method == "POST":
            self.calls += 1
            self.behaviour(route)
        else:
            route.fulfill(status=404, body="not found")

    # ---- behaviour presets ----

    @staticmethod
    def _succeed(route) -> None:
        route.fulfill(status=200, content_type="application/json", body=json.dumps({"message": "Fetched 3 tools", "success": True}))

    @staticmethod
    def _http_error(route) -> None:
        route.fulfill(status=500, content_type="application/json", body=json.dumps({"detail": "upstream server error"}))

    def _hold(self, route) -> None:
        self._held.append(route)

    def use_success(self) -> None:
        """Switch to success mode."""
        self.behaviour = self._succeed

    def use_http_error(self) -> None:
        """Switch to HTTP 500 mode."""
        self.behaviour = self._http_error

    def use_hold(self) -> None:
        """Hold all fetch-tools requests without responding."""
        self.behaviour = self._hold

    def release_held(self, succeed: bool = True) -> None:
        """Release all held routes with success or error."""
        for route in self._held:
            if succeed:
                self._succeed(route)
            else:
                self._http_error(route)
        self._held.clear()


@pytest.fixture()
def stub(context: BrowserContext, callback_html: str) -> _RouteStub:
    """Route stub bound to the browser context for one test."""
    return _RouteStub(context, callback_html)


# ---------------------------------------------------------------------------
# Helpers: popup and step pacing
# ---------------------------------------------------------------------------


def _open_popup(opener: Page) -> Page:
    """Click the 'Authorize via OAuth' button on the /mcp-auth opener page.

    Uses the ``#open-btn`` button already wired up in ``_OPENER_HTML``.
    After the click the button transitions to "🔄 Redirecting…" — a pause lets
    the observer read that state before the popup steals focus.

    Returns:
        The popup ``Page`` after it has finished loading.
    """
    with opener.expect_popup() as info:
        opener.click("#open-btn")
    if _STEP_DELAY_MS > 0:
        opener.wait_for_timeout(_STEP_DELAY_MS)
    popup = info.value
    popup.wait_for_load_state("domcontentloaded")
    return popup


def _pause(page: Page, label: str) -> None:
    """Pause for ``_STEP_DELAY_MS`` milliseconds and print *label* to stdout.

    Has no effect (and no output) when ``_STEP_DELAY_MS`` is 0, so CI runs
    are not slowed down. Pass ``--headed`` and set ``OAUTH_TEST_DELAY=1200``
    to watch each step at a comfortable pace.

    Args:
        page: Any live ``Page`` in the current test (used for the timeout call).
        label: Short description of the step, printed as ``[STEP] <label>``.
    """
    if _STEP_DELAY_MS > 0:
        print(f"\n[STEP] {label}", flush=True)
        page.wait_for_timeout(_STEP_DELAY_MS)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.ui
@pytest.mark.regression
class TestOAuthCallbackFetchTools:
    """Full OAuth callback popup flow — success and both failure branches."""

    def test_success_popup_closes_and_opener_updated(self, page: Page, stub: _RouteStub) -> None:
        """Success: popup closes, opener receives one postMessage, /mcp-auth shows 'Tools Fetched!'.

        The fetch-tools response is held until the loading indicator is visible,
        then released.  This makes the loading state observable before the popup
        closes, giving confidence the full success path ran.
        """
        _pause(page, "Navigating to /mcp-auth — starts in pending state")
        page.goto(_OPENER_URL)
        page.bring_to_front()
        expect(page.locator("#auth-status")).to_contain_text("Pending Authorization")

        _pause(page, "Opening OAuth callback popup (fetch will be held for spinner check)")
        stub.use_hold()
        popup = _open_popup(page)

        _pause(popup, "Clicking 'Fetch Tools from MCP Server' in the popup window")
        popup.bring_to_front()
        expect(popup.locator("#fetch-tools-btn")).to_be_enabled()
        popup.evaluate("document.getElementById('fetch-tools-btn').scrollIntoView({block:'center'})")
        popup.evaluate("document.getElementById('fetch-tools-btn').style.outline='3px solid #f97316'")
        _pause(popup, "Button highlighted — clicking now")
        popup.click("#fetch-tools-btn")
        popup.evaluate("document.getElementById('fetch-tools-btn').style.outline=''")

        # Confirm the loading indicator appears before the response lands.
        popup.wait_for_function(
            "document.getElementById('fetch-tools-btn').textContent.includes('Fetching Tools')",
            timeout=5000,
        )
        _pause(popup, "Loading spinner visible — releasing fetch response")
        stub.release_held(succeed=True)

        # Popup must close and the opener must show success.
        popup.wait_for_event("close", timeout=10000)
        assert popup.is_closed()

        page.wait_for_function("window.__messages.length > 0", timeout=5000)
        messages = page.evaluate("window.__messages")
        assert len(messages) == 1
        assert messages[0]["type"] == "oauth_callback"
        assert messages[0]["status"] == "success"
        assert messages[0]["gatewayId"] == _GATEWAY_ID
        assert messages[0]["gatewayName"] == _GATEWAY_NAME

        expect(page.locator("#auth-status")).to_contain_text("Tools Fetched!", timeout=5000)
        expect(page.locator("#auth-detail")).to_contain_text(_GATEWAY_NAME)
        _pause(page, "All assertions passed — OAuth flow complete")

    def test_failure_user_closes_popup_mcp_auth_resets_to_pending(self, page: Page, stub: _RouteStub) -> None:
        """Fetch fails, user closes popup: /mcp-auth resets to pending so OAuth can restart.

        Scenario:
          1. ``fetch-tools`` returns HTTP 500.
          2. The error panel appears inside the popup.
          3. The user closes the popup manually.
          4. ``_watchPopup()`` on ``/mcp-auth`` fires, resets the page back to
             "⏳ Pending Authorization…", and re-enables "Authorize via OAuth".
          5. No postMessage was delivered to the opener.
        """
        _pause(page, "Navigating to /mcp-auth")
        page.goto(_OPENER_URL)
        page.bring_to_front()
        expect(page.locator("#auth-status")).to_contain_text("Pending Authorization")

        # Hold the request so we can observe the spinner before releasing as error.
        stub.use_hold()
        _pause(page, "Opening OAuth callback popup")
        popup = _open_popup(page)

        _pause(popup, "Clicking 'Fetch Tools' in the popup window — will fail after spinner")
        popup.bring_to_front()
        expect(popup.locator("#fetch-tools-btn")).to_be_enabled()
        popup.evaluate("document.getElementById('fetch-tools-btn').scrollIntoView({block:'center'})")
        popup.evaluate("document.getElementById('fetch-tools-btn').style.outline='3px solid #f97316'")
        _pause(popup, "Button highlighted — clicking now")
        popup.click("#fetch-tools-btn")
        popup.evaluate("document.getElementById('fetch-tools-btn').style.outline=''")

        popup.wait_for_function(
            "document.getElementById('fetch-tools-btn').textContent.includes('Fetching Tools')",
            timeout=5000,
        )
        _pause(popup, "Spinner visible — releasing as HTTP 500")
        stub.use_http_error()
        stub.release_held(succeed=False)

        # Error panel appears; popup stays open.
        expect(popup.locator("#fetch-status")).to_contain_text("Failed to Fetch Tools", timeout=10000)
        assert not popup.is_closed()
        assert page.evaluate("window.__messages") == []

        # User closes the popup without completing the flow.
        _pause(popup, "User closes the popup")
        popup.close()

        # _watchPopup() detects the closed popup and resets /mcp-auth.
        expect(page.locator("#auth-status")).to_contain_text("Pending Authorization", timeout=2000)
        expect(page.locator("#open-btn")).to_be_enabled()
        expect(page.locator("#auth-step")).to_contain_text("Try again")
        _pause(page, "/mcp-auth reset — user can click 'Authorize via OAuth' to retry")

    def test_failure_popup_stays_open_focus_back_enables_oauth_button(self, page: Page, stub: _RouteStub) -> None:
        """Fetch fails, popup stays open: returning focus to /mcp-auth re-enables the OAuth button.

        Scenario:
          1. ``fetch-tools`` returns HTTP 500.
          2. The error panel and "Retry Fetch Tools" button appear in the popup.
          3. The popup is NOT closed — the user switches focus back to /mcp-auth.
          4. The ``focus`` listener on /mcp-auth fires and immediately re-enables
             the "Authorize via OAuth" button (``_completed`` is still false).
          5. The user can click the button to open a new OAuth popup and retry
             — the old popup is still open in the background.
          6. No postMessage was delivered to the opener at any point.
        """
        _pause(page, "Navigating to /mcp-auth")
        page.goto(_OPENER_URL)
        page.bring_to_front()
        expect(page.locator("#auth-status")).to_contain_text("Pending Authorization")

        stub.use_http_error()
        _pause(page, "Opening OAuth callback popup (fetch will fail immediately)")
        popup = _open_popup(page)

        _pause(popup, "Clicking 'Fetch Tools' in the popup window — fetch will fail")
        popup.bring_to_front()
        expect(popup.locator("#fetch-tools-btn")).to_be_enabled()
        popup.evaluate("document.getElementById('fetch-tools-btn').scrollIntoView({block:'center'})")
        popup.evaluate("document.getElementById('fetch-tools-btn').style.outline='3px solid #f97316'")
        _pause(popup, "Button highlighted — clicking now")
        popup.click("#fetch-tools-btn")
        popup.evaluate("document.getElementById('fetch-tools-btn').style.outline=''")

        # Error panel and retry button appear; popup stays open.
        expect(popup.locator("#fetch-status")).to_contain_text("Failed to Fetch Tools", timeout=10000)
        expect(popup.locator("#fetch-tools-btn")).to_contain_text("Retry Fetch Tools", timeout=5000)
        expect(popup.locator("#fetch-tools-btn")).to_be_enabled()
        assert not popup.is_closed()

        # No postMessage reached the opener.
        page.wait_for_timeout(300)
        assert page.evaluate("window.__messages") == []

        # User switches focus back to /mcp-auth.  bring_to_front() switches the
        # active tab but does not dispatch a DOM focus event in headless Chromium,
        # so we fire it explicitly.  This mirrors what happens in headed mode when
        # the OS delivers a real focus event to the window.
        _pause(page, "Returning focus to /mcp-auth — focus listener will re-enable the button")
        page.bring_to_front()
        page.evaluate("window.dispatchEvent(new Event('focus'))")
        _pause(page, "Focus on /mcp-auth — clicking 'Authorize via OAuth' will start a new flow")

        # /mcp-auth must reset to pending with the button re-enabled — popup still open.
        expect(page.locator("#auth-status")).to_contain_text("Pending Authorization", timeout=2000)
        expect(page.locator("#open-btn")).to_be_enabled()
        page.evaluate("document.getElementById('open-btn').scrollIntoView({block:'center'})")
        page.evaluate("document.getElementById('open-btn').style.outline='3px solid #f97316'")
        _pause(page, "Button highlighted — user would click 'Authorize via OAuth' here to start a new flow")
        page.evaluate("document.getElementById('open-btn').style.outline=''")
        assert not popup.is_closed()
        _pause(page, "Old popup still alive in background — fresh OAuth flow ready to start")
