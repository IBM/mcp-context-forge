# -*- coding: utf-8 -*-
"""Tests for identity propagation utilities.

Tests cover:
- UserContext model creation and serialization
- build_identity_headers() with various configurations and all optional fields
- build_identity_meta() merging behavior with all optional fields
- filter_sensitive_attributes() including settings fallback
- _resolve_config() per-gateway overrides for all keys
- _sign_claims() JWT secret fallback
- Per-gateway configuration override
- Plugin convenience helpers (PluginContext.user_context, user_email, user_groups)
- _set_user_identity_from_dict() transport helper
- _inject_userinfo_instate() UserContext population
- Audit trail service identity fields (auth_method, acting_as, delegation_chain)
- OAuthManager.token_exchange() RFC 8693
"""

# Standard
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import httpx
from pydantic import SecretStr
import pytest

# First-Party
from mcpgateway.plugins.framework.models import GlobalContext, PluginContext, UserContext
from mcpgateway.utils.identity_propagation import (
    _resolve_config,
    _sign_claims,
    build_identity_headers,
    build_identity_meta,
    filter_sensitive_attributes,
)


# ---------------------------------------------------------------------------
# UserContext model tests
# ---------------------------------------------------------------------------
class TestUserContext:
    """Tests for the UserContext Pydantic model."""

    def test_minimal_creation(self):
        uc = UserContext(user_id="alice@example.com")
        assert uc.user_id == "alice@example.com"
        assert uc.email is None
        assert uc.is_admin is False
        assert uc.groups == []
        assert uc.roles == []
        assert uc.teams is None
        assert uc.attributes == {}
        assert uc.delegation_chain == []

    def test_full_creation(self):
        uc = UserContext(
            user_id="bob@co.com",
            email="bob@co.com",
            full_name="Bob Smith",
            is_admin=True,
            groups=["engineering", "devops"],
            roles=["developer"],
            team_id="team-1",
            teams=["team-1", "team-2"],
            department="Engineering",
            attributes={"level": "senior"},
            auth_method="bearer",
            authenticated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            service_account="gateway-service",
            delegation_chain=["gateway-service", "bob@co.com"],
        )
        assert uc.is_admin is True
        assert uc.groups == ["engineering", "devops"]
        assert uc.teams == ["team-1", "team-2"]
        assert uc.auth_method == "bearer"
        assert uc.delegation_chain == ["gateway-service", "bob@co.com"]

    def test_serialization_roundtrip(self):
        uc = UserContext(user_id="alice@co.com", email="alice@co.com", groups=["eng"])
        data = uc.model_dump()
        uc2 = UserContext(**data)
        assert uc2.user_id == uc.user_id
        assert uc2.groups == uc.groups


# ---------------------------------------------------------------------------
# build_identity_headers tests
# ---------------------------------------------------------------------------
class TestBuildIdentityHeaders:
    """Tests for build_identity_headers()."""

    @patch("mcpgateway.utils.identity_propagation.settings")
    def test_disabled_returns_empty(self, mock_settings):
        mock_settings.identity_propagation_enabled = False
        uc = UserContext(user_id="alice@co.com")
        assert build_identity_headers(uc) == {}

    @patch("mcpgateway.utils.identity_propagation.settings")
    def test_basic_headers(self, mock_settings):
        mock_settings.identity_propagation_enabled = True
        mock_settings.identity_propagation_mode = "both"
        mock_settings.identity_propagation_headers_prefix = "X-Forwarded-User"
        mock_settings.identity_sign_claims = False
        mock_settings.identity_sensitive_attributes = []
        uc = UserContext(
            user_id="alice@co.com",
            email="alice@co.com",
            full_name="Alice",
            is_admin=False,
            groups=["eng", "dev"],
            teams=["team-1"],
            auth_method="bearer",
        )
        headers = build_identity_headers(uc)
        assert headers["X-Forwarded-User-Id"] == "alice@co.com"
        assert headers["X-Forwarded-User-Email"] == "alice@co.com"
        assert headers["X-Forwarded-User-Full-Name"] == "Alice"
        assert headers["X-Forwarded-User-Groups"] == "eng,dev"
        assert headers["X-Forwarded-User-Teams"] == "team-1"
        assert headers["X-Forwarded-User-Admin"] == "false"
        assert headers["X-Forwarded-User-Auth-Method"] == "bearer"

    @patch("mcpgateway.utils.identity_propagation.settings")
    def test_admin_header_true(self, mock_settings):
        mock_settings.identity_propagation_enabled = True
        mock_settings.identity_propagation_mode = "headers"
        mock_settings.identity_propagation_headers_prefix = "X-Forwarded-User"
        mock_settings.identity_sign_claims = False
        mock_settings.identity_sensitive_attributes = []
        uc = UserContext(user_id="admin@co.com", is_admin=True)
        headers = build_identity_headers(uc)
        assert headers["X-Forwarded-User-Admin"] == "true"

    @patch("mcpgateway.utils.identity_propagation.settings")
    def test_custom_prefix(self, mock_settings):
        mock_settings.identity_propagation_enabled = True
        mock_settings.identity_propagation_mode = "headers"
        mock_settings.identity_propagation_headers_prefix = "X-Auth-User"
        mock_settings.identity_sign_claims = False
        mock_settings.identity_sensitive_attributes = []
        uc = UserContext(user_id="alice@co.com")
        headers = build_identity_headers(uc)
        assert "X-Auth-User-Id" in headers
        assert "X-Forwarded-User-Id" not in headers

    @patch("mcpgateway.utils.identity_propagation.settings")
    def test_signed_claims(self, mock_settings):
        mock_settings.identity_propagation_enabled = True
        mock_settings.identity_propagation_mode = "both"
        mock_settings.identity_propagation_headers_prefix = "X-Forwarded-User"
        mock_settings.identity_sign_claims = True
        mock_settings.identity_claims_secret = "test-secret"
        mock_settings.identity_sensitive_attributes = []
        uc = UserContext(user_id="alice@co.com", email="alice@co.com")
        headers = build_identity_headers(uc)
        assert "X-Forwarded-User-Claims-Signature" in headers
        assert len(headers["X-Forwarded-User-Claims-Signature"]) == 64  # SHA-256 hex

    @patch("mcpgateway.utils.identity_propagation.settings")
    def test_delegation_chain_header(self, mock_settings):
        mock_settings.identity_propagation_enabled = True
        mock_settings.identity_propagation_mode = "headers"
        mock_settings.identity_propagation_headers_prefix = "X-Forwarded-User"
        mock_settings.identity_sign_claims = False
        mock_settings.identity_sensitive_attributes = []
        uc = UserContext(user_id="alice@co.com", delegation_chain=["service-a", "alice@co.com"])
        headers = build_identity_headers(uc)
        assert headers["X-Forwarded-User-Delegation-Chain"] == "service-a,alice@co.com"

    @patch("mcpgateway.utils.identity_propagation.settings")
    def test_per_gateway_override(self, mock_settings):
        mock_settings.identity_propagation_enabled = False  # Global disabled
        mock_settings.identity_propagation_mode = "headers"
        mock_settings.identity_propagation_headers_prefix = "X-Forwarded-User"
        mock_settings.identity_sign_claims = False
        mock_settings.identity_sensitive_attributes = []

        # Gateway overrides to enabled
        class MockGateway:
            identity_propagation = {"enabled": True, "headers_prefix": "X-GW-User"}

        uc = UserContext(user_id="alice@co.com")
        headers = build_identity_headers(uc, gateway=MockGateway())
        assert "X-GW-User-Id" in headers


# ---------------------------------------------------------------------------
# build_identity_meta tests
# ---------------------------------------------------------------------------
class TestBuildIdentityMeta:
    """Tests for build_identity_meta()."""

    @patch("mcpgateway.utils.identity_propagation.settings")
    def test_disabled_returns_existing(self, mock_settings):
        mock_settings.identity_propagation_enabled = False
        uc = UserContext(user_id="alice@co.com")
        existing = {"key": "value"}
        result = build_identity_meta(uc, existing)
        assert result == {"key": "value"}

    @patch("mcpgateway.utils.identity_propagation.settings")
    def test_basic_meta(self, mock_settings):
        mock_settings.identity_propagation_enabled = True
        mock_settings.identity_propagation_mode = "meta"
        mock_settings.identity_propagation_headers_prefix = "X-Forwarded-User"
        mock_settings.identity_sign_claims = False
        mock_settings.identity_sensitive_attributes = []
        uc = UserContext(
            user_id="alice@co.com",
            email="alice@co.com",
            groups=["eng"],
            is_admin=False,
            auth_method="bearer",
        )
        meta = build_identity_meta(uc)
        assert meta["user"]["id"] == "alice@co.com"
        assert meta["user"]["email"] == "alice@co.com"
        assert meta["user"]["groups"] == ["eng"]
        assert meta["user"]["is_admin"] is False
        assert meta["user"]["auth_method"] == "bearer"

    @patch("mcpgateway.utils.identity_propagation.settings")
    def test_merge_with_existing(self, mock_settings):
        mock_settings.identity_propagation_enabled = True
        mock_settings.identity_propagation_mode = "meta"
        mock_settings.identity_propagation_headers_prefix = "X-Forwarded-User"
        mock_settings.identity_sign_claims = False
        mock_settings.identity_sensitive_attributes = []
        uc = UserContext(user_id="alice@co.com")
        existing = {"trace_id": "abc123"}
        meta = build_identity_meta(uc, existing)
        assert meta["trace_id"] == "abc123"
        assert meta["user"]["id"] == "alice@co.com"

    @patch("mcpgateway.utils.identity_propagation.settings")
    def test_none_existing_meta(self, mock_settings):
        mock_settings.identity_propagation_enabled = True
        mock_settings.identity_propagation_mode = "meta"
        mock_settings.identity_propagation_headers_prefix = "X-Forwarded-User"
        mock_settings.identity_sign_claims = False
        mock_settings.identity_sensitive_attributes = []
        uc = UserContext(user_id="x")
        meta = build_identity_meta(uc, None)
        assert "user" in meta


# ---------------------------------------------------------------------------
# filter_sensitive_attributes tests
# ---------------------------------------------------------------------------
class TestFilterSensitiveAttributes:
    """Tests for filter_sensitive_attributes()."""

    def test_removes_sensitive_keys(self):
        uc = UserContext(
            user_id="alice@co.com",
            attributes={"password_hash": "secret", "department": "eng", "ssn": "123"},
        )
        filtered = filter_sensitive_attributes(uc, ["password_hash", "ssn"])
        assert "password_hash" not in filtered.attributes
        assert "ssn" not in filtered.attributes
        assert filtered.attributes["department"] == "eng"

    def test_original_unchanged(self):
        uc = UserContext(user_id="alice@co.com", attributes={"password_hash": "secret"})
        filtered = filter_sensitive_attributes(uc, ["password_hash"])
        assert "password_hash" in uc.attributes  # Original unchanged
        assert "password_hash" not in filtered.attributes

    def test_empty_sensitive_list(self):
        uc = UserContext(user_id="alice@co.com", attributes={"a": 1, "b": 2})
        filtered = filter_sensitive_attributes(uc, [])
        assert filtered.attributes == {"a": 1, "b": 2}


# ---------------------------------------------------------------------------
# GlobalContext.user_context tests
# ---------------------------------------------------------------------------
class TestGlobalContextUserContext:
    """Tests for GlobalContext.user_context field."""

    def test_default_none(self):
        ctx = GlobalContext(request_id="req-1")
        assert ctx.user_context is None

    def test_set_user_context(self):
        uc = UserContext(user_id="alice@co.com", is_admin=True)
        ctx = GlobalContext(request_id="req-1", user_context=uc)
        assert ctx.user_context.user_id == "alice@co.com"
        assert ctx.user_context.is_admin is True

    def test_backward_compat_user_dict(self):
        ctx = GlobalContext(
            request_id="req-1",
            user={"email": "alice@co.com", "is_admin": True},
            user_context=UserContext(user_id="alice@co.com"),
        )
        assert ctx.user["email"] == "alice@co.com"
        assert ctx.user_context.user_id == "alice@co.com"


# ---------------------------------------------------------------------------
# PluginContext convenience helpers tests
# ---------------------------------------------------------------------------
class TestPluginContextHelpers:
    """Tests for PluginContext convenience properties."""

    def test_user_context_property(self):
        uc = UserContext(user_id="alice@co.com", groups=["eng"])
        gctx = GlobalContext(request_id="req-1", user_context=uc)
        ctx = PluginContext(global_context=gctx)
        assert ctx.user_context is uc

    def test_user_context_none(self):
        gctx = GlobalContext(request_id="req-1")
        ctx = PluginContext(global_context=gctx)
        assert ctx.user_context is None

    def test_user_email_from_user_context(self):
        uc = UserContext(user_id="alice@co.com", email="alice@co.com")
        gctx = GlobalContext(request_id="req-1", user_context=uc)
        ctx = PluginContext(global_context=gctx)
        assert ctx.user_email == "alice@co.com"

    def test_user_email_from_legacy_string(self):
        gctx = GlobalContext(request_id="req-1", user="bob@co.com")
        ctx = PluginContext(global_context=gctx)
        assert ctx.user_email == "bob@co.com"

    def test_user_email_from_legacy_dict(self):
        gctx = GlobalContext(request_id="req-1", user={"email": "charlie@co.com"})
        ctx = PluginContext(global_context=gctx)
        assert ctx.user_email == "charlie@co.com"

    def test_user_email_none(self):
        gctx = GlobalContext(request_id="req-1")
        ctx = PluginContext(global_context=gctx)
        assert ctx.user_email is None

    def test_user_groups_from_context(self):
        uc = UserContext(user_id="alice@co.com", groups=["eng", "dev"])
        gctx = GlobalContext(request_id="req-1", user_context=uc)
        ctx = PluginContext(global_context=gctx)
        assert ctx.user_groups == ["eng", "dev"]

    def test_user_groups_empty_default(self):
        gctx = GlobalContext(request_id="req-1")
        ctx = PluginContext(global_context=gctx)
        assert ctx.user_groups == []

    def test_user_email_none_when_uc_email_is_none(self):
        uc = UserContext(user_id="alice@co.com")  # email is None
        gctx = GlobalContext(request_id="req-1", user_context=uc)
        ctx = PluginContext(global_context=gctx)
        assert ctx.user_email is None

    def test_user_groups_empty_list_from_uc(self):
        uc = UserContext(user_id="alice@co.com", groups=[])
        gctx = GlobalContext(request_id="req-1", user_context=uc)
        ctx = PluginContext(global_context=gctx)
        assert ctx.user_groups == []


# ---------------------------------------------------------------------------
# _resolve_config tests
# ---------------------------------------------------------------------------
class TestResolveConfig:
    """Tests for _resolve_config() per-gateway overrides."""

    @patch("mcpgateway.utils.identity_propagation.settings")
    def test_no_gateway_uses_global(self, mock_settings):
        mock_settings.identity_propagation_enabled = True
        mock_settings.identity_propagation_mode = "both"
        mock_settings.identity_propagation_headers_prefix = "X-Forwarded-User"
        mock_settings.identity_sign_claims = False
        mock_settings.identity_sensitive_attributes = ["ssn"]
        cfg = _resolve_config(None)
        assert cfg["enabled"] is True
        assert cfg["mode"] == "both"
        assert cfg["headers_prefix"] == "X-Forwarded-User"
        assert cfg["sign_claims"] is False
        assert cfg["sensitive_attributes"] == ["ssn"]

    @patch("mcpgateway.utils.identity_propagation.settings")
    def test_gateway_with_none_identity_propagation(self, mock_settings):
        mock_settings.identity_propagation_enabled = True
        mock_settings.identity_propagation_mode = "headers"
        mock_settings.identity_propagation_headers_prefix = "X-Forwarded-User"
        mock_settings.identity_sign_claims = False
        mock_settings.identity_sensitive_attributes = []

        class GW:
            identity_propagation = None

        cfg = _resolve_config(GW())
        assert cfg["enabled"] is True  # Falls back to global

    @patch("mcpgateway.utils.identity_propagation.settings")
    def test_gateway_overrides_mode(self, mock_settings):
        mock_settings.identity_propagation_enabled = True
        mock_settings.identity_propagation_mode = "both"
        mock_settings.identity_propagation_headers_prefix = "X-Forwarded-User"
        mock_settings.identity_sign_claims = False
        mock_settings.identity_sensitive_attributes = []

        class GW:
            identity_propagation = {"mode": "meta"}

        cfg = _resolve_config(GW())
        assert cfg["mode"] == "meta"

    @patch("mcpgateway.utils.identity_propagation.settings")
    def test_gateway_overrides_sign_claims(self, mock_settings):
        mock_settings.identity_propagation_enabled = True
        mock_settings.identity_propagation_mode = "headers"
        mock_settings.identity_propagation_headers_prefix = "X-Forwarded-User"
        mock_settings.identity_sign_claims = False
        mock_settings.identity_sensitive_attributes = []

        class GW:
            identity_propagation = {"sign_claims": True}

        cfg = _resolve_config(GW())
        assert cfg["sign_claims"] is True

    @patch("mcpgateway.utils.identity_propagation.settings")
    def test_gateway_overrides_sensitive_attributes(self, mock_settings):
        mock_settings.identity_propagation_enabled = True
        mock_settings.identity_propagation_mode = "headers"
        mock_settings.identity_propagation_headers_prefix = "X-Forwarded-User"
        mock_settings.identity_sign_claims = False
        mock_settings.identity_sensitive_attributes = ["ssn"]

        class GW:
            identity_propagation = {"sensitive_attributes": ["internal_id"]}

        cfg = _resolve_config(GW())
        assert cfg["sensitive_attributes"] == ["internal_id"]

    @patch("mcpgateway.utils.identity_propagation.settings")
    def test_gateway_without_identity_propagation_attr(self, mock_settings):
        mock_settings.identity_propagation_enabled = False
        mock_settings.identity_propagation_mode = "both"
        mock_settings.identity_propagation_headers_prefix = "X-Forwarded-User"
        mock_settings.identity_sign_claims = False
        mock_settings.identity_sensitive_attributes = []

        class GW:
            pass  # No identity_propagation attr

        cfg = _resolve_config(GW())
        assert cfg["enabled"] is False  # Falls back to global


# ---------------------------------------------------------------------------
# _sign_claims tests
# ---------------------------------------------------------------------------
class TestSignClaims:
    """Tests for _sign_claims() HMAC signing."""

    @patch("mcpgateway.utils.identity_propagation.settings")
    def test_uses_identity_claims_secret(self, mock_settings):
        mock_settings.identity_claims_secret = "my-secret"
        sig = _sign_claims("test-payload")
        assert len(sig) == 64  # SHA-256 hex

    @patch("mcpgateway.utils.identity_propagation.settings")
    def test_falls_back_to_jwt_secret(self, mock_settings):
        mock_settings.identity_claims_secret = None
        mock_settings.jwt_secret_key = SecretStr("jwt-fallback-secret")
        sig = _sign_claims("test-payload")
        assert len(sig) == 64

    @patch("mcpgateway.utils.identity_propagation.settings")
    def test_falls_back_to_empty_when_no_secrets(self, mock_settings):
        mock_settings.identity_claims_secret = None
        mock_settings.jwt_secret_key = None
        sig = _sign_claims("test-payload")
        assert len(sig) == 64  # Still produces a valid HMAC (with empty key)


# ---------------------------------------------------------------------------
# build_identity_headers — additional branch coverage
# ---------------------------------------------------------------------------
class TestBuildIdentityHeadersBranches:
    """Additional tests for build_identity_headers() optional field branches."""

    @patch("mcpgateway.utils.identity_propagation.settings")
    def test_roles_header(self, mock_settings):
        mock_settings.identity_propagation_enabled = True
        mock_settings.identity_propagation_mode = "headers"
        mock_settings.identity_propagation_headers_prefix = "X-Forwarded-User"
        mock_settings.identity_sign_claims = False
        mock_settings.identity_sensitive_attributes = []
        uc = UserContext(user_id="alice@co.com", roles=["developer", "reviewer"])
        headers = build_identity_headers(uc)
        assert headers["X-Forwarded-User-Roles"] == "developer,reviewer"

    @patch("mcpgateway.utils.identity_propagation.settings")
    def test_service_account_header(self, mock_settings):
        mock_settings.identity_propagation_enabled = True
        mock_settings.identity_propagation_mode = "headers"
        mock_settings.identity_propagation_headers_prefix = "X-Forwarded-User"
        mock_settings.identity_sign_claims = False
        mock_settings.identity_sensitive_attributes = []
        uc = UserContext(user_id="alice@co.com", service_account="ci-bot")
        headers = build_identity_headers(uc)
        assert headers["X-Forwarded-User-Service-Account"] == "ci-bot"

    @patch("mcpgateway.utils.identity_propagation.settings")
    def test_no_email_header_when_email_none(self, mock_settings):
        mock_settings.identity_propagation_enabled = True
        mock_settings.identity_propagation_mode = "headers"
        mock_settings.identity_propagation_headers_prefix = "X-Forwarded-User"
        mock_settings.identity_sign_claims = False
        mock_settings.identity_sensitive_attributes = []
        uc = UserContext(user_id="alice@co.com")  # email is None
        headers = build_identity_headers(uc)
        assert "X-Forwarded-User-Id" in headers
        assert "X-Forwarded-User-Email" not in headers

    @patch("mcpgateway.utils.identity_propagation.settings")
    def test_no_teams_header_when_teams_none(self, mock_settings):
        mock_settings.identity_propagation_enabled = True
        mock_settings.identity_propagation_mode = "headers"
        mock_settings.identity_propagation_headers_prefix = "X-Forwarded-User"
        mock_settings.identity_sign_claims = False
        mock_settings.identity_sensitive_attributes = []
        uc = UserContext(user_id="alice@co.com")  # teams is None
        headers = build_identity_headers(uc)
        assert "X-Forwarded-User-Teams" not in headers

    @patch("mcpgateway.utils.identity_propagation.settings")
    def test_no_roles_header_when_empty(self, mock_settings):
        mock_settings.identity_propagation_enabled = True
        mock_settings.identity_propagation_mode = "headers"
        mock_settings.identity_propagation_headers_prefix = "X-Forwarded-User"
        mock_settings.identity_sign_claims = False
        mock_settings.identity_sensitive_attributes = []
        uc = UserContext(user_id="alice@co.com", roles=[])
        headers = build_identity_headers(uc)
        assert "X-Forwarded-User-Roles" not in headers

    @patch("mcpgateway.utils.identity_propagation.settings")
    def test_team_id_header(self, mock_settings):
        mock_settings.identity_propagation_enabled = True
        mock_settings.identity_propagation_mode = "headers"
        mock_settings.identity_propagation_headers_prefix = "X-Forwarded-User"
        mock_settings.identity_sign_claims = False
        mock_settings.identity_sensitive_attributes = []
        uc = UserContext(user_id="alice@co.com", team_id="team-alpha")
        headers = build_identity_headers(uc)
        # team_id is not directly a header field in the implementation;
        # only teams list is. Verify it doesn't error.
        assert "X-Forwarded-User-Id" in headers

    @patch("mcpgateway.utils.identity_propagation.settings")
    def test_gateway_disables_when_global_enabled(self, mock_settings):
        mock_settings.identity_propagation_enabled = True
        mock_settings.identity_propagation_mode = "both"
        mock_settings.identity_propagation_headers_prefix = "X-Forwarded-User"
        mock_settings.identity_sign_claims = False
        mock_settings.identity_sensitive_attributes = []

        class GW:
            identity_propagation = {"enabled": False}

        uc = UserContext(user_id="alice@co.com")
        headers = build_identity_headers(uc, gateway=GW())
        assert headers == {}


# ---------------------------------------------------------------------------
# build_identity_meta — additional branch coverage
# ---------------------------------------------------------------------------
class TestBuildIdentityMetaBranches:
    """Additional tests for build_identity_meta() optional field branches."""

    @patch("mcpgateway.utils.identity_propagation.settings")
    def test_meta_includes_roles(self, mock_settings):
        mock_settings.identity_propagation_enabled = True
        mock_settings.identity_propagation_mode = "meta"
        mock_settings.identity_propagation_headers_prefix = "X-Forwarded-User"
        mock_settings.identity_sign_claims = False
        mock_settings.identity_sensitive_attributes = []
        uc = UserContext(user_id="alice@co.com", roles=["developer"])
        meta = build_identity_meta(uc)
        assert meta["user"]["roles"] == ["developer"]

    @patch("mcpgateway.utils.identity_propagation.settings")
    def test_meta_includes_teams(self, mock_settings):
        mock_settings.identity_propagation_enabled = True
        mock_settings.identity_propagation_mode = "meta"
        mock_settings.identity_propagation_headers_prefix = "X-Forwarded-User"
        mock_settings.identity_sign_claims = False
        mock_settings.identity_sensitive_attributes = []
        uc = UserContext(user_id="alice@co.com", teams=["t1", "t2"])
        meta = build_identity_meta(uc)
        assert meta["user"]["teams"] == ["t1", "t2"]

    @patch("mcpgateway.utils.identity_propagation.settings")
    def test_meta_includes_service_account(self, mock_settings):
        mock_settings.identity_propagation_enabled = True
        mock_settings.identity_propagation_mode = "meta"
        mock_settings.identity_propagation_headers_prefix = "X-Forwarded-User"
        mock_settings.identity_sign_claims = False
        mock_settings.identity_sensitive_attributes = []
        uc = UserContext(user_id="alice@co.com", service_account="bot")
        meta = build_identity_meta(uc)
        assert meta["user"]["service_account"] == "bot"

    @patch("mcpgateway.utils.identity_propagation.settings")
    def test_meta_includes_delegation_chain(self, mock_settings):
        mock_settings.identity_propagation_enabled = True
        mock_settings.identity_propagation_mode = "meta"
        mock_settings.identity_propagation_headers_prefix = "X-Forwarded-User"
        mock_settings.identity_sign_claims = False
        mock_settings.identity_sensitive_attributes = []
        uc = UserContext(user_id="alice@co.com", delegation_chain=["svc", "alice"])
        meta = build_identity_meta(uc)
        assert meta["user"]["delegation_chain"] == ["svc", "alice"]

    @patch("mcpgateway.utils.identity_propagation.settings")
    def test_meta_includes_full_name(self, mock_settings):
        mock_settings.identity_propagation_enabled = True
        mock_settings.identity_propagation_mode = "meta"
        mock_settings.identity_propagation_headers_prefix = "X-Forwarded-User"
        mock_settings.identity_sign_claims = False
        mock_settings.identity_sensitive_attributes = []
        uc = UserContext(user_id="alice@co.com", full_name="Alice Smith")
        meta = build_identity_meta(uc)
        assert meta["user"]["full_name"] == "Alice Smith"

    @patch("mcpgateway.utils.identity_propagation.settings")
    def test_meta_gateway_override(self, mock_settings):
        mock_settings.identity_propagation_enabled = False
        mock_settings.identity_propagation_mode = "meta"
        mock_settings.identity_propagation_headers_prefix = "X-Forwarded-User"
        mock_settings.identity_sign_claims = False
        mock_settings.identity_sensitive_attributes = []

        class GW:
            identity_propagation = {"enabled": True}

        uc = UserContext(user_id="alice@co.com", email="alice@co.com")
        meta = build_identity_meta(uc, gateway=GW())
        assert meta["user"]["id"] == "alice@co.com"

    @patch("mcpgateway.utils.identity_propagation.settings")
    def test_meta_disabled_returns_empty_when_none_existing(self, mock_settings):
        mock_settings.identity_propagation_enabled = False
        uc = UserContext(user_id="alice@co.com")
        meta = build_identity_meta(uc, None)
        assert meta == {}


# ---------------------------------------------------------------------------
# filter_sensitive_attributes — settings fallback
# ---------------------------------------------------------------------------
class TestFilterSensitiveAttributesFallback:
    """Test filter_sensitive_attributes() settings fallback path."""

    @patch("mcpgateway.utils.identity_propagation.settings")
    def test_uses_settings_when_keys_none(self, mock_settings):
        mock_settings.identity_sensitive_attributes = ["password_hash", "ssn"]
        uc = UserContext(
            user_id="alice@co.com",
            attributes={"password_hash": "secret", "dept": "eng", "ssn": "123"},
        )
        filtered = filter_sensitive_attributes(uc)  # No explicit sensitive_keys
        assert "password_hash" not in filtered.attributes
        assert "ssn" not in filtered.attributes
        assert filtered.attributes["dept"] == "eng"


# ---------------------------------------------------------------------------
# _set_user_identity_from_dict tests
# ---------------------------------------------------------------------------
class TestSetUserIdentityFromDict:
    """Tests for _set_user_identity_from_dict() in streamablehttp_transport."""

    def test_sets_identity_with_email(self):
        # First-Party
        from mcpgateway.transports.streamablehttp_transport import _set_user_identity_from_dict, user_identity_var

        _set_user_identity_from_dict(
            {
                "email": "alice@co.com",
                "is_admin": True,
                "teams": ["t1", "t2"],
                "auth_method": "sso",
            }
        )
        uc = user_identity_var.get()
        assert uc is not None
        assert uc.user_id == "alice@co.com"
        assert uc.email == "alice@co.com"
        assert uc.is_admin is True
        assert uc.teams == ["t1", "t2"]
        assert uc.auth_method == "sso"
        assert uc.authenticated_at is not None
        # Reset
        user_identity_var.set(None)

    def test_noop_without_email(self):
        # First-Party
        from mcpgateway.transports.streamablehttp_transport import _set_user_identity_from_dict, user_identity_var

        user_identity_var.set(None)
        _set_user_identity_from_dict({"is_admin": False})
        assert user_identity_var.get() is None

    def test_defaults_auth_method_to_bearer(self):
        # First-Party
        from mcpgateway.transports.streamablehttp_transport import _set_user_identity_from_dict, user_identity_var

        _set_user_identity_from_dict({"email": "bob@co.com"})
        uc = user_identity_var.get()
        assert uc.auth_method == "bearer"
        assert uc.is_admin is False
        assert uc.teams is None
        user_identity_var.set(None)

    def test_teams_none_when_not_in_ctx(self):
        # First-Party
        from mcpgateway.transports.streamablehttp_transport import _set_user_identity_from_dict, user_identity_var

        _set_user_identity_from_dict({"email": "bob@co.com", "teams": None})
        uc = user_identity_var.get()
        assert uc.teams is None
        user_identity_var.set(None)

    def test_proxy_auth_method(self):
        # First-Party
        from mcpgateway.transports.streamablehttp_transport import _set_user_identity_from_dict, user_identity_var

        _set_user_identity_from_dict({"email": "proxy@co.com", "auth_method": "proxy"})
        uc = user_identity_var.get()
        assert uc.auth_method == "proxy"
        user_identity_var.set(None)


# ---------------------------------------------------------------------------
# _inject_userinfo_instate — UserContext population
# ---------------------------------------------------------------------------
class TestInjectUserInfoUserContext:
    """Test that _inject_userinfo_instate populates user_context on GlobalContext."""

    def test_populates_user_context(self):
        # First-Party
        from mcpgateway.auth import _inject_userinfo_instate

        mock_user = MagicMock()
        mock_user.email = "alice@example.com"
        mock_user.is_admin = True
        mock_user.full_name = "Alice"

        mock_request = MagicMock()
        mock_request.state.plugin_global_context = None
        mock_request.state.request_id = "req-123"
        mock_request.state.auth_method = "bearer"
        mock_request.state.token_teams = ["team-1", "team-2"]
        mock_request.state.team_id = "team-1"

        with patch("mcpgateway.auth.get_correlation_id", return_value="corr-123"):
            _inject_userinfo_instate(mock_request, mock_user)

        gctx = mock_request.state.plugin_global_context
        assert gctx is not None
        assert gctx.user_context is not None
        assert gctx.user_context.user_id == "alice@example.com"
        assert gctx.user_context.email == "alice@example.com"
        assert gctx.user_context.is_admin is True
        assert gctx.user_context.full_name == "Alice"
        assert gctx.user_context.teams == ["team-1", "team-2"]
        assert gctx.user_context.team_id == "team-1"
        assert gctx.user_context.auth_method == "bearer"
        assert gctx.user_context.authenticated_at is not None

    def test_populates_legacy_user_dict(self):
        # First-Party
        from mcpgateway.auth import _inject_userinfo_instate

        mock_user = MagicMock()
        mock_user.email = "bob@example.com"
        mock_user.is_admin = False
        mock_user.full_name = "Bob"

        mock_request = MagicMock()
        mock_request.state.plugin_global_context = None
        mock_request.state.request_id = "req-456"
        mock_request.state.auth_method = "api_key"
        mock_request.state.token_teams = None
        mock_request.state.team_id = None

        with patch("mcpgateway.auth.get_correlation_id", return_value="corr-456"):
            _inject_userinfo_instate(mock_request, mock_user)

        gctx = mock_request.state.plugin_global_context
        assert gctx.user["email"] == "bob@example.com"
        assert gctx.user["is_admin"] is False
        assert gctx.user_context.teams is None  # None is not a list

    def test_with_existing_global_context(self):
        # First-Party
        from mcpgateway.auth import _inject_userinfo_instate

        mock_user = MagicMock()
        mock_user.email = "charlie@example.com"
        mock_user.is_admin = False
        mock_user.full_name = "Charlie"

        existing_gctx = GlobalContext(request_id="existing-req")
        mock_request = MagicMock()
        mock_request.state.plugin_global_context = existing_gctx
        mock_request.state.auth_method = "basic"
        mock_request.state.token_teams = []
        mock_request.state.team_id = None

        _inject_userinfo_instate(mock_request, mock_user)

        assert existing_gctx.user_context is not None
        assert existing_gctx.user_context.auth_method == "basic"
        # [] is a list, so isinstance([], list) is True → teams = []
        assert existing_gctx.user_context.teams == []

    def test_no_request_still_builds_context(self):
        # First-Party
        from mcpgateway.auth import _inject_userinfo_instate

        mock_user = MagicMock()
        mock_user.email = "nouser@example.com"
        mock_user.is_admin = False
        mock_user.full_name = "No Request"

        with patch("mcpgateway.auth.get_correlation_id", return_value="corr-789"):
            # When request is None, getattr returns None for all state attrs
            _inject_userinfo_instate(None, mock_user)
        # Should not raise — just builds context without request state

    def test_no_user_skips_context_population(self):
        # First-Party
        from mcpgateway.auth import _inject_userinfo_instate

        mock_request = MagicMock()
        mock_request.state.plugin_global_context = None
        mock_request.state.request_id = "req-no-user"

        with patch("mcpgateway.auth.get_correlation_id", return_value="corr-no-user"):
            _inject_userinfo_instate(mock_request, None)
        # Should not create user_context when user is None
        gctx = mock_request.state.plugin_global_context
        assert gctx.user_context is None


# ---------------------------------------------------------------------------
# Audit trail service — identity fields
# ---------------------------------------------------------------------------
class TestAuditTrailIdentityFields:
    """Test audit_trail_service.log_action() with new identity fields."""

    def test_log_action_with_auth_method(self, monkeypatch):
        # First-Party
        from mcpgateway.services import audit_trail_service as svc

        monkeypatch.setattr(svc.settings, "audit_trail_enabled", True)
        captured = {}

        def _fake_audit(**kwargs):
            captured.update(kwargs)
            return MagicMock()

        monkeypatch.setattr(svc, "AuditTrail", _fake_audit)

        dummy_session = MagicMock()
        monkeypatch.setattr(svc, "SessionLocal", lambda: dummy_session)

        service = svc.AuditTrailService()
        service.log_action(
            action="EXECUTE",
            resource_type="tool",
            resource_id="tool-1",
            user_id="alice@example.com",
            auth_method="bearer",
            db=dummy_session,
        )

        assert captured["auth_method"] == "bearer"

    def test_log_action_with_acting_as(self, monkeypatch):
        # First-Party
        from mcpgateway.services import audit_trail_service as svc

        monkeypatch.setattr(svc.settings, "audit_trail_enabled", True)
        captured = {}

        def _fake_audit(**kwargs):
            captured.update(kwargs)
            return MagicMock()

        monkeypatch.setattr(svc, "AuditTrail", _fake_audit)

        dummy_session = MagicMock()
        monkeypatch.setattr(svc, "SessionLocal", lambda: dummy_session)

        service = svc.AuditTrailService()
        service.log_action(
            action="EXECUTE",
            resource_type="tool",
            resource_id="tool-1",
            user_id="alice@example.com",
            acting_as="gateway-service",
            db=dummy_session,
        )

        assert captured["acting_as"] == "gateway-service"

    def test_log_action_with_delegation_chain(self, monkeypatch):
        # First-Party
        from mcpgateway.services import audit_trail_service as svc

        monkeypatch.setattr(svc.settings, "audit_trail_enabled", True)
        captured = {}

        def _fake_audit(**kwargs):
            captured.update(kwargs)
            return MagicMock()

        monkeypatch.setattr(svc, "AuditTrail", _fake_audit)

        dummy_session = MagicMock()
        monkeypatch.setattr(svc, "SessionLocal", lambda: dummy_session)

        service = svc.AuditTrailService()
        chain = {"principals": ["gateway", "alice@example.com"]}
        service.log_action(
            action="EXECUTE",
            resource_type="tool",
            resource_id="tool-1",
            user_id="alice@example.com",
            delegation_chain=chain,
            db=dummy_session,
        )

        assert captured["delegation_chain"] == chain

    def test_log_action_identity_fields_default_none(self, monkeypatch):
        # First-Party
        from mcpgateway.services import audit_trail_service as svc

        monkeypatch.setattr(svc.settings, "audit_trail_enabled", True)
        captured = {}

        def _fake_audit(**kwargs):
            captured.update(kwargs)
            return MagicMock()

        monkeypatch.setattr(svc, "AuditTrail", _fake_audit)

        dummy_session = MagicMock()
        monkeypatch.setattr(svc, "SessionLocal", lambda: dummy_session)

        service = svc.AuditTrailService()
        service.log_action(
            action="READ",
            resource_type="tool",
            resource_id="tool-1",
            user_id="user-1",
            db=dummy_session,
        )

        assert captured["auth_method"] is None
        assert captured["acting_as"] is None
        assert captured["delegation_chain"] is None


# ---------------------------------------------------------------------------
# OAuthManager.token_exchange() — RFC 8693
# ---------------------------------------------------------------------------
class TestOAuthTokenExchange:
    """Tests for OAuthManager.token_exchange() RFC 8693."""

    @pytest.mark.asyncio
    async def test_successful_exchange(self):
        # First-Party
        from mcpgateway.services.oauth_manager import OAuthManager

        manager = OAuthManager()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "access_token": "exchanged-token",
            "token_type": "Bearer",
            "expires_in": 3600,
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        manager._get_client = AsyncMock(return_value=mock_client)

        result = await manager.token_exchange(
            token_url="https://auth.example.com/token",
            subject_token="original-user-token",
            client_id="gateway-client",
            client_secret="",  # Empty = no decryption
            audience="downstream-service",
            scope="read write",
        )

        assert result["access_token"] == "exchanged-token"
        assert result["token_type"] == "Bearer"

        # Verify the POST was called with correct params
        call_kwargs = mock_client.post.call_args
        post_data = call_kwargs.kwargs.get("data") or call_kwargs[1].get("data")
        assert post_data["grant_type"] == "urn:ietf:params:oauth:grant-type:token-exchange"
        assert post_data["subject_token"] == "original-user-token"
        assert post_data["audience"] == "downstream-service"
        assert post_data["scope"] == "read write"

    @pytest.mark.asyncio
    async def test_missing_access_token_raises(self):
        # First-Party
        from mcpgateway.services.oauth_manager import OAuthError, OAuthManager

        manager = OAuthManager()
        mock_response = MagicMock()
        mock_response.json.return_value = {"error": "invalid_grant"}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        manager._get_client = AsyncMock(return_value=mock_client)

        with pytest.raises(OAuthError, match="No access_token"):
            await manager.token_exchange(
                token_url="https://auth.example.com/token",
                subject_token="token",
                client_id="client",
                client_secret="",
            )

    @pytest.mark.asyncio
    async def test_http_error_retries_and_raises(self):
        # First-Party
        from mcpgateway.services.oauth_manager import OAuthError, OAuthManager

        manager = OAuthManager(max_retries=2)

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.HTTPError("connection failed"))
        manager._get_client = AsyncMock(return_value=mock_client)

        with pytest.raises(OAuthError, match="Token exchange failed"):
            await manager.token_exchange(
                token_url="https://auth.example.com/token",
                subject_token="token",
                client_id="client",
                client_secret="",
            )

        assert mock_client.post.call_count == 2

    @pytest.mark.asyncio
    async def test_no_audience_or_scope(self):
        # First-Party
        from mcpgateway.services.oauth_manager import OAuthManager

        manager = OAuthManager()
        mock_response = MagicMock()
        mock_response.json.return_value = {"access_token": "tok"}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        manager._get_client = AsyncMock(return_value=mock_client)

        result = await manager.token_exchange(
            token_url="https://auth.example.com/token",
            subject_token="token",
            client_id="client",
            client_secret="",
        )

        assert result["access_token"] == "tok"
        call_kwargs = mock_client.post.call_args
        post_data = call_kwargs.kwargs.get("data") or call_kwargs[1].get("data")
        assert "audience" not in post_data
        assert "scope" not in post_data

    @pytest.mark.asyncio
    async def test_client_secret_decryption_failure_continues(self):
        # First-Party
        from mcpgateway.services.oauth_manager import OAuthManager

        manager = OAuthManager()
        mock_response = MagicMock()
        mock_response.json.return_value = {"access_token": "tok"}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        manager._get_client = AsyncMock(return_value=mock_client)

        # Even with a non-empty secret that causes decryption to fail,
        # the original secret is used
        with patch("mcpgateway.services.oauth_manager.get_settings"), patch("mcpgateway.services.oauth_manager.get_encryption_service") as mock_get_enc:
            mock_get_enc.side_effect = Exception("encryption not available")
            result = await manager.token_exchange(
                token_url="https://auth.example.com/token",
                subject_token="token",
                client_id="client",
                client_secret="raw-secret",
            )
            assert result["access_token"] == "tok"


# ---------------------------------------------------------------------------
# MCP session pool identity headers
# ---------------------------------------------------------------------------
class TestSessionPoolIdentityHeaders:
    """Test that identity headers are in ManagedSessionPool.DEFAULT_IDENTITY_HEADERS."""

    def test_identity_headers_included(self):
        # First-Party
        from mcpgateway.services.mcp_session_pool import MCPSessionPool

        assert "x-forwarded-user-id" in MCPSessionPool.DEFAULT_IDENTITY_HEADERS
        assert "x-forwarded-user-email" in MCPSessionPool.DEFAULT_IDENTITY_HEADERS


# ---------------------------------------------------------------------------
# Schema validation for identity_propagation field
# ---------------------------------------------------------------------------
class TestSchemaIdentityPropagation:
    """Test Pydantic schemas accept identity_propagation field."""

    def test_gateway_create_accepts_identity_propagation(self):
        # First-Party
        from mcpgateway.schemas import GatewayCreate

        gw = GatewayCreate(
            name="test-gw",
            url="https://example.com",
            identity_propagation={"enabled": True, "mode": "headers"},
        )
        assert gw.identity_propagation["enabled"] is True

    def test_gateway_create_identity_propagation_defaults_none(self):
        # First-Party
        from mcpgateway.schemas import GatewayCreate

        gw = GatewayCreate(name="test-gw", url="https://example.com")
        assert gw.identity_propagation is None

    def test_gateway_update_accepts_identity_propagation(self):
        # First-Party
        from mcpgateway.schemas import GatewayUpdate

        gw = GatewayUpdate(identity_propagation={"enabled": False})
        assert gw.identity_propagation["enabled"] is False
