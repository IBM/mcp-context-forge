# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/e2e/test_oauth_browser_binding.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Exercise OAuth browser binding against a running gateway.
"""

# Standard
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import parse_qs, urlparse

# Third-Party
import httpx
import pytest

# Local
from tests.helpers.oauth_binding import binding_environment, BindingEnvironment

pytestmark = pytest.mark.e2e


@pytest.fixture
def environment(tmp_path: Path) -> Iterator[BindingEnvironment]:
    """Provide isolated gateway and provider servers."""
    with binding_environment(tmp_path) as environment:
        yield environment


def callback_parameters(response: httpx.Response, code: str = "attacker") -> dict[str, str]:
    """Extract callback parameters from a real initiation response."""
    return {"state": parse_qs(urlparse(response.headers["location"]).query)["state"][0], "code": code}


def test_same_browser_and_replay(environment: BindingEnvironment) -> None:
    """Store the correct identity once and use it through production token lookup."""
    with environment.client() as client:
        parameters = callback_parameters(environment.authorize(client))
        response = client.get(environment.base_url + "/oauth/callback", params=parameters)
        assert response.status_code == 200
        assert environment.exchanges == ["attacker"]
        assert environment.probe(client)["success"]
        assert environment.upstream_identities[-1] == "attacker"
        assert client.get(environment.base_url + "/oauth/callback", params=parameters).status_code == 400
        assert environment.exchanges == ["attacker"]
        assert not any(cookie.name.startswith("oauth_bind_") for cookie in client.cookies.jar)


@pytest.mark.parametrize("existing_token", [False, True])
def test_cross_browser_rejected(environment: BindingEnvironment, existing_token: bool) -> None:
    """Reject victim consent without creating or replacing attacker credentials."""
    with environment.client() as attacker, environment.client(False) as victim:
        if existing_token:
            parameters = callback_parameters(environment.authorize(attacker))
            assert attacker.get(environment.base_url + "/oauth/callback", params=parameters).status_code == 200
        before = list(environment.exchanges)
        parameters = callback_parameters(environment.authorize(attacker), "victim")
        assert not victim.cookies
        response = victim.get(environment.base_url + "/oauth/callback", params=parameters)
        assert response.status_code == 400
        assert environment.exchanges == before
        assert attacker.get(environment.base_url + "/oauth/callback", params=parameters).status_code == 400
        result = environment.probe(attacker)
        if existing_token:
            assert result["success"]
            assert environment.upstream_identities[-1] == "attacker"
        else:
            assert result["errorCode"] == "authorization_missing"
        assert "victim" not in environment.upstream_identities


@pytest.mark.parametrize("error", [None, "access_denied"])
def test_terminal_errors_consume_and_cleanup(environment: BindingEnvironment, error: str | None) -> None:
    """Consume provider-error and missing-code callbacks without token exchange."""
    with environment.client() as client:
        parameters = callback_parameters(environment.authorize(client))
        parameters.pop("code")
        if error:
            parameters["error"] = error
        response = client.get(environment.base_url + "/oauth/callback", params=parameters)
        assert response.status_code == 400
        assert not any(cookie.name.startswith("oauth_bind_") for cookie in client.cookies.jar)
        assert "Max-Age=0" in response.headers["set-cookie"]
        assert client.get(environment.base_url + "/oauth/callback", params={"state": parameters["state"], "code": "attacker"}).status_code == 400
        assert environment.exchanges == []


def test_custom_redirect_deletes_binding_cookie(tmp_path: Path) -> None:
    """Keep cookie deletion on the final custom redirect response."""
    with binding_environment(tmp_path, custom_redirect=True) as environment, environment.client() as client:
        parameters = callback_parameters(environment.authorize(client, popup=False))
        response = client.get(environment.base_url + "/oauth/callback", params=parameters)
        assert response.status_code == 302
        assert response.headers["location"] == environment.base_url + "/health"
        assert "Max-Age=0" in response.headers["set-cookie"]
        assert "Domain=" not in response.headers["set-cookie"]
        assert not any(cookie.name.startswith("oauth_bind_") for cookie in client.cookies.jar)
        assert environment.exchanges == ["attacker"]
