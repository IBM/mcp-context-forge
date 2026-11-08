# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_oauth_extra_auth_params.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for ``oauth_config.extra_auth_params`` (issue #4044).

Tests cover:
- The shared validator: accepted shapes and every rejection path
- Reserved names are rejected case-insensitively
- The schema (create and update) rejects invalid values with 422-style errors
- The authorization URL carries the extra parameters
- A stored config that skipped the schema cannot override state, PKCE or redirect_uri
"""

# Standard
from urllib.parse import parse_qs, urlparse

# Third-Party
from pydantic import ValidationError
import pytest

# First-Party
from mcpgateway.common.oauth import MAX_EXTRA_AUTH_PARAM_VALUE_LENGTH, MAX_EXTRA_AUTH_PARAMS, RESERVED_AUTHORIZATION_PARAMS, validate_extra_auth_params
from mcpgateway.schemas import GatewayCreate, GatewayUpdate
from mcpgateway.services.oauth_manager import OAuthManager
from mcpgateway.utils.error_formatter import PublicValidationError


def _credentials(extra_auth_params=None, **overrides):
    """Build authorization-code credentials for the URL builder."""
    credentials = {
        "client_id": "test-client",
        "authorization_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "redirect_uri": "https://gateway.example.com/oauth/callback",
        "scopes": ["https://www.googleapis.com/auth/gmail.readonly"],
    }
    if extra_auth_params is not None:
        credentials["extra_auth_params"] = extra_auth_params
    credentials.update(overrides)
    return credentials


def _oauth_config(extra_auth_params):
    """Build a gateway oauth_config for the schema."""
    return {
        "grant_type": "authorization_code",
        "client_id": "test-client",
        "authorization_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "redirect_uri": "https://gateway.example.com/oauth/callback",
        "extra_auth_params": extra_auth_params,
    }


def _query(url):
    """Parse a URL query string into single values."""
    return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}


class TestValidateExtraAuthParams:
    """The shared validator used by the schema and the URL builder."""

    @pytest.mark.parametrize("value", [None, {}])
    def test_empty_values_return_empty_dict(self, value):
        assert validate_extra_auth_params(value) == {}

    def test_valid_params_return_a_copy(self):
        raw = {"access_type": "offline", "prompt": "consent"}
        result = validate_extra_auth_params(raw)
        assert result == raw
        assert result is not raw

    @pytest.mark.parametrize("value", ["access_type=offline", ["access_type", "offline"], 1, True])
    def test_non_mapping_is_rejected(self, value):
        with pytest.raises(ValueError, match="must be an object"):
            validate_extra_auth_params(value)

    def test_too_many_entries_are_rejected(self):
        raw = {f"p{i}": "x" for i in range(MAX_EXTRA_AUTH_PARAMS + 1)}
        with pytest.raises(ValueError, match="too many entries"):
            validate_extra_auth_params(raw)

    def test_max_entries_are_accepted(self):
        raw = {f"p{i}": "x" for i in range(MAX_EXTRA_AUTH_PARAMS)}
        assert validate_extra_auth_params(raw) == raw

    @pytest.mark.parametrize("name", ["", "has space", "a&b", "a=b", "a?b", "x" * 65, 7])
    def test_invalid_names_are_rejected(self, name):
        with pytest.raises(ValueError, match="names must be"):
            validate_extra_auth_params({name: "x"})

    @pytest.mark.parametrize("name", sorted(RESERVED_AUTHORIZATION_PARAMS))
    def test_reserved_names_are_rejected(self, name):
        with pytest.raises(ValueError, match="cannot set"):
            validate_extra_auth_params({name: "x"})

    @pytest.mark.parametrize("name", ["State", "REDIRECT_URI", "Code_Challenge"])
    def test_reserved_names_are_case_insensitive(self, name):
        with pytest.raises(ValueError, match="cannot set"):
            validate_extra_auth_params({name: "x"})

    @pytest.mark.parametrize("value", [None, 1, True, ["offline"], {"a": "b"}])
    def test_non_string_values_are_rejected(self, value):
        with pytest.raises(ValueError, match="must be a string"):
            validate_extra_auth_params({"access_type": value})

    def test_too_long_values_are_rejected(self):
        with pytest.raises(ValueError, match="too long"):
            validate_extra_auth_params({"login_hint": "x" * (MAX_EXTRA_AUTH_PARAM_VALUE_LENGTH + 1)})

    @pytest.mark.parametrize("value", ["a\nb", "a\rb", "a\x00b", "a\x7fb"])
    def test_control_characters_are_rejected(self, value):
        with pytest.raises(ValueError, match="control characters"):
            validate_extra_auth_params({"login_hint": value})


class TestSchemaValidation:
    """GatewayCreate and GatewayUpdate reject invalid values at the API boundary."""

    @pytest.mark.parametrize("schema", ["create", "update"])
    def test_valid_params_are_accepted(self, schema):
        config = _oauth_config({"access_type": "offline", "prompt": "consent"})
        gateway = GatewayCreate(name="gw", url="https://example.com", oauth_config=config) if schema == "create" else GatewayUpdate(oauth_config=config)
        assert gateway.oauth_config["extra_auth_params"] == {"access_type": "offline", "prompt": "consent"}

    @pytest.mark.parametrize("schema", ["create", "update"])
    @pytest.mark.parametrize("extra", [{"state": "attacker"}, {"redirect_uri": "https://evil.example.com"}, {"code_challenge_method": "plain"}, "access_type=offline"])
    def test_invalid_params_are_rejected(self, schema, extra):
        config = _oauth_config(extra)
        with pytest.raises(ValidationError, match="extra_auth_params"):
            if schema == "create":
                GatewayCreate(name="gw", url="https://example.com", oauth_config=config)
            else:
                GatewayUpdate(oauth_config=config)


class TestAuthorizationUrl:
    """The PKCE authorization URL builder."""

    @pytest.fixture
    def oauth_manager(self):
        """Create an OAuthManager instance."""
        return OAuthManager()

    def _build(self, oauth_manager, credentials):
        return oauth_manager._create_authorization_url_with_pkce(credentials, state="test-state", code_challenge="test-challenge", code_challenge_method="S256")

    def test_extra_params_are_added(self, oauth_manager):
        url = self._build(oauth_manager, _credentials({"access_type": "offline", "prompt": "consent"}))
        query = _query(url)
        assert query["access_type"] == "offline"
        assert query["prompt"] == "consent"
        assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")

    def test_standard_params_are_unchanged(self, oauth_manager):
        query = _query(self._build(oauth_manager, _credentials({"access_type": "offline"})))
        assert query["response_type"] == "code"
        assert query["client_id"] == "test-client"
        assert query["redirect_uri"] == "https://gateway.example.com/oauth/callback"
        assert query["state"] == "test-state"
        assert query["code_challenge"] == "test-challenge"
        assert query["code_challenge_method"] == "S256"
        assert query["scope"] == "https://www.googleapis.com/auth/gmail.readonly"

    def test_without_extra_params_the_url_is_unchanged(self, oauth_manager):
        assert self._build(oauth_manager, _credentials()) == self._build(oauth_manager, _credentials({}))

    def test_values_are_url_encoded(self, oauth_manager):
        url = self._build(oauth_manager, _credentials({"login_hint": "a b&c=d@example.com"}))
        assert "login_hint=a+b%26c%3Dd%40example.com" in url
        assert _query(url)["login_hint"] == "a b&c=d@example.com"

    def test_extra_params_coexist_with_audience(self, oauth_manager):
        query = _query(self._build(oauth_manager, _credentials({"prompt": "consent"}, audience="api.atlassian.com", authorization_url="https://auth.atlassian.com/authorize")))
        assert query["audience"] == "api.atlassian.com"
        assert query["prompt"] == "consent"

    @pytest.mark.parametrize("name", ["state", "redirect_uri", "code_challenge", "STATE"])
    def test_stored_config_cannot_override_reserved_params(self, oauth_manager, name):
        # A config written to the database directly, or before this validator
        # existed, never reaches the provider with a replaced reserved value.
        with pytest.raises(PublicValidationError, match="cannot set"):
            self._build(oauth_manager, _credentials({name: "attacker-value"}))

    def test_stored_config_with_wrong_type_fails_closed(self, oauth_manager):
        with pytest.raises(PublicValidationError, match="must be an object"):
            self._build(oauth_manager, _credentials("access_type=offline"))
