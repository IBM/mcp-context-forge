# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_token_validation_service.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for token_validation_service.
"""

# Standard
from unittest.mock import patch

# Third-Party
import jwt
import pytest

# First-Party
from mcpgateway.services.token_validation_service import (
    _derive_issuer_from_token_url,
    _normalize_scope,
    TokenValidationResult,
    validate_oauth_token_claims,
)


def _make_jwt(claims: dict) -> str:
    """Create an unsigned JWT for testing (HS256 with a dummy key)."""
    return jwt.encode(claims, "test-key", algorithm="HS256")


# ---------- TokenValidationResult ----------


class TestTokenValidationResult:
    def test_defaults(self):
        r = TokenValidationResult()
        assert r.is_jwt is False
        assert r.warnings == []
        assert r.audience_match is None
        assert r.scopes_sufficient is None
        assert r.issuer_match is None
        assert r.token_type_valid is None

    def test_blocking_errors_empty_when_no_warnings(self):
        r = TokenValidationResult(is_jwt=True)
        assert r.blocking_errors == []

    def test_blocking_errors_none_flags_are_not_blocking(self):
        """Missing claims (None) must NOT produce blocking errors."""
        r = TokenValidationResult(is_jwt=True)
        r.audience_match = None
        r.scopes_sufficient = None
        r.issuer_match = None
        assert r.blocking_errors == []

    def test_blocking_errors_true_flags_are_not_blocking(self):
        """Matching claims (True) must NOT produce blocking errors."""
        r = TokenValidationResult(is_jwt=True)
        r.audience_match = True
        r.scopes_sufficient = True
        r.issuer_match = True
        assert r.blocking_errors == []

    def test_blocking_errors_audience_mismatch(self):
        r = TokenValidationResult(is_jwt=True)
        r.audience_match = False
        r.warnings.append("Token audience mismatch: token aud does not match expected resource or gateway URL")
        errors = r.blocking_errors
        assert len(errors) == 1
        assert "audience" in errors[0].lower()

    def test_blocking_errors_scope_mismatch(self):
        r = TokenValidationResult(is_jwt=True)
        r.scopes_sufficient = False
        r.warnings.append("Token may be missing required scopes: [write]")
        errors = r.blocking_errors
        assert len(errors) == 1
        assert "scope" in errors[0].lower()

    def test_blocking_errors_issuer_mismatch(self):
        r = TokenValidationResult(is_jwt=True)
        r.issuer_match = False
        r.warnings.append("Token issuer mismatch: token iss='https://wrong.com', expected 'https://right.com'")
        errors = r.blocking_errors
        assert len(errors) == 1
        assert "issuer" in errors[0].lower()

    def test_blocking_errors_multiple_mismatches(self):
        r = TokenValidationResult(is_jwt=True)
        r.audience_match = False
        r.scopes_sufficient = False
        r.issuer_match = False
        r.warnings = [
            "Token audience mismatch: token aud does not match expected resource or gateway URL",
            "Token may be missing required scopes: [write]",
            "Token issuer mismatch: token iss='wrong', expected 'right'",
        ]
        assert len(r.blocking_errors) == 3

    def test_blocking_errors_only_false_not_none(self):
        """audience_match=False blocks; scopes_sufficient=None does NOT."""
        r = TokenValidationResult(is_jwt=True)
        r.audience_match = False
        r.scopes_sufficient = None  # absent claim — must not block
        r.warnings.append("Token audience mismatch: token aud does not match expected resource or gateway URL")
        errors = r.blocking_errors
        assert len(errors) == 1
        assert "audience" in errors[0].lower()


# ---------- _derive_issuer_from_token_url ----------


class TestDeriveIssuerFromTokenUrl:
    def test_entra_id_v2(self):
        url = "https://login.microsoftonline.com/tenant-abc/oauth2/v2.0/token"
        assert _derive_issuer_from_token_url(url) == "https://login.microsoftonline.com/tenant-abc/v2.0"

    def test_generic_idp(self):
        url = "https://auth.example.com/oauth/token"
        assert _derive_issuer_from_token_url(url) == "https://auth.example.com"

    def test_empty_url(self):
        assert _derive_issuer_from_token_url("") is None

    def test_no_scheme(self):
        assert _derive_issuer_from_token_url("just-a-host.com/token") is None


# ---------- _normalize_scope ----------


class TestNormalizeScope:
    def test_simple_scopes(self):
        scopes = _normalize_scope("read write")
        assert "read" in scopes
        assert "write" in scopes

    def test_uri_prefixed_scopes(self):
        scopes = _normalize_scope("api://app-a/Tools.Read api://app-a/Tools.Write")
        assert "api://app-a/Tools.Read" in scopes
        assert "Tools.Read" in scopes
        assert "api://app-a/Tools.Write" in scopes
        assert "Tools.Write" in scopes

    def test_empty_string(self):
        assert _normalize_scope("") == set()


# ---------- validate_oauth_token_claims ----------


class TestValidateOauthTokenClaims:
    """Tests for the main validation function."""

    # -- Happy path: all claims match --

    def test_valid_jwt_all_matching(self):
        token = _make_jwt(
            {
                "aud": "https://mcp-server.example.com",
                "scope": "Tools.Read Tools.Write",
                "iss": "https://login.microsoftonline.com/tenant/v2.0",
            }
        )
        oauth_config = {
            "scopes": ["Tools.Read"],
            "resource": "https://mcp-server.example.com",
            "token_url": "https://login.microsoftonline.com/tenant/oauth2/v2.0/token",
        }
        result = validate_oauth_token_claims(token, oauth_config, "https://gw.example.com", "test-gw")

        assert result.is_jwt is True
        assert result.warnings == []
        assert result.audience_match is True
        assert result.scopes_sufficient is True
        assert result.issuer_match is True
        assert result.token_type_valid is True

    # -- Audience mismatch --

    def test_audience_mismatch(self):
        token = _make_jwt({"aud": "api://wrong-app"})
        oauth_config = {"resource": "api://correct-app"}
        result = validate_oauth_token_claims(token, oauth_config, "https://gw.example.com", "test-gw")

        assert result.is_jwt is True
        assert result.audience_match is False
        assert any("audience mismatch" in w.lower() for w in result.warnings)

    def test_audience_match_with_list(self):
        token = _make_jwt({"aud": ["api://app-a", "api://app-b"]})
        oauth_config = {"resource": "api://app-b"}
        result = validate_oauth_token_claims(token, oauth_config, "https://gw.example.com", "test-gw")

        assert result.audience_match is True
        assert not any("audience" in w.lower() for w in result.warnings)

    def test_audience_falls_back_to_gateway_url(self):
        token = _make_jwt({"aud": "https://mcp.example.com/sse"})
        oauth_config = {}  # No resource configured
        result = validate_oauth_token_claims(token, oauth_config, "https://mcp.example.com/sse", "test-gw")

        assert result.audience_match is True

    def test_audience_no_aud_claim(self):
        token = _make_jwt({"scope": "read"})
        oauth_config = {"resource": "https://example.com"}
        result = validate_oauth_token_claims(token, oauth_config, "https://gw.example.com", "test-gw")

        # No aud claim — cannot validate, no warning
        assert result.audience_match is None
        assert not any("audience" in w.lower() for w in result.warnings)

    def test_audience_no_expected_audience(self):
        """When neither resource nor gateway_url is set, audience validation is skipped."""
        token = _make_jwt({"aud": "api://anything"})
        oauth_config = {}
        result = validate_oauth_token_claims(token, oauth_config, "", "test-gw")

        assert result.audience_match is None
        assert not any("audience" in w.lower() for w in result.warnings)

    def test_audience_resource_list_matches(self):
        """When resource is a list (learned from IdP aud array), any overlap is a match."""
        token = _make_jwt({"aud": "my-client-id"})
        oauth_config = {"resource": ["https://api.example.com", "my-client-id"]}
        result = validate_oauth_token_claims(token, oauth_config, "https://gw.example.com", "test-gw")

        assert result.audience_match is True

    def test_audience_resource_takes_precedence_over_gateway_url(self):
        """When resource is set, gateway_url is not used as fallback."""
        token = _make_jwt({"aud": "https://gw.example.com"})
        oauth_config = {"resource": "some-other-value"}
        result = validate_oauth_token_claims(token, oauth_config, "https://gw.example.com", "test-gw")

        assert result.audience_match is False

    # -- Scope mismatch --

    def test_scope_mismatch(self):
        token = _make_jwt({"scope": "read"})
        oauth_config = {"scopes": ["write", "admin"]}
        result = validate_oauth_token_claims(token, oauth_config, "https://gw.example.com", "test-gw")

        assert result.scopes_sufficient is False
        assert any("missing required scopes" in w.lower() for w in result.warnings)

    def test_scope_match_with_uri_prefix(self):
        """Entra ID returns scopes without URI prefix; config has full URI."""
        token = _make_jwt({"scp": "Tools.Read Tools.Write"})
        oauth_config = {"scopes": ["api://app-a/Tools.Read"]}
        result = validate_oauth_token_claims(token, oauth_config, "https://gw.example.com", "test-gw")

        assert result.scopes_sufficient is True

    def test_scope_scp_claim(self):
        """Entra ID uses 'scp' instead of 'scope'."""
        token = _make_jwt({"scp": "Files.Read User.Read"})
        oauth_config = {"scopes": ["Files.Read"]}
        result = validate_oauth_token_claims(token, oauth_config, "https://gw.example.com", "test-gw")

        assert result.scopes_sufficient is True

    def test_no_scope_claim(self):
        token = _make_jwt({"aud": "test"})
        oauth_config = {"scopes": ["read"]}
        result = validate_oauth_token_claims(token, oauth_config, "https://gw.example.com", "test-gw")

        # No scope claim — cannot validate, scopes_sufficient stays None
        assert result.scopes_sufficient is None

    def test_no_configured_scopes(self):
        token = _make_jwt({"scope": "read write"})
        oauth_config = {}  # No scopes configured
        result = validate_oauth_token_claims(token, oauth_config, "https://gw.example.com", "test-gw")

        # Nothing to compare against
        assert result.scopes_sufficient is None

    # -- Issuer mismatch --

    def test_issuer_mismatch(self):
        token = _make_jwt({"iss": "https://wrong-issuer.com"})
        oauth_config = {"issuer": "https://correct-issuer.com"}
        result = validate_oauth_token_claims(token, oauth_config, "https://gw.example.com", "test-gw")

        assert result.issuer_match is False
        assert any("issuer mismatch" in w.lower() for w in result.warnings)

    def test_issuer_match_explicit(self):
        token = _make_jwt({"iss": "https://auth.example.com"})
        oauth_config = {"issuer": "https://auth.example.com"}
        result = validate_oauth_token_claims(token, oauth_config, "https://gw.example.com", "test-gw")

        assert result.issuer_match is True

    def test_issuer_derived_from_token_url(self):
        token = _make_jwt({"iss": "https://login.microsoftonline.com/tenant1/v2.0"})
        oauth_config = {"token_url": "https://login.microsoftonline.com/tenant1/oauth2/v2.0/token"}
        result = validate_oauth_token_claims(token, oauth_config, "https://gw.example.com", "test-gw")

        assert result.issuer_match is True

    def test_issuer_trailing_slash_normalization(self):
        token = _make_jwt({"iss": "https://auth.example.com/"})
        oauth_config = {"issuer": "https://auth.example.com"}
        result = validate_oauth_token_claims(token, oauth_config, "https://gw.example.com", "test-gw")

        assert result.issuer_match is True

    def test_no_iss_claim(self):
        token = _make_jwt({"aud": "test"})
        oauth_config = {"issuer": "https://auth.example.com"}
        result = validate_oauth_token_claims(token, oauth_config, "https://gw.example.com", "test-gw")

        # No iss claim — cannot validate
        assert result.issuer_match is None

    # -- Token type --

    def test_token_type_bearer_valid(self):
        token = _make_jwt({})
        result = validate_oauth_token_claims(token, {}, "https://gw.example.com", "test-gw", token_type="Bearer")
        assert result.token_type_valid is True

    def test_token_type_bearer_case_insensitive(self):
        token = _make_jwt({})
        result = validate_oauth_token_claims(token, {}, "https://gw.example.com", "test-gw", token_type="bearer")
        assert result.token_type_valid is True

    def test_token_type_invalid(self):
        token = _make_jwt({})
        result = validate_oauth_token_claims(token, {}, "https://gw.example.com", "test-gw", token_type="mac")
        assert result.token_type_valid is False
        assert any("token_type" in w.lower() for w in result.warnings)

    # -- Opaque (non-JWT) tokens --

    def test_opaque_token(self):
        result = validate_oauth_token_claims("not-a-jwt-at-all", {}, "https://gw.example.com", "test-gw")

        assert result.is_jwt is False
        # token_type is still validated even for opaque tokens
        assert result.token_type_valid is True
        # No JWT-related warnings (only token_type could warn)
        assert not any("audience" in w.lower() or "scope" in w.lower() or "issuer" in w.lower() for w in result.warnings)

    # -- Multiple warnings --

    def test_multiple_warnings(self):
        token = _make_jwt(
            {
                "aud": "api://wrong",
                "scope": "read",
                "iss": "https://wrong-issuer.com",
            }
        )
        oauth_config = {
            "resource": "api://correct",
            "scopes": ["write"],
            "issuer": "https://correct-issuer.com",
        }
        result = validate_oauth_token_claims(token, oauth_config, "https://gw.example.com", "test-gw")

        assert result.audience_match is False
        assert result.scopes_sufficient is False
        assert result.issuer_match is False
        assert len(result.warnings) == 3

    # -- Missing oauth_config fields --

    def test_empty_oauth_config(self):
        token = _make_jwt({"aud": "test", "scope": "read", "iss": "https://auth.com"})
        result = validate_oauth_token_claims(token, {}, "https://gw.example.com", "test-gw")

        assert result.is_jwt is True
        # With empty config: aud checked against gateway_url, scopes not checked, issuer not checked
        assert result.scopes_sufficient is None
        assert result.issuer_match is None

    def test_none_values_in_oauth_config(self):
        """Graceful handling of None values in config fields."""
        token = _make_jwt({"aud": "test"})
        oauth_config = {"resource": None, "scopes": None, "issuer": None, "token_url": None}
        result = validate_oauth_token_claims(token, oauth_config, "https://gw.example.com", "test-gw")

        # Should not crash
        assert result.is_jwt is True
