# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/utils/test_gateway_access.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for gateway access control utilities.
"""

# Standard
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.utils.gateway_access import build_gateway_auth_headers

# Local
from tests.helpers.admin_mocks import install_admin_user


class TestBuildGatewayAuthHeaders:
    """Test suite for build_gateway_auth_headers function."""

    def test_bearer_auth_with_dict_value(self):
        """Should extract bearer token from dict auth_value."""
        gateway = MagicMock()
        gateway.auth_type = "bearer"
        gateway.auth_value = {"Authorization": "Bearer token123"}

        headers = build_gateway_auth_headers(gateway)

        assert headers == {"Authorization": "Bearer token123"}

    def test_bearer_auth_with_dict_value_no_bearer_prefix(self):
        """Should add Bearer prefix if missing in dict auth_value."""
        gateway = MagicMock()
        gateway.auth_type = "bearer"
        gateway.auth_value = {"Authorization": "token123"}

        headers = build_gateway_auth_headers(gateway)

        assert headers == {"Authorization": "Bearer token123"}

    def test_bearer_auth_with_encoded_string(self):
        """Should decode and extract bearer token from encoded string."""
        gateway = MagicMock()
        gateway.auth_type = "bearer"
        gateway.auth_value = "encoded_string"

        with patch("mcpgateway.utils.gateway_access.decode_auth") as mock_decode:
            mock_decode.return_value = {"Authorization": "Bearer decoded_token"}

            headers = build_gateway_auth_headers(gateway)

            assert headers == {"Authorization": "Bearer decoded_token"}
            mock_decode.assert_called_once_with("encoded_string")

    def test_bearer_auth_with_encoded_string_no_bearer_prefix(self):
        """Should add Bearer prefix when decoding encoded string."""
        gateway = MagicMock()
        gateway.auth_type = "bearer"
        gateway.auth_value = "encoded_string"

        with patch("mcpgateway.utils.gateway_access.decode_auth") as mock_decode:
            mock_decode.return_value = {"Authorization": "decoded_token"}

            headers = build_gateway_auth_headers(gateway)

            assert headers == {"Authorization": "Bearer decoded_token"}

    def test_basic_auth_with_dict_value(self):
        """Should extract basic auth header from dict auth_value."""
        gateway = MagicMock()
        gateway.auth_type = "basic"
        gateway.auth_value = {"Authorization": "Basic dXNlcjpwYXNz"}

        headers = build_gateway_auth_headers(gateway)

        assert headers == {"Authorization": "Basic dXNlcjpwYXNz"}

    def test_basic_auth_with_encoded_string(self):
        """Should decode and extract basic auth from encoded string."""
        gateway = MagicMock()
        gateway.auth_type = "basic"
        gateway.auth_value = "encoded_string"

        with patch("mcpgateway.utils.gateway_access.decode_auth") as mock_decode:
            mock_decode.return_value = {"Authorization": "Basic dXNlcjpwYXNz"}

            headers = build_gateway_auth_headers(gateway)

            assert headers == {"Authorization": "Basic dXNlcjpwYXNz"}
            mock_decode.assert_called_once_with("encoded_string")

    def test_no_auth_type(self):
        """Should return empty dict when no auth_type is set."""
        gateway = MagicMock()
        gateway.auth_type = None
        gateway.auth_value = {"Authorization": "Bearer token"}

        headers = build_gateway_auth_headers(gateway)

        assert headers == {}

    def test_no_auth_value(self):
        """Should return empty dict when no auth_value is set."""
        gateway = MagicMock()
        gateway.auth_type = "bearer"
        gateway.auth_value = None

        headers = build_gateway_auth_headers(gateway)

        assert headers == {}

    def test_empty_auth_value_dict(self):
        """Should return empty dict when auth_value dict is empty."""
        gateway = MagicMock()
        gateway.auth_type = "bearer"
        gateway.auth_value = {}

        headers = build_gateway_auth_headers(gateway)

        assert headers == {}

    def test_missing_authorization_key_in_dict(self):
        """Should return empty dict when Authorization key is missing."""
        gateway = MagicMock()
        gateway.auth_type = "bearer"
        gateway.auth_value = {"SomeOtherKey": "value"}

        headers = build_gateway_auth_headers(gateway)

        assert headers == {}

    def test_unknown_auth_type(self):
        """Should return empty dict for unknown auth types."""
        gateway = MagicMock()
        gateway.auth_type = "oauth"
        gateway.auth_value = {"Authorization": "Bearer token"}

        headers = build_gateway_auth_headers(gateway)

        assert headers == {}

    def test_bearer_auth_empty_token(self):
        """Should return empty dict when token is empty."""
        gateway = MagicMock()
        gateway.auth_type = "bearer"
        gateway.auth_value = {"Authorization": ""}

        headers = build_gateway_auth_headers(gateway)

        assert headers == {}

    def test_basic_auth_empty_value(self):
        """Should return empty dict when basic auth value is empty."""
        gateway = MagicMock()
        gateway.auth_type = "basic"
        gateway.auth_value = {"Authorization": ""}

        headers = build_gateway_auth_headers(gateway)

        assert headers == {}


# First-Party
from mcpgateway.utils import gateway_access  # noqa: E402  (module-attribute access keeps red-first failures per-test)


class TestNormalizeDownstreamAuthHeaders:
    """Strict stored-credential normalization for PROXIED downstream forwarding (Phase 4 T3)."""

    def test_bearer_dict_normalizes_authorization_header(self):
        """Bearer dict material normalizes to a single Authorization header."""
        headers = gateway_access.normalize_downstream_auth_headers("bearer", {"Authorization": "Bearer token123"})

        assert headers == {"Authorization": "Bearer token123"}

    def test_bearer_dict_without_prefix_gets_prefixed(self):
        """Bearer material lacking the scheme prefix is prefixed, matching legacy behavior."""
        headers = gateway_access.normalize_downstream_auth_headers("bearer", {"Authorization": "token123"})

        assert headers == {"Authorization": "Bearer token123"}

    def test_basic_dict_passes_authorization_through(self):
        """Basic material forwards the stored Authorization header verbatim."""
        headers = gateway_access.normalize_downstream_auth_headers("basic", {"Authorization": "Basic dXNlcjpwYXNz"})

        assert headers == {"Authorization": "Basic dXNlcjpwYXNz"}

    def test_authheaders_dict_forwards_full_mapping(self):
        """Custom authheaders material forwards every stored header (the Oracle authheaders gap)."""
        headers = gateway_access.normalize_downstream_auth_headers("authheaders", {"X-Api-Key": "k", "X-Tenant": "t"})

        assert headers == {"X-Api-Key": "k", "X-Tenant": "t"}

    def test_encoded_string_form_round_trips(self):
        """The encrypted string form (tool invoke-seam representation) decodes to the same mapping."""
        # First-Party
        from mcpgateway.utils.services_auth import encode_auth

        encoded = encode_auth({"X-Api-Key": "encoded-marker"})  # pragma: allowlist secret

        headers = gateway_access.normalize_downstream_auth_headers("authheaders", encoded)

        assert headers == {"X-Api-Key": "encoded-marker"}  # pragma: allowlist secret

    @pytest.mark.parametrize("auth_type,auth_value", [(None, {"Authorization": "Bearer x"}), ("bearer", None), ("bearer", {}), ("", {"Authorization": "Bearer x"})])
    def test_absent_material_returns_empty(self, auth_type, auth_value):
        """No stored material means no headers (the envelope omits authentication entirely)."""
        assert gateway_access.normalize_downstream_auth_headers(auth_type, auth_value) == {}

    @pytest.mark.parametrize("auth_type", ["query_param", "oauth", "one_time_auth", "ntlm"])
    def test_unsupported_modes_raise_code_only(self, auth_type):
        """Unsupported auth modes are explicitly rejected, never silently omitted; message carries no values."""
        with pytest.raises(gateway_access.GatewayAuthValueError) as exc_info:
            gateway_access.normalize_downstream_auth_headers(auth_type, {"Authorization": "Bearer marker-secret"})

        message = str(exc_info.value)
        assert auth_type in message
        assert "marker-secret" not in message

    def test_corrupt_encoded_string_raises_without_echo(self):
        """Undecryptable material raises a code-only typed error that never echoes the blob."""
        with pytest.raises(gateway_access.GatewayAuthValueError) as exc_info:
            gateway_access.normalize_downstream_auth_headers("bearer", "!!!not-valid-encoded!!!")

        assert "!!!not-valid-encoded!!!" not in str(exc_info.value)

    def test_non_string_mapping_value_raises_without_echo(self):
        """Non-string header values are rejected at the boundary; the value never appears in the error."""
        with pytest.raises(gateway_access.GatewayAuthValueError) as exc_info:
            gateway_access.normalize_downstream_auth_headers("authheaders", {"X-Api-Key": 12345})

        assert "12345" not in str(exc_info.value)

    def test_non_mapping_non_string_representation_raises(self):
        """A wholly unsupported stored representation raises the code-only typed error."""
        with pytest.raises(gateway_access.GatewayAuthValueError):
            gateway_access.normalize_downstream_auth_headers("bearer", 12345)

    def test_bearer_non_string_authorization_raises_not_attribute_error(self):
        """Malformed bearer material yields the typed error, never an AttributeError from .replace."""
        with pytest.raises(gateway_access.GatewayAuthValueError) as exc_info:
            gateway_access.normalize_downstream_auth_headers("bearer", {"Authorization": 999})

        assert "999" not in str(exc_info.value)


# First-Party
from mcpgateway.utils.gateway_access import check_gateway_access


class TestCheckGatewayAccess:
    """Test suite for check_gateway_access function."""

    @pytest.mark.asyncio
    async def test_public_gateway_accessible_by_all(self):
        """Public gateways should be accessible by everyone."""
        db = MagicMock()
        gateway = MagicMock()
        gateway.visibility = "public"
        gateway.team_id = None
        gateway.owner_email = None

        # Authenticated user
        result = await check_gateway_access(db, gateway, "user@example.com", [])
        assert result is True

        # Unauthenticated user
        result = await check_gateway_access(db, gateway, None, [])
        assert result is True

        # Public-only token
        result = await check_gateway_access(db, gateway, "user@example.com", [])
        assert result is True

    @pytest.mark.asyncio
    async def test_admin_bypass_denies_private(self):
        """PR #4341: anonymous admin bypass (None, None) must NOT see another user's private gateway."""
        db = MagicMock()
        gateway = MagicMock()
        gateway.visibility = "private"
        gateway.team_id = "team1"
        gateway.owner_email = "owner@example.com"

        result = await check_gateway_access(db, gateway, None, None)
        assert result is False

    @pytest.mark.asyncio
    async def test_admin_bypass_sees_team(self):
        """Anonymous admin bypass (None, None) still sees team gateways (only private is denied)."""
        db = MagicMock()
        gateway = MagicMock()
        gateway.visibility = "team"
        gateway.team_id = "team1"
        gateway.owner_email = "owner@example.com"

        result = await check_gateway_access(db, gateway, None, None)
        assert result is True

    @pytest.mark.asyncio
    async def test_database_admin_bypass(self):
        """DB-admin (email, None) shape: own private allowed, other user's private denied (PR #4341)."""
        db = MagicMock()
        own_private = MagicMock()
        own_private.visibility = "private"
        own_private.team_id = "team1"
        own_private.owner_email = "admin@test.com"

        others_private = MagicMock()
        others_private.visibility = "private"
        others_private.team_id = "team1"
        others_private.owner_email = "owner@example.com"

        install_admin_user(db)

        # PR #4341 carve-out: DB admin sees own private.
        assert await check_gateway_access(db, own_private, "admin@test.com", None) is True
        # PR #4341 invariant: DB admin still cannot see another user's private.
        assert await check_gateway_access(db, others_private, "admin@test.com", None) is False

    @pytest.mark.asyncio
    async def test_database_admin_with_narrowed_token_still_narrowed(self):
        """DB admin with team-scoped token must NOT bypass (#4106 guard)."""
        db = MagicMock()
        gateway = MagicMock()
        gateway.visibility = "private"
        gateway.team_id = "team1"
        gateway.owner_email = "owner@example.com"

        install_admin_user(db)

        result = await check_gateway_access(db, gateway, "admin@test.com", ["some-team"])
        assert result is False

    @pytest.mark.asyncio
    async def test_database_admin_with_public_only_token_stays_public_only(self):
        """DB admin with public-only token (token_teams=[]) sees only public gateways."""
        db = MagicMock()
        gateway = MagicMock()
        gateway.visibility = "private"
        gateway.team_id = "team1"
        gateway.owner_email = "owner@example.com"

        install_admin_user(db)

        result = await check_gateway_access(db, gateway, "admin@test.com", [])
        assert result is False

    @pytest.mark.asyncio
    async def test_platform_admin_bypass(self, monkeypatch):
        """Platform admin (email, None) shape: own private allowed, other user's private denied (PR #4341)."""
        # First-Party
        from mcpgateway.config import settings

        db = MagicMock()
        others_private = MagicMock()
        others_private.visibility = "private"
        others_private.team_id = "team1"
        others_private.owner_email = "owner@example.com"

        own_private = MagicMock()
        own_private.visibility = "private"
        own_private.team_id = "team1"
        own_private.owner_email = "platform-admin@example.com"

        monkeypatch.setattr(settings, "platform_admin_email", "platform-admin@example.com")

        # PR #4341 invariant: platform admin still cannot read another user's private gateway.
        assert await check_gateway_access(db, others_private, "platform-admin@example.com", None) is False
        # PR #4341 carve-out: platform admin can read their own private gateway.
        assert await check_gateway_access(db, own_private, "platform-admin@example.com", None) is True

    @pytest.mark.asyncio
    async def test_database_exception_handling(self):
        """Database exceptions during admin check should be handled gracefully."""
        db = MagicMock()
        gateway = MagicMock()
        gateway.visibility = "private"
        gateway.team_id = "team1"
        gateway.owner_email = "owner@example.com"

        # Mock database to raise exception
        db.execute.side_effect = Exception("Database error")

        # Should not raise exception, should continue with normal checks
        result = await check_gateway_access(db, gateway, "user@example.com", ["team1"])

        # Exception was caught and handled, access denied due to team mismatch
        assert result is False

    @pytest.mark.asyncio
    async def test_private_gateway_owner_access(self):
        """Private gateway owner should have access."""
        db = MagicMock()
        gateway = MagicMock()
        gateway.visibility = "private"
        gateway.team_id = None
        gateway.owner_email = "owner@example.com"

        # Owner has access
        result = await check_gateway_access(db, gateway, "owner@example.com", ["team1"])
        assert result is True

        # Non-owner denied
        result = await check_gateway_access(db, gateway, "other@example.com", ["team1"])
        assert result is False

    @pytest.mark.asyncio
    async def test_private_gateway_unauthenticated_denied(self):
        """Unauthenticated users should not access private gateways."""
        db = MagicMock()
        gateway = MagicMock()
        gateway.visibility = "private"
        gateway.team_id = None
        gateway.owner_email = "owner@example.com"

        result = await check_gateway_access(db, gateway, None, [])
        assert result is False

    @pytest.mark.asyncio
    async def test_public_only_token_denied_non_public(self):
        """Public-only tokens (empty teams array) should only access public gateways."""
        db = MagicMock()
        gateway = MagicMock()
        gateway.visibility = "team"
        gateway.team_id = "team1"
        gateway.owner_email = "owner@example.com"

        # Public-only token (empty teams array)
        result = await check_gateway_access(db, gateway, "user@example.com", [])
        assert result is False

        # Even if user is the owner
        result = await check_gateway_access(db, gateway, "owner@example.com", [])
        assert result is False

    @pytest.mark.asyncio
    async def test_team_gateway_team_member_access(self):
        """Team gateway should be accessible by team members."""
        db = MagicMock()
        gateway = MagicMock()
        gateway.visibility = "team"
        gateway.team_id = "team1"
        gateway.owner_email = "owner@example.com"

        # Team member has access
        result = await check_gateway_access(db, gateway, "member@example.com", ["team1", "team2"])
        assert result is True

        # Non-team member denied
        result = await check_gateway_access(db, gateway, "other@example.com", ["team2", "team3"])
        assert result is False

    @pytest.mark.asyncio
    async def test_team_gateway_owner_access(self):
        """Team gateway owner should have access even if not in token teams."""
        db = MagicMock()
        gateway = MagicMock()
        gateway.visibility = "team"
        gateway.team_id = "team1"
        gateway.owner_email = "owner@example.com"

        # Owner has access even without team in token
        result = await check_gateway_access(db, gateway, "owner@example.com", ["team2"])
        assert result is True

    @pytest.mark.asyncio
    async def test_team_gateway_db_lookup_when_token_teams_none(self):
        """Should look up teams from DB when token_teams is None (non-admin)."""
        db = MagicMock()
        gateway = MagicMock()
        gateway.visibility = "team"
        gateway.team_id = "team1"
        gateway.owner_email = "other@example.com"

        # Mock team service
        mock_team = MagicMock()
        mock_team.id = "team1"

        with patch("mcpgateway.services.team_management_service.TeamManagementService") as mock_service_class:
            mock_service = MagicMock()
            mock_service.get_user_teams = AsyncMock(return_value=[mock_team])
            mock_service_class.return_value = mock_service

            # token_teams=None but user_email provided (non-admin case)
            result = await check_gateway_access(db, gateway, "user@example.com", None)
            assert result is True

            # Verify team service was called
            mock_service_class.assert_called_once_with(db)
            mock_service.get_user_teams.assert_called_once_with("user@example.com")

    @pytest.mark.asyncio
    async def test_team_gateway_db_lookup_no_access(self):
        """Should deny access when DB lookup shows user not in team."""
        db = MagicMock()
        gateway = MagicMock()
        gateway.visibility = "team"
        gateway.team_id = "team1"
        gateway.owner_email = "other@example.com"

        # Mock team service - user in different team
        mock_team = MagicMock()
        mock_team.id = "team2"

        with patch("mcpgateway.services.team_management_service.TeamManagementService") as mock_service_class:
            mock_service = MagicMock()
            mock_service.get_user_teams = AsyncMock(return_value=[mock_team])
            mock_service_class.return_value = mock_service

            result = await check_gateway_access(db, gateway, "user@example.com", None)
            assert result is False

    @pytest.mark.asyncio
    async def test_gateway_without_visibility_defaults_to_public(self):
        """Gateway without visibility attribute should default to public."""
        db = MagicMock()
        gateway = MagicMock(spec=[])  # No attributes

        result = await check_gateway_access(db, gateway, "user@example.com", [])
        assert result is True

    @pytest.mark.asyncio
    async def test_team_gateway_with_public_visibility(self):
        """Team gateway with public visibility should allow team members."""
        db = MagicMock()
        gateway = MagicMock()
        gateway.visibility = "public"
        gateway.team_id = "team1"
        gateway.owner_email = "owner@example.com"

        # Team member has access
        result = await check_gateway_access(db, gateway, "member@example.com", ["team1"])
        assert result is True

        # Non-team member also has access (public visibility)
        result = await check_gateway_access(db, gateway, "other@example.com", ["team2"])
        assert result is True

    @pytest.mark.asyncio
    async def test_multiple_teams_in_token(self):
        """Should grant access if any team in token matches gateway team."""
        db = MagicMock()
        gateway = MagicMock()
        gateway.visibility = "team"
        gateway.team_id = "team2"
        gateway.owner_email = "owner@example.com"

        # User has multiple teams, one matches
        result = await check_gateway_access(db, gateway, "user@example.com", ["team1", "team2", "team3"])
        assert result is True

    @pytest.mark.asyncio
    async def test_no_user_email_non_public_denied(self):
        """No user email (non-admin) should be denied for non-public gateways."""
        db = MagicMock()
        gateway = MagicMock()
        gateway.visibility = "team"
        gateway.team_id = "team1"
        gateway.owner_email = "owner@example.com"

        # No user email, not admin (token_teams is not None)
        result = await check_gateway_access(db, gateway, None, ["team1"])
        assert result is False

    @pytest.mark.asyncio
    async def test_gateway_without_team_id(self):
        """Gateway without team_id should not grant team-based access."""
        db = MagicMock()
        gateway = MagicMock()
        gateway.visibility = "team"
        gateway.team_id = None
        gateway.owner_email = "owner@example.com"

        # Non-owner with teams should be denied
        result = await check_gateway_access(db, gateway, "user@example.com", ["team1"])
        assert result is False

        # Owner should still have access
        result = await check_gateway_access(db, gateway, "owner@example.com", ["team1"])
        assert result is True

    @pytest.mark.asyncio
    async def test_gateway_without_owner_email(self):
        """Gateway without owner_email should not grant owner-based access."""
        db = MagicMock()
        gateway = MagicMock()
        gateway.visibility = "private"
        gateway.team_id = None
        gateway.owner_email = None

        # No owner, so no one can access private gateway
        result = await check_gateway_access(db, gateway, "user@example.com", ["team1"])
        assert result is False


# First-Party
from mcpgateway.utils.gateway_access import extract_gateway_id_from_headers, GATEWAY_ID_HEADER


def test_gateway_id_header_constant_value():
    """GATEWAY_ID_HEADER should equal the canonical header name."""
    assert GATEWAY_ID_HEADER == "X-Context-Forge-Gateway-Id"


class TestExtractGatewayIdFromHeaders:
    """Test suite for extract_gateway_id_from_headers function."""

    def test_extract_gateway_id_found(self):
        """Should return the gateway ID when header is present."""
        headers = {"X-Context-Forge-Gateway-Id": "gw-123"}
        result = extract_gateway_id_from_headers(headers)
        assert result == "gw-123"

    def test_extract_gateway_id_case_insensitive(self):
        """Should match the header name case-insensitively."""
        headers = {"x-context-forge-gateway-id": "gw-456"}
        result = extract_gateway_id_from_headers(headers)
        assert result == "gw-456"

    def test_extract_gateway_id_not_found(self):
        """Should return None when the header is absent."""
        headers = {"Authorization": "Bearer token", "X-Other": "value"}
        result = extract_gateway_id_from_headers(headers)
        assert result is None

    def test_extract_gateway_id_none_headers(self):
        """Should return None when headers is None."""
        result = extract_gateway_id_from_headers(None)
        assert result is None

    def test_extract_gateway_id_empty_headers(self):
        """Should return None when headers dict is empty."""
        result = extract_gateway_id_from_headers({})
        assert result is None


# Made with Bob
# Co-authored by Venkat (010gvr@gmail.com)
