# -*- coding: utf-8 -*-
"""Location: ./tests/playwright/test_oauth_browser_binding.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Verify real cross-site OAuth cookie delivery and browser isolation.
"""

# Standard
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlparse

# Third-Party
from playwright.sync_api import Browser, BrowserContext, expect
import pytest

# Local
from tests.helpers.oauth_binding import binding_environment, BindingEnvironment

pytestmark = [pytest.mark.ui, pytest.mark.playwright_security_e2e]


@pytest.fixture(params=["", "/forge"])
def environment(tmp_path: Path, request: pytest.FixtureRequest) -> Iterator[BindingEnvironment]:
    """Provide HTTPS gateway and provider sites with an optional application root."""
    with binding_environment(tmp_path, request.param) as environment:
        yield environment


def browser_context(browser: Browser, environment: BindingEnvironment, authenticated: bool = True) -> BrowserContext:
    """Create an isolated browser context with optional caller authentication."""
    context = browser.new_context(ignore_https_errors=True)
    if authenticated:
        context.add_cookies([{"name": "jwt_token", "value": environment.token, "url": environment.base_url + "/", "secure": True, "httpOnly": True, "sameSite": "Lax"}])
    return context


def test_top_level_get_and_popup(browser: Browser, environment: BindingEnvironment) -> None:
    """Deliver host-only binding cookies across sites in redirects and popups."""
    context = browser_context(browser, environment)
    callbacks = []
    context.on("request", lambda request: callbacks.append(request.all_headers()) if urlparse(request.url).path.endswith("/oauth/callback") else None)
    responses = []
    context.on("response", lambda response: responses.append(response.all_headers()) if urlparse(response.url).path.endswith("/oauth/callback") else None)
    initiations = []
    context.on("response", lambda response: initiations.append(response.all_headers()) if "/oauth/authorize/" in urlparse(response.url).path else None)
    try:
        for popup in (False, True):
            page = context.new_page()
            if popup:
                page.goto(environment.base_url + "/health")
                page.evaluate("""() => {
                    window.oauthMessages = [];
                    window.addEventListener('message', event => { if (event.origin === location.origin) { window.oauthMessages.push(event.data); document.body.dataset.oauthStatus = event.data.status; } });
                    const button = document.createElement('button'); button.id = 'open-oauth'; button.textContent = 'Authorize'; document.body.appendChild(button);
                }""")
                page.locator("#open-oauth").evaluate(
                    "(button, url) => button.onclick = () => window.open(url, 'oauth')", environment.base_url + f"/oauth/authorize/{environment.gateway_id}?popup=true"
                )
                with page.expect_popup() as opened:
                    page.locator("#open-oauth").click()
                authorization_page = opened.value
                authorization_page.wait_for_url(environment.provider_url + "/authorize**")
            else:
                authorization_page = page
                authorization_page.goto(environment.base_url + f"/oauth/authorize/{environment.gateway_id}")
            cookies = [cookie for cookie in context.cookies() if cookie["name"].startswith("oauth_bind_")]
            assert len(cookies) == 1
            assert "Domain=" not in initiations[-1]["set-cookie"]
            cookie = cookies[0]
            assert cookie["httpOnly"] and cookie["secure"] and cookie["sameSite"] == "Lax"
            assert cookie["domain"] == "127.0.0.1"
            assert cookie["path"] == urlparse(environment.base_url).path + "/oauth/callback"
            with authorization_page.expect_response(lambda response: urlparse(response.url).path.endswith("/oauth/callback")) as callback:
                authorization_page.locator("#consent").click()
            assert callback.value.status == 200
            assert cookie["name"] in callbacks[-1].get("cookie", "")
            assert not any(item["name"].startswith("oauth_bind_") for item in context.cookies())
            assert "Domain=" not in responses[-1]["set-cookie"]
            if popup:
                expect(page.locator("body")).to_have_attribute("data-oauth-status", "success")
                assert page.evaluate("window.oauthMessages") == [{"type": "oauth_callback", "status": "success", "gatewayId": environment.gateway_id, "gatewayName": "binding-provider"}]
            page.close()
        assert environment.exchanges == ["attacker", "attacker"]
    finally:
        context.close()


def test_victim_browser_rejected(browser: Browser, environment: BindingEnvironment) -> None:
    """Reject the copied authorization URL after consent in another browser context."""
    attacker = browser_context(browser, environment)
    victim = browser_context(browser, environment, False)
    try:
        page = attacker.new_page()
        page.goto(environment.base_url + f"/oauth/authorize/{environment.gateway_id}?popup=true")
        authorization_url = page.url + "&identity=victim"
        victim_page = victim.new_page()
        assert not victim.cookies()
        victim_page.goto(authorization_url)
        with victim_page.expect_response(lambda response: urlparse(response.url).path.endswith("/oauth/callback")) as callback:
            victim_page.locator("#consent").click()
        assert callback.value.status == 400
        assert environment.exchanges == []
        assert not any(cookie["name"].startswith("oauth_bind_") for cookie in victim.cookies())
    finally:
        victim.close()
        attacker.close()


def test_parallel_tabs_keep_independent_bindings(browser: Browser, environment: BindingEnvironment) -> None:
    """Complete two transactions without overwriting either browser-binding cookie."""
    context = browser_context(browser, environment)
    try:
        pages = [context.new_page(), context.new_page()]
        for page in pages:
            page.goto(environment.base_url + f"/oauth/authorize/{environment.gateway_id}?popup=true")
        cookies = [cookie for cookie in context.cookies() if cookie["name"].startswith("oauth_bind_")]
        assert len(cookies) == 2 and cookies[0]["name"] != cookies[1]["name"]
        for index, page in enumerate(pages):
            with page.expect_response(lambda response: urlparse(response.url).path.endswith("/oauth/callback")) as callback:
                page.locator("#consent").click()
            assert callback.value.status == 200
            assert len([cookie for cookie in context.cookies() if cookie["name"].startswith("oauth_bind_")]) == 1 - index
        assert environment.exchanges == ["attacker", "attacker"]
    finally:
        context.close()
