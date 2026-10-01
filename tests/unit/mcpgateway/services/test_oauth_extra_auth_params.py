# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_oauth_extra_auth_params.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for extra authorization URL parameters (``oauth_config.extra_auth_params``, issue #4115).
"""

# Standard
from urllib.parse import parse_qs, urlparse

# Third-Party
from pydantic import ValidationError
import pytest

# First-Party
from mcpgateway.schemas import GatewayCreate, GatewayUpdate
from mcpgateway.services.oauth_manager import OAuthManager

CREDENTIALS = {
    "client_id": "gateway-client",
    "authorization_url": "https://accounts.google.com/o/oauth2/v2/auth",
    "redirect_uri": "https://gateway.example.com/oauth/callback",
    "scopes": ["openid", "email"],
}
GATEWAY_SCHEMAS = [(GatewayCreate, {"name": "google", "url": "https://mcp.example.com"}), (GatewayUpdate, {})]


def _authorization_query(extra_auth_params):
    url = OAuthManager()._create_authorization_url_with_pkce({**CREDENTIALS, "extra_auth_params": extra_auth_params}, "gateway-state", "gateway-challenge", "S256")
    return parse_qs(urlparse(url).query)


def test_authorization_url_carries_extra_auth_params():
    """Google issues a refresh token only with access_type=offline, and on every consent with prompt=consent."""
    query = _authorization_query({"access_type": "offline", "prompt": "consent"})

    assert query["access_type"] == ["offline"]
    assert query["prompt"] == ["consent"]


def test_authorization_url_skips_reserved_and_non_string_entries():
    """Reserved, secret, and non-string entries never reach the URL, even when they skipped schema validation."""
    query = _authorization_query(
        {"redirect_uri": "https://attacker.example.com/callback", "State": "attacker", "code_challenge_method": "plain", "audience": "attacker-api", "token": "secret", "max_age": 0, 1: "numeric-name"}
    )

    assert query["redirect_uri"] == [CREDENTIALS["redirect_uri"]]
    assert query["state"] == ["gateway-state"]
    assert query["code_challenge_method"] == ["S256"]
    assert not {"State", "audience", "token", "max_age", "1"} & query.keys()


@pytest.mark.parametrize(("model", "base_fields"), GATEWAY_SCHEMAS)
def test_gateway_schemas_accept_extra_auth_params(model, base_fields):
    """Gateway POST and PUT schemas keep valid extra parameters."""
    gateway = model(**base_fields, oauth_config={"extra_auth_params": {"access_type": "offline", "prompt": "consent"}})

    assert gateway.oauth_config["extra_auth_params"] == {"access_type": "offline", "prompt": "consent"}


@pytest.mark.parametrize(("model", "base_fields"), GATEWAY_SCHEMAS)
@pytest.mark.parametrize(
    "extra_auth_params",
    [
        "access_type=offline",
        {"access_type": ["offline"]},
        {"redirect_uri": "https://attacker.example.com/callback"},
        {"Redirect.URI": "https://attacker.example.com/callback"},
        {"client-secret": "value"},  # pragma: allowlist secret
        {"access type": "offline"},
    ],
)
def test_gateway_schemas_reject_invalid_extra_auth_params(model, base_fields, extra_auth_params):
    """Gateway POST and PUT schemas reject non-string values, reserved or secret names, and malformed names."""
    with pytest.raises(ValidationError, match="extra_auth_params (cannot set|must be an object|values must be strings)"):
        model(**base_fields, oauth_config={"extra_auth_params": extra_auth_params})
