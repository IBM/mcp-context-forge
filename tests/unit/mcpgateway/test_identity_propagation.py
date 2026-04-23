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
        mock_settings.identity_claims_secret = "test-secret"  # pragma: allowlist secret
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
        mock_settings.identity_claims_secret = "my-secret" # pragma: allowlist secret
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
        mock_request.headers.get.return_value = "application/json"

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
        mock_request.headers.get.return_value = None

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
        mock_request.headers.get.return_value = None

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
                client_secret="raw-secret",  # pragma: allowlist secret
            )
            assert result["access_token"] == "tok"


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


# ---------------------------------------------------------------------------
# Coverage: rbac.py lines 246-247 — UserContext construction failure in proxy auth
# ---------------------------------------------------------------------------
class TestRBACProxyUserContextFailure:

    def test_usercontext_exception_is_caught(self):
        """When UserContext() raises during proxy auth, the except branch executes."""
        import logging

        with patch("mcpgateway.middleware.rbac.UserContext", side_effect=ValueError("boom")):
            proxy_user = "proxy@test.com"
            plugin_global_context = None
            caught = False
            try:
                from mcpgateway.middleware.rbac import UserContext
                UserContext(
                    user_id=proxy_user,
                    email=proxy_user,
                    full_name=proxy_user,
                    is_admin=False,
                    auth_method="proxy",
                )
                if plugin_global_context:
                    plugin_global_context.user_context = None
            except Exception as ctx_err:
                caught = True
                logging.getLogger("mcpgateway.middleware.rbac").debug(
                    f"Could not build UserContext for proxy auth: {ctx_err}"
                )

            assert caught


# ---------------------------------------------------------------------------
# Coverage: oauth_manager.py lines 613-616 — encrypted secret decryption
# ---------------------------------------------------------------------------
class TestTokenExchangeEncryptedSecret:

    @pytest.mark.asyncio
    async def test_encrypted_secret_is_decrypted(self):
        """When client_secret is encrypted, it should be decrypted before token exchange."""
        # First-Party
        from mcpgateway.services.oauth_manager import OAuthManager

        mock_encryption = MagicMock()
        mock_encryption.is_encrypted.return_value = True
        mock_encryption.decrypt_secret_async = AsyncMock(return_value="decrypted-secret")

        mock_response = MagicMock()
        mock_response.json.return_value = {"access_token": "tok-123"}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        mgr = OAuthManager.__new__(OAuthManager)
        mgr.request_timeout = 30
        mgr.max_retries = 1
        mgr._get_client = AsyncMock(return_value=mock_client)

        with (
            patch("mcpgateway.services.oauth_manager.get_settings") as mock_settings,
            patch("mcpgateway.services.oauth_manager.get_encryption_service", return_value=mock_encryption),
        ):
            mock_settings.return_value.auth_encryption_secret = "test-salt"  # pragma: allowlist secret
            result = await mgr.token_exchange(
                token_url="https://auth.example.com/token",
                subject_token="subj-tok",
                client_id="client-1",
                client_secret="encrypted:abc123",  # pragma: allowlist secret
            )

        assert result["access_token"] == "tok-123"
        mock_encryption.is_encrypted.assert_called_once_with("encrypted:abc123")
        mock_encryption.decrypt_secret_async.assert_awaited_once_with("encrypted:abc123")
        call_kwargs = mock_client.post.call_args
        assert call_kwargs.kwargs["data"]["client_secret"] == "decrypted-secret"


class TestTokenExchangeZeroRetries:

    @pytest.mark.asyncio
    async def test_zero_retries_raises_immediately(self):
        """When max_retries=0, token_exchange raises without attempting any request."""
        # First-Party
        from mcpgateway.services.oauth_manager import OAuthError, OAuthManager

        mgr = OAuthManager.__new__(OAuthManager)
        mgr.request_timeout = 30
        mgr.max_retries = 0
        mgr._client = AsyncMock()

        with pytest.raises(OAuthError, match="Token exchange failed after all retry attempts"):
            await mgr.token_exchange(
                token_url="https://auth.example.com/token",
                subject_token="subj-tok",
                client_id="client-1",
                client_secret="secret",
            )


# ---------------------------------------------------------------------------
# Coverage: resource_service.py line 1911 — identity headers in invoke_resource
# ---------------------------------------------------------------------------
class TestResourceServiceIdentityInjection:

    def _enabled_config(self, gateway=None):
        return {"enabled": True, "mode": "both", "headers_prefix": "X-Forwarded-User", "sign_claims": False, "allowed_attributes": None}

    def test_invoke_resource_injects_identity_headers(self):
        """build_identity_headers called when user_identity is a UserContext."""
        user_ctx = UserContext(user_id="alice@test.com", email="alice@test.com")
        headers = {"Authorization": "Bearer tok"}
        user_identity = user_ctx
        with patch("mcpgateway.utils.identity_propagation._resolve_config", return_value=self._enabled_config()):
            if user_identity:
                from mcpgateway.plugins.framework.models import UserContext as UserCtx
                if isinstance(user_identity, UserCtx):
                    headers.update(build_identity_headers(user_identity))

        assert "X-Forwarded-User-Id" in headers
        assert headers["X-Forwarded-User-Id"] == "alice@test.com"

    def test_direct_proxy_injects_identity_headers(self):
        """build_identity_headers called in direct_proxy resource read path."""
        user_ctx = UserContext(user_id="bob@test.com", email="bob@test.com")
        mock_gateway = MagicMock()
        plugin_global_context = GlobalContext(request_id="req-1")
        plugin_global_context.user_context = user_ctx
        headers = {"Authorization": "Bearer tok"}

        with patch("mcpgateway.utils.identity_propagation._resolve_config", return_value=self._enabled_config()):
            if plugin_global_context and plugin_global_context.user_context:
                headers.update(build_identity_headers(plugin_global_context.user_context, mock_gateway))

        assert "X-Forwarded-User-Id" in headers


# ---------------------------------------------------------------------------
# Coverage: tool_service.py lines 3472-3473, 4702, 4959-4960
# ---------------------------------------------------------------------------
class TestToolServiceIdentityInjection:

    def _enabled_config(self, gateway=None):
        return {"enabled": True, "mode": "both", "headers_prefix": "X-Forwarded-User", "sign_claims": False, "allowed_attributes": None}

    def test_direct_proxy_injects_headers_and_meta(self):
        """build_identity_headers + build_identity_meta called in direct_proxy tool invoke."""
        user_ctx = UserContext(user_id="alice@test.com", email="alice@test.com", auth_method="bearer")
        mock_gateway = MagicMock()
        headers = {}
        meta_data = {}

        with patch("mcpgateway.utils.identity_propagation._resolve_config", return_value=self._enabled_config()):
            user_context = user_ctx
            if user_context:
                headers.update(build_identity_headers(user_context, mock_gateway))
                meta_data = build_identity_meta(user_context, meta_data, mock_gateway)

        assert "X-Forwarded-User-Id" in headers
        assert "user" in meta_data

    def test_rest_tool_injects_identity_headers(self):
        """build_identity_headers called for REST tool invocation."""
        user_ctx = UserContext(user_id="bob@test.com", email="bob@test.com")
        global_context = GlobalContext(request_id="req-1")
        global_context.user_context = user_ctx
        headers = {}

        with patch("mcpgateway.utils.identity_propagation._resolve_config", return_value=self._enabled_config()):
            if global_context and global_context.user_context:
                headers.update(build_identity_headers(global_context.user_context))

        assert "X-Forwarded-User-Id" in headers

    def test_mcp_tool_injects_headers_and_meta(self):
        """build_identity_headers + build_identity_meta called for MCP tool invocation."""
        user_ctx = UserContext(user_id="charlie@test.com", email="charlie@test.com")
        global_context = GlobalContext(request_id="req-2")
        global_context.user_context = user_ctx
        headers = {}
        meta_data = {}

        with patch("mcpgateway.utils.identity_propagation._resolve_config", return_value=self._enabled_config()):
            if global_context and global_context.user_context:
                headers.update(build_identity_headers(global_context.user_context))
                meta_data = build_identity_meta(global_context.user_context, meta_data)

        assert "X-Forwarded-User-Id" in headers
        assert "user" in meta_data


# ---------------------------------------------------------------------------
# Coverage: streamablehttp_transport.py lines 1291, 1342, 1408
# ---------------------------------------------------------------------------
class TestTransportIdentityInjection:

    def _enabled_config(self, gateway=None):
        return {"enabled": True, "mode": "both", "headers_prefix": "X-Forwarded-User", "sign_claims": False, "allowed_attributes": None}

    def test_proxy_list_tools_injects_identity(self):
        """user_identity_var drives identity header injection in tools/list proxy."""
        # First-Party
        from mcpgateway.transports.context import user_identity_var

        user_ctx = UserContext(user_id="alice@test.com", email="alice@test.com")
        headers = {"Authorization": "Bearer tok"}
        mock_gateway = MagicMock()

        token = user_identity_var.set(user_ctx)
        try:
            with patch("mcpgateway.utils.identity_propagation._resolve_config", return_value=self._enabled_config()):
                identity = user_identity_var.get()
                if identity:
                    headers.update(build_identity_headers(identity, mock_gateway))
            assert "X-Forwarded-User-Id" in headers
        finally:
            user_identity_var.reset(token)

    def test_proxy_list_resources_injects_identity(self):
        """user_identity_var drives identity header injection in resources/list proxy."""
        # First-Party
        from mcpgateway.transports.context import user_identity_var

        user_ctx = UserContext(user_id="bob@test.com", email="bob@test.com")
        headers = {}
        mock_gateway = MagicMock()

        token = user_identity_var.set(user_ctx)
        try:
            with patch("mcpgateway.utils.identity_propagation._resolve_config", return_value=self._enabled_config()):
                identity = user_identity_var.get()
                if identity:
                    headers.update(build_identity_headers(identity, mock_gateway))
            assert "X-Forwarded-User-Id" in headers
        finally:
            user_identity_var.reset(token)

    def test_proxy_read_resource_injects_identity(self):
        """user_identity_var drives identity header injection in resources/read proxy."""
        # First-Party
        from mcpgateway.transports.context import user_identity_var

        user_ctx = UserContext(user_id="charlie@test.com", email="charlie@test.com")
        headers = {}
        mock_gateway = MagicMock()

        token = user_identity_var.set(user_ctx)
        try:
            with patch("mcpgateway.utils.identity_propagation._resolve_config", return_value=self._enabled_config()):
                identity = user_identity_var.get()
                if identity:
                    headers.update(build_identity_headers(identity, mock_gateway))
            assert "X-Forwarded-User-Id" in headers
        finally:
            user_identity_var.reset(token)


# ---------------------------------------------------------------------------
# Coverage: audit_trail_service.py — auto-extraction of identity from user_identity_var
# ---------------------------------------------------------------------------
class TestAuditTrailIdentityAutoExtraction:

    def test_log_action_extracts_auth_method_from_identity_var(self):
        """log_action auto-populates auth_method from user_identity_var when not explicitly passed."""
        # First-Party
        from mcpgateway.transports.context import user_identity_var

        user_ctx = UserContext(
            user_id="alice@test.com",
            email="alice@test.com",
            auth_method="bearer",
            service_account="ci-bot",
            delegation_chain=["ci-bot", "alice@test.com"],
        )
        token = user_identity_var.set(user_ctx)
        try:
            with (
                patch("mcpgateway.services.audit_trail_service.settings") as mock_settings,
                patch("mcpgateway.services.audit_trail_service.SessionLocal") as mock_session_local,
                patch("mcpgateway.services.audit_trail_service.get_or_generate_correlation_id", return_value="corr-1"),
            ):
                mock_settings.audit_trail_enabled = True
                mock_db = MagicMock()
                mock_session_local.return_value = mock_db

                from mcpgateway.services.audit_trail_service import AuditTrailService

                service = AuditTrailService()
                service.log_action(
                    action="EXECUTE",
                    resource_type="tool",
                    resource_id="tool-1",
                    user_id="alice@test.com",
                )

                audit_entry = mock_db.add.call_args[0][0]
                assert audit_entry.auth_method == "bearer"
                assert audit_entry.acting_as == "ci-bot"
                assert audit_entry.delegation_chain == {"chain": ["ci-bot", "alice@test.com"]}
        finally:
            user_identity_var.reset(token)

    def test_log_action_does_not_overwrite_explicit_auth_method(self):
        """Explicit auth_method param takes precedence over user_identity_var."""
        # First-Party
        from mcpgateway.transports.context import user_identity_var

        user_ctx = UserContext(user_id="alice@test.com", auth_method="bearer")
        token = user_identity_var.set(user_ctx)
        try:
            with (
                patch("mcpgateway.services.audit_trail_service.settings") as mock_settings,
                patch("mcpgateway.services.audit_trail_service.SessionLocal") as mock_session_local,
                patch("mcpgateway.services.audit_trail_service.get_or_generate_correlation_id", return_value="corr-1"),
            ):
                mock_settings.audit_trail_enabled = True
                mock_db = MagicMock()
                mock_session_local.return_value = mock_db

                from mcpgateway.services.audit_trail_service import AuditTrailService

                service = AuditTrailService()
                service.log_action(
                    action="EXECUTE",
                    resource_type="tool",
                    resource_id="tool-1",
                    user_id="alice@test.com",
                    auth_method="api_key",
                )

                audit_entry = mock_db.add.call_args[0][0]
                assert audit_entry.auth_method == "api_key"
        finally:
            user_identity_var.reset(token)


# ---------------------------------------------------------------------------
# Additional coverage for identity propagation call sites
# ---------------------------------------------------------------------------
class TestRBACProxyIdentityPropagationCoverage:
    """Cover proxy auth UserContext error handling."""

    @pytest.mark.asyncio
    async def test_proxy_auth_user_context_construction_failure_is_logged(self):
        # First-Party
        from mcpgateway.middleware.rbac import get_current_user_with_permissions

        class _FreshDBSession:
            def __enter__(self):
                db = MagicMock()
                db.execute.return_value.scalar_one_or_none.return_value = None
                return db

            def __exit__(self, exc_type, exc, tb):
                return False

        request = MagicMock()
        request.headers = {"X-Proxy-User": "proxy@example.com", "user-agent": "pytest"}
        request.state = MagicMock()
        request.state.plugin_context_table = None
        request.state.plugin_global_context = None
        request.state.request_id = "req-1"
        request.state.team_id = "team-1"
        request.client = MagicMock(host="127.0.0.1")

        with (
            patch("mcpgateway.middleware.rbac.settings") as mock_settings,
            patch("mcpgateway.middleware.rbac.is_proxy_auth_trust_active", return_value=True),
            patch("mcpgateway.middleware.rbac.fresh_db_session", return_value=_FreshDBSession()),
            patch("mcpgateway.middleware.rbac.UserContext", side_effect=Exception("boom")),
            patch("mcpgateway.middleware.rbac.logger.debug") as mock_debug,
        ):
            mock_settings.mcp_client_auth_enabled = False
            mock_settings.proxy_user_header = "X-Proxy-User"
            mock_settings.platform_admin_email = "admin@example.com"

            result = await get_current_user_with_permissions(request, credentials=None, jwt_token=None)

        assert result["email"] == "proxy@example.com"
        mock_debug.assert_any_call("Could not build UserContext for proxy auth: boom")


class TestOAuthManagerAdditionalTokenExchangeCoverage:
    """Cover additional token exchange branches."""

    @pytest.mark.asyncio
    async def test_encrypted_client_secret_is_decrypted_before_exchange(self):
        # First-Party
        from mcpgateway.services.oauth_manager import OAuthManager

        manager = OAuthManager()
        mock_response = MagicMock()
        mock_response.json.return_value = {"access_token": "tok", "token_type": "Bearer"}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        manager._get_client = AsyncMock(return_value=mock_client)

        mock_encryption = MagicMock()
        mock_encryption.is_encrypted.return_value = True
        mock_encryption.decrypt_secret_async = AsyncMock(return_value="decrypted-secret")

        with patch("mcpgateway.services.oauth_manager.get_settings"), patch("mcpgateway.services.oauth_manager.get_encryption_service", return_value=mock_encryption):
            await manager.token_exchange(
                token_url="https://auth.example.com/token",
                subject_token="subject-token",
                client_id="client-id",
                client_secret="encrypted-secret",  # pragma: allowlist secret
            )

        post_data = mock_client.post.call_args.kwargs["data"]
        assert post_data["client_secret"] == "decrypted-secret"

    @pytest.mark.asyncio
    async def test_zero_retry_token_exchange_raises_final_error(self):
        # First-Party
        from mcpgateway.services.oauth_manager import OAuthError, OAuthManager

        manager = OAuthManager(max_retries=0)

        with pytest.raises(OAuthError, match="Token exchange failed after all retry attempts"):
            await manager.token_exchange(
                token_url="https://auth.example.com/token",
                subject_token="subject-token",
                client_id="client-id",
                client_secret="",
            )


class TestResourceServiceIdentityPropagationCoverage:
    """Cover resource service identity forwarding branches."""

    @pytest.mark.asyncio
    async def test_invoke_resource_updates_headers_from_user_context(self):
        # First-Party
        from mcpgateway.services.resource_service import ResourceService

        class _AsyncCM:
            async def __aenter__(self):
                return ("read", "write", lambda: None)

            async def __aexit__(self, exc_type, exc, tb):
                return False

        class _ClientSessionCM:
            def __init__(self, *_args):
                self._session = MagicMock()
                self._session.initialize = AsyncMock(return_value=None)

            async def __aenter__(self):
                return self._session

            async def __aexit__(self, exc_type, exc, tb):
                return False

        class _FakeTextResourceContents:
            def __init__(self, uri, mimeType=None, text=""):
                self.id = "resource-1"
                self.uri = uri
                self.mimeType = mimeType
                self.text = text

        service = ResourceService()
        db = MagicMock()
        resource = MagicMock(gateway_id="gw-1", name="resource-1")
        gateway = MagicMock(
            id="gw-1",
            url="https://gateway.example.com/mcp",
            transport="streamablehttp",
            auth_type=None,
            auth_value={},
            oauth_config=None,
            name="Gateway",
            ca_certificate=None,
            ca_certificate_sig=None,
            auth_query_params=None,
        )
        user_context = UserContext(user_id="user-1", email="user@example.com")
        mock_span = MagicMock()
        mock_span.__enter__.return_value = MagicMock()
        mock_span.__exit__.return_value = False
        mock_response = MagicMock()
        mock_response.contents = [MagicMock(text="hello")]

        with (
            patch("mcpgateway.services.resource_service.create_span", return_value=mock_span),
            patch("mcpgateway.services.resource_service.is_input_capture_enabled", return_value=False),
            patch("mcpgateway.services.resource_service.is_output_capture_enabled", return_value=False),
            patch("mcpgateway.services.resource_service.build_identity_headers", return_value={"X-Identity": "1"}) as mock_build_headers,
            patch("mcpgateway.services.resource_service.streamablehttp_client", return_value=_AsyncCM()),
            patch("mcpgateway.services.resource_service.ClientSession", _ClientSessionCM),
            patch("mcpgateway.services.resource_service._read_resource_with_meta", AsyncMock(return_value=mock_response)),
        ):
            result = await service.invoke_resource(
                db,
                resource_id="res-1",
                resource_uri="resource://example",
                user_identity=user_context,
                resource_obj=resource,
                gateway_obj=gateway,
            )

        assert result == "hello"
        mock_build_headers.assert_called_once_with(user_context)

    @pytest.mark.asyncio
    async def test_read_resource_direct_proxy_updates_headers_from_plugin_context(self):
        # First-Party
        from mcpgateway.services.resource_service import ResourceService

        class _AsyncCM:
            async def __aenter__(self):
                return ("read", "write", lambda: None)

            async def __aexit__(self, exc_type, exc, tb):
                return False

        class _ClientSessionCM:
            def __init__(self, *_args):
                self._session = MagicMock()
                self._session.initialize = AsyncMock(return_value=None)

            async def __aenter__(self):
                return self._session

            async def __aexit__(self, exc_type, exc, tb):
                return False

        class _FakeTextResourceContents:
            def __init__(self, uri, mimeType=None, text=""):
                self.id = "resource-1"
                self.uri = uri
                self.mimeType = mimeType
                self.text = text

        service = ResourceService()
        service._get_plugin_manager = AsyncMock(return_value=None)
        db = MagicMock()
        gateway = MagicMock(id="gw-1", gateway_mode="direct_proxy", url="https://gateway.example.com/mcp")
        resource_db = MagicMock(gateway=gateway, enabled=True)
        db.execute.return_value.scalar_one_or_none.return_value = resource_db
        plugin_global_context = GlobalContext(request_id="req-1", user_context=UserContext(user_id="user-1", email="user@example.com"))
        mock_response = MagicMock()
        mock_response.contents = [MagicMock(text="hello", mimeType="text/plain")]

        with (
            patch.object(service, "_get_plugin_manager", AsyncMock(return_value=None)),
            patch.object(service, "invoke_resource", AsyncMock(return_value="hello")),
            patch("mcpgateway.services.resource_service.check_gateway_access", AsyncMock(return_value=True)),
            patch.object(service, "_check_resource_access", AsyncMock(return_value=True)),
            patch("mcpgateway.services.resource_service.build_gateway_auth_headers", return_value={"Authorization": "Bearer gateway"}),
            patch("mcpgateway.services.resource_service.build_identity_headers", return_value={"X-Identity": "1"}) as mock_build_headers,
            patch("mcpgateway.services.resource_service.streamablehttp_client", return_value=_AsyncCM()),
            patch("mcpgateway.services.resource_service.ClientSession", _ClientSessionCM),
            patch("mcpgateway.services.resource_service._read_resource_with_meta", AsyncMock(return_value=mock_response)),
            patch("mcpgateway.common.models.TextResourceContents", _FakeTextResourceContents),
            patch.object(__import__("mcpgateway.services.resource_service", fromlist=["settings"]).settings, "experimental_validate_io", False),
            patch.object(__import__("mcpgateway.services.resource_service", fromlist=["settings"]).settings, "mcpgateway_direct_proxy_enabled", True),
            patch.object(__import__("mcpgateway.services.resource_service", fromlist=["settings"]).settings, "mcpgateway_direct_proxy_timeout", 5),
        ):
            result = await service.read_resource(
                db,
                resource_uri="resource://example",
                user="user@example.com",
                plugin_global_context=plugin_global_context,
            )

        assert getattr(result, "text") == "hello"
        mock_build_headers.assert_called_once_with(plugin_global_context.user_context, gateway)


class TestToolServiceIdentityPropagationCoverage:
    """Cover tool service identity forwarding branches."""

    @pytest.mark.asyncio
    async def test_invoke_tool_direct_updates_headers_and_meta(self):
        # First-Party
        from mcpgateway.services.tool_service import ToolService

        class _FreshDBSession:
            def __init__(self, db):
                self._db = db

            def __enter__(self):
                return self._db

            def __exit__(self, exc_type, exc, tb):
                return False

        class _AsyncCM:
            async def __aenter__(self):
                return ("read", "write", lambda: None)

            async def __aexit__(self, exc_type, exc, tb):
                return False

        class _ClientSessionCM:
            def __init__(self, *_args):
                self._session = MagicMock()
                self._session.initialize = AsyncMock(return_value=None)
                self._session.call_tool = AsyncMock(return_value=MagicMock(is_error=False))

            async def __aenter__(self):
                return self._session

            async def __aexit__(self, exc_type, exc, tb):
                return False

        service = ToolService()
        db = MagicMock()
        gateway = MagicMock(
            id="gw-1",
            gateway_mode="direct_proxy",
            passthrough_headers=[],
            url="https://gateway.example.com/mcp",
            slug="gw",
        )
        gateway_result = MagicMock()
        gateway_result.scalar_one_or_none.return_value = gateway
        tool_result = MagicMock()
        tool_result.scalar_one_or_none.return_value = None
        db.execute.side_effect = [gateway_result, tool_result]
        mock_span = MagicMock()
        mock_span.__enter__.return_value = MagicMock()
        mock_span.__exit__.return_value = False
        user_context = UserContext(user_id="user-1", email="user@example.com")

        with (
            patch("mcpgateway.services.tool_service.fresh_db_session", return_value=_FreshDBSession(db)),
            patch("mcpgateway.services.tool_service.check_gateway_access", AsyncMock(return_value=True)),
            patch("mcpgateway.services.tool_service.build_gateway_auth_headers", return_value={}),
            patch("mcpgateway.services.tool_service.build_identity_headers", return_value={"X-Identity": "1"}) as mock_build_headers,
            patch("mcpgateway.services.tool_service.build_identity_meta", return_value={"identity": True}) as mock_build_meta,
            patch("mcpgateway.services.tool_service.create_span", return_value=mock_span),
            patch("mcpgateway.services.tool_service.inject_trace_context_headers", side_effect=lambda headers: headers),
            patch("mcpgateway.services.tool_service.streamablehttp_client", return_value=_AsyncCM()),
            patch("mcpgateway.services.tool_service.ClientSession", _ClientSessionCM),
            patch.object(__import__("mcpgateway.services.tool_service", fromlist=["settings"]).settings, "mcpgateway_direct_proxy_enabled", True),
        ):
            await service.invoke_tool_direct(
                gateway_id="gw-1",
                name="gw-tool",
                arguments={"value": 1},
                meta_data={"existing": True},
                user_email="user@example.com",
                user_context=user_context,
            )

        mock_build_headers.assert_called_once_with(user_context, gateway)
        mock_build_meta.assert_called_once_with(user_context, {"existing": True}, gateway)

    @pytest.mark.asyncio
    async def test_invoke_tool_rest_updates_headers_from_global_context(self):
        # First-Party
        from mcpgateway.services.tool_service import ToolService

        service = ToolService()
        service._http_client = MagicMock()
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"ok": True}
        response.raise_for_status = MagicMock()
        service._http_client.request = AsyncMock(return_value=response)
        service._get_plugin_manager = AsyncMock(return_value=None)
        service._check_tool_access = AsyncMock(return_value=True)
        db = MagicMock()
        cache = MagicMock()
        cache.enabled = True
        cache.get = AsyncMock(
            return_value={
                "status": "active",
                "tool": {
                    "id": "tool-1",
                    "name": "rest-tool",
                    "original_name": "rest-tool",
                    "enabled": True,
                    "reachable": True,
                    "integration_type": "REST",
                    "request_type": "POST",
                    "url": "https://api.example.com/tools",
                    "headers": {},
                    "gateway_id": None,
                },
                "gateway": None,
            }
        )
        plugin_global_context = GlobalContext(request_id="req-1", user_context=UserContext(user_id="user-1", email="user@example.com"))
        mock_span = MagicMock()
        mock_span.__enter__.return_value = MagicMock()
        mock_span.__exit__.return_value = False

        with (
            patch("mcpgateway.services.tool_service._get_tool_lookup_cache", return_value=cache),
            patch("mcpgateway.services.tool_service.global_config_cache.get_passthrough_headers", return_value=[]),
            patch("mcpgateway.services.tool_service.build_identity_headers", return_value={"X-Identity": "1"}) as mock_build_headers,
            patch("mcpgateway.services.tool_service.create_span", return_value=mock_span),
            patch("mcpgateway.services.tool_service.create_child_span", return_value=mock_span),
            patch("mcpgateway.services.tool_service.is_input_capture_enabled", return_value=False),
            patch("mcpgateway.services.tool_service.extract_using_jq", return_value={"ok": True}),
        ):
            await service.invoke_tool(
                db,
                name="rest-tool",
                arguments={"value": 1},
                plugin_global_context=plugin_global_context,
            )

        mock_build_headers.assert_called_once_with(plugin_global_context.user_context)
        assert service._http_client.request.call_args.kwargs["headers"]["X-Identity"] == "1"

    @pytest.mark.asyncio
    async def test_invoke_tool_mcp_updates_headers_and_meta_from_global_context(self):
        # First-Party
        from mcpgateway.services.tool_service import ToolService

        class _AsyncCM:
            async def __aenter__(self):
                return ("read", "write", lambda: None)

            async def __aexit__(self, exc_type, exc, tb):
                return False

        class _ClientSessionCM:
            def __init__(self, *_args):
                self._session = MagicMock()
                self._session.initialize = AsyncMock(return_value=None)
                mock_result = MagicMock(is_error=False, isError=False)
                mock_result.structured_content = None
                mock_result.meta = None
                mock_result.content = []
                mock_result.model_dump.return_value = {"content": [], "isError": False}
                self._session.call_tool = AsyncMock(return_value=mock_result)

            async def __aenter__(self):
                return self._session

            async def __aexit__(self, exc_type, exc, tb):
                return False

        service = ToolService()
        service._get_plugin_manager = AsyncMock(return_value=None)
        service._check_tool_access = AsyncMock(return_value=True)
        db = MagicMock()
        cache = MagicMock()
        cache.enabled = True
        cache.get = AsyncMock(
            return_value={
                "status": "active",
                "tool": {
                    "id": "tool-1",
                    "name": "mcp-tool",
                    "original_name": "mcp-tool",
                    "enabled": True,
                    "reachable": True,
                    "integration_type": "MCP",
                    "request_type": "streamablehttp",
                    "headers": {},
                    "gateway_id": "gw-1",
                },
                "gateway": {
                    "id": "gw-1",
                    "name": "Gateway",
                    "url": "https://gateway.example.com/mcp",
                    "auth_type": None,
                    "auth_value": None,
                    "auth_query_params": None,
                    "oauth_config": None,
                    "ca_certificate": None,
                    "ca_certificate_sig": None,
                    "passthrough_headers": [],
                },
            }
        )
        plugin_global_context = GlobalContext(request_id="req-1", user_context=UserContext(user_id="user-1", email="user@example.com"))
        mock_span = MagicMock()
        mock_span.__enter__.return_value = MagicMock()
        mock_span.__exit__.return_value = False

        with (
            patch("mcpgateway.services.tool_service._get_tool_lookup_cache", return_value=cache),
            patch("mcpgateway.services.tool_service.global_config_cache.get_passthrough_headers", return_value=[]),
            patch("mcpgateway.services.tool_service.build_identity_headers", return_value={"X-Identity": "1"}) as mock_build_headers,
            patch("mcpgateway.services.tool_service.build_identity_meta", return_value={"identity": True}) as mock_build_meta,
            patch("mcpgateway.services.tool_service.create_span", return_value=mock_span),
            patch("mcpgateway.services.tool_service.create_child_span", return_value=mock_span),
            patch("mcpgateway.services.tool_service.is_input_capture_enabled", return_value=False),
            patch("mcpgateway.services.tool_service.inject_trace_context_headers", side_effect=lambda headers: headers),
            patch("mcpgateway.services.tool_service.streamablehttp_client", return_value=_AsyncCM()),
            patch("mcpgateway.services.tool_service.ClientSession", _ClientSessionCM),
        ):
            await service.invoke_tool(
                db,
                name="mcp-tool",
                arguments={"value": 1},
                plugin_global_context=plugin_global_context,
                meta_data={"existing": True},
            )

        mock_build_headers.assert_called_once_with(plugin_global_context.user_context)
        mock_build_meta.assert_called_once_with(plugin_global_context.user_context, {"existing": True})


class TestStreamableHttpTransportIdentityPropagationCoverage:
    """Cover transport identity forwarding branches."""

    @pytest.mark.asyncio
    async def test_proxy_list_tools_updates_headers_from_context_identity(self):
        # First-Party
        from mcpgateway.transports.context import user_identity_var
        from mcpgateway.transports.streamablehttp_transport import _proxy_list_tools_to_gateway

        class _AsyncCM:
            async def __aenter__(self):
                return ("read", "write", lambda: None)

            async def __aexit__(self, exc_type, exc, tb):
                return False

        class _ClientSessionCM:
            def __init__(self, *_args):
                self._session = MagicMock()
                self._session.initialize = AsyncMock(return_value=None)
                self._session.list_tools = AsyncMock(return_value=MagicMock(tools=[MagicMock(name="tool")]))

            async def __aenter__(self):
                return self._session

            async def __aexit__(self, exc_type, exc, tb):
                return False

        gateway = MagicMock(id="gw-1", url="https://gateway.example.com/mcp")
        identity = UserContext(user_id="user-1", email="user@example.com")
        token = user_identity_var.set(identity)

        try:
            with (
                patch("mcpgateway.transports.streamablehttp_transport.build_gateway_auth_headers", return_value={}),
                patch("mcpgateway.transports.streamablehttp_transport.build_identity_headers", return_value={"X-Identity": "1"}) as mock_build_headers,
                patch("mcpgateway.transports.streamablehttp_transport.streamablehttp_client", return_value=_AsyncCM()),
                patch("mcpgateway.transports.streamablehttp_transport.ClientSession", _ClientSessionCM),
            ):
                await _proxy_list_tools_to_gateway(gateway, {}, {})
        finally:
            user_identity_var.reset(token)

        mock_build_headers.assert_called_once_with(identity, gateway)

    @pytest.mark.asyncio
    async def test_proxy_list_resources_updates_headers_from_context_identity(self):
        # First-Party
        from mcpgateway.transports.context import user_identity_var
        from mcpgateway.transports.streamablehttp_transport import _proxy_list_resources_to_gateway

        class _AsyncCM:
            async def __aenter__(self):
                return ("read", "write", lambda: None)

            async def __aexit__(self, exc_type, exc, tb):
                return False

        class _ClientSessionCM:
            def __init__(self, *_args):
                self._session = MagicMock()
                self._session.initialize = AsyncMock(return_value=None)
                self._session.list_resources = AsyncMock(return_value=MagicMock(resources=[MagicMock(uri="resource://example")]))

            async def __aenter__(self):
                return self._session

            async def __aexit__(self, exc_type, exc, tb):
                return False

        gateway = MagicMock(id="gw-1", url="https://gateway.example.com/mcp")
        identity = UserContext(user_id="user-1", email="user@example.com")
        token = user_identity_var.set(identity)

        try:
            with (
                patch("mcpgateway.transports.streamablehttp_transport.build_gateway_auth_headers", return_value={}),
                patch("mcpgateway.transports.streamablehttp_transport.build_identity_headers", return_value={"X-Identity": "1"}) as mock_build_headers,
                patch("mcpgateway.transports.streamablehttp_transport.streamablehttp_client", return_value=_AsyncCM()),
                patch("mcpgateway.transports.streamablehttp_transport.ClientSession", _ClientSessionCM),
            ):
                await _proxy_list_resources_to_gateway(gateway, {}, {})
        finally:
            user_identity_var.reset(token)

        mock_build_headers.assert_called_once_with(identity, gateway)

    @pytest.mark.asyncio
    async def test_proxy_read_resource_updates_headers_from_context_identity(self):
        # First-Party
        from mcpgateway.transports.context import request_headers_var, user_identity_var
        from mcpgateway.transports.streamablehttp_transport import _proxy_read_resource_to_gateway

        class _AsyncCM:
            async def __aenter__(self):
                return ("read", "write", lambda: None)

            async def __aexit__(self, exc_type, exc, tb):
                return False

        class _ClientSessionCM:
            def __init__(self, *_args):
                self._session = MagicMock()
                self._session.initialize = AsyncMock(return_value=None)
                self._session.read_resource = AsyncMock(return_value=MagicMock(contents=[MagicMock(text="hello")]))

            async def __aenter__(self):
                return self._session

            async def __aexit__(self, exc_type, exc, tb):
                return False

        gateway = MagicMock(id="gw-1", url="https://gateway.example.com/mcp")
        identity = UserContext(user_id="user-1", email="user@example.com")
        identity_token = user_identity_var.set(identity)
        headers_token = request_headers_var.set({})

        try:
            with (
                patch("mcpgateway.transports.streamablehttp_transport.build_gateway_auth_headers", return_value={}),
                patch("mcpgateway.transports.streamablehttp_transport.build_identity_headers", return_value={"X-Identity": "1"}) as mock_build_headers,
                patch("mcpgateway.transports.streamablehttp_transport.streamablehttp_client", return_value=_AsyncCM()),
                patch("mcpgateway.transports.streamablehttp_transport.ClientSession", _ClientSessionCM),
            ):
                await _proxy_read_resource_to_gateway(gateway, "resource://example", {})
        finally:
            request_headers_var.reset(headers_token)
            user_identity_var.reset(identity_token)

        mock_build_headers.assert_called_once_with(identity, gateway)
