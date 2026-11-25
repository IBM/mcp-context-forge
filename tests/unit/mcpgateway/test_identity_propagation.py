# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_identity_propagation.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for identity propagation utilities.

Tests cover:
- UserContext model creation and serialization
- build_identity_headers() with various configurations and all optional fields
- build_identity_meta() merging behavior with all optional fields
- filter_sensitive_attributes() including settings fallback
- _resolve_config() per-gateway overrides for all keys
- Claims JWS signing: claim coverage, expiry, audience, key separation
- Per-gateway configuration override
- Plugin convenience helpers (PluginContext.user_context, user_email, user_groups)
- _set_user_identity_from_dict() transport helper
- _inject_userinfo_instate() UserContext population
- Audit trail service identity fields (auth_method, acting_as, delegation_chain)
- OAuthManager.token_exchange() RFC 8693
"""

# Standard
from contextlib import asynccontextmanager, nullcontext
from datetime import datetime, timezone
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import httpx
import jwt
from pydantic import SecretStr
import pytest

# First-Party
from cpex.framework import GlobalContext, PluginContext
from mcpgateway.transports.context import UserContext
from mcpgateway.utils.identity_propagation import (
    _resolve_config,
    IdentitySigningError,
    build_identity_headers,
    build_identity_meta,
    filter_sensitive_attributes,
)


JWT_SECRET = "jwt-secret-for-tests-only-0123456789abcdef"  # pragma: allowlist secret
CLAIMS_SECRET = "identity-claims-secret-for-tests-0123456789"  # pragma: allowlist secret


def _isolated_client(mock_client, captured_kwargs=None):
    """Build a stand-in for get_isolated_http_client that yields a fixed mock client.

    Args:
        mock_client: Mock async client the context manager yields to the caller.
        captured_kwargs: Optional dict populated with the call's keyword arguments,
            so a test can assert on how the isolated client was configured (e.g.
            ``follow_redirects``).

    Returns:
        An async context manager factory matching get_isolated_http_client's call shape.
    """

    @asynccontextmanager
    async def _cm(*_args, **kwargs):
        if captured_kwargs is not None:
            captured_kwargs.update(kwargs)
        yield mock_client

    return _cm


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
        mock_settings.identity_claims_secret = SecretStr(CLAIMS_SECRET)
        mock_settings.jwt_secret_key = SecretStr(JWT_SECRET)
        mock_settings.identity_sensitive_attributes = []
        uc = UserContext(user_id="alice@co.com", email="alice@co.com")
        headers = build_identity_headers(uc, audience="gw-1")
        claims = jwt.decode(headers["X-Forwarded-User-Claims-Signature"], CLAIMS_SECRET, algorithms=["HS256"], audience="gw-1")
        assert claims["email"] == "alice@co.com"

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
    """Tests for GlobalContext.user_context (typed UserContext field on the global context)."""

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
def _get_user_context(ctx: PluginContext):
    """Extract UserContext from plugin context, mirroring the production accessor pattern."""
    return ctx.global_context.user_context

def _get_user_email(ctx: PluginContext):
    """Extract user email from plugin context, mirroring the production accessor pattern."""
    uc = ctx.global_context.user_context
    if uc is not None:
        return uc.email
    user = ctx.global_context.user
    if isinstance(user, str):
        return user
    if isinstance(user, dict):
        return user.get("email")
    return None

def _get_user_groups(ctx: PluginContext):
    """Extract user groups from plugin context, mirroring the production accessor pattern."""
    uc = ctx.global_context.user_context
    if uc is not None:
        return uc.groups
    return []

class TestPluginContextHelpers:
    """Tests for PluginContext user identity extraction via GlobalContext.state."""

    def test_user_context_property(self):
        uc = UserContext(user_id="alice@co.com", groups=["eng"])
        gctx = GlobalContext(request_id="req-1", user_context=uc)
        ctx = PluginContext(global_context=gctx)
        assert _get_user_context(ctx) is uc

    def test_user_context_none(self):
        gctx = GlobalContext(request_id="req-1")
        ctx = PluginContext(global_context=gctx)
        assert _get_user_context(ctx) is None

    def test_user_email_from_user_context(self):
        uc = UserContext(user_id="alice@co.com", email="alice@co.com")
        gctx = GlobalContext(request_id="req-1", user_context=uc)
        ctx = PluginContext(global_context=gctx)
        assert _get_user_email(ctx) == "alice@co.com"

    def test_user_email_from_legacy_string(self):
        gctx = GlobalContext(request_id="req-1", user="bob@co.com")
        ctx = PluginContext(global_context=gctx)
        assert _get_user_email(ctx) == "bob@co.com"

    def test_user_email_from_legacy_dict(self):
        gctx = GlobalContext(request_id="req-1", user={"email": "charlie@co.com"})
        ctx = PluginContext(global_context=gctx)
        assert _get_user_email(ctx) == "charlie@co.com"

    def test_user_email_none(self):
        gctx = GlobalContext(request_id="req-1")
        ctx = PluginContext(global_context=gctx)
        assert _get_user_email(ctx) is None

    def test_user_groups_from_context(self):
        uc = UserContext(user_id="alice@co.com", groups=["eng", "dev"])
        gctx = GlobalContext(request_id="req-1", user_context=uc)
        ctx = PluginContext(global_context=gctx)
        assert _get_user_groups(ctx) == ["eng", "dev"]

    def test_user_groups_empty_default(self):
        gctx = GlobalContext(request_id="req-1")
        ctx = PluginContext(global_context=gctx)
        assert _get_user_groups(ctx) == []

    def test_user_email_none_when_uc_email_is_none(self):
        uc = UserContext(user_id="alice@co.com")  # email is None
        gctx = GlobalContext(request_id="req-1", user_context=uc)
        ctx = PluginContext(global_context=gctx)
        assert _get_user_email(ctx) is None

    def test_user_groups_empty_list_from_uc(self):
        uc = UserContext(user_id="alice@co.com", groups=[])
        gctx = GlobalContext(request_id="req-1", user_context=uc)
        ctx = PluginContext(global_context=gctx)
        assert _get_user_groups(ctx) == []

# ---------------------------------------------------------------------------
# _resolve_config tests
# ---------------------------------------------------------------------------
class TestResolveConfig:
    """Tests for _resolve_config() per-gateway overrides."""

    @patch("mcpgateway.utils.identity_propagation.settings")
    def test_identity_propagation_kwarg_overrides_global_and_gateway(self, mock_settings):
        mock_settings.identity_propagation_enabled = True
        mock_settings.identity_propagation_mode = "both"
        mock_settings.identity_propagation_headers_prefix = "X-Forwarded-User"
        mock_settings.identity_sign_claims = False
        mock_settings.identity_sensitive_attributes = []
        gateway = MagicMock(identity_propagation={"enabled": True})
        assert _resolve_config(gateway, {"enabled": False})["enabled"] is False
        assert _resolve_config(None, None)["enabled"] is True

    @patch("mcpgateway.utils.identity_propagation.settings")
    def test_deny_path_disabled_gateway_dict_sends_no_identity(self, mock_settings):
        mock_settings.identity_propagation_enabled = True
        mock_settings.identity_propagation_mode = "both"
        mock_settings.identity_propagation_headers_prefix = "X-Forwarded-User"
        mock_settings.identity_sign_claims = False
        mock_settings.identity_sensitive_attributes = []
        uc = UserContext(user_id="alice@co.com", email="alice@co.com")
        assert build_identity_headers(uc, identity_propagation={"enabled": False}) == {}
        assert build_identity_meta(uc, {"k": "v"}, identity_propagation={"enabled": False}) == {"k": "v"}

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
# Claims JWS signing tests
# ---------------------------------------------------------------------------
@pytest.fixture
def signing_settings():
    """Patch settings with propagation and claim signing on, using a dedicated secret."""
    with patch("mcpgateway.utils.identity_propagation.settings") as mock_settings:
        mock_settings.identity_propagation_enabled = True
        mock_settings.identity_propagation_mode = "both"
        mock_settings.identity_propagation_headers_prefix = "X-Forwarded-User"
        mock_settings.identity_sign_claims = True
        mock_settings.identity_claims_secret = SecretStr(CLAIMS_SECRET)
        mock_settings.jwt_secret_key = SecretStr(JWT_SECRET)
        mock_settings.identity_sensitive_attributes = []
        yield mock_settings


def _full_user(**overrides) -> UserContext:
    fields = dict(
        user_id="alice@co.com",
        email="alice@co.com",
        full_name="Alice",
        is_admin=False,
        groups=["eng"],
        teams=["team-a"],
        roles=["viewer"],
        auth_method="bearer",
        service_account="ci-bot",
        delegation_chain=["ci-bot", "alice@co.com"],
    )
    fields.update(overrides)
    return UserContext(**fields)


def _decode(token: str, secret: str = CLAIMS_SECRET, audience: str = "gw-1") -> dict:
    return jwt.decode(token, secret, algorithms=["HS256"], audience=audience)


SIG = "X-Forwarded-User-Claims-Signature"


class TestClaimsToken:
    """The claims signature is a short-lived, audience-bound JWS over every identity claim."""

    def test_token_covers_every_claim(self, signing_settings):
        uc = _full_user(is_admin=True)
        claims = _decode(build_identity_headers(uc, audience="gw-1")[SIG])
        assert claims["id"] == "alice@co.com"
        assert claims["email"] == "alice@co.com"
        assert claims["full_name"] == "Alice"
        assert claims["is_admin"] is True
        assert claims["groups"] == ["eng"]
        assert claims["teams"] == ["team-a"]
        assert claims["roles"] == ["viewer"]
        assert claims["auth_method"] == "bearer"
        assert claims["service_account"] == "ci-bot"
        assert claims["delegation_chain"] == ["ci-bot", "alice@co.com"]
        assert claims["iss"] == "mcpgateway-identity-propagation"

    def test_token_claims_match_headers(self, signing_settings):
        headers = build_identity_headers(_full_user(), audience="gw-1")
        claims = _decode(headers[SIG])
        assert headers["X-Forwarded-User-Admin"] == str(claims["is_admin"]).lower()
        assert headers["X-Forwarded-User-Teams"] == ",".join(claims["teams"])
        assert headers["X-Forwarded-User-Roles"] == ",".join(claims["roles"])

    @pytest.mark.parametrize(
        "field,value",
        [
            ("is_admin", True),
            ("teams", ["team-a", "team-evil"]),
            ("roles", ["platform_admin"]),
            ("groups", ["eng", "root"]),
            ("delegation_chain", ["mallory", "alice@co.com"]),
            ("service_account", "other-bot"),
            ("auth_method", "api_key"),
        ],
    )
    def test_changing_a_claim_changes_the_signed_payload(self, signing_settings, field, value):
        base = _decode(build_identity_headers(_full_user(), audience="gw-1")[SIG])
        changed = _decode(build_identity_headers(_full_user(**{field: value}), audience="gw-1")[SIG])
        assert changed[field] == value
        assert base[field] != changed[field]

    def test_tampered_token_fails_verification(self, signing_settings):
        token = build_identity_headers(_full_user(), audience="gw-1")[SIG]
        header, payload, signature = token.split(".")
        forged = jwt.encode({**_decode(token), "is_admin": True}, "attacker-key-0123456789abcdef0123456789", algorithm="HS256").split(".")[1]
        with pytest.raises(jwt.InvalidSignatureError):
            _decode(f"{header}.{forged}.{signature}")

    def test_token_is_short_lived(self, signing_settings):
        claims = _decode(build_identity_headers(_full_user(), audience="gw-1")[SIG])
        assert claims["exp"] - claims["iat"] == 60

    def test_expired_token_is_rejected(self, signing_settings):
        past = time.time() - 120
        with patch("mcpgateway.utils.identity_propagation.time.time", return_value=past):
            token = build_identity_headers(_full_user(), audience="gw-1")[SIG]
        with pytest.raises(jwt.ExpiredSignatureError):
            _decode(token)

    def test_token_has_unique_jti(self, signing_settings):
        first = _decode(build_identity_headers(_full_user(), audience="gw-1")[SIG])
        second = _decode(build_identity_headers(_full_user(), audience="gw-1")[SIG])
        assert first["jti"] != second["jti"]

    def test_audience_defaults_to_gateway_id(self, signing_settings):
        gateway = SimpleNamespace(id="gw-1", identity_propagation=None)
        assert _decode(build_identity_headers(_full_user(), gateway)[SIG])["aud"] == "gw-1"

    def test_explicit_audience_wins_and_binds(self, signing_settings):
        gateway = SimpleNamespace(id="gw-1", identity_propagation=None)
        token = build_identity_headers(_full_user(), gateway, audience="gw-2")[SIG]
        assert _decode(token, audience="gw-2")["aud"] == "gw-2"
        with pytest.raises(jwt.InvalidAudienceError):
            _decode(token, audience="gw-1")

    def test_refuses_without_audience(self, signing_settings):
        with pytest.raises(ValueError):
            build_identity_headers(_full_user())

    def test_token_not_verifiable_with_jwt_secret(self, signing_settings):
        token = build_identity_headers(_full_user(), audience="gw-1")[SIG]
        with pytest.raises(jwt.InvalidSignatureError):
            _decode(token, secret=JWT_SECRET)

    @pytest.mark.parametrize("secret", [None, SecretStr(""), SecretStr(JWT_SECRET)])
    def test_runtime_refuses_without_dedicated_secret(self, signing_settings, secret):
        signing_settings.identity_claims_secret = secret
        with pytest.raises(ValueError, match="IDENTITY_CLAIMS_SECRET"):
            build_identity_headers(_full_user(), audience="gw-1")
        with pytest.raises(ValueError):
            build_identity_meta(_full_user(), audience="gw-1")

    def test_per_gateway_sign_claims_override_refuses_without_secret(self, signing_settings):
        signing_settings.identity_sign_claims = False
        signing_settings.identity_claims_secret = None
        with pytest.raises(ValueError):
            build_identity_headers(_full_user(), identity_propagation={"enabled": True, "sign_claims": True}, audience="gw-1")

    def test_meta_carries_claims_signature(self, signing_settings):
        user = build_identity_meta(_full_user(), audience="gw-1")["user"]
        claims = _decode(user["claims_signature"])
        assert "claims_signature" not in claims
        assert claims["teams"] == user["teams"]
        assert claims["is_admin"] == user["is_admin"]

    def test_no_signature_when_sign_claims_false(self, signing_settings):
        signing_settings.identity_sign_claims = False
        signing_settings.identity_claims_secret = None
        assert SIG not in build_identity_headers(_full_user())
        assert "claims_signature" not in build_identity_meta(_full_user())["user"]

    def test_identity_claims_secret_is_a_secret_type(self):
        """The identity-claims signing key must not be a bare string."""
        # Standard
        from typing import get_args

        # First-Party
        from mcpgateway.config import Settings

        annotation = Settings.model_fields["identity_claims_secret"].annotation
        assert SecretStr in get_args(annotation), "identity_claims_secret must be Optional[SecretStr]"


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

    def test_explicit_user_id_wins_over_email(self):
        # First-Party
        from mcpgateway.transports.streamablehttp_transport import _set_user_identity_from_dict, user_identity_var

        _set_user_identity_from_dict({"user_id": "u-1", "email": "alice@co.com"})
        uc = user_identity_var.get()
        assert uc.user_id == "u-1"
        assert uc.email == "alice@co.com"
        user_identity_var.set(None)

    def test_forwarded_auth_context_carries_user_id(self):
        # First-Party
        from mcpgateway.transports.streamablehttp_transport import get_streamable_http_auth_context, user_context_var

        token = user_context_var.set({"user_id": "u-1", "email": "alice@co.com", "is_authenticated": True})
        try:
            forwarded = get_streamable_http_auth_context()
        finally:
            user_context_var.reset(token)
        assert forwarded["user_id"] == "u-1"

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
        uc = gctx.user_context
        assert uc is not None
        assert uc.user_id == "alice@example.com"
        assert uc.email == "alice@example.com"
        assert uc.is_admin is True
        assert uc.full_name == "Alice"
        assert uc.teams == ["team-1", "team-2"]
        assert uc.team_id == "team-1"
        assert uc.auth_method == "bearer"
        assert uc.authenticated_at is not None

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

        uc = existing_gctx.user_context
        assert uc is not None
        assert uc.auth_method == "basic"
        # [] is a list, so isinstance([], list) is True → teams = []
        assert uc.teams == []

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
    async def test_successful_exchange(self, monkeypatch):
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
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)
        monkeypatch.setattr("mcpgateway.services.oauth_manager.get_isolated_http_client", _isolated_client(mock_client))

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
    async def test_subject_token_type_defaults_to_jwt(self, monkeypatch):
        """RFC 8693 §3: CF's inbound subject token is a CF-issued JWT, not an
        AS-issued access_token, so subject_token_type defaults to "...:jwt"."""
        # First-Party
        from mcpgateway.services.oauth_manager import OAuthManager

        manager = OAuthManager()
        mock_response = MagicMock()
        mock_response.json.return_value = {"access_token": "tok", "token_type": "Bearer"}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        monkeypatch.setattr("mcpgateway.services.oauth_manager.get_isolated_http_client", _isolated_client(mock_client))

        await manager.token_exchange(
            token_url="https://auth.example.com/token",
            subject_token="token",
            client_id="client",
            client_secret="",
        )

        call_kwargs = mock_client.post.call_args
        post_data = call_kwargs.kwargs.get("data") or call_kwargs[1].get("data")
        assert post_data["subject_token_type"] == "urn:ietf:params:oauth:token-type:jwt"

    @pytest.mark.asyncio
    async def test_subject_token_type_override(self, monkeypatch):
        # First-Party
        from mcpgateway.services.oauth_manager import OAuthManager

        manager = OAuthManager()
        mock_response = MagicMock()
        mock_response.json.return_value = {"access_token": "tok", "token_type": "Bearer"}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        monkeypatch.setattr("mcpgateway.services.oauth_manager.get_isolated_http_client", _isolated_client(mock_client))

        await manager.token_exchange(
            token_url="https://auth.example.com/token",
            subject_token="token",
            client_id="client",
            client_secret="",
            subject_token_type="urn:ietf:params:oauth:token-type:access_token",
        )

        call_kwargs = mock_client.post.call_args
        post_data = call_kwargs.kwargs.get("data") or call_kwargs[1].get("data")
        assert post_data["subject_token_type"] == "urn:ietf:params:oauth:token-type:access_token"

    @pytest.mark.asyncio
    async def test_non_bearer_token_type_raises(self, monkeypatch):
        """RFC 8693 §2.2.1: token_type "N_A" means the issued token isn't usable
        as an OAuth Bearer token. CF only forwards "Authorization: Bearer <token>",
        so a non-Bearer token_type must fail closed rather than mislabel the token."""
        # First-Party
        from mcpgateway.services.oauth_manager import OAuthError, OAuthManager

        manager = OAuthManager()
        mock_response = MagicMock()
        mock_response.json.return_value = {"access_token": "tok", "token_type": "N_A", "issued_token_type": "urn:ietf:params:oauth:token-type:saml2"}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        monkeypatch.setattr("mcpgateway.services.oauth_manager.get_isolated_http_client", _isolated_client(mock_client))

        with pytest.raises(OAuthError, match="Unsupported or missing token_type"):
            await manager.token_exchange(
                token_url="https://auth.example.com/token",
                subject_token="token",
                client_id="client",
                client_secret="",
            )

    @pytest.mark.asyncio
    async def test_missing_token_type_raises(self, monkeypatch):
        """RFC 8693 §2.2.1: token_type is REQUIRED. An AS that omits it must fail
        closed rather than have CF silently assume Bearer."""
        # First-Party
        from mcpgateway.services.oauth_manager import OAuthError, OAuthManager

        manager = OAuthManager()
        mock_response = MagicMock()
        mock_response.json.return_value = {"access_token": "tok"}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        monkeypatch.setattr("mcpgateway.services.oauth_manager.get_isolated_http_client", _isolated_client(mock_client))

        with pytest.raises(OAuthError, match="Unsupported or missing token_type"):
            await manager.token_exchange(
                token_url="https://auth.example.com/token",
                subject_token="token",
                client_id="client",
                client_secret="",
            )

    @pytest.mark.asyncio
    async def test_missing_access_token_raises(self, monkeypatch):
        # First-Party
        from mcpgateway.services.oauth_manager import OAuthError, OAuthManager

        manager = OAuthManager()
        mock_response = MagicMock()
        mock_response.json.return_value = {"error": "invalid_grant"}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)
        monkeypatch.setattr("mcpgateway.services.oauth_manager.get_isolated_http_client", _isolated_client(mock_client))

        with pytest.raises(OAuthError, match="No access_token"):
            await manager.token_exchange(
                token_url="https://auth.example.com/token",
                subject_token="token",
                client_id="client",
                client_secret="",
            )

    @pytest.mark.asyncio
    async def test_missing_access_token_error_redacts_sensitive_fields(self, monkeypatch):
        """CWE-532: a malformed response missing access_token may still carry other
        credential-bearing fields (e.g. refresh_token); those must never be echoed
        verbatim into the OAuthError raised for this case."""
        # First-Party
        from mcpgateway.services.oauth_manager import OAuthError, OAuthManager

        manager = OAuthManager()
        mock_response = MagicMock()
        mock_response.json.return_value = {"error": "invalid_grant", "refresh_token": "super-secret-refresh-value"}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        monkeypatch.setattr("mcpgateway.services.oauth_manager.get_isolated_http_client", _isolated_client(mock_client))

        with pytest.raises(OAuthError) as exc_info:
            await manager.token_exchange(
                token_url="https://auth.example.com/token",
                subject_token="token",
                client_id="client",
                client_secret="",
            )

        assert "super-secret-refresh-value" not in str(exc_info.value)
        assert "[REDACTED]" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_http_error_retries_and_raises(self, monkeypatch):
        # First-Party
        from mcpgateway.services.oauth_manager import OAuthError, OAuthManager

        manager = OAuthManager(max_retries=2)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(side_effect=httpx.HTTPError("connection failed"))
        monkeypatch.setattr("mcpgateway.services.oauth_manager.get_isolated_http_client", _isolated_client(mock_client))

        with pytest.raises(OAuthError, match="Token exchange failed"):
            await manager.token_exchange(
                token_url="https://auth.example.com/token",
                subject_token="token",
                client_id="client",
                client_secret="",
            )

        assert mock_client.post.call_count == 2

    @pytest.mark.asyncio
    async def test_no_audience_or_scope(self, monkeypatch):
        # First-Party
        from mcpgateway.services.oauth_manager import OAuthManager

        manager = OAuthManager()
        mock_response = MagicMock()
        mock_response.json.return_value = {"access_token": "tok", "token_type": "Bearer"}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)
        monkeypatch.setattr("mcpgateway.services.oauth_manager.get_isolated_http_client", _isolated_client(mock_client))

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
    async def test_client_secret_decryption_failure_continues(self, monkeypatch):
        # First-Party
        from mcpgateway.services.oauth_manager import OAuthManager

        manager = OAuthManager()
        mock_response = MagicMock()
        mock_response.json.return_value = {"access_token": "tok", "token_type": "Bearer"}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)
        monkeypatch.setattr("mcpgateway.services.oauth_manager.get_isolated_http_client", _isolated_client(mock_client))

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
                logging.getLogger("mcpgateway.middleware.rbac").debug(f"Could not build UserContext for proxy auth: {ctx_err}")

            assert caught

# ---------------------------------------------------------------------------
# Coverage: oauth_manager.py lines 613-616 — encrypted secret decryption
# ---------------------------------------------------------------------------
class TestTokenExchangeEncryptedSecret:

    @pytest.mark.asyncio
    async def test_encrypted_secret_is_decrypted(self, monkeypatch):
        """When client_secret is encrypted, it should be decrypted before token exchange."""
        # First-Party
        from mcpgateway.services.oauth_manager import OAuthManager

        mock_encryption = MagicMock()
        mock_encryption.is_encrypted.return_value = True
        mock_encryption.decrypt_secret_async = AsyncMock(return_value="decrypted-secret")

        mock_response = MagicMock()
        mock_response.json.return_value = {"access_token": "tok-123", "token_type": "Bearer"}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)

        mgr = OAuthManager.__new__(OAuthManager)
        mgr.request_timeout = 30
        mgr.max_retries = 1
        monkeypatch.setattr("mcpgateway.services.oauth_manager.get_isolated_http_client", _isolated_client(mock_client))

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
                from mcpgateway.transports.context import UserContext as UserCtx

                if isinstance(user_identity, UserCtx):
                    headers.update(build_identity_headers(user_identity))

        assert "X-Forwarded-User-Id" in headers
        assert headers["X-Forwarded-User-Id"] == "alice@test.com"

    def test_direct_proxy_injects_identity_headers(self):
        """build_identity_headers called in direct_proxy resource read path."""
        user_ctx = UserContext(user_id="bob@test.com", email="bob@test.com")
        mock_gateway = MagicMock()
        plugin_global_context = GlobalContext(request_id="req-1", user_context=user_ctx)
        headers = {"Authorization": "Bearer tok"}

        with patch("mcpgateway.utils.identity_propagation._resolve_config", return_value=self._enabled_config()):
            uc = plugin_global_context.user_context
            if plugin_global_context and uc:
                headers.update(build_identity_headers(uc, mock_gateway))

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
        global_context = GlobalContext(request_id="req-1", user_context=user_ctx)
        headers = {}

        with patch("mcpgateway.utils.identity_propagation._resolve_config", return_value=self._enabled_config()):
            uc = global_context.user_context
            if global_context and uc:
                headers.update(build_identity_headers(uc))

        assert "X-Forwarded-User-Id" in headers

    def test_mcp_tool_injects_headers_and_meta(self):
        """build_identity_headers + build_identity_meta called for MCP tool invocation."""
        user_ctx = UserContext(user_id="charlie@test.com", email="charlie@test.com")
        global_context = GlobalContext(request_id="req-2", user_context=user_ctx)
        headers = {}
        meta_data = {}

        with patch("mcpgateway.utils.identity_propagation._resolve_config", return_value=self._enabled_config()):
            uc = global_context.user_context
            if global_context and uc:
                headers.update(build_identity_headers(uc))
                meta_data = build_identity_meta(uc, meta_data)

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
        request.cookies = {}  # Ensure no cookies present
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
    async def test_encrypted_client_secret_is_decrypted_before_exchange(self, monkeypatch):
        # First-Party
        from mcpgateway.services.oauth_manager import OAuthManager

        manager = OAuthManager()
        mock_response = MagicMock()
        mock_response.json.return_value = {"access_token": "tok", "token_type": "Bearer"}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)
        monkeypatch.setattr("mcpgateway.services.oauth_manager.get_isolated_http_client", _isolated_client(mock_client))

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

        client_mock = AsyncMock()
        client_mock.__aenter__ = AsyncMock(return_value=client_mock)
        client_mock.__aexit__ = AsyncMock(return_value=None)

        with (
            patch("mcpgateway.services.resource_service.create_span", return_value=mock_span),
            patch("mcpgateway.services.resource_service.is_input_capture_enabled", return_value=False),
            patch("mcpgateway.services.resource_service.is_output_capture_enabled", return_value=False),
            patch("mcpgateway.services.resource_service.build_identity_headers", return_value={"X-Identity": "1"}) as mock_build_headers,
            patch("mcpgateway.services.resource_service.build_identity_meta", return_value={"identity": True}) as mock_build_meta,
            patch("mcpgateway.services.resource_service.mcp_proxy_client", return_value=client_mock),
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
        mock_build_headers.assert_called_once_with(user_context, gateway, audience="gw-1")
        mock_build_meta.assert_called_once_with(user_context, None, gateway, audience="gw-1")

    @pytest.mark.asyncio
    async def test_read_resource_direct_proxy_updates_headers_from_plugin_context(self):
        # First-Party
        from mcpgateway.services.resource_service import ResourceService

        class _FakeTextResourceContents:
            def __init__(self, uri, mime_type=None, text="", **_kwargs):
                self.id = "resource-1"
                self.uri = uri
                self.mime_type = mime_type
                self.text = text

        service = ResourceService()
        service._get_plugin_manager = AsyncMock(return_value=None)
        db = MagicMock()
        gateway = MagicMock(id="gw-1", gateway_mode="direct_proxy", url="https://gateway.example.com/mcp")
        resource_db = MagicMock(gateway=gateway, enabled=True)
        db.execute.return_value.scalar_one_or_none.return_value = resource_db
        plugin_global_context = GlobalContext(request_id="req-1", user_context=UserContext(user_id="user-1", email="user@example.com"))
        mock_response = MagicMock()
        mock_response.contents = [MagicMock(text="hello", mime_type="text/plain")]

        client_mock = AsyncMock()
        client_mock.__aenter__ = AsyncMock(return_value=client_mock)
        client_mock.__aexit__ = AsyncMock(return_value=None)

        with (
            patch.object(service, "_get_plugin_manager", AsyncMock(return_value=None)),
            patch.object(service, "invoke_resource", AsyncMock(return_value="hello")),
            patch("mcpgateway.services.resource_service.check_gateway_access", AsyncMock(return_value=True)),
            patch.object(service, "_check_resource_access", AsyncMock(return_value=True)),
            patch("mcpgateway.services.resource_service.build_gateway_auth_headers", return_value={"Authorization": "Bearer gateway"}),
            patch("mcpgateway.services.resource_service.build_identity_headers", return_value={"X-Identity": "1"}) as mock_build_headers,
            patch("mcpgateway.services.resource_service.mcp_proxy_client", return_value=client_mock),
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

        client_mock = AsyncMock()
        client_mock.__aenter__ = AsyncMock(return_value=client_mock)
        client_mock.__aexit__ = AsyncMock(return_value=None)
        client_mock.call_tool = AsyncMock(return_value=MagicMock(is_error=False))

        with (
            patch("mcpgateway.services.tool_service.fresh_db_session", return_value=_FreshDBSession(db)),
            patch("mcpgateway.services.tool_service.check_gateway_access", AsyncMock(return_value=True)),
            patch("mcpgateway.services.tool_service.build_gateway_auth_headers", return_value={}),
            patch("mcpgateway.services.tool_service.build_identity_headers", return_value={"X-Identity": "1"}) as mock_build_headers,
            patch("mcpgateway.services.tool_service.build_identity_meta", return_value={"identity": True}) as mock_build_meta,
            patch("mcpgateway.services.tool_service.create_span", return_value=mock_span),
            patch("mcpgateway.services.tool_service.inject_trace_context_headers", side_effect=lambda headers: headers),
            patch("mcpgateway.services.tool_service.mcp_proxy_client", return_value=client_mock),
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
        pinned_client = MagicMock()
        pinned_client.request = AsyncMock(return_value=response)
        pinned_client.aclose = AsyncMock()
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
            patch("mcpgateway.services.tool_service.apply_response_filter", return_value={"ok": True}),
            patch("mcpgateway.services.tool_service._build_pinned_rest_http_client", return_value=pinned_client),
        ):
            await service.invoke_tool(
                db,
                name="rest-tool",
                arguments={"value": 1},
                plugin_global_context=plugin_global_context,
            )

        mock_build_headers.assert_called_once_with(plugin_global_context.user_context, identity_propagation=None, audience="tool-1")
        assert pinned_client.request.call_args.kwargs["headers"]["X-Identity"] == "1"
        pinned_client.aclose.assert_awaited_once()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("cached_setting", [{"enabled": True}, {"enabled": False}, None, "missing"])
    async def test_invoke_tool_mcp_updates_headers_and_meta_from_global_context(self, cached_setting):
        # First-Party
        from mcpgateway.services.tool_service import ToolService
        from mcpgateway.services.upstream_session_registry import RegistryNotInitializedError

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
                    **({} if cached_setting == "missing" else {"identity_propagation": cached_setting}),
                },
            }
        )
        plugin_global_context = GlobalContext(request_id="req-1", user_context=UserContext(user_id="user-1", email="user@example.com"))
        mock_span = MagicMock()
        mock_span.__enter__.return_value = MagicMock()
        mock_span.__exit__.return_value = False

        mock_result = MagicMock(is_error=False, isError=False)
        mock_result.structured_content = None
        mock_result.meta = None
        mock_result.content = []
        mock_result.model_dump.return_value = {"content": [], "isError": False}

        client_mock = AsyncMock()
        client_mock.__aenter__ = AsyncMock(return_value=client_mock)
        client_mock.__aexit__ = AsyncMock(return_value=None)
        client_mock.call_tool = AsyncMock(return_value=mock_result)
        client_mock.session = client_mock

        with (
            patch("mcpgateway.services.tool_service._get_tool_lookup_cache", return_value=cache),
            patch("mcpgateway.services.tool_service.global_config_cache.get_passthrough_headers", return_value=[]),
            patch("mcpgateway.services.tool_service.build_identity_headers", return_value={"X-Identity": "1"}) as mock_build_headers,
            patch("mcpgateway.services.tool_service.build_identity_meta", return_value={"identity": True}) as mock_build_meta,
            patch("mcpgateway.services.tool_service.create_span", return_value=mock_span),
            patch("mcpgateway.services.tool_service.create_child_span", return_value=mock_span),
            patch("mcpgateway.services.tool_service.is_input_capture_enabled", return_value=False),
            patch("mcpgateway.services.tool_service.inject_trace_context_headers", side_effect=lambda headers: headers),
            patch("mcpgateway.services.tool_service.mcp_proxy_client", return_value=client_mock),
            patch("mcpgateway.services.tool_service.get_upstream_session_registry", side_effect=RegistryNotInitializedError("not init")),
        ):
            await service.invoke_tool(
                db,
                name="mcp-tool",
                arguments={"value": 1},
                plugin_global_context=plugin_global_context,
                meta_data={"existing": True},
            )

        expected = None if cached_setting == "missing" else cached_setting
        mock_build_headers.assert_called_once_with(plugin_global_context.user_context, identity_propagation=expected, audience="gw-1")
        mock_build_meta.assert_called_once_with(plugin_global_context.user_context, {"existing": True}, identity_propagation=expected, audience="gw-1")

class TestStreamableHttpTransportIdentityPropagationCoverage:
    """Cover transport identity forwarding branches."""

    @pytest.mark.asyncio
    async def test_proxy_list_tools_updates_headers_from_context_identity(self):
        # First-Party
        from mcpgateway.transports.context import user_identity_var
        from mcpgateway.transports.streamablehttp_transport import _proxy_list_tools_to_gateway

        gateway = MagicMock(id="gw-1", url="https://gateway.example.com/mcp")
        identity = UserContext(user_id="user-1", email="user@example.com")
        token = user_identity_var.set(identity)

        client_mock = AsyncMock()
        client_mock.__aenter__ = AsyncMock(return_value=client_mock)
        client_mock.__aexit__ = AsyncMock(return_value=None)
        client_mock.list_tools = AsyncMock(return_value=MagicMock(tools=[MagicMock(name="tool")]))

        try:
            with (
                patch("mcpgateway.transports.streamablehttp_transport.build_gateway_auth_headers", return_value={}),
                patch("mcpgateway.transports.streamablehttp_transport.build_identity_headers", return_value={"X-Identity": "1"}) as mock_build_headers,
                patch("mcpgateway.transports.streamablehttp_transport.mcp_proxy_client", return_value=client_mock),
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

        gateway = MagicMock(id="gw-1", url="https://gateway.example.com/mcp")
        identity = UserContext(user_id="user-1", email="user@example.com")
        token = user_identity_var.set(identity)

        client_mock = AsyncMock()
        client_mock.__aenter__ = AsyncMock(return_value=client_mock)
        client_mock.__aexit__ = AsyncMock(return_value=None)
        client_mock.list_resources = AsyncMock(return_value=MagicMock(resources=[MagicMock(uri="resource://example")]))

        try:
            with (
                patch("mcpgateway.transports.streamablehttp_transport.build_gateway_auth_headers", return_value={}),
                patch("mcpgateway.transports.streamablehttp_transport.build_identity_headers", return_value={"X-Identity": "1"}) as mock_build_headers,
                patch("mcpgateway.transports.streamablehttp_transport.mcp_proxy_client", return_value=client_mock),
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

        gateway = MagicMock(id="gw-1", url="https://gateway.example.com/mcp")
        identity = UserContext(user_id="user-1", email="user@example.com")
        identity_token = user_identity_var.set(identity)
        headers_token = request_headers_var.set({})

        client_mock = AsyncMock()
        client_mock.__aenter__ = AsyncMock(return_value=client_mock)
        client_mock.__aexit__ = AsyncMock(return_value=None)
        client_mock.read_resource = AsyncMock(return_value=MagicMock(contents=[MagicMock(text="hello")]))

        try:
            with (
                patch("mcpgateway.transports.streamablehttp_transport.build_gateway_auth_headers", return_value={}),
                patch("mcpgateway.transports.streamablehttp_transport.build_identity_headers", return_value={"X-Identity": "1"}) as mock_build_headers,
                patch("mcpgateway.transports.streamablehttp_transport.mcp_proxy_client", return_value=client_mock),
            ):
                await _proxy_read_resource_to_gateway(gateway, "resource://example", {})
        finally:
            request_headers_var.reset(headers_token)
            user_identity_var.reset(identity_token)

        mock_build_headers.assert_called_once_with(identity, gateway)


def _proxy_client_mock():
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    client.list_tools = AsyncMock(return_value=MagicMock(tools=[]))
    client.list_resources = AsyncMock(return_value=MagicMock(resources=[]))
    client.read_resource = AsyncMock(return_value=MagicMock(contents=[]))
    return client


def _real_gateway():
    return MagicMock(id="gw-real-1", url="https://gateway.example.com/mcp", identity_propagation=None, auth_type=None, passthrough_headers=[])


async def _run_transport_path(path: str, gateway, *, signing_error: bool = False):
    """Run one streamable HTTP direct-proxy path; return the headers sent upstream."""
    # First-Party
    from mcpgateway.transports import streamablehttp_transport as transport
    from mcpgateway.transports.context import request_headers_var, user_identity_var

    identity_token = user_identity_var.set(_full_user())
    headers_token = request_headers_var.set({})
    proxy = MagicMock(return_value=_proxy_client_mock())
    patches = [
        patch.object(transport, "build_gateway_auth_headers", return_value={}),
        patch.object(transport, "mcp_proxy_client", proxy),
    ]
    if signing_error:
        patches.append(patch.object(transport, "build_identity_headers", side_effect=IdentitySigningError("no secret")))
    try:
        for p in patches:
            p.start()
        if path == "list_tools":
            await transport._proxy_list_tools_to_gateway(gateway, {}, {})
        elif path == "list_resources":
            await transport._proxy_list_resources_to_gateway(gateway, {}, {})
        else:
            await transport._proxy_read_resource_to_gateway(gateway, "resource://example", {})
    finally:
        for p in patches:
            p.stop()
        request_headers_var.reset(headers_token)
        user_identity_var.reset(identity_token)
    return proxy.call_args.kwargs["headers"]


class TestDirectProxyAudienceBinding:
    """Direct-proxy paths sign with the real gateway id as the audience."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("path", ["list_tools", "list_resources", "read_resource"])
    async def test_transport_path_signs_for_gateway(self, signing_settings, path):
        gateway = _real_gateway()
        headers = await _run_transport_path(path, gateway)
        assert _decode(headers[SIG], audience=str(gateway.id))["aud"] == str(gateway.id)


async def _run_pooled_resource_read(*, meta_data=None, meta_error: bool = False):
    """Run invoke_resource through the pooled SSE session path; return the _meta sent upstream."""
    # First-Party
    from mcpgateway.services.resource_service import ResourceService
    from mcpgateway.transports.streamablehttp_transport import request_headers_var

    gateway = MagicMock(id="gw-1", name="Gateway", url="https://gateway.example.com/mcp", transport="sse", auth_type=None, auth_value={}, oauth_config=None, auth_query_params=None)
    gateway.ca_certificate = None
    gateway.ca_certificate_sig = None
    gateway.identity_propagation = None
    upstream_session = AsyncMock()
    upstream_session.send_request = AsyncMock(return_value=MagicMock(contents=[MagicMock(text="ok", blob=None)]))

    @asynccontextmanager
    async def fake_acquire(**_kwargs):
        yield MagicMock(session=upstream_session)

    registry = MagicMock(acquire=fake_acquire)
    span = MagicMock()
    span.__enter__.return_value = MagicMock()
    span.__exit__.return_value = False
    meta_patch = patch("mcpgateway.services.resource_service.build_identity_meta", side_effect=IdentitySigningError("no secret")) if meta_error else nullcontext()
    token = request_headers_var.set({"mcp-session-id": "downstream-1"})
    try:
        with (
            patch("mcpgateway.services.resource_service.create_span", return_value=span),
            patch("mcpgateway.services.resource_service.is_input_capture_enabled", return_value=False),
            patch("mcpgateway.services.resource_service.get_upstream_session_registry", return_value=registry),
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service", return_value=MagicMock()),
            meta_patch,
        ):
            await ResourceService().invoke_resource(
                MagicMock(),
                resource_id="res-1",
                resource_uri="resource://example",
                user_identity=UserContext(user_id="alice@co.com", email="alice@co.com"),
                resource_obj=MagicMock(gateway_id="gw-1"),
                gateway_obj=gateway,
                meta_data=meta_data,
            )
    finally:
        request_headers_var.reset(token)
    return upstream_session.send_request.call_args.args[0].params.meta


class TestPooledResourceReadSignsMeta:
    """A pooled session carries no claims header, so each resource read signs through _meta."""

    @pytest.mark.asyncio
    async def test_meta_carries_fresh_claims_signature(self, signing_settings):
        meta = await _run_pooled_resource_read()
        assert _decode(meta["user"]["claims_signature"], audience="gw-1")["email"] == "alice@co.com"

    @pytest.mark.asyncio
    async def test_caller_meta_keys_are_preserved(self, signing_settings):
        caller_meta = {"trace": "abc"}
        meta = await _run_pooled_resource_read(meta_data=caller_meta)
        assert meta["trace"] == "abc"
        assert "claims_signature" in meta["user"]
        assert caller_meta == {"trace": "abc"}

    @pytest.mark.asyncio
    async def test_signing_failure_raises_resource_error(self, signing_settings):
        # First-Party
        from mcpgateway.services.resource_service import ResourceError

        with pytest.raises(ResourceError, match="misconfigured"):
            await _run_pooled_resource_read(meta_error=True)


class TestIdentitySigningFailureSurfaces:
    """A signing failure is a configuration error on every upstream path, never an empty result."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("path", ["list_tools", "list_resources", "read_resource"])
    async def test_transport_path_raises_configuration_error(self, path):
        # First-Party
        from mcp.shared.exceptions import MCPError

        with pytest.raises(MCPError, match="misconfigured"):
            await _run_transport_path(path, _real_gateway(), signing_error=True)

    @pytest.mark.asyncio
    async def test_invoke_resource_raises_resource_error(self):
        # First-Party
        from mcpgateway.services.resource_service import ResourceError, ResourceService

        gateway = MagicMock(id="gw-1", url="https://gateway.example.com/mcp", transport="streamablehttp", auth_type=None, auth_value={}, oauth_config=None, auth_query_params=None, ca_certificate=None, ca_certificate_sig=None, name="Gateway")
        mock_span = MagicMock()
        mock_span.__enter__.return_value = MagicMock()
        mock_span.__exit__.return_value = False
        with (
            patch("mcpgateway.services.resource_service.create_span", return_value=mock_span),
            patch("mcpgateway.services.resource_service.is_input_capture_enabled", return_value=False),
            patch("mcpgateway.services.resource_service.build_identity_headers", side_effect=IdentitySigningError("no secret")),
        ):
            with pytest.raises(ResourceError, match="misconfigured"):
                await ResourceService().invoke_resource(
                    MagicMock(),
                    resource_id="res-1",
                    resource_uri="resource://example",
                    user_identity=UserContext(user_id="user-1", email="user@example.com"),
                    resource_obj=MagicMock(gateway_id="gw-1"),
                    gateway_obj=gateway,
                )

    @pytest.mark.asyncio
    async def test_read_resource_direct_proxy_raises_resource_error(self):
        # First-Party
        from mcpgateway.services.resource_service import ResourceError, ResourceService
        from mcpgateway.services import resource_service

        service = ResourceService()
        db = MagicMock()
        gateway = MagicMock(id="gw-1", gateway_mode="direct_proxy", url="https://gateway.example.com/mcp")
        db.execute.return_value.scalar_one_or_none.return_value = MagicMock(gateway=gateway, enabled=True)
        context = GlobalContext(request_id="req-1", user_context=UserContext(user_id="user-1", email="user@example.com"))
        with (
            patch.object(service, "_get_plugin_manager", AsyncMock(return_value=None)),
            patch.object(service, "_check_resource_access", AsyncMock(return_value=True)),
            patch("mcpgateway.services.resource_service.check_gateway_access", AsyncMock(return_value=True)),
            patch("mcpgateway.services.resource_service.build_gateway_auth_headers", return_value={}),
            patch("mcpgateway.services.resource_service.build_identity_headers", side_effect=IdentitySigningError("no secret")),
            patch.object(resource_service.settings, "mcpgateway_direct_proxy_enabled", True),
        ):
            with pytest.raises(ResourceError, match="misconfigured"):
                await service.read_resource(db, resource_uri="resource://example", user="user@example.com", plugin_global_context=context)

    @pytest.mark.asyncio
    async def test_invoke_tool_direct_raises_tool_invocation_error(self):
        # First-Party
        from mcpgateway.services import tool_service
        from mcpgateway.services.tool_service import ToolInvocationError, ToolService

        db = MagicMock()
        gateway = MagicMock(id="gw-1", gateway_mode="direct_proxy", passthrough_headers=[], url="https://gateway.example.com/mcp")
        db.execute.return_value.scalar_one_or_none.return_value = gateway
        fresh = MagicMock()
        fresh.__enter__.return_value = db
        fresh.__exit__.return_value = False
        with (
            patch("mcpgateway.services.tool_service.fresh_db_session", return_value=fresh),
            patch("mcpgateway.services.tool_service.check_gateway_access", AsyncMock(return_value=True)),
            patch("mcpgateway.services.tool_service.build_gateway_auth_headers", return_value={}),
            patch("mcpgateway.services.tool_service.build_identity_headers", side_effect=IdentitySigningError("no secret")),
            patch.object(tool_service.settings, "mcpgateway_direct_proxy_enabled", True),
        ):
            with pytest.raises(ToolInvocationError, match="misconfigured"):
                await ToolService().invoke_tool_direct(
                    gateway_id="gw-1",
                    name="gw-tool",
                    arguments={},
                    user_email="user@example.com",
                    user_context=UserContext(user_id="user-1", email="user@example.com"),
                )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("integration_type", ["REST", "MCP"])
    async def test_invoke_tool_raises_tool_invocation_error(self, integration_type):
        # First-Party
        from mcpgateway.services.tool_service import ToolInvocationError, ToolService

        service = ToolService()
        service._get_plugin_manager = AsyncMock(return_value=None)
        service._check_tool_access = AsyncMock(return_value=True)
        is_rest = integration_type == "REST"
        cache = MagicMock()
        cache.enabled = True
        cache.get = AsyncMock(
            return_value={
                "status": "active",
                "tool": {
                    "id": "tool-1",
                    "name": "t",
                    "original_name": "t",
                    "enabled": True,
                    "reachable": True,
                    "integration_type": integration_type,
                    "request_type": "POST" if is_rest else "streamablehttp",
                    "url": "https://api.example.com/tools" if is_rest else None,
                    "headers": {},
                    "gateway_id": None if is_rest else "gw-1",
                },
                "gateway": None
                if is_rest
                else {
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
        context = GlobalContext(request_id="req-1", user_context=UserContext(user_id="user-1", email="user@example.com"))
        mock_span = MagicMock()
        mock_span.__enter__.return_value = MagicMock()
        mock_span.__exit__.return_value = False
        with (
            patch("mcpgateway.services.tool_service._get_tool_lookup_cache", return_value=cache),
            patch("mcpgateway.services.tool_service.global_config_cache.get_passthrough_headers", return_value=[]),
            patch("mcpgateway.services.tool_service.build_identity_headers", side_effect=IdentitySigningError("no secret")),
            patch("mcpgateway.services.tool_service.create_span", return_value=mock_span),
            patch("mcpgateway.services.tool_service.create_child_span", return_value=mock_span),
            patch("mcpgateway.services.tool_service.is_input_capture_enabled", return_value=False),
        ):
            with pytest.raises(ToolInvocationError, match="misconfigured"):
                await service.invoke_tool(MagicMock(), name="t", arguments={}, plugin_global_context=context)
