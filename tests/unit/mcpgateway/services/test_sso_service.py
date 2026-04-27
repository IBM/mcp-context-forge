# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_sso_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Unit tests for SSOService.
"""

# Future
from __future__ import annotations

# Standard
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
import urllib.parse

# Third-Party
import pytest

# First-Party
from mcpgateway.services.sso_service import SSOService

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_db():
    db = MagicMock()
    db.execute.return_value = MagicMock()
    db.add = MagicMock()
    db.commit = MagicMock()
    db.rollback = MagicMock()
    db.refresh = MagicMock()
    db.delete = MagicMock()
    return db


@pytest.fixture
def sso_service(mock_db):
    with patch("mcpgateway.services.sso_service.get_encryption_service") as mock_enc:
        enc_instance = MagicMock()
        enc_instance.encrypt_secret_async = AsyncMock(return_value="encrypted")
        enc_instance.decrypt_secret_async = AsyncMock(return_value="decrypted")
        mock_enc.return_value = enc_instance
        service = SSOService(mock_db)
        return service


def _make_provider(**overrides):
    """Factory for mock SSOProvider."""
    defaults = {
        "id": "github",
        "name": "github",
        "display_name": "GitHub",
        "is_enabled": True,
        "provider_type": "oauth2",
        "client_id": "cid",
        "client_secret_encrypted": "enc",
        "authorization_url": "https://github.com/login/oauth/authorize",
        "token_url": "https://github.com/login/oauth/access_token",
        "userinfo_url": "https://api.github.com/user",
        "scope": "user:email",
        "issuer": None,
        "jwks_uri": None,
        "auto_create_users": True,
        "trusted_domains": None,
        "provider_metadata": None,
        "team_mapping": {},
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_auth_session(**overrides):
    """Factory for mock SSOAuthSession."""
    defaults = {
        "provider_id": "github",
        "state": "test-state",
        "code_verifier": "verifier123",
        "nonce": None,
        "redirect_uri": "https://app/callback",
        "is_expired": False,
        "provider": _make_provider(),
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# ---------------------------------------------------------------------------
# Encryption tests
# ---------------------------------------------------------------------------


class TestEncryption:
    @pytest.mark.asyncio
    async def test_encrypt_secret(self, sso_service):
        result = await sso_service._encrypt_secret("my-secret")
        assert result == "encrypted"

    @pytest.mark.asyncio
    async def test_decrypt_secret(self, sso_service):
        result = await sso_service._decrypt_secret("encrypted-data")
        assert result == "decrypted"

    @pytest.mark.asyncio
    async def test_decrypt_secret_returns_none(self, sso_service):
        sso_service._encryption.decrypt_secret_async = AsyncMock(return_value=None)
        result = await sso_service._decrypt_secret("bad-data")
        assert result is None


# ---------------------------------------------------------------------------
# CRUD tests
# ---------------------------------------------------------------------------


class TestProviderCRUD:
    def test_list_enabled_providers(self, sso_service, mock_db):
        providers = [_make_provider(), _make_provider(id="google", name="google")]
        mock_db.execute.return_value.scalars.return_value.all.return_value = providers
        result = sso_service.list_enabled_providers()
        assert len(result) == 2

    def test_list_all_providers(self, sso_service, mock_db):
        """Test list_all_providers returns all providers regardless of enabled status."""
        providers = [_make_provider(), _make_provider(id="google", name="google", is_enabled=False)]
        mock_db.execute.return_value.scalars.return_value.all.return_value = providers
        result = sso_service.list_all_providers()
        assert len(result) == 2

    def test_get_provider(self, sso_service, mock_db):
        provider = _make_provider()
        mock_db.execute.return_value.scalar_one_or_none.return_value = provider
        result = sso_service.get_provider("github")
        assert result.id == "github"

    def test_get_provider_not_found(self, sso_service, mock_db):
        mock_db.execute.return_value.scalar_one_or_none.return_value = None
        result = sso_service.get_provider("missing")
        assert result is None

    def test_get_provider_by_name(self, sso_service, mock_db):
        provider = _make_provider()
        mock_db.execute.return_value.scalar_one_or_none.return_value = provider
        result = sso_service.get_provider_by_name("github")
        assert result.id == "github"

    @pytest.mark.asyncio
    async def test_create_provider(self, sso_service, mock_db):
        data = {
            "id": "github",
            "name": "github",
            "display_name": "GitHub",
            "provider_type": "oauth2",
            "client_id": "cid",
            "client_secret": "sec",
            "authorization_url": "https://auth",
            "token_url": "https://token",
            "userinfo_url": "https://userinfo",
            "scope": "user:email",
        }
        result = await sso_service.create_provider(data)
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_provider_rejects_disallowed_issuer(self, sso_service):
        data = {
            "id": "github",
            "name": "github",
            "display_name": "GitHub",
            "provider_type": "oidc",
            "client_id": "cid",
            "client_secret": "sec",
            "authorization_url": "https://auth",
            "token_url": "https://token",
            "userinfo_url": "https://userinfo",
            "issuer": "https://issuer.denied.example.com",
            "scope": "openid profile email",
        }
        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_issuers = ["https://issuer.allowed.example.com"]
            with pytest.raises(ValueError, match="Issuer is not allowed"):
                await sso_service.create_provider(data)

    def test_enforce_allowed_issuer_ignores_blank_candidate(self, sso_service):
        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_issuers = ["https://issuer.allowed.example.com"]
            sso_service._enforce_allowed_issuer("  ")

    @pytest.mark.asyncio
    async def test_update_provider(self, sso_service, mock_db):
        existing = _make_provider()
        sso_service.get_provider = lambda _id: existing
        result = await sso_service.update_provider("github", {"client_id": "new-cid", "client_secret": "new-sec"})
        assert result.client_id == "new-cid"
        assert result.client_secret_encrypted == "encrypted"

    @pytest.mark.asyncio
    async def test_update_provider_rejects_disallowed_issuer(self, sso_service):
        existing = _make_provider()
        sso_service.get_provider = lambda _id: existing
        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_issuers = ["https://issuer.allowed.example.com"]
            with pytest.raises(ValueError, match="Issuer is not allowed"):
                await sso_service.update_provider("github", {"issuer": "https://issuer.denied.example.com"})

    @pytest.mark.asyncio
    async def test_update_provider_not_found(self, sso_service):
        sso_service.get_provider = lambda _id: None
        result = await sso_service.update_provider("missing", {"client_id": "x"})
        assert result is None

    @pytest.mark.asyncio
    async def test_update_provider_no_secret(self, sso_service, mock_db):
        existing = _make_provider()
        sso_service.get_provider = lambda _id: existing
        result = await sso_service.update_provider("github", {"client_id": "updated"})
        assert result.client_id == "updated"

    def test_delete_provider(self, sso_service, mock_db):
        sso_service.get_provider = lambda _id: _make_provider()
        result = sso_service.delete_provider("github")
        assert result is True
        mock_db.delete.assert_called_once()

    def test_delete_provider_not_found(self, sso_service):
        sso_service.get_provider = lambda _id: None
        result = sso_service.delete_provider("missing")
        assert result is False


# ---------------------------------------------------------------------------
# PKCE and authorization URL tests
# ---------------------------------------------------------------------------


class TestAuthFlow:
    def test_generate_pkce_challenge(self, sso_service):
        verifier, challenge = sso_service.generate_pkce_challenge()
        assert isinstance(verifier, str) and len(verifier) >= 43
        assert isinstance(challenge, str) and len(challenge) >= 43
        assert verifier != challenge

    def test_get_authorization_url(self, sso_service, mock_db):
        provider = _make_provider()
        sso_service.get_provider = lambda _id: provider
        url = sso_service.get_authorization_url("github", "https://app/callback", ["user:email"])
        assert url is not None
        assert "client_id=cid" in url
        assert "state=" in url
        assert "code_challenge=" in url

    def test_get_authorization_url_with_nonce(self, sso_service, mock_db):
        provider = _make_provider(provider_type="oidc")
        sso_service.get_provider = lambda _id: provider
        url = sso_service.get_authorization_url("github", "https://app/callback")
        assert url is not None
        assert "nonce=" in url

    def test_get_authorization_url_rejects_scope_outside_allowlist(self, sso_service):
        provider = _make_provider(scope="openid profile email")
        sso_service.get_provider = lambda _id: provider

        with pytest.raises(ValueError, match="Invalid scopes requested"):
            sso_service.get_authorization_url("github", "https://app/callback", ["openid", "admin"])

    def test_get_authorization_url_with_session_binding(self, sso_service):
        provider = _make_provider()
        sso_service.get_provider = lambda _id: provider

        url = sso_service.get_authorization_url("github", "https://app/callback", ["user:email"], session_binding="browser-session-1")
        assert url is not None
        state_value = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["state"][0]
        assert sso_service._is_session_bound_state(state_value) is True
        assert sso_service._verify_session_bound_state("github", state_value, "browser-session-1") is True

    def test_get_authorization_url_not_found(self, sso_service):
        sso_service.get_provider = lambda _id: None
        url = sso_service.get_authorization_url("missing", "https://app/callback")
        assert url is None

    def test_get_authorization_url_disabled(self, sso_service):
        provider = _make_provider(is_enabled=False)
        sso_service.get_provider = lambda _id: provider
        url = sso_service.get_authorization_url("disabled", "https://app/callback")
        assert url is None

    def test_normalize_scope_values_none_returns_empty_list(self, sso_service):
        assert sso_service._normalize_scope_values(None) == []

    def test_normalize_scope_values_deduplicates_and_strips(self, sso_service):
        normalized = sso_service._normalize_scope_values(["openid", " ", "openid", "email"])
        assert normalized == ["openid", "email"]

    def test_resolve_login_scopes_rejects_missing_provider_scopes(self, sso_service):
        provider = _make_provider(scope=None)

        with pytest.raises(ValueError, match="Provider has no configured scopes"):
            sso_service._resolve_login_scopes(provider, requested_scopes=None)

    def test_resolve_login_scopes_applies_metadata_allowlist(self, sso_service):
        provider = _make_provider(scope="openid profile email", provider_metadata={"allowed_scopes": ["openid", "email"]})

        resolved = sso_service._resolve_login_scopes(provider, requested_scopes=None)
        assert resolved == ["openid", "email"]

    def test_resolve_login_scopes_rejects_empty_metadata_intersection(self, sso_service):
        provider = _make_provider(scope="openid profile", provider_metadata={"allowed_scopes": ["admin"]})

        with pytest.raises(ValueError, match="No allowed scopes configured for provider"):
            sso_service._resolve_login_scopes(provider, requested_scopes=None)

    def test_resolve_login_scopes_empty_requested_after_normalization_returns_allowed(self, sso_service):
        provider = _make_provider(scope="openid profile")
        resolved = sso_service._resolve_login_scopes(provider, requested_scopes=[" ", ""])
        assert resolved == ["openid", "profile"]

    def test_get_state_binding_secret_uses_secret_value_accessor(self, sso_service):
        class _Secret:
            def get_secret_value(self):
                return "from-secret"

        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.auth_encryption_secret = _Secret()
            secret_bytes = sso_service._get_state_binding_secret()

        assert secret_bytes == b"from-secret"

    def test_get_state_binding_secret_falls_back_to_string_encoding(self, sso_service):
        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.auth_encryption_secret = "plain-secret"
            secret_bytes = sso_service._get_state_binding_secret()

        assert secret_bytes == b"plain-secret"

    def test_verify_session_bound_state_rejects_legacy_unbound_state(self, sso_service):
        assert sso_service._verify_session_bound_state("github", "legacy-state", "session-1") is False

    def test_is_email_verified_claim_handles_int_values(self, sso_service):
        assert sso_service._is_email_verified_claim({"email_verified": 1}) is True
        assert sso_service._is_email_verified_claim({"email_verified": 0}) is False

    def test_is_email_verified_claim_handles_string_and_unknown_values(self, sso_service):
        assert sso_service._is_email_verified_claim({"email_verified": "yes"}) is True
        assert sso_service._is_email_verified_claim({"email_verified": "no"}) is False
        assert sso_service._is_email_verified_claim({"email_verified": object()}) is False

    def test_is_email_verified_claim_none_value_is_rejected(self, sso_service):
        # Explicit None (JSON null) is distinct from absent key: key IS present,
        # so the absent-means-pass-through branch does not fire.  None falls
        # through all isinstance checks and returns False — blocking login.
        assert sso_service._is_email_verified_claim({"email_verified": None}) is False

    def test_is_email_verified_claim_missing_claim_is_pass_through(self, sso_service):
        # Absent claim (e.g. Entra ID, GitHub work accounts) must NOT block login.
        assert sso_service._is_email_verified_claim({"email": "user@example.com"}) is True
        assert sso_service._is_email_verified_claim({}) is True

    def test_is_email_verified_claim_microsoft_verified_primary_email(self, sso_service):
        """Test Microsoft Entra ID verified_primary_email claim is recognized."""
        assert sso_service._is_email_verified_claim({"verified_primary_email": True}) is True
        assert sso_service._is_email_verified_claim({"verified_primary_email": False}) is False
        assert sso_service._is_email_verified_claim({"verified_primary_email": 1}) is True
        assert sso_service._is_email_verified_claim({"verified_primary_email": 0}) is False
        assert sso_service._is_email_verified_claim({"verified_primary_email": "true"}) is True
        assert sso_service._is_email_verified_claim({"verified_primary_email": "false"}) is False

    def test_is_email_verified_claim_microsoft_verified_secondary_email(self, sso_service):
        """Test Microsoft Entra ID verified_secondary_email claim is recognized."""
        assert sso_service._is_email_verified_claim({"verified_secondary_email": True}) is True
        assert sso_service._is_email_verified_claim({"verified_secondary_email": False}) is False
        assert sso_service._is_email_verified_claim({"verified_secondary_email": 1}) is True
        assert sso_service._is_email_verified_claim({"verified_secondary_email": 0}) is False
        assert sso_service._is_email_verified_claim({"verified_secondary_email": "yes"}) is True
        assert sso_service._is_email_verified_claim({"verified_secondary_email": "no"}) is False

    def test_is_email_verified_claim_standard_takes_precedence(self, sso_service):
        """Test that standard email_verified claim takes precedence over Microsoft claims."""
        # Standard claim is True, Microsoft claim is False - standard wins
        assert sso_service._is_email_verified_claim({"email_verified": True, "verified_primary_email": False}) is True

        # Standard claim is False, Microsoft claim is True - standard wins
        assert sso_service._is_email_verified_claim({"email_verified": False, "verified_primary_email": True}) is False

    def test_is_email_verified_claim_primary_takes_precedence_over_secondary(self, sso_service):
        """Test that verified_primary_email takes precedence over verified_secondary_email."""
        # Primary is True, Secondary is False - primary wins
        assert sso_service._is_email_verified_claim({"verified_primary_email": True, "verified_secondary_email": False}) is True

        # Primary is False, Secondary is True - primary wins (blocks login)
        assert sso_service._is_email_verified_claim({"verified_primary_email": False, "verified_secondary_email": True}) is False

    def test_is_email_verified_claim_all_microsoft_claims_absent_is_pass_through(self, sso_service):
        """Test that absence of all verification claims allows login (Entra ID work accounts)."""
        # No verification claims at all - should pass through
        assert sso_service._is_email_verified_claim({"email": "user@company.com", "name": "Test User", "sub": "abc123"}) is True

    def test_is_email_verified_claim_microsoft_unrecognized_type_fails_secure(self, sso_service):
        """Unrecognized value types on Microsoft claims are rejected, symmetric with email_verified."""
        # None / dict / list on the primary claim blocks login instead of silently
        # falling through to the secondary claim.
        assert sso_service._is_email_verified_claim({"verified_primary_email": None}) is False
        assert sso_service._is_email_verified_claim({"verified_secondary_email": None}) is False
        assert sso_service._is_email_verified_claim({"verified_primary_email": {}}) is False
        assert sso_service._is_email_verified_claim({"verified_primary_email": None, "verified_secondary_email": True}) is False

    def test_normalize_adfs_email_returns_none_for_empty_input(self, sso_service):
        """Test _normalize_adfs_email returns None when raw_email is empty."""
        assert sso_service._normalize_adfs_email("", "example.com") is None
        assert sso_service._normalize_adfs_email(None, "example.com") is None

    def test_normalize_adfs_email_fallback_returns_as_is(self, sso_service):
        """Test _normalize_adfs_email fallback path returns raw value as-is."""
        # Edge case: has @ but no dot in domain part (malformed but not caught by earlier checks)
        result = sso_service._normalize_adfs_email("user@nodot", None)
        assert result == "user@nodot"


# ---------------------------------------------------------------------------
# OAuth callback tests
# ---------------------------------------------------------------------------


class TestOAuthCallback:
    @pytest.mark.asyncio
    async def test_handle_oauth_callback_success(self, sso_service, mock_db):
        auth_session = _make_auth_session()
        mock_db.execute.return_value.scalar_one_or_none.return_value = auth_session

        async def _exchange(p, sess, c):
            return {"access_token": "tok", "id_token": "id_tok"}

        async def _user_info(p, access, token_data=None, expected_nonce=None):  # noqa: ARG001
            return {"email": "user@example.com", "provider": "github"}

        sso_service._exchange_code_for_tokens = _exchange
        sso_service._get_user_info = _user_info

        result = await sso_service.handle_oauth_callback("github", "code", "test-state")
        assert result is not None
        assert result["email"] == "user@example.com"

    @pytest.mark.asyncio
    async def test_handle_oauth_callback_with_tokens_success(self, sso_service, mock_db):
        auth_session = _make_auth_session()
        mock_db.execute.return_value.scalar_one_or_none.return_value = auth_session

        async def _exchange(p, sess, c):
            return {"access_token": "tok", "id_token": "id_tok"}

        async def _user_info(p, access, token_data=None, expected_nonce=None):  # noqa: ARG001
            return {"email": "user@example.com", "provider": "github"}

        sso_service._exchange_code_for_tokens = _exchange
        sso_service._get_user_info = _user_info

        result = await sso_service.handle_oauth_callback_with_tokens("github", "code", "test-state")
        assert result is not None
        user_info, token_data = result
        assert user_info["email"] == "user@example.com"
        assert token_data["id_token"] == "id_tok"

    @pytest.mark.asyncio
    async def test_handle_oauth_callback_with_tokens_rejects_session_mismatch(self, sso_service, mock_db):
        session_bound_state = sso_service._generate_session_bound_state("github", "session-1")
        auth_session = _make_auth_session(state=session_bound_state)
        mock_db.execute.return_value.scalar_one_or_none.return_value = auth_session

        result = await sso_service.handle_oauth_callback_with_tokens(
            "github",
            "code",
            session_bound_state,
            session_binding="session-2",
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_handle_oauth_callback_with_tokens_oidc_rejects_unverified_id_token(self, sso_service, mock_db):
        """OIDC callback should fail when id_token verification fails."""
        provider = _make_provider(id="keycloak", provider_type="oidc", issuer="https://issuer.example.com", jwks_uri="https://issuer.example.com/jwks")
        auth_session = _make_auth_session(provider=provider, nonce="nonce-1")
        mock_db.execute.return_value.scalar_one_or_none.return_value = auth_session

        async def _exchange(p, sess, c):
            return {"access_token": "tok", "id_token": "bad-id-token"}

        sso_service._exchange_code_for_tokens = _exchange
        sso_service._verify_oidc_id_token = AsyncMock(return_value=None)
        sso_service._get_user_info = AsyncMock(return_value={"email": "user@example.com", "provider": "keycloak"})

        result = await sso_service.handle_oauth_callback_with_tokens("keycloak", "code", "test-state")
        assert result is None
        sso_service._get_user_info.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_oauth_callback_with_tokens_oidc_passes_verified_claims(self, sso_service, mock_db):
        """OIDC callback should pass verified id_token claims to user-info path."""
        provider = _make_provider(id="keycloak", provider_type="oidc", issuer="https://issuer.example.com", jwks_uri="https://issuer.example.com/jwks")
        auth_session = _make_auth_session(provider=provider, nonce="nonce-1")
        mock_db.execute.return_value.scalar_one_or_none.return_value = auth_session

        async def _exchange(p, sess, c):
            return {"access_token": "tok", "id_token": "good-id-token"}

        async def _user_info(_provider, _access, token_data=None, expected_nonce=None):  # noqa: ARG001
            assert token_data is not None
            assert token_data["_verified_id_token_claims"] == {"sub": "user-1", "nonce": "nonce-1"}
            return {"email": "user@example.com", "provider": "keycloak"}

        sso_service._exchange_code_for_tokens = _exchange
        sso_service._verify_oidc_id_token = AsyncMock(return_value={"sub": "user-1", "nonce": "nonce-1"})
        sso_service._get_user_info = _user_info

        result = await sso_service.handle_oauth_callback_with_tokens("keycloak", "code", "test-state")
        assert result is not None
        user_info, token_data = result
        assert user_info["email"] == "user@example.com"
        assert token_data["_verified_id_token_claims"]["sub"] == "user-1"

    @pytest.mark.asyncio
    async def test_handle_oauth_callback_no_session(self, sso_service, mock_db):
        mock_db.execute.return_value.scalar_one_or_none.return_value = None
        result = await sso_service.handle_oauth_callback("github", "code", "bad-state")
        assert result is None

    @pytest.mark.asyncio
    async def test_handle_oauth_callback_expired(self, sso_service, mock_db):
        auth_session = _make_auth_session(is_expired=True)
        mock_db.execute.return_value.scalar_one_or_none.return_value = auth_session
        result = await sso_service.handle_oauth_callback("github", "code", "test-state")
        assert result is None

    @pytest.mark.asyncio
    async def test_handle_oauth_callback_disabled_provider(self, sso_service, mock_db):
        auth_session = _make_auth_session(provider=_make_provider(is_enabled=False))
        mock_db.execute.return_value.scalar_one_or_none.return_value = auth_session
        result = await sso_service.handle_oauth_callback("github", "code", "test-state")
        assert result is None

    @pytest.mark.asyncio
    async def test_handle_oauth_callback_token_exchange_fails(self, sso_service, mock_db):
        auth_session = _make_auth_session()
        mock_db.execute.return_value.scalar_one_or_none.return_value = auth_session

        async def _exchange(p, sess, c):
            return None

        sso_service._exchange_code_for_tokens = _exchange
        result = await sso_service.handle_oauth_callback("github", "code", "test-state")
        assert result is None

    @pytest.mark.asyncio
    async def test_handle_oauth_callback_with_tokens_oidc_requires_nonce(self, sso_service, mock_db):
        """OIDC callback should fail when auth session nonce is missing."""
        provider = _make_provider(id="keycloak", provider_type="oidc", issuer="https://issuer.example.com", jwks_uri="https://issuer.example.com/jwks")
        auth_session = _make_auth_session(provider=provider, nonce=None)
        mock_db.execute.return_value.scalar_one_or_none.return_value = auth_session

        async def _exchange(_p, _sess, _code):
            return {"access_token": "tok", "id_token": "id-token"}

        sso_service._exchange_code_for_tokens = _exchange
        sso_service._verify_oidc_id_token = AsyncMock(return_value={"sub": "user-1"})
        sso_service._get_user_info = AsyncMock(return_value={"email": "user@example.com"})

        result = await sso_service.handle_oauth_callback_with_tokens("keycloak", "code", "test-state")
        assert result is None
        sso_service._verify_oidc_id_token.assert_not_called()
        sso_service._get_user_info.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_oauth_callback_with_tokens_oidc_requires_id_token(self, sso_service, mock_db):
        """OIDC callback should fail when token response does not contain id_token."""
        provider = _make_provider(id="keycloak", provider_type="oidc", issuer="https://issuer.example.com", jwks_uri="https://issuer.example.com/jwks")
        auth_session = _make_auth_session(provider=provider, nonce="nonce-1")
        mock_db.execute.return_value.scalar_one_or_none.return_value = auth_session

        async def _exchange(_p, _sess, _code):
            return {"access_token": "tok"}

        sso_service._exchange_code_for_tokens = _exchange
        sso_service._verify_oidc_id_token = AsyncMock(return_value={"sub": "user-1"})
        sso_service._get_user_info = AsyncMock(return_value={"email": "user@example.com"})

        result = await sso_service.handle_oauth_callback_with_tokens("keycloak", "code", "test-state")
        assert result is None
        sso_service._verify_oidc_id_token.assert_not_called()
        sso_service._get_user_info.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_oauth_callback_user_info_fails(self, sso_service, mock_db):
        auth_session = _make_auth_session()
        mock_db.execute.return_value.scalar_one_or_none.return_value = auth_session

        async def _exchange(p, sess, c):
            return {"access_token": "tok"}

        async def _user_info(p, access, token_data=None, expected_nonce=None):  # noqa: ARG001
            return None

        sso_service._exchange_code_for_tokens = _exchange
        sso_service._get_user_info = _user_info
        result = await sso_service.handle_oauth_callback("github", "code", "test-state")
        assert result is None

    @pytest.mark.asyncio
    async def test_handle_oauth_callback_exception(self, sso_service, mock_db):
        auth_session = _make_auth_session()
        mock_db.execute.return_value.scalar_one_or_none.return_value = auth_session

        async def _exchange(p, sess, c):
            raise RuntimeError("network error")

        sso_service._exchange_code_for_tokens = _exchange
        result = await sso_service.handle_oauth_callback("github", "code", "test-state")
        assert result is None
        # Auth session should be cleaned up
        mock_db.delete.assert_called()


# ---------------------------------------------------------------------------
# Token exchange tests
# ---------------------------------------------------------------------------


class TestTokenExchange:
    @pytest.mark.asyncio
    async def test_exchange_code_for_tokens_success(self, sso_service):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"access_token": "tok", "token_type": "bearer"}

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        provider = _make_provider()
        auth_session = _make_auth_session()

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock) as mock_get_client:
            mock_get_client.return_value = mock_client
            result = await sso_service._exchange_code_for_tokens(provider, auth_session, "code123")

        assert result == {"access_token": "tok", "token_type": "bearer"}

    @pytest.mark.asyncio
    async def test_exchange_code_for_tokens_failure(self, sso_service):
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Bad request"

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        provider = _make_provider()
        auth_session = _make_auth_session()

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock) as mock_get_client:
            mock_get_client.return_value = mock_client


# ---------------------------------------------------------------------------
# User info extraction tests
# ---------------------------------------------------------------------------


class TestUserInfoExtraction:
    @pytest.mark.asyncio
    async def test_get_user_info_adfs_extracts_username_from_email_with_at(self, sso_service):
        """Test ADFS user info extraction when raw email contains @ but no preferred_username."""
        # Standard Library
        import base64
        import json
        import time

        provider = _make_provider(id="adfs", provider_type="oidc", provider_metadata={"provider_id": "adfs"})

        # Create a fake ID token with ADFS claims (including aud/exp for validation)
        claims = {"upn": "user@example.com", "name": "Test User", "sub": "user-id", "aud": "cid", "exp": int(time.time()) + 3600}
        payload = json.dumps(claims).encode()
        payload_b64 = base64.urlsafe_b64encode(payload).decode().rstrip("=")
        fake_id_token = f"header.{payload_b64}.signature"

        token_data = {"access_token": "at", "id_token": fake_id_token}

        # Mock HTTP client
        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock):
            user_info = await sso_service._get_user_info(provider, "at", token_data)
            assert user_info is not None
            assert user_info["username"] == "user"
            assert user_info["email"] == "user@example.com"


# ---------------------------------------------------------------------------
# User info tests
# ---------------------------------------------------------------------------


class TestGetUserInfo:
    @pytest.mark.asyncio
    async def test_get_user_info_github_with_orgs(self, sso_service):
        user_response = MagicMock()
        user_response.status_code = 200
        user_response.json.return_value = {"login": "testuser", "email": "test@github.com", "name": "Test"}

        orgs_response = MagicMock()
        orgs_response.status_code = 200
        orgs_response.json.return_value = [{"login": "my-org"}, {"login": "other-org"}]

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[user_response, orgs_response])

        provider = _make_provider()

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock) as mock_get_client, patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_get_client.return_value = mock_client
            mock_settings.sso_github_admin_orgs = ["my-org"]
            result = await sso_service._get_user_info(provider, "access_token")

        assert result is not None
        assert result["provider"] == "github"
        assert result["username"] == "testuser"

    @pytest.mark.asyncio
    async def test_get_user_info_github_orgs_failure(self, sso_service):
        user_response = MagicMock()
        user_response.status_code = 200
        user_response.json.return_value = {"login": "testuser", "email": "test@github.com"}

        orgs_response = MagicMock()
        orgs_response.status_code = 403

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[user_response, orgs_response])

        provider = _make_provider()

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock) as mock_get_client, patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_get_client.return_value = mock_client
            mock_settings.sso_github_admin_orgs = ["my-org"]
            result = await sso_service._get_user_info(provider, "access_token")

        assert result is not None
        # organizations should be empty list on failure
        assert "organizations" in result

    @pytest.mark.asyncio
    async def test_get_user_info_entra_with_id_token(self, sso_service):
        """Entra ID provider extracts groups/roles from id_token."""
        # Standard
        import base64

        # Third-Party
        import orjson

        user_response = MagicMock()
        user_response.status_code = 200
        user_response.json.return_value = {"email": "user@contoso.com", "name": "Test User"}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=user_response)

        provider = _make_provider(id="entra", name="entra", provider_type="oidc", provider_metadata={})

        # Build a fake id_token with groups
        payload = orjson.dumps({"sub": "user-oid", "groups": ["group-id-1", "group-id-2"], "roles": ["App.Admin"]})
        payload_b64 = base64.urlsafe_b64encode(payload).decode().rstrip("=")
        fake_id_token = f"eyJhbGciOiJSUzI1NiJ9.{payload_b64}.sig"

        token_data = {"access_token": "at", "id_token": fake_id_token, "_verified_id_token_claims": orjson.loads(payload)}

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock) as mock_get_client, patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_get_client.return_value = mock_client
            mock_settings.sso_github_admin_orgs = []
            result = await sso_service._get_user_info(provider, "at", token_data)

        assert result is not None
        assert result["provider"] == "entra"
        assert "group-id-1" in result["groups"]
        assert "App.Admin" in result["groups"]

    @pytest.mark.asyncio
    async def test_get_user_info_oidc_fallback_verification_uses_expected_nonce(self, sso_service):
        """OIDC fallback id_token verification should enforce the callback nonce when provided."""
        user_response = MagicMock()
        user_response.status_code = 200
        user_response.json.return_value = {"email": "user@example.com", "name": "Test User"}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=user_response)

        provider = _make_provider(id="oidc-test", provider_type="oidc", issuer="https://issuer.example.com", jwks_uri="https://issuer.example.com/jwks")
        token_data = {"access_token": "at", "id_token": "id-token-without-cached-claims"}

        sso_service._verify_oidc_id_token = AsyncMock(return_value={"sub": "user-1", "nonce": "nonce-1"})

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock) as mock_get_client:
            mock_get_client.return_value = mock_client
            result = await sso_service._get_user_info(provider, "at", token_data, expected_nonce="nonce-1")

        assert result is not None
        sso_service._verify_oidc_id_token.assert_awaited_once_with(provider, "id-token-without-cached-claims", expected_nonce="nonce-1")

    @pytest.mark.asyncio
    async def test_get_user_info_oidc_fallback_skips_verification_without_nonce(self, sso_service):
        """OIDC fallback id_token verification should be skipped when nonce context is unavailable."""
        user_response = MagicMock()
        user_response.status_code = 200
        user_response.json.return_value = {"email": "user@example.com", "name": "Test User"}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=user_response)

        provider = _make_provider(id="oidc-test", provider_type="oidc", issuer="https://issuer.example.com", jwks_uri="https://issuer.example.com/jwks")
        token_data = {"access_token": "at", "id_token": "id-token-without-cached-claims"}

        sso_service._verify_oidc_id_token = AsyncMock(return_value={"sub": "user-1", "nonce": "nonce-1"})

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock) as mock_get_client:
            mock_get_client.return_value = mock_client
            result = await sso_service._get_user_info(provider, "at", token_data, expected_nonce=None)

        assert result is not None
        sso_service._verify_oidc_id_token.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_user_info_failure(self, sso_service):
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        provider = _make_provider()

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock) as mock_get_client:
            mock_get_client.return_value = mock_client
            result = await sso_service._get_user_info(provider, "bad-token")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_user_info_github_orgs_exception(self, sso_service):
        """GitHub orgs fetch raises exception -> orgs set to empty list."""
        user_response = MagicMock()
        user_response.status_code = 200
        user_response.json.return_value = {"login": "testuser", "email": "test@github.com"}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[user_response, RuntimeError("network")])

        provider = _make_provider()

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock) as mock_get_client, patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_get_client.return_value = mock_client
            mock_settings.sso_github_admin_orgs = ["my-org"]
            result = await sso_service._get_user_info(provider, "access_token")

        assert result is not None
        assert result.get("organizations", []) == []

    @pytest.mark.asyncio
    async def test_get_user_info_entra_group_overage(self, sso_service):
        """Entra ID group overage detection (>200 groups)."""
        # Standard
        import base64

        # Third-Party
        import orjson

        user_response = MagicMock()
        user_response.status_code = 200
        user_response.json.return_value = {"email": "user@contoso.com", "name": "User"}

        graph_response = MagicMock()
        graph_response.status_code = 200
        graph_response.json.return_value = {"value": ["group-id-1", "group-id-2", "group-id-2"]}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=user_response)
        mock_client.post = AsyncMock(return_value=graph_response)

        provider = _make_provider(id="entra", name="entra", provider_type="oidc", provider_metadata={})

        # Build id_token with group overage indicator
        payload = orjson.dumps({"sub": "oid", "_claim_names": {"groups": "src1"}, "_claim_sources": {"src1": {"endpoint": "https://graph"}}})
        payload_b64 = base64.urlsafe_b64encode(payload).decode().rstrip("=")
        fake_id_token = f"eyJhbGciOiJSUzI1NiJ9.{payload_b64}.sig"
        token_data = {"access_token": "at", "id_token": fake_id_token, "_verified_id_token_claims": orjson.loads(payload)}

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock) as mock_get_client, patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_get_client.return_value = mock_client
            mock_settings.sso_github_admin_orgs = []
            mock_settings.sso_entra_graph_api_enabled = True
            mock_settings.sso_entra_graph_api_timeout = 10
            mock_settings.sso_entra_graph_api_max_groups = 0
            result = await sso_service._get_user_info(provider, "at", token_data)

        assert result is not None
        assert result["provider"] == "entra"
        assert "group-id-1" in result["groups"]
        assert "group-id-2" in result["groups"]
        mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_user_info_entra_group_overage_hasgroups_marker(self, sso_service):
        """Entra overage fallback should trigger for hasgroups marker."""
        # Standard
        import base64

        # Third-Party
        import orjson

        user_response = MagicMock()
        user_response.status_code = 200
        user_response.json.return_value = {"email": "user@contoso.com", "name": "User"}

        graph_response = MagicMock()
        graph_response.status_code = 200
        graph_response.json.return_value = {"value": ["group-id-1"]}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=user_response)
        mock_client.post = AsyncMock(return_value=graph_response)

        provider = _make_provider(id="entra", name="entra", provider_type="oidc", provider_metadata={})

        payload = orjson.dumps({"sub": "oid", "hasgroups": True})
        payload_b64 = base64.urlsafe_b64encode(payload).decode().rstrip("=")
        fake_id_token = f"eyJhbGciOiJSUzI1NiJ9.{payload_b64}.sig"
        token_data = {"access_token": "at", "id_token": fake_id_token, "_verified_id_token_claims": orjson.loads(payload)}

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock) as mock_get_client, patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_get_client.return_value = mock_client
            mock_settings.sso_github_admin_orgs = []
            mock_settings.sso_entra_graph_api_enabled = True
            mock_settings.sso_entra_graph_api_timeout = 10
            mock_settings.sso_entra_graph_api_max_groups = 0
            result = await sso_service._get_user_info(provider, "at", token_data)

        assert result is not None
        assert result["provider"] == "entra"
        assert "group-id-1" in result["groups"]
        mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_user_info_entra_group_overage_groups_src_marker(self, sso_service):
        """Entra overage fallback should trigger for groups:srcN marker."""
        # Standard
        import base64

        # Third-Party
        import orjson

        user_response = MagicMock()
        user_response.status_code = 200
        user_response.json.return_value = {"email": "user@contoso.com", "name": "User"}

        graph_response = MagicMock()
        graph_response.status_code = 200
        graph_response.json.return_value = {"value": ["group-id-2"]}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=user_response)
        mock_client.post = AsyncMock(return_value=graph_response)

        provider = _make_provider(id="entra", name="entra", provider_type="oidc", provider_metadata={})

        payload = orjson.dumps({"sub": "oid", "groups:src1": {"@odata.type": "x"}})
        payload_b64 = base64.urlsafe_b64encode(payload).decode().rstrip("=")
        fake_id_token = f"eyJhbGciOiJSUzI1NiJ9.{payload_b64}.sig"
        token_data = {"access_token": "at", "id_token": fake_id_token, "_verified_id_token_claims": orjson.loads(payload)}

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock) as mock_get_client, patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_get_client.return_value = mock_client
            mock_settings.sso_github_admin_orgs = []
            mock_settings.sso_entra_graph_api_enabled = True
            mock_settings.sso_entra_graph_api_timeout = 10
            mock_settings.sso_entra_graph_api_max_groups = 0
            result = await sso_service._get_user_info(provider, "at", token_data)

        assert result is not None
        assert result["provider"] == "entra"
        assert "group-id-2" in result["groups"]
        mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_user_info_entra_group_overage_graph_fallback_failure(self, sso_service):
        """Overage with failed Graph fallback should continue with safe defaults."""
        # Standard
        import base64

        # Third-Party
        import orjson

        user_response = MagicMock()
        user_response.status_code = 200
        user_response.json.return_value = {"email": "user@contoso.com", "name": "User"}

        graph_response = MagicMock()
        graph_response.status_code = 401

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=user_response)
        mock_client.post = AsyncMock(return_value=graph_response)

        provider = _make_provider(id="entra", name="entra", provider_type="oidc", provider_metadata={})

        payload = orjson.dumps({"sub": "oid", "_claim_names": {"groups": "src1"}})
        payload_b64 = base64.urlsafe_b64encode(payload).decode().rstrip("=")
        fake_id_token = f"eyJhbGciOiJSUzI1NiJ9.{payload_b64}.sig"
        token_data = {"access_token": "at", "id_token": fake_id_token, "_verified_id_token_claims": orjson.loads(payload)}

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock) as mock_get_client, patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_get_client.return_value = mock_client
            mock_settings.sso_github_admin_orgs = []
            mock_settings.sso_entra_graph_api_enabled = True
            mock_settings.sso_entra_graph_api_timeout = 10
            mock_settings.sso_entra_graph_api_max_groups = 0
            result = await sso_service._get_user_info(provider, "at", token_data)

        assert result is not None
        assert result["provider"] == "entra"
        assert result["groups"] == []

    @pytest.mark.asyncio
    async def test_get_user_info_keycloak_with_id_token(self, sso_service):
        """Keycloak extracts realm_access, resource_access, groups from id_token."""
        # Standard
        import base64

        # Third-Party
        import orjson

        user_response = MagicMock()
        user_response.status_code = 200
        user_response.json.return_value = {"email": "user@kc.com", "name": "KC User", "preferred_username": "kcuser", "sub": "kc-123"}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=user_response)

        provider = _make_provider(
            id="keycloak",
            name="keycloak",
            provider_type="oidc",
            provider_metadata={"map_realm_roles": True, "map_client_roles": True},
        )

        payload = orjson.dumps({"realm_access": {"roles": ["admin"]}, "resource_access": {"app": {"roles": ["edit"]}}, "groups": ["/team"]})
        payload_b64 = base64.urlsafe_b64encode(payload).decode().rstrip("=")
        fake_id_token = f"eyJhbGciOiJSUzI1NiJ9.{payload_b64}.sig"
        token_data = {"access_token": "at", "id_token": fake_id_token, "_verified_id_token_claims": orjson.loads(payload)}

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock) as mock_get_client, patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_get_client.return_value = mock_client
            mock_settings.sso_github_admin_orgs = []
            result = await sso_service._get_user_info(provider, "at", token_data)

        assert result is not None
        assert result["provider"] == "keycloak"
        assert "admin" in result["groups"]
        assert "app:edit" in result["groups"]

    @pytest.mark.asyncio
    async def test_get_user_info_keycloak_falls_back_to_id_token_when_userinfo_fails(self, sso_service):
        """Keycloak should use id_token claims when userinfo endpoint returns 401."""
        # Standard
        import base64

        # Third-Party
        import orjson

        fail_response = MagicMock()
        fail_response.status_code = 401
        fail_response.text = ""

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=fail_response)

        provider = _make_provider(
            id="keycloak",
            name="keycloak",
            provider_type="oidc",
            provider_metadata={"map_realm_roles": True, "map_client_roles": False, "base_url": "http://keycloak:8080", "public_base_url": "http://localhost:8180"},
        )

        payload = orjson.dumps(
            {
                "sub": "kc-123",
                "email": "user@kc.com",
                "name": "KC User",
                "preferred_username": "kcuser",
                "realm_access": {"roles": ["admin"]},
                "groups": ["/team"],
            }
        )
        payload_b64 = base64.urlsafe_b64encode(payload).decode().rstrip("=")
        fake_id_token = f"eyJhbGciOiJSUzI1NiJ9.{payload_b64}.sig"
        token_data = {"access_token": "at", "id_token": fake_id_token, "_verified_id_token_claims": orjson.loads(payload)}

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock) as mock_get_client, patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_get_client.return_value = mock_client
            mock_settings.sso_github_admin_orgs = []
            result = await sso_service._get_user_info(provider, "at", token_data)

        assert result is not None
        assert result["provider"] == "keycloak"
        assert result["email"] == "user@kc.com"
        assert "admin" in result["groups"]
        assert "/team" in result["groups"]

    @pytest.mark.asyncio
    async def test_get_user_info_generic_oidc_merges_groups_from_id_token(self, sso_service):
        """Generic OIDC provider merges configured groups claim from id_token when userinfo omits it."""
        user_response = MagicMock()
        user_response.status_code = 200
        user_response.json.return_value = {"email": "user@jumpcloud.com", "name": "JC User", "sub": "jc-123"}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=user_response)

        provider = _make_provider(id="jumpcloud", name="jumpcloud", provider_type="oidc", provider_metadata={"groups_claim": "groups"})

        id_token_claims = {"sub": "jc-123", "groups": ["Engineering", "Platform"]}
        token_data = {"access_token": "at", "_verified_id_token_claims": id_token_claims}

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock) as mock_get_client, patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_get_client.return_value = mock_client
            mock_settings.sso_github_admin_orgs = []
            result = await sso_service._get_user_info(provider, "at", token_data)

        assert result is not None
        assert sorted(result["groups"]) == ["Engineering", "Platform"]

    @pytest.mark.asyncio
    async def test_get_user_info_generic_oidc_prefers_userinfo_groups_over_id_token(self, sso_service):
        """When userinfo already contains the groups claim, id_token groups are not merged."""
        user_response = MagicMock()
        user_response.status_code = 200
        user_response.json.return_value = {"email": "user@provider.com", "name": "Test", "sub": "u-1", "groups": ["FromUserinfo"]}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=user_response)

        provider = _make_provider(id="custom_oidc", name="custom_oidc", provider_type="oidc", provider_metadata={})

        id_token_claims = {"sub": "u-1", "groups": ["FromIdToken"]}
        token_data = {"access_token": "at", "_verified_id_token_claims": id_token_claims}

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock) as mock_get_client, patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_get_client.return_value = mock_client
            mock_settings.sso_github_admin_orgs = []
            result = await sso_service._get_user_info(provider, "at", token_data)

        assert result is not None
        assert result["groups"] == ["FromUserinfo"]

    @pytest.mark.asyncio
    async def test_get_user_info_generic_oidc_custom_groups_claim_from_id_token(self, sso_service):
        """Generic OIDC provider merges custom-named groups claim from id_token."""
        user_response = MagicMock()
        user_response.status_code = 200
        user_response.json.return_value = {"email": "user@auth0.com", "name": "A0 User", "sub": "a0-1"}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=user_response)

        provider = _make_provider(id="auth0", name="auth0", provider_type="oidc", provider_metadata={"groups_claim": "https://myapp/roles"})

        id_token_claims = {"sub": "a0-1", "https://myapp/roles": ["admin", "editor"]}
        token_data = {"access_token": "at", "_verified_id_token_claims": id_token_claims}

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock) as mock_get_client, patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_get_client.return_value = mock_client
            mock_settings.sso_github_admin_orgs = []
            result = await sso_service._get_user_info(provider, "at", token_data)

        assert result is not None
        assert sorted(result["groups"]) == ["admin", "editor"]

    @pytest.mark.asyncio
    async def test_get_user_info_okta_merges_groups_from_id_token(self, sso_service):
        """Okta provider merges groups claim from id_token when userinfo omits it."""
        user_response = MagicMock()
        user_response.status_code = 200
        user_response.json.return_value = {"email": "user@okta.com", "name": "Okta User", "sub": "okta-123"}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=user_response)

        provider = _make_provider(id="okta", name="okta", provider_type="oidc", provider_metadata={})

        id_token_claims = {"sub": "okta-123", "groups": ["Engineering", "Platform"]}
        token_data = {"access_token": "at", "_verified_id_token_claims": id_token_claims}

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock) as mock_get_client, patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_get_client.return_value = mock_client
            mock_settings.sso_github_admin_orgs = []
            result = await sso_service._get_user_info(provider, "at", token_data)

        assert result is not None
        assert sorted(result["groups"]) == ["Engineering", "Platform"]

    @pytest.mark.asyncio
    async def test_get_user_info_okta_merges_roles_from_id_token(self, sso_service):
        """Okta provider merges roles claim from id_token when userinfo omits it."""
        user_response = MagicMock()
        user_response.status_code = 200
        user_response.json.return_value = {"email": "user@okta.com", "name": "Okta User", "sub": "okta-123"}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=user_response)

        provider = _make_provider(id="okta", name="okta", provider_type="oidc", provider_metadata={})

        id_token_claims = {"sub": "okta-123", "roles": ["admin", "editor"]}
        token_data = {"access_token": "at", "_verified_id_token_claims": id_token_claims}

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock) as mock_get_client, patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_get_client.return_value = mock_client
            mock_settings.sso_github_admin_orgs = []
            result = await sso_service._get_user_info(provider, "at", token_data)

        assert result is not None
        assert sorted(result["groups"]) == ["admin", "editor"]

    @pytest.mark.asyncio
    async def test_get_user_info_okta_prefers_userinfo_groups(self, sso_service):
        """When userinfo already contains groups, Okta id_token groups are not merged."""
        user_response = MagicMock()
        user_response.status_code = 200
        user_response.json.return_value = {"email": "user@okta.com", "name": "Okta User", "sub": "okta-123", "groups": ["FromUserinfo"]}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=user_response)

        provider = _make_provider(id="okta", name="okta", provider_type="oidc", provider_metadata={})

        id_token_claims = {"sub": "okta-123", "groups": ["FromIdToken"]}
        token_data = {"access_token": "at", "_verified_id_token_claims": id_token_claims}

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock) as mock_get_client, patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_get_client.return_value = mock_client
            mock_settings.sso_github_admin_orgs = []
            result = await sso_service._get_user_info(provider, "at", token_data)

        assert result is not None
        assert result["groups"] == ["FromUserinfo"]

    @pytest.mark.asyncio
    async def test_get_user_info_ibm_verify_merges_groups_from_id_token(self, sso_service):
        """IBM Verify provider merges groups claim from id_token when userinfo omits it."""
        user_response = MagicMock()
        user_response.status_code = 200
        user_response.json.return_value = {"email": "user@ibm.com", "name": "IBM User", "sub": "ibm-123"}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=user_response)

        provider = _make_provider(id="ibm_verify", name="ibm_verify", provider_type="oidc", provider_metadata={})

        id_token_claims = {"sub": "ibm-123", "groups": ["CloudOps", "Security"]}
        token_data = {"access_token": "at", "_verified_id_token_claims": id_token_claims}

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock) as mock_get_client, patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_get_client.return_value = mock_client
            mock_settings.sso_github_admin_orgs = []
            result = await sso_service._get_user_info(provider, "at", token_data)

        assert result is not None
        assert sorted(result["groups"]) == ["CloudOps", "Security"]


# ---------------------------------------------------------------------------
# _enrich_user_data_from_claims tests
# ---------------------------------------------------------------------------


class TestEnrichUserDataFromClaims:
    """Tests for _enrich_user_data_from_claims extracted from _get_user_info."""

    @pytest.mark.asyncio
    async def test_github_orgs_fetched_when_configured(self, sso_service):
        """GitHub orgs are fetched and added to user_data when sso_github_admin_orgs is set."""
        provider = _make_provider(id="github")
        user_data = {"email": "user@github.com"}

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [{"login": "org1"}, {"login": "org2"}]

        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_github_admin_orgs = ["org1"]
            with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock) as mock_get_client:
                mock_client = AsyncMock()
                mock_client.get.return_value = mock_response
                mock_get_client.return_value = mock_client

                await sso_service._enrich_user_data_from_claims(provider, user_data, "access-token", None)

        assert user_data["organizations"] == ["org1", "org2"]

    @pytest.mark.asyncio
    async def test_github_orgs_empty_when_fetch_fails(self, sso_service):
        """GitHub orgs default to empty list when API call fails."""
        provider = _make_provider(id="github")
        user_data = {"email": "user@github.com"}

        mock_response = MagicMock()
        mock_response.status_code = 403

        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_github_admin_orgs = ["org1"]
            with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock) as mock_get_client:
                mock_client = AsyncMock()
                mock_client.get.return_value = mock_response
                mock_get_client.return_value = mock_client

                await sso_service._enrich_user_data_from_claims(provider, user_data, "access-token", None)

        assert user_data["organizations"] == []

    @pytest.mark.asyncio
    async def test_github_skipped_when_no_admin_orgs_configured(self, sso_service):
        """No orgs fetch when sso_github_admin_orgs is empty."""
        provider = _make_provider(id="github")
        user_data = {"email": "user@github.com"}

        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_github_admin_orgs = []
            await sso_service._enrich_user_data_from_claims(provider, user_data, "access-token", None)

        assert "organizations" not in user_data

    @pytest.mark.asyncio
    async def test_entra_extracts_groups_and_roles_from_id_token(self, sso_service):
        """Entra enrichment merges groups and roles from verified id_token claims."""
        provider = _make_provider(id="entra", provider_metadata={})
        user_data = {"email": "user@entra.com"}
        verified_claims = {
            "groups": ["grp-id-1", "grp-id-2"],
            "roles": ["role-a"],
            "oid": "oid-123",
        }

        await sso_service._enrich_user_data_from_claims(provider, user_data, "token", verified_claims)

        assert user_data["groups"] == ["grp-id-1", "grp-id-2"]
        assert user_data["roles"] == ["role-a"]
        assert user_data["oid"] == "oid-123"

    @pytest.mark.asyncio
    async def test_entra_no_op_without_verified_claims(self, sso_service):
        """Entra enrichment is a no-op when verified_id_token_claims is None."""
        provider = _make_provider(id="entra", provider_metadata={})
        user_data = {"email": "user@entra.com"}

        await sso_service._enrich_user_data_from_claims(provider, user_data, "token", None)

        assert "groups" not in user_data
        assert "roles" not in user_data

    @pytest.mark.asyncio
    async def test_entra_backfills_missing_basic_claims(self, sso_service):
        """Entra enrichment fills missing basic claims from id_token."""
        provider = _make_provider(id="entra", provider_metadata={})
        user_data = {}
        verified_claims = {"email": "from-token@e.com", "name": "Token Name", "sub": "sub-1"}

        await sso_service._enrich_user_data_from_claims(provider, user_data, "token", verified_claims)

        assert user_data["email"] == "from-token@e.com"
        assert user_data["name"] == "Token Name"

    @pytest.mark.asyncio
    async def test_entra_does_not_overwrite_existing_claims(self, sso_service):
        """Entra enrichment does not overwrite claims already in user_data."""
        provider = _make_provider(id="entra", provider_metadata={})
        user_data = {"email": "from-userinfo@e.com"}
        verified_claims = {"email": "from-token@e.com", "sub": "sub-1"}

        await sso_service._enrich_user_data_from_claims(provider, user_data, "token", verified_claims)

        assert user_data["email"] == "from-userinfo@e.com"

    @pytest.mark.asyncio
    async def test_keycloak_merges_realm_access_from_id_token(self, sso_service):
        """Keycloak enrichment merges realm_access, resource_access, groups from id_token."""
        provider = _make_provider(id="keycloak")
        user_data = {"email": "user@kc.com"}
        verified_claims = {
            "realm_access": {"roles": ["admin"]},
            "resource_access": {"client1": {"roles": ["editor"]}},
            "groups": ["/team-a"],
        }

        await sso_service._enrich_user_data_from_claims(provider, user_data, "token", verified_claims)

        assert user_data["realm_access"] == {"roles": ["admin"]}
        assert user_data["resource_access"] == {"client1": {"roles": ["editor"]}}
        assert user_data["groups"] == ["/team-a"]

    @pytest.mark.asyncio
    async def test_keycloak_does_not_overwrite_existing_claims(self, sso_service):
        """Keycloak enrichment skips claims already present in user_data."""
        provider = _make_provider(id="keycloak")
        user_data = {"email": "user@kc.com", "groups": ["existing-group"]}
        verified_claims = {"groups": ["/from-token"]}

        await sso_service._enrich_user_data_from_claims(provider, user_data, "token", verified_claims)

        assert user_data["groups"] == ["existing-group"]

    @pytest.mark.asyncio
    async def test_generic_oidc_merges_groups_from_id_token(self, sso_service):
        """Generic OIDC enrichment merges groups claim from id_token when not in userinfo."""
        provider = _make_provider(id="okta", provider_metadata={})
        user_data = {"email": "user@okta.com"}
        verified_claims = {"groups": ["okta-grp1"], "roles": ["okta-role1"]}

        await sso_service._enrich_user_data_from_claims(provider, user_data, "token", verified_claims)

        assert user_data["groups"] == ["okta-grp1"]
        assert user_data["roles"] == ["okta-role1"]

    @pytest.mark.asyncio
    async def test_generic_oidc_prefers_userinfo_over_id_token(self, sso_service):
        """Generic OIDC enrichment does not overwrite groups already from userinfo."""
        provider = _make_provider(id="okta", provider_metadata={})
        user_data = {"email": "user@okta.com", "groups": ["from-userinfo"]}
        verified_claims = {"groups": ["from-token"]}

        await sso_service._enrich_user_data_from_claims(provider, user_data, "token", verified_claims)

        assert user_data["groups"] == ["from-userinfo"]

    @pytest.mark.asyncio
    async def test_generic_oidc_custom_groups_claim(self, sso_service):
        """Generic OIDC enrichment respects custom groups_claim from provider_metadata."""
        provider = _make_provider(id="custom_oidc", provider_metadata={"groups_claim": "team_groups"})
        user_data = {"email": "user@custom.com"}
        verified_claims = {"team_groups": ["custom-grp"]}

        await sso_service._enrich_user_data_from_claims(provider, user_data, "token", verified_claims)

        assert user_data["team_groups"] == ["custom-grp"]

    @pytest.mark.asyncio
    async def test_google_is_not_enriched(self, sso_service):
        """Google provider does not get generic OIDC enrichment."""
        provider = _make_provider(id="google")
        user_data = {"email": "user@google.com"}
        verified_claims = {"groups": ["should-not-appear"]}

        await sso_service._enrich_user_data_from_claims(provider, user_data, "token", verified_claims)

        assert "groups" not in user_data

    @pytest.mark.asyncio
    async def test_no_enrichment_without_verified_claims(self, sso_service):
        """Generic OIDC enrichment is a no-op when verified claims are None."""
        provider = _make_provider(id="custom_oidc", provider_metadata={})
        user_data = {"email": "user@custom.com"}

        await sso_service._enrich_user_data_from_claims(provider, user_data, "token", None)

        assert "groups" not in user_data


# ---------------------------------------------------------------------------
# Entra Graph API fallback tests
# ---------------------------------------------------------------------------


class TestEntraGraphFallback:
    """Tests for _resolve_entra_graph_fallback_settings and _fetch_entra_groups_from_graph_api."""

    def test_resolve_entra_graph_fallback_settings_valid_overrides(self, sso_service):
        """Provider metadata should parse valid string overrides."""
        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_entra_graph_api_enabled = False
            mock_settings.sso_entra_graph_api_timeout = 10
            mock_settings.sso_entra_graph_api_max_groups = 0

            enabled, timeout, max_groups = sso_service._resolve_entra_graph_fallback_settings(
                {
                    "graph_api_enabled": "true",
                    "graph_api_timeout": "15",
                    "graph_api_max_groups": "4",
                }
            )

        assert enabled is True
        assert timeout == 15
        assert max_groups == 4

    def test_resolve_entra_graph_fallback_settings_invalid_string_enabled(self, sso_service):
        """Invalid string values should keep defaults for graph_api_enabled."""
        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_entra_graph_api_enabled = True
            mock_settings.sso_entra_graph_api_timeout = 10
            mock_settings.sso_entra_graph_api_max_groups = 9

            enabled, timeout, max_groups = sso_service._resolve_entra_graph_fallback_settings({"graph_api_enabled": "maybe"})

        assert enabled is True
        assert timeout == 10
        assert max_groups == 9

    def test_resolve_entra_graph_fallback_settings_non_string_enabled(self, sso_service):
        """Non-string metadata values should be coerced to bool for graph_api_enabled."""
        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_entra_graph_api_enabled = True
            mock_settings.sso_entra_graph_api_timeout = 10
            mock_settings.sso_entra_graph_api_max_groups = 9

            enabled, timeout, max_groups = sso_service._resolve_entra_graph_fallback_settings({"graph_api_enabled": 0})

        assert enabled is False
        assert timeout == 10
        assert max_groups == 9

    def test_resolve_entra_graph_fallback_settings_invalid_timeout_and_max_groups(self, sso_service):
        """Invalid timeout/max values should keep defaults."""
        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_entra_graph_api_enabled = True
            mock_settings.sso_entra_graph_api_timeout = 10
            mock_settings.sso_entra_graph_api_max_groups = 9

            enabled, timeout, max_groups = sso_service._resolve_entra_graph_fallback_settings({"graph_api_timeout": "0", "graph_api_max_groups": "-1"})

        assert enabled is True
        assert timeout == 10
        assert max_groups == 9

    def test_resolve_entra_graph_fallback_settings_unparseable_timeout_and_max_groups(self, sso_service):
        """Unparseable timeout/max values should keep defaults."""
        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_entra_graph_api_enabled = True
            mock_settings.sso_entra_graph_api_timeout = 10
            mock_settings.sso_entra_graph_api_max_groups = 9

            enabled, timeout, max_groups = sso_service._resolve_entra_graph_fallback_settings({"graph_api_timeout": "abc", "graph_api_max_groups": "xyz"})

        assert enabled is True
        assert timeout == 10
        assert max_groups == 9

    @pytest.mark.asyncio
    async def test_fetch_entra_groups_from_graph_api_handles_401(self, sso_service):
        """Graph API failures should degrade safely and return None."""
        graph_response = MagicMock()
        graph_response.status_code = 401

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=graph_response)

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock) as mock_get_client, patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_get_client.return_value = mock_client
            mock_settings.sso_entra_graph_api_enabled = True
            mock_settings.sso_entra_graph_api_timeout = 10
            mock_settings.sso_entra_graph_api_max_groups = 0
            groups = await sso_service._fetch_entra_groups_from_graph_api("at", "user@contoso.com")

        assert groups is None

    @pytest.mark.asyncio
    async def test_fetch_entra_groups_from_graph_api_handles_403(self, sso_service):
        """Graph API forbidden responses should degrade safely and return None."""
        graph_response = MagicMock()
        graph_response.status_code = 403

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=graph_response)

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock) as mock_get_client, patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_get_client.return_value = mock_client
            mock_settings.sso_entra_graph_api_enabled = True
            mock_settings.sso_entra_graph_api_timeout = 10
            mock_settings.sso_entra_graph_api_max_groups = 0
            groups = await sso_service._fetch_entra_groups_from_graph_api("at", "user@contoso.com")

        assert groups is None

    @pytest.mark.asyncio
    async def test_fetch_entra_groups_from_graph_api_handles_500(self, sso_service):
        """Non-auth Graph API failures should degrade safely and return None."""
        graph_response = MagicMock()
        graph_response.status_code = 500

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=graph_response)

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock) as mock_get_client, patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_get_client.return_value = mock_client
            mock_settings.sso_entra_graph_api_enabled = True
            mock_settings.sso_entra_graph_api_timeout = 10
            mock_settings.sso_entra_graph_api_max_groups = 0
            groups = await sso_service._fetch_entra_groups_from_graph_api("at", "user@contoso.com")

        assert groups is None

    @pytest.mark.asyncio
    async def test_fetch_entra_groups_from_graph_api_invalid_json_response(self, sso_service):
        """Invalid Graph JSON payload should degrade safely and return None."""
        graph_response = MagicMock()
        graph_response.status_code = 200
        graph_response.json.side_effect = ValueError("invalid json")

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=graph_response)

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock) as mock_get_client, patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_get_client.return_value = mock_client
            mock_settings.sso_entra_graph_api_enabled = True
            mock_settings.sso_entra_graph_api_timeout = 10
            mock_settings.sso_entra_graph_api_max_groups = 0
            groups = await sso_service._fetch_entra_groups_from_graph_api("at", "user@contoso.com")

        assert groups is None

    @pytest.mark.asyncio
    async def test_fetch_entra_groups_from_graph_api_non_list_value(self, sso_service):
        """Graph response with non-list value should return empty list."""
        graph_response = MagicMock()
        graph_response.status_code = 200
        graph_response.json.return_value = {"value": "not-a-list"}

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=graph_response)

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock) as mock_get_client, patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_get_client.return_value = mock_client
            mock_settings.sso_entra_graph_api_enabled = True
            mock_settings.sso_entra_graph_api_timeout = 10
            mock_settings.sso_entra_graph_api_max_groups = 0
            groups = await sso_service._fetch_entra_groups_from_graph_api("at", "user@contoso.com")

        assert groups == []

    @pytest.mark.asyncio
    async def test_fetch_entra_groups_from_graph_api_skips_non_string_ids(self, sso_service):
        """Graph response should ignore non-string group IDs."""
        graph_response = MagicMock()
        graph_response.status_code = 200
        graph_response.json.return_value = {"value": [123, "group-1", None, "group-2"]}

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=graph_response)

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock) as mock_get_client, patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_get_client.return_value = mock_client
            mock_settings.sso_entra_graph_api_enabled = True
            mock_settings.sso_entra_graph_api_timeout = 10
            mock_settings.sso_entra_graph_api_max_groups = 0
            groups = await sso_service._fetch_entra_groups_from_graph_api("at", "user@contoso.com")

        assert groups == ["group-1", "group-2"]

    @pytest.mark.asyncio
    async def test_fetch_entra_groups_from_graph_api_applies_max_group_cap(self, sso_service):
        """Configured Graph max_groups should truncate the returned list."""
        graph_response = MagicMock()
        graph_response.status_code = 200
        graph_response.json.return_value = {"value": ["g1", "g2", "g3"]}

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=graph_response)

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock) as mock_get_client, patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_get_client.return_value = mock_client
            mock_settings.sso_entra_graph_api_enabled = True
            mock_settings.sso_entra_graph_api_timeout = 10
            mock_settings.sso_entra_graph_api_max_groups = 2
            groups = await sso_service._fetch_entra_groups_from_graph_api("at", "user@contoso.com")

        assert groups == ["g1", "g2"]

    @pytest.mark.asyncio
    async def test_fetch_entra_groups_from_graph_api_disabled(self, sso_service):
        """Disabled Graph fallback should skip network calls."""
        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock) as mock_get_client, patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_entra_graph_api_enabled = False
            mock_settings.sso_entra_graph_api_timeout = 10
            mock_settings.sso_entra_graph_api_max_groups = 0
            groups = await sso_service._fetch_entra_groups_from_graph_api("at", "user@contoso.com")

        assert groups is None
        mock_get_client.assert_not_called()

    @pytest.mark.asyncio
    async def test_fetch_entra_groups_from_graph_api_timeout(self, sso_service):
        """Timeouts or transport errors should not break login flow."""
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=TimeoutError("request timed out"))

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock) as mock_get_client, patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_get_client.return_value = mock_client
            mock_settings.sso_entra_graph_api_enabled = True
            mock_settings.sso_entra_graph_api_timeout = 1
            mock_settings.sso_entra_graph_api_max_groups = 0
            groups = await sso_service._fetch_entra_groups_from_graph_api("at", "user@contoso.com")

        assert groups is None

    @pytest.mark.asyncio
    async def test_fetch_entra_groups_from_graph_api_respects_provider_metadata_override(self, sso_service):
        """Provider metadata should override global Graph fallback defaults."""
        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock) as mock_get_client, patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_entra_graph_api_enabled = True
            mock_settings.sso_entra_graph_api_timeout = 10
            mock_settings.sso_entra_graph_api_max_groups = 0
            groups = await sso_service._fetch_entra_groups_from_graph_api(
                "at",
                "user@contoso.com",
                {"graph_api_enabled": False},
            )

        assert groups is None
        mock_get_client.assert_not_called()

    @pytest.mark.asyncio
    async def test_fetch_entra_groups_from_graph_api_respects_string_bool_override(self, sso_service):
        """String provider metadata values should be parsed for graph_api_enabled."""
        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock) as mock_get_client, patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_entra_graph_api_enabled = True
            mock_settings.sso_entra_graph_api_timeout = 10
            mock_settings.sso_entra_graph_api_max_groups = 0
            groups = await sso_service._fetch_entra_groups_from_graph_api(
                "at",
                "user@contoso.com",
                {"graph_api_enabled": "false"},
            )

        assert groups is None
        mock_get_client.assert_not_called()


# ---------------------------------------------------------------------------
# Normalization tests
# ---------------------------------------------------------------------------


class TestNormalization:
    def test_normalize_github(self, sso_service):
        provider = _make_provider(id="github")
        result = sso_service._normalize_user_info(
            provider,
            {
                "login": "ghuser",
                "email": "gh@test.com",
                "name": "GH User",
                "avatar_url": "https://avatar",
                "id": 123,
                "organizations": ["org1"],
            },
        )
        assert result["provider"] == "github"
        assert result["username"] == "ghuser"
        assert result["organizations"] == ["org1"]

    def test_normalize_google(self, sso_service):
        provider = _make_provider(id="google", name="google")
        result = sso_service._normalize_user_info(
            provider,
            {
                "email": "user@gmail.com",
                "name": "Google User",
                "picture": "https://pic",
                "sub": "google-123",
            },
        )
        assert result["provider"] == "google"
        assert result["username"] == "user"
        assert result["provider_id"] == "google-123"

    def test_normalize_entra(self, sso_service):
        provider = _make_provider(id="entra", name="entra", provider_metadata={})
        result = sso_service._normalize_user_info(
            provider,
            {
                "email": "user@contoso.com",
                "name": "Entra User",
                "sub": "entra-oid",
                "groups": ["grp1"],
                "roles": ["role1"],
            },
        )
        assert result["provider"] == "entra"
        assert "grp1" in result["groups"]
        assert "role1" in result["groups"]

    def test_normalize_generic(self, sso_service):
        provider = _make_provider(id="custom", name="custom")
        result = sso_service._normalize_user_info(
            provider,
            {
                "email": "user@custom.com",
                "name": "Custom User",
                "sub": "c123",
            },
        )
        assert result["provider"] == "custom"
        assert result["email"] == "user@custom.com"

    def test_normalize_okta(self, sso_service):
        provider = _make_provider(id="okta", name="okta")
        result = sso_service._normalize_user_info(
            provider,
            {
                "email": "user@okta.com",
                "name": "Okta User",
                "preferred_username": "oktauser",
                "sub": "okta-123",
            },
        )
        assert result["provider"] == "okta"
        assert result["username"] == "oktauser"

    def test_normalize_keycloak(self, sso_service):
        provider = _make_provider(
            id="keycloak",
            name="keycloak",
            provider_metadata={"map_realm_roles": True, "map_client_roles": True},
        )
        result = sso_service._normalize_user_info(
            provider,
            {
                "email": "user@kc.com",
                "name": "KC User",
                "preferred_username": "kcuser",
                "sub": "kc-123",
                "realm_access": {"roles": ["admin", "user"]},
                "resource_access": {"my-app": {"roles": ["editor"]}},
                "groups": ["/team-a"],
            },
        )
        assert result["provider"] == "keycloak"
        assert "admin" in result["groups"]
        assert "my-app:editor" in result["groups"]
        assert "/team-a" in result["groups"]

    def test_normalize_adfs_with_valid_email(self, sso_service):
        """Test ADFS normalization when email claim is already in valid format."""
        provider = _make_provider(id="adfs", name="adfs", provider_metadata={})
        result = sso_service._normalize_user_info(
            provider,
            {
                "email": "user@company.com",
                "name": "ADFS User",
                "sub": "adfs-123",
                "groups": ["group1", "group2"],
            },
        )
        assert result["provider"] == "adfs"
        assert result["email"] == "user@company.com"
        assert result["username"] == "user"
        assert result["full_name"] == "ADFS User"
        assert result["email_verified"] is True
        assert set(result["groups"]) == {"group1", "group2"}
        assert result["provider_id"] == "adfs-123"

    def test_normalize_adfs_with_preferred_username(self, sso_service):
        """Test ADFS normalization when preferred_username contains email (Entra ID federation)."""
        provider = _make_provider(id="adfs", name="adfs", provider_metadata={})
        result = sso_service._normalize_user_info(
            provider,
            {
                "preferred_username": "user@company.com",
                "upn": "DOMAIN\\user",
                "name": "ADFS User",
                "sub": "adfs-456",
            },
        )
        assert result["provider"] == "adfs"
        assert result["email"] == "user@company.com"
        assert result["username"] == "user"
        assert result["email_verified"] is True

    def test_normalize_adfs_with_upn_email_format(self, sso_service):
        """Test ADFS normalization when UPN is already in email format."""
        provider = _make_provider(id="adfs", name="adfs", provider_metadata={})
        result = sso_service._normalize_user_info(
            provider,
            {
                "upn": "user@company.com",
                "name": "ADFS User",
                "sub": "adfs-789",
            },
        )
        assert result["provider"] == "adfs"
        assert result["email"] == "user@company.com"
        assert result["username"] == "user"

    def test_normalize_adfs_with_domain_backslash_format_provider_metadata(self, sso_service):
        """Test ADFS normalization with DOMAIN\\username format using provider metadata."""
        provider = _make_provider(
            id="adfs",
            name="adfs",
            provider_metadata={"default_email_domain": "company.com"},
        )
        result = sso_service._normalize_user_info(
            provider,
            {
                "upn": "DOMAIN\\user",
                "name": "ADFS User",
                "sub": "adfs-101",
            },
        )
        assert result["provider"] == "adfs"
        assert result["email"] == "user@company.com"
        assert result["username"] == "user"
        assert result["email_verified"] is True

    def test_normalize_adfs_with_domain_backslash_format_global_setting(self, sso_service):
        """Test ADFS normalization with DOMAIN\\username format using global setting."""
        provider = _make_provider(id="adfs", name="adfs", provider_metadata={})
        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_adfs_default_email_domain = "company.com"
            result = sso_service._normalize_user_info(
                provider,
                {
                    "upn": "DOMAIN\\user",
                    "name": "ADFS User",
                    "sub": "adfs-102",
                },
            )
            assert result["provider"] == "adfs"
            assert result["email"] == "user@company.com"
            assert result["username"] == "user"

    def test_normalize_adfs_with_domain_backslash_no_default_domain(self, sso_service):
        """Test ADFS normalization with DOMAIN\\username format but no default domain configured."""
        provider = _make_provider(id="adfs", name="adfs", provider_metadata={})
        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_adfs_default_email_domain = None
            result = sso_service._normalize_user_info(
                provider,
                {
                    "upn": "DOMAIN\\user",
                    "name": "ADFS User",
                    "sub": "adfs-103",
                },
            )
        assert result["provider"] == "adfs"
        assert result["email"] is None
        assert result["username"] == "user"  # Username extracted from DOMAIN\username

    def test_normalize_adfs_with_plain_username_provider_metadata(self, sso_service):
        """Test ADFS normalization with plain username using provider metadata."""
        provider = _make_provider(
            id="adfs",
            name="adfs",
            provider_metadata={"default_email_domain": "company.com"},
        )
        result = sso_service._normalize_user_info(
            provider,
            {
                "upn": "plainuser",
                "name": "ADFS User",
                "sub": "adfs-104",
            },
        )
        assert result["provider"] == "adfs"
        assert result["email"] == "plainuser@company.com"
        assert result["username"] == "plainuser"
        assert result["email_verified"] is True

    def test_normalize_adfs_with_plain_username_global_setting(self, sso_service):
        """Test ADFS normalization with plain username using global setting."""
        provider = _make_provider(id="adfs", name="adfs", provider_metadata={})
        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_adfs_default_email_domain = "company.com"
            result = sso_service._normalize_user_info(
                provider,
                {
                    "upn": "plainuser",
                    "name": "ADFS User",
                    "sub": "adfs-105",
                },
            )
            assert result["provider"] == "adfs"
            assert result["email"] == "plainuser@company.com"
            assert result["username"] == "plainuser"

    def test_normalize_adfs_with_plain_username_no_default_domain(self, sso_service):
        """Test ADFS normalization with plain username but no default domain configured."""
        provider = _make_provider(id="adfs", name="adfs", provider_metadata={})
        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_adfs_default_email_domain = None
            result = sso_service._normalize_user_info(
                provider,
                {
                    "upn": "plainuser",
                    "name": "ADFS User",
                    "sub": "adfs-106",
                },
            )
        assert result["provider"] == "adfs"
        assert result["email"] is None
        assert result["username"] == "plainuser"

    def test_normalize_adfs_with_unique_name_fallback(self, sso_service):
        """Test ADFS normalization using unique_name as fallback."""
        provider = _make_provider(id="adfs", name="adfs", provider_metadata={})
        result = sso_service._normalize_user_info(
            provider,
            {
                "unique_name": "user@company.com",
                "name": "ADFS User",
                "sub": "adfs-107",
            },
        )
        assert result["provider"] == "adfs"
        assert result["email"] == "user@company.com"
        assert result["username"] == "user"

    def test_normalize_adfs_username_fallback_from_at_sign(self, sso_service):
        """Test ADFS username extraction from raw_email containing @ when email normalization fails."""
        provider = _make_provider(id="adfs", name="adfs", provider_metadata={})
        # Mock _normalize_adfs_email to return None even for an @-containing value,
        # forcing the fallback username extraction from raw_email.split("@")[0]
        with patch.object(sso_service, "_normalize_adfs_email", return_value=None):
            result = sso_service._normalize_user_info(
                provider,
                {
                    "upn": "user@broken-domain",
                    "name": "ADFS User",
                    "sub": "adfs-108",
                },
            )
        assert result["email"] is None
        assert result["username"] == "user"

    def test_normalize_adfs_priority_order(self, sso_service):
        """Test ADFS claim priority: email > preferred_username > upn > unique_name."""
        provider = _make_provider(id="adfs", name="adfs", provider_metadata={})

        # Test email takes priority
        result = sso_service._normalize_user_info(
            provider,
            {
                "email": "priority@company.com",
                "preferred_username": "second@company.com",
                "upn": "third@company.com",
                "unique_name": "fourth@company.com",
                "name": "ADFS User",
            },
        )
        assert result["email"] == "priority@company.com"

        # Test preferred_username takes priority when email is missing
        result = sso_service._normalize_user_info(
            provider,
            {
                "preferred_username": "second@company.com",
                "upn": "third@company.com",
                "unique_name": "fourth@company.com",
                "name": "ADFS User",
            },
        )
        assert result["email"] == "second@company.com"

        # Test upn takes priority when email and preferred_username are missing
        result = sso_service._normalize_user_info(
            provider,
            {
                "upn": "third@company.com",
                "unique_name": "fourth@company.com",
                "name": "ADFS User",
            },
        )
        assert result["email"] == "third@company.com"

    def test_normalize_adfs_no_email_claims(self, sso_service):
        """Test ADFS normalization when no email-related claims are present."""
        provider = _make_provider(id="adfs", name="adfs", provider_metadata={})
        result = sso_service._normalize_user_info(
            provider,
            {
                "name": "ADFS User",
                "sub": "adfs-108",
            },
        )
        assert result["provider"] == "adfs"
        assert result["email"] is None
        assert result["username"] is None

    def test_normalize_adfs_with_given_and_family_name(self, sso_service):
        """Test ADFS normalization constructs full_name from given_name and family_name."""
        provider = _make_provider(id="adfs", name="adfs", provider_metadata={})
        result = sso_service._normalize_user_info(
            provider,
            {
                "email": "user@company.com",
                "given_name": "John",
                "family_name": "Doe",
                "sub": "adfs-109",
            },
        )
        assert result["provider"] == "adfs"
        assert result["full_name"] == "John Doe"

    def test_normalize_adfs_full_name_fallback(self, sso_service):
        """Test ADFS normalization full_name fallback to email or username."""
        provider = _make_provider(id="adfs", name="adfs", provider_metadata={})

        # Fallback to email when name is missing
        result = sso_service._normalize_user_info(
            provider,
            {
                "email": "user@company.com",
                "sub": "adfs-110",
            },
        )
        assert result["full_name"] == "user@company.com"

        # Fallback to username when both name and email are missing
        result = sso_service._normalize_user_info(
            provider,
            {
                "upn": "DOMAIN\\user",
                "sub": "adfs-111",
            },
        )
        assert result["full_name"] == "user"

    def test_normalize_adfs_provider_id_fallback(self, sso_service):
        """Test ADFS normalization provider_id fallback chain: sub > oid > email > username."""
        provider = _make_provider(id="adfs", name="adfs", provider_metadata={})

        # Test sub is used when present
        result = sso_service._normalize_user_info(
            provider,
            {
                "email": "user@company.com",
                "sub": "adfs-sub-123",
                "oid": "adfs-oid-456",
            },
        )
        assert result["provider_id"] == "adfs-sub-123"

        # Test oid is used when sub is missing
        result = sso_service._normalize_user_info(
            provider,
            {
                "email": "user@company.com",
                "oid": "adfs-oid-456",
            },
        )
        assert result["provider_id"] == "adfs-oid-456"

        # Test email is used when both sub and oid are missing
        result = sso_service._normalize_user_info(
            provider,
            {
                "email": "user@company.com",
            },
        )
        assert result["provider_id"] == "user@company.com"

    def test_normalize_adfs_with_groups_claim(self, sso_service):
        """Test ADFS normalization properly handles groups claim."""
        provider = _make_provider(id="adfs", name="adfs", provider_metadata={})
        result = sso_service._normalize_user_info(
            provider,
            {
                "email": "user@company.com",
                "name": "ADFS User",
                "groups": ["IT-Admins", "Developers", "Users"],
            },
        )
        assert result["provider"] == "adfs"
        assert set(result["groups"]) == {"IT-Admins", "Developers", "Users"}

    def test_normalize_adfs_with_non_list_groups(self, sso_service):
        """Test ADFS normalization handles string groups claim via shared utility."""
        provider = _make_provider(id="adfs", name="adfs", provider_metadata={})
        result = sso_service._normalize_user_info(
            provider,
            {
                "email": "user@company.com",
                "name": "ADFS User",
                "groups": "single-group-string",
            },
        )
        assert result["provider"] == "adfs"
        # _extract_groups_and_roles handles string groups by appending as single element
        assert result["groups"] == ["single-group-string"]

    def test_normalize_adfs_email_verified_always_true(self, sso_service):
        """Test ADFS normalization always sets email_verified to True."""
        provider = _make_provider(id="adfs", name="adfs", provider_metadata={})
        result = sso_service._normalize_user_info(
            provider,
            {
                "email": "user@company.com",
                "name": "ADFS User",
            },
        )
        assert result["email_verified"] is True

    def test_normalize_adfs_provider_metadata_takes_precedence(self, sso_service):
        """Test ADFS normalization prefers provider metadata over global setting."""
        provider = _make_provider(
            id="adfs",
            name="adfs",
            provider_metadata={"default_email_domain": "metadata.com"},
        )
        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_adfs_default_email_domain = "global.com"
            result = sso_service._normalize_user_info(
                provider,
                {
                    "upn": "plainuser",
                    "name": "ADFS User",
                },
            )
        assert result["email"] == "plainuser@metadata.com"

    def test_normalize_adfs_whitespace_handling(self, sso_service):
        """Test ADFS normalization properly strips whitespace from claims."""
        provider = _make_provider(
            id="adfs",
            name="adfs",
            provider_metadata={"default_email_domain": "company.com"},
        )
        result = sso_service._normalize_user_info(
            provider,
            {
                "upn": "  user  ",
                "name": "ADFS User",
            },
        )
        assert result["email"] == "user@company.com"
        assert result["username"] == "user"
        assert result["groups"] == []  # No groups provided in test data


# ---------------------------------------------------------------------------
# Helper tests (extracted from normalization-related code)
# ---------------------------------------------------------------------------


class TestExtractGroupsAndRoles:
    """Tests for the extracted _extract_groups_and_roles helper."""

    def test_extracts_groups_from_default_claim(self):
        user_data = {"groups": ["engineering", "finance"]}
        result = SSOService._extract_groups_and_roles(user_data)
        assert result == ["engineering", "finance"]

    def test_extracts_groups_from_custom_claim(self):
        user_data = {"team_groups": ["alpha", "beta"]}
        result = SSOService._extract_groups_and_roles(user_data, groups_claim="team_groups")
        assert result == ["alpha", "beta"]

    def test_merges_roles_into_groups(self):
        user_data = {"groups": ["eng"], "roles": ["admin", "viewer"]}
        result = SSOService._extract_groups_and_roles(user_data)
        assert result == ["eng", "admin", "viewer"]

    def test_handles_string_groups_claim(self):
        user_data = {"groups": "single-group"}
        result = SSOService._extract_groups_and_roles(user_data)
        assert result == ["single-group"]

    def test_handles_string_roles_claim(self):
        user_data = {"roles": "single-role"}
        result = SSOService._extract_groups_and_roles(user_data)
        assert result == ["single-role"]

    def test_filters_non_string_values(self):
        user_data = {"groups": ["valid", 123, None, "also-valid"], "roles": [True, "role1"]}
        result = SSOService._extract_groups_and_roles(user_data)
        assert result == ["valid", "also-valid", "role1"]

    def test_returns_empty_when_no_claims(self):
        result = SSOService._extract_groups_and_roles({})
        assert result == []

    def test_returns_empty_for_empty_lists(self):
        user_data = {"groups": [], "roles": []}
        result = SSOService._extract_groups_and_roles(user_data)
        assert result == []


class TestBuildNormalizedUserInfo:
    """Tests for the extracted _build_normalized_user_info helper."""

    def test_builds_base_dict_from_standard_claims(self):
        user_data = {"email": "u@e.com", "name": "User", "picture": "https://img", "sub": "123", "preferred_username": "user1"}
        result = SSOService._build_normalized_user_info(user_data, "test_provider", ["grp1"])
        assert result["email"] == "u@e.com"
        assert result["full_name"] == "User"
        assert result["avatar_url"] == "https://img"
        assert result["provider_id"] == "123"
        assert result["username"] == "user1"
        assert result["provider"] == "test_provider"
        assert result["groups"] == ["grp1"]

    def test_overrides_take_precedence(self):
        user_data = {"email": "original@e.com", "name": "Original"}
        result = SSOService._build_normalized_user_info(user_data, "p", [], email="override@e.com", full_name="Override")
        assert result["email"] == "override@e.com"
        assert result["full_name"] == "Override"

    def test_propagates_email_verified_only_when_present(self):
        with_claim = {"email": "u@e.com", "email_verified": True}
        without_claim = {"email": "u@e.com"}

        result_with = SSOService._build_normalized_user_info(with_claim, "p", [])
        result_without = SSOService._build_normalized_user_info(without_claim, "p", [])

        assert "email_verified" in result_with
        assert result_with["email_verified"] is True
        assert "email_verified" not in result_without

    def test_deduplicates_groups(self):
        result = SSOService._build_normalized_user_info({}, "p", ["a", "b", "a"])
        assert sorted(result["groups"]) == ["a", "b"]

    def test_extra_keys_merged(self):
        result = SSOService._build_normalized_user_info({}, "p", [], extra={"organizations": ["org1"]})
        assert result["organizations"] == ["org1"]

    def test_username_falls_back_to_email_prefix(self):
        user_data = {"email": "alice@example.com"}
        result = SSOService._build_normalized_user_info(user_data, "p", [])
        assert result["username"] == "alice"

    def test_username_falls_back_to_empty_string_when_no_email(self):
        result = SSOService._build_normalized_user_info({}, "p", [])
        assert result["username"] == ""


class TestShouldSyncRoles:
    """Tests for the extracted _should_sync_roles helper."""

    def test_returns_true_by_default(self):
        assert SSOService._should_sync_roles("github", {}) is True

    def test_respects_sync_roles_true(self):
        assert SSOService._should_sync_roles("entra", {"sync_roles": True}) is True

    def test_respects_sync_roles_false(self):
        assert SSOService._should_sync_roles("entra", {"sync_roles": False}) is False

    def test_entra_fallback_to_legacy_setting(self):
        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_entra_sync_roles_on_login = False
            assert SSOService._should_sync_roles("entra", {}) is False

    def test_non_entra_ignores_legacy_setting(self):
        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_entra_sync_roles_on_login = False
            assert SSOService._should_sync_roles("github", {}) is True

    def test_sync_roles_overrides_entra_legacy(self):
        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_entra_sync_roles_on_login = False
            assert SSOService._should_sync_roles("entra", {"sync_roles": True}) is True


class TestCheckPendingApproval:
    """Tests for the extracted _check_pending_approval helper."""

    def test_creates_new_pending_when_none_exists(self, sso_service, mock_db):
        mock_db.execute.return_value.scalar_one_or_none.return_value = None
        result = sso_service._check_pending_approval("user@test.com", "github", {"full_name": "User"})
        assert result is False
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called()

    def test_returns_false_for_pending_status(self, sso_service, mock_db):
        pending = MagicMock()
        pending.status = "pending"
        pending.is_expired.return_value = False
        mock_db.execute.return_value.scalar_one_or_none.return_value = pending
        assert sso_service._check_pending_approval("u@t.com", "github", {}) is False

    def test_resets_expired_pending(self, sso_service, mock_db):
        pending = MagicMock()
        pending.status = "pending"
        pending.is_expired.return_value = True
        mock_db.execute.return_value.scalar_one_or_none.return_value = pending
        result = sso_service._check_pending_approval("u@t.com", "github", {"full_name": "User"})
        assert result is False
        # After reset, status should have been set to "pending" via _reset_pending_approval
        assert pending.auth_provider == "github"

    def test_returns_false_for_rejected(self, sso_service, mock_db):
        pending = MagicMock()
        pending.status = "rejected"
        mock_db.execute.return_value.scalar_one_or_none.return_value = pending
        assert sso_service._check_pending_approval("u@t.com", "github", {}) is False

    def test_returns_true_for_approved(self, sso_service, mock_db):
        pending = MagicMock()
        pending.status = "approved"
        pending.is_expired.return_value = False
        mock_db.execute.return_value.scalar_one_or_none.return_value = pending
        assert sso_service._check_pending_approval("u@t.com", "github", {}) is True

    def test_returns_false_for_expired_approved(self, sso_service, mock_db):
        pending = MagicMock()
        pending.status = "approved"
        pending.is_expired.return_value = True
        mock_db.execute.return_value.scalar_one_or_none.return_value = pending
        assert sso_service._check_pending_approval("u@t.com", "github", {}) is False

    def test_resets_expired_status(self, sso_service, mock_db):
        pending = MagicMock()
        pending.status = "expired"
        mock_db.execute.return_value.scalar_one_or_none.return_value = pending
        result = sso_service._check_pending_approval("u@t.com", "github", {"full_name": "User"})
        assert result is False
        assert pending.auth_provider == "github"

    def test_returns_false_for_completed(self, sso_service, mock_db):
        pending = MagicMock()
        pending.status = "completed"
        mock_db.execute.return_value.scalar_one_or_none.return_value = pending
        assert sso_service._check_pending_approval("u@t.com", "github", {}) is False

    def test_returns_false_for_unknown_status(self, sso_service, mock_db):
        pending = MagicMock()
        pending.status = "something_unexpected"
        mock_db.execute.return_value.scalar_one_or_none.return_value = pending
        assert sso_service._check_pending_approval("u@t.com", "github", {}) is False


# ---------------------------------------------------------------------------
# OIDC id_token verification tests
# ---------------------------------------------------------------------------


class TestOidcMetadataAndJwksHelpers:
    @pytest.mark.asyncio
    async def test_get_oidc_provider_metadata_returns_fresh_cached_value(self, sso_service):
        # Standard
        import time

        sso_service._oidc_config_cache["https://issuer.example.com"] = (time.monotonic(), {"jwks_uri": "https://issuer.example.com/jwks"})

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock) as mock_get_client:
            metadata = await sso_service._get_oidc_provider_metadata("https://issuer.example.com/")

        assert metadata == {"jwks_uri": "https://issuer.example.com/jwks"}
        mock_get_client.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_oidc_provider_metadata_expires_cache_and_handles_non_200(self, sso_service):
        # Standard
        import time

        sso_service._oidc_config_cache["https://issuer.example.com"] = (
            time.monotonic() - sso_service._OIDC_METADATA_CACHE_TTL_SECONDS - 1,
            {"jwks_uri": "stale"},
        )

        response = MagicMock()
        response.status_code = 500
        client = AsyncMock()
        client.get = AsyncMock(return_value=response)

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock, return_value=client):
            metadata = await sso_service._get_oidc_provider_metadata("https://issuer.example.com")

        assert metadata is None
        assert "https://issuer.example.com" not in sso_service._oidc_config_cache

    @pytest.mark.asyncio
    async def test_get_oidc_provider_metadata_rejects_non_object_json(self, sso_service):
        issuer = "https://issuer-bad-json.example.com"
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = ["not", "an", "object"]
        client = AsyncMock()
        client.get = AsyncMock(return_value=response)

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock, return_value=client):
            metadata = await sso_service._get_oidc_provider_metadata(issuer)

        assert metadata is None

    @pytest.mark.asyncio
    async def test_get_oidc_provider_metadata_caches_successful_discovery(self, sso_service):
        issuer = "https://issuer-cache-success.example.com"
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"issuer": issuer, "jwks_uri": f"{issuer}/jwks"}
        client = AsyncMock()
        client.get = AsyncMock(return_value=response)

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock, return_value=client):
            metadata = await sso_service._get_oidc_provider_metadata(issuer)

        assert metadata == {"issuer": issuer, "jwks_uri": f"{issuer}/jwks"}
        assert issuer in sso_service._oidc_config_cache

    @pytest.mark.asyncio
    async def test_get_oidc_provider_metadata_handles_request_exception(self, sso_service):
        issuer = "https://issuer-error.example.com"
        client = AsyncMock()
        client.get = AsyncMock(side_effect=RuntimeError("network error"))

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock, return_value=client):
            metadata = await sso_service._get_oidc_provider_metadata(issuer)

        assert metadata is None

    @pytest.mark.asyncio
    async def test_resolve_oidc_issuer_and_jwks_from_discovery(self, sso_service):
        provider = _make_provider(provider_type="oidc", issuer="https://issuer.example.com", jwks_uri=None)
        sso_service._get_oidc_provider_metadata = AsyncMock(return_value={"jwks_uri": " https://issuer.example.com/jwks ", "issuer": " https://resolved-issuer.example.com "})

        issuer, jwks_uri = await sso_service._resolve_oidc_issuer_and_jwks(provider)

        assert issuer == "https://resolved-issuer.example.com"
        assert jwks_uri == "https://issuer.example.com/jwks"

    def test_get_jwks_client_reuses_cached_instance(self, sso_service):
        first = sso_service._get_jwks_client("https://issuer.example.com/jwks")
        second = sso_service._get_jwks_client("https://issuer.example.com/jwks")

        assert first is second


class TestVerifyOidcIdToken:
    @pytest.mark.asyncio
    async def test_verify_oidc_id_token_returns_none_for_non_oidc_provider(self, sso_service):
        provider = _make_provider(provider_type="oauth2")
        claims = await sso_service._verify_oidc_id_token(provider, "id-token", expected_nonce=None)
        assert claims is None

    @pytest.mark.asyncio
    async def test_verify_oidc_id_token_success(self, sso_service):
        provider = _make_provider(id="oidc", provider_type="oidc", issuer="https://issuer.example.com", jwks_uri="https://issuer.example.com/jwks", client_id="cid")

        signing_key = SimpleNamespace(key="public-key")
        jwks_client = MagicMock()
        jwks_client.get_signing_key_from_jwt.return_value = signing_key

        with (
            patch.object(sso_service, "_get_jwks_client", return_value=jwks_client),
            patch("mcpgateway.services.sso_service.jwt.decode", return_value={"sub": "user-1", "nonce": "nonce-1"}),
        ):
            claims = await sso_service._verify_oidc_id_token(provider, "id-token", expected_nonce="nonce-1")

        assert claims is not None
        assert claims["sub"] == "user-1"

    @pytest.mark.asyncio
    async def test_verify_oidc_id_token_nonce_mismatch(self, sso_service):
        provider = _make_provider(id="oidc", provider_type="oidc", issuer="https://issuer.example.com", jwks_uri="https://issuer.example.com/jwks", client_id="cid")

        signing_key = SimpleNamespace(key="public-key")
        jwks_client = MagicMock()
        jwks_client.get_signing_key_from_jwt.return_value = signing_key

        with (
            patch.object(sso_service, "_get_jwks_client", return_value=jwks_client),
            patch("mcpgateway.services.sso_service.jwt.decode", return_value={"sub": "user-1", "nonce": "nonce-2"}),
        ):
            claims = await sso_service._verify_oidc_id_token(provider, "id-token", expected_nonce="nonce-1")

        assert claims is None

    @pytest.mark.asyncio
    async def test_verify_oidc_id_token_missing_jwks(self, sso_service):
        provider = _make_provider(id="oidc", provider_type="oidc", issuer=None, jwks_uri=None, client_id="cid")
        claims = await sso_service._verify_oidc_id_token(provider, "id-token", expected_nonce=None)
        assert claims is None

    @pytest.mark.asyncio
    async def test_verify_oidc_id_token_handles_pyjwt_error(self, sso_service):
        provider = _make_provider(id="oidc", provider_type="oidc", issuer="https://issuer.example.com", jwks_uri="https://issuer.example.com/jwks", client_id="cid")

        signing_key = SimpleNamespace(key="public-key")
        jwks_client = MagicMock()
        jwks_client.get_signing_key_from_jwt.return_value = signing_key

        # First-Party
        from mcpgateway.services import sso_service as sso_mod

        with (
            patch.object(sso_service, "_get_jwks_client", return_value=jwks_client),
            patch("mcpgateway.services.sso_service.jwt.decode", side_effect=sso_mod.jwt.PyJWTError("bad token")),
        ):
            claims = await sso_service._verify_oidc_id_token(provider, "id-token", expected_nonce=None)

        assert claims is None

    @pytest.mark.asyncio
    async def test_verify_oidc_id_token_handles_unexpected_exception(self, sso_service):
        provider = _make_provider(id="oidc", provider_type="oidc", issuer="https://issuer.example.com", jwks_uri="https://issuer.example.com/jwks", client_id="cid")

        with patch.object(sso_service, "_get_jwks_client", side_effect=RuntimeError("boom")):
            claims = await sso_service._verify_oidc_id_token(provider, "id-token", expected_nonce=None)

        assert claims is None


# ---------------------------------------------------------------------------
# JWT decode tests
# ---------------------------------------------------------------------------


class TestDecodeJWTClaims:
    def test_valid_jwt(self, sso_service):
        # Standard
        import base64

        # Third-Party
        import orjson

        payload = orjson.dumps({"sub": "123", "groups": ["admin"]})
        payload_b64 = base64.urlsafe_b64encode(payload).decode().rstrip("=")
        token = f"eyJhbGciOiJSUzI1NiJ9.{payload_b64}.signature"
        result = sso_service._decode_jwt_claims(token)
        assert result is not None
        assert result["sub"] == "123"

    def test_invalid_jwt_format(self, sso_service):
        result = sso_service._decode_jwt_claims("not-a-jwt")
        assert result is None

    def test_invalid_jwt_payload(self, sso_service):
        result = sso_service._decode_jwt_claims("header.!!!invalid!!!.sig")
        assert result is None


# ---------------------------------------------------------------------------
# Admin determination tests
# ---------------------------------------------------------------------------


class TestShouldUserBeAdmin:
    def test_admin_by_domain(self, sso_service):
        provider = _make_provider()
        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_auto_admin_domains = ["admin.com"]
            mock_settings.sso_github_admin_orgs = []
            mock_settings.sso_google_admin_domains = []
            mock_settings.sso_entra_admin_groups = []
            result = sso_service._should_user_be_admin("user@admin.com", {}, provider)
        assert result is True

    def test_not_admin_by_domain(self, sso_service):
        provider = _make_provider()
        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_auto_admin_domains = ["admin.com"]
            mock_settings.sso_github_admin_orgs = []
            mock_settings.sso_google_admin_domains = []
            mock_settings.sso_entra_admin_groups = []
            result = sso_service._should_user_be_admin("user@other.com", {}, provider)
        assert result is False

    def test_admin_by_github_org(self, sso_service):
        provider = _make_provider(id="github")
        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_auto_admin_domains = []
            mock_settings.sso_github_admin_orgs = ["my-org"]
            mock_settings.sso_google_admin_domains = []
            mock_settings.sso_entra_admin_groups = []
            result = sso_service._should_user_be_admin("user@github.com", {"organizations": ["my-org"]}, provider)
        assert result is True

    def test_admin_by_entra_group(self, sso_service):
        provider = _make_provider(id="entra")
        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_auto_admin_domains = []
            mock_settings.sso_github_admin_orgs = []
            mock_settings.sso_google_admin_domains = []
            mock_settings.sso_entra_admin_groups = ["admin-group-id"]
            result = sso_service._should_user_be_admin("user@contoso.com", {"groups": ["admin-group-id"]}, provider)
        assert result is True

    def test_admin_by_google_domain(self, sso_service):
        provider = _make_provider(id="google")
        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_auto_admin_domains = []
            mock_settings.sso_github_admin_orgs = []
            mock_settings.sso_google_admin_domains = ["google-admin.com"]
            mock_settings.sso_entra_admin_groups = []
            result = sso_service._should_user_be_admin("user@google-admin.com", {}, provider)
        assert result is True

    def test_invalid_email_rejects_admin_check(self, sso_service):
        """Security: Invalid emails should never be granted admin privileges."""
        provider = _make_provider(id="github")
        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_auto_admin_domains = ["admin.com"]
            mock_settings.sso_github_admin_orgs = ["my-org"]
            mock_settings.sso_google_admin_domains = []
            mock_settings.sso_entra_admin_groups = []

            # Test missing email
            result = sso_service._should_user_be_admin("", {"organizations": ["my-org"]}, provider)
            assert result is False

            # Test None email
            result = sso_service._should_user_be_admin(None, {"organizations": ["my-org"]}, provider)
            assert result is False

            # Test email without @ symbol
            result = sso_service._should_user_be_admin("invalid-email", {"organizations": ["my-org"]}, provider)
            assert result is False

    def test_invalid_email_rejects_admin_check_entra(self, sso_service):
        """Security: Invalid emails should never be granted admin privileges via Entra groups."""
        provider = _make_provider(id="entra")
        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_auto_admin_domains = []
            mock_settings.sso_github_admin_orgs = []
            mock_settings.sso_google_admin_domains = []
            mock_settings.sso_entra_admin_groups = ["admin-group-id"]

            # Test that even with matching Entra group, invalid email is rejected
            result = sso_service._should_user_be_admin("", {"groups": ["admin-group-id"]}, provider)
            assert result is False

            result = sso_service._should_user_be_admin(None, {"groups": ["admin-group-id"]}, provider)
            assert result is False


# ---------------------------------------------------------------------------
# Role mapping tests
# ---------------------------------------------------------------------------


class TestMapGroupsToRoles:
    @pytest.mark.asyncio
    async def test_no_mappings_returns_empty(self, sso_service):
        provider = _make_provider(provider_metadata={})
        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_entra_admin_groups = []
            mock_settings.sso_entra_default_role = None
            mock_settings.sso_entra_role_mappings = {}
            result = await sso_service._map_groups_to_roles("user@test.com", ["group1"], provider)
        assert result == []

    @pytest.mark.asyncio
    async def test_entra_admin_group_mapping(self, sso_service):
        provider = _make_provider(id="entra", provider_metadata={})
        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_entra_admin_groups = ["admin-grp"]
            mock_settings.sso_entra_default_role = None
            mock_settings.sso_entra_role_mappings = {}
            mock_settings.default_admin_role = "platform_admin"
            result = await sso_service._map_groups_to_roles("user@test.com", ["admin-grp"], provider)
        assert len(result) == 1
        assert result[0]["role_name"] == "platform_admin"

    @pytest.mark.asyncio
    async def test_role_mapping_with_admin_shorthand(self, sso_service):
        provider = _make_provider(provider_metadata={"role_mappings": {"super-group": "admin"}})
        with patch("mcpgateway.services.sso_service.settings") as mock_settings, patch("mcpgateway.services.role_service.RoleService") as mock_role_svc:
            mock_settings.sso_entra_admin_groups = []
            mock_settings.sso_entra_default_role = None
            mock_settings.sso_entra_role_mappings = {}
            mock_settings.default_admin_role = "platform_admin"
            result = await sso_service._map_groups_to_roles("user@test.com", ["super-group"], provider)
        assert any(r["role_name"] == "platform_admin" for r in result)

    @pytest.mark.asyncio
    async def test_role_mapping_with_custom_role(self, sso_service):
        mock_role = SimpleNamespace(name="developer", scope="team", id="r1")
        provider = _make_provider(provider_metadata={"role_mappings": {"dev-group": "developer"}})

        with patch("mcpgateway.services.sso_service.settings") as mock_settings, patch("mcpgateway.services.role_service.RoleService") as MockRoleService:
            mock_settings.sso_entra_admin_groups = []
            mock_settings.sso_entra_default_role = None
            mock_settings.sso_entra_role_mappings = {}
            role_svc_instance = AsyncMock()
            role_svc_instance.get_role_by_name = AsyncMock(return_value=mock_role)
            MockRoleService.return_value = role_svc_instance
            result = await sso_service._map_groups_to_roles("user@test.com", ["dev-group"], provider)

        assert len(result) == 1
        assert result[0]["role_name"] == "developer"

    @pytest.mark.asyncio
    async def test_entra_default_role_fallback(self, sso_service):
        mock_role = SimpleNamespace(name="viewer", scope="global", id="r2")
        provider = _make_provider(id="entra", provider_metadata={})

        with patch("mcpgateway.services.sso_service.settings") as mock_settings, patch("mcpgateway.services.role_service.RoleService") as MockRoleService:
            mock_settings.sso_entra_admin_groups = []
            mock_settings.sso_entra_default_role = "viewer"
            mock_settings.sso_entra_role_mappings = {}
            role_svc_instance = AsyncMock()
            role_svc_instance.get_role_by_name = AsyncMock(return_value=mock_role)
            MockRoleService.return_value = role_svc_instance
            result = await sso_service._map_groups_to_roles("user@test.com", ["unmatched-group"], provider)

        assert len(result) == 1
        assert result[0]["role_name"] == "viewer"

    @pytest.mark.asyncio
    async def test_provider_metadata_default_role_fallback(self, sso_service):
        mock_role = SimpleNamespace(name="viewer", scope="global", id="r-viewer")
        provider = _make_provider(
            id="keycloak",
            provider_metadata={"default_role": "viewer"},
        )

        with patch("mcpgateway.services.sso_service.settings") as mock_settings, patch("mcpgateway.services.role_service.RoleService") as MockRoleService:
            mock_settings.sso_entra_admin_groups = []
            mock_settings.sso_entra_default_role = None
            mock_settings.sso_entra_role_mappings = {}
            mock_settings.default_admin_role = "platform_admin"
            role_svc_instance = AsyncMock()
            role_svc_instance.get_role_by_name = AsyncMock(return_value=mock_role)
            MockRoleService.return_value = role_svc_instance
            result = await sso_service._map_groups_to_roles("user@test.com", ["unmatched-group"], provider)

        assert len(result) == 1
        assert result[0]["role_name"] == "viewer"
        assert result[0]["scope"] == "global"
        assert result[0]["scope_id"] is None

    @pytest.mark.asyncio
    async def test_role_mapping_resolves_team_scope_to_personal_team(self, sso_service):
        mock_role = SimpleNamespace(name="developer", scope="team", id="r-dev")
        provider = _make_provider(
            id="keycloak",
            provider_metadata={
                "role_mappings": {"gateway-developer": "developer"},
                "resolve_team_scope_to_personal_team": True,
            },
        )

        with (
            patch("mcpgateway.services.sso_service.settings") as mock_settings,
            patch("mcpgateway.services.role_service.RoleService") as MockRoleService,
            patch("mcpgateway.services.personal_team_service.PersonalTeamService") as MockPersonalTeamService,
        ):
            mock_settings.sso_entra_admin_groups = []
            mock_settings.sso_entra_default_role = None
            mock_settings.sso_entra_role_mappings = {}
            mock_settings.default_admin_role = "platform_admin"

            role_svc_instance = AsyncMock()
            role_svc_instance.get_role_by_name = AsyncMock(return_value=mock_role)
            MockRoleService.return_value = role_svc_instance

            personal_team_service = AsyncMock()
            personal_team_service.get_personal_team = AsyncMock(return_value=SimpleNamespace(id="team-123"))
            MockPersonalTeamService.return_value = personal_team_service

            result = await sso_service._map_groups_to_roles("user@test.com", ["gateway-developer"], provider)

        assert len(result) == 1
        assert result[0]["role_name"] == "developer"
        assert result[0]["scope"] == "team"
        assert result[0]["scope_id"] == "team-123"

    @pytest.mark.asyncio
    async def test_role_mapping_reuses_cached_personal_team_resolution(self, sso_service):
        """Personal team lookup should be cached across multiple team-scoped mappings."""
        provider = _make_provider(
            id="keycloak",
            provider_metadata={
                "role_mappings": {"grp-a": "developer", "grp-b": "viewer"},
                "resolve_team_scope_to_personal_team": True,
            },
        )
        role_dev = SimpleNamespace(name="developer", scope="team", id="r-dev")
        role_view = SimpleNamespace(name="viewer", scope="team", id="r-view")

        with (
            patch("mcpgateway.services.sso_service.settings") as mock_settings,
            patch("mcpgateway.services.role_service.RoleService") as MockRoleService,
            patch("mcpgateway.services.personal_team_service.PersonalTeamService") as MockPersonalTeamService,
        ):
            mock_settings.sso_entra_admin_groups = []
            mock_settings.sso_entra_default_role = None
            mock_settings.sso_entra_role_mappings = {}
            mock_settings.default_admin_role = "platform_admin"

            role_svc_instance = AsyncMock()

            async def _get_role_by_name(role_name, scope="team"):
                if scope != "team":
                    return None
                if role_name == "developer":
                    return role_dev
                if role_name == "viewer":
                    return role_view
                return None

            role_svc_instance.get_role_by_name = AsyncMock(side_effect=_get_role_by_name)
            MockRoleService.return_value = role_svc_instance

            personal_team_service = AsyncMock()
            personal_team_service.get_personal_team = AsyncMock(return_value=SimpleNamespace(id="team-abc"))
            MockPersonalTeamService.return_value = personal_team_service

            result = await sso_service._map_groups_to_roles("user@test.com", ["grp-a", "grp-b"], provider)

        assert len(result) == 2
        assert {entry["role_name"] for entry in result} == {"developer", "viewer"}
        assert all(entry["scope"] == "team" for entry in result)
        assert all(entry["scope_id"] == "team-abc" for entry in result)
        assert personal_team_service.get_personal_team.await_count == 1

    @pytest.mark.asyncio
    async def test_role_mapping_skips_team_scope_when_personal_team_missing(self, sso_service):
        """Team-scoped mapping is skipped when personal team cannot be resolved."""
        provider = _make_provider(
            id="keycloak",
            provider_metadata={
                "role_mappings": {"grp-a": "developer"},
                "resolve_team_scope_to_personal_team": True,
            },
        )
        role_dev = SimpleNamespace(name="developer", scope="team", id="r-dev")

        with (
            patch("mcpgateway.services.sso_service.settings") as mock_settings,
            patch("mcpgateway.services.role_service.RoleService") as MockRoleService,
            patch("mcpgateway.services.personal_team_service.PersonalTeamService") as MockPersonalTeamService,
        ):
            mock_settings.sso_entra_admin_groups = []
            mock_settings.sso_entra_default_role = None
            mock_settings.sso_entra_role_mappings = {}
            mock_settings.default_admin_role = "platform_admin"

            role_svc_instance = AsyncMock()
            role_svc_instance.get_role_by_name = AsyncMock(return_value=role_dev)
            MockRoleService.return_value = role_svc_instance

            personal_team_service = AsyncMock()
            personal_team_service.get_personal_team = AsyncMock(return_value=None)
            MockPersonalTeamService.return_value = personal_team_service

            result = await sso_service._map_groups_to_roles("user@test.com", ["grp-a"], provider)

        assert result == []

    @pytest.mark.asyncio
    async def test_role_mapping_handles_personal_team_resolution_exception(self, sso_service):
        """Team-scoped mapping is skipped if personal team resolution raises."""
        provider = _make_provider(
            id="keycloak",
            provider_metadata={
                "role_mappings": {"grp-a": "developer"},
                "resolve_team_scope_to_personal_team": True,
            },
        )
        role_dev = SimpleNamespace(name="developer", scope="team", id="r-dev")

        with (
            patch("mcpgateway.services.sso_service.settings") as mock_settings,
            patch("mcpgateway.services.role_service.RoleService") as MockRoleService,
            patch("mcpgateway.services.personal_team_service.PersonalTeamService") as MockPersonalTeamService,
        ):
            mock_settings.sso_entra_admin_groups = []
            mock_settings.sso_entra_default_role = None
            mock_settings.sso_entra_role_mappings = {}
            mock_settings.default_admin_role = "platform_admin"

            role_svc_instance = AsyncMock()
            role_svc_instance.get_role_by_name = AsyncMock(return_value=role_dev)
            MockRoleService.return_value = role_svc_instance

            personal_team_service = AsyncMock()
            personal_team_service.get_personal_team = AsyncMock(side_effect=RuntimeError("boom"))
            MockPersonalTeamService.return_value = personal_team_service

            result = await sso_service._map_groups_to_roles("user@test.com", ["grp-a"], provider)

        assert result == []

    @pytest.mark.asyncio
    async def test_default_team_role_skipped_when_personal_team_missing(self, sso_service):
        """Team-scoped default role should not be assigned without a personal team."""
        provider = _make_provider(
            id="keycloak",
            provider_metadata={
                "default_role": "developer",
                "resolve_team_scope_to_personal_team": True,
            },
        )
        role_dev = SimpleNamespace(name="developer", scope="team", id="r-dev")

        with (
            patch("mcpgateway.services.sso_service.settings") as mock_settings,
            patch("mcpgateway.services.role_service.RoleService") as MockRoleService,
            patch("mcpgateway.services.personal_team_service.PersonalTeamService") as MockPersonalTeamService,
        ):
            mock_settings.sso_entra_admin_groups = []
            mock_settings.sso_entra_default_role = None
            mock_settings.sso_entra_role_mappings = {}
            mock_settings.default_admin_role = "platform_admin"

            role_svc_instance = AsyncMock()
            role_svc_instance.get_role_by_name = AsyncMock(return_value=role_dev)
            MockRoleService.return_value = role_svc_instance

            personal_team_service = AsyncMock()
            personal_team_service.get_personal_team = AsyncMock(return_value=None)
            MockPersonalTeamService.return_value = personal_team_service

            result = await sso_service._map_groups_to_roles("user@test.com", ["unmatched-group"], provider)

        assert result == []


# ---------------------------------------------------------------------------
# Entra legacy role mapping fallback
# ---------------------------------------------------------------------------


class TestEntraLegacyRoleMappings:
    @pytest.mark.asyncio
    async def test_entra_legacy_role_mappings_fallback(self, sso_service):
        """When no role_mappings in metadata, falls back to sso_entra_role_mappings."""
        mock_role = SimpleNamespace(name="developer", scope="team", id="r1")
        provider = _make_provider(id="entra", provider_metadata={})

        with patch("mcpgateway.services.sso_service.settings") as mock_settings, patch("mcpgateway.services.role_service.RoleService") as MockRoleService:
            mock_settings.sso_entra_admin_groups = []
            mock_settings.sso_entra_default_role = None
            mock_settings.sso_entra_role_mappings = {"dev-group": "developer"}
            role_svc = AsyncMock()
            role_svc.get_role_by_name = AsyncMock(return_value=mock_role)
            MockRoleService.return_value = role_svc
            result = await sso_service._map_groups_to_roles("user@test.com", ["dev-group"], provider)

        assert len(result) == 1
        assert result[0]["role_name"] == "developer"

    @pytest.mark.asyncio
    async def test_role_not_found_in_cache(self, sso_service):
        """Role mapping to non-existent role logs warning."""
        provider = _make_provider(provider_metadata={"role_mappings": {"grp": "missing-role"}})

        with patch("mcpgateway.services.sso_service.settings") as mock_settings, patch("mcpgateway.services.role_service.RoleService") as MockRoleService:
            mock_settings.sso_entra_admin_groups = []
            mock_settings.sso_entra_default_role = None
            mock_settings.sso_entra_role_mappings = {}
            role_svc = AsyncMock()
            role_svc.get_role_by_name = AsyncMock(return_value=None)
            MockRoleService.return_value = role_svc
            result = await sso_service._map_groups_to_roles("user@test.com", ["grp"], provider)

        assert result == []  # Nothing mapped

    @pytest.mark.asyncio
    async def test_entra_admin_group_checked_before_role_mappings(self, sso_service):
        """Entra admin groups produce platform_admin even without role_mappings."""
        provider = _make_provider(id="entra", provider_metadata={})

        with patch("mcpgateway.services.sso_service.settings") as mock_settings, patch("mcpgateway.services.role_service.RoleService") as MockRoleService:
            mock_settings.sso_entra_admin_groups = ["admin-grp"]
            mock_settings.sso_entra_default_role = None
            mock_settings.sso_entra_role_mappings = {}
            mock_settings.default_admin_role = "platform_admin"
            role_svc = AsyncMock()
            MockRoleService.return_value = role_svc
            result = await sso_service._map_groups_to_roles("user@test.com", ["admin-grp", "other"], provider)

        assert any(r["role_name"] == "platform_admin" for r in result)


# ---------------------------------------------------------------------------
# _sync_user_roles tests
# ---------------------------------------------------------------------------


class TestSyncUserRoles:
    @pytest.mark.asyncio
    async def test_revokes_removed_roles(self, sso_service):
        """Roles no longer in desired set are revoked."""
        old_role = SimpleNamespace(
            role=SimpleNamespace(name="old-role", id="r-old"),
            scope="team",
            scope_id=None,
            grant_source="sso",
            role_id="r-old",
        )

        with patch("mcpgateway.services.role_service.RoleService") as MockRoleService:
            role_svc = AsyncMock()
            role_svc.list_user_roles = AsyncMock(return_value=[old_role])
            role_svc.revoke_role_from_user = AsyncMock()
            role_svc.get_role_by_name = AsyncMock(return_value=SimpleNamespace(name="new-role", id="r-new", scope="team"))
            role_svc.get_user_role_assignment = AsyncMock(return_value=None)
            role_svc.assign_role_to_user = AsyncMock()
            MockRoleService.return_value = role_svc

            provider = _make_provider()
            await sso_service._sync_user_roles(
                "user@test.com",
                [{"role_name": "new-role", "scope": "team", "scope_id": None}],
                provider,
            )

        role_svc.revoke_role_from_user.assert_called_once()
        role_svc.assign_role_to_user.assert_called_once()

    @pytest.mark.asyncio
    async def test_assigns_new_roles(self, sso_service):
        """New roles are assigned when not existing."""
        with patch("mcpgateway.services.role_service.RoleService") as MockRoleService:
            role_svc = AsyncMock()
            role_svc.list_user_roles = AsyncMock(return_value=[])  # No existing
            role_svc.get_role_by_name = AsyncMock(return_value=SimpleNamespace(name="developer", id="r1", scope="team"))
            role_svc.get_user_role_assignment = AsyncMock(return_value=None)
            role_svc.assign_role_to_user = AsyncMock()
            MockRoleService.return_value = role_svc

            await sso_service._sync_user_roles(
                "user@test.com",
                [{"role_name": "developer", "scope": "team"}],
                _make_provider(),
            )

        role_svc.assign_role_to_user.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_existing_active_role(self, sso_service):
        """Existing active role assignment is not re-assigned."""
        existing_assignment = SimpleNamespace(is_active=True)

        with patch("mcpgateway.services.role_service.RoleService") as MockRoleService:
            role_svc = AsyncMock()
            role_svc.list_user_roles = AsyncMock(return_value=[])
            role_svc.get_role_by_name = AsyncMock(return_value=SimpleNamespace(name="viewer", id="r2", scope="global"))
            role_svc.get_user_role_assignment = AsyncMock(return_value=existing_assignment)
            role_svc.assign_role_to_user = AsyncMock()
            MockRoleService.return_value = role_svc

            await sso_service._sync_user_roles(
                "user@test.com",
                [{"role_name": "viewer", "scope": "global"}],
                _make_provider(),
            )

        role_svc.assign_role_to_user.assert_not_called()

    @pytest.mark.asyncio
    async def test_role_not_found_skipped(self, sso_service):
        """Role not found by name is logged and skipped."""
        with patch("mcpgateway.services.role_service.RoleService") as MockRoleService:
            role_svc = AsyncMock()
            role_svc.list_user_roles = AsyncMock(return_value=[])
            role_svc.get_role_by_name = AsyncMock(return_value=None)
            role_svc.assign_role_to_user = AsyncMock()
            MockRoleService.return_value = role_svc

            await sso_service._sync_user_roles(
                "user@test.com",
                [{"role_name": "nonexistent", "scope": "team"}],
                _make_provider(),
            )

        role_svc.assign_role_to_user.assert_not_called()

    @pytest.mark.asyncio
    async def test_assignment_exception_handled(self, sso_service):
        """Exception during role assignment is caught and logged."""
        with patch("mcpgateway.services.role_service.RoleService") as MockRoleService:
            role_svc = AsyncMock()
            role_svc.list_user_roles = AsyncMock(return_value=[])
            role_svc.get_role_by_name = AsyncMock(return_value=SimpleNamespace(name="dev", id="r1", scope="team"))
            role_svc.get_user_role_assignment = AsyncMock(return_value=None)
            role_svc.assign_role_to_user = AsyncMock(side_effect=RuntimeError("db error"))
            MockRoleService.return_value = role_svc

            # Should not raise
            await sso_service._sync_user_roles(
                "user@test.com",
                [{"role_name": "dev", "scope": "team"}],
                _make_provider(),
            )

        sso_service.db.rollback.assert_called()

    @pytest.mark.asyncio
    async def test_assignment_exception_handles_rollback_failure(self, sso_service):
        """Rollback errors after assignment failure are swallowed and logged."""
        sso_service.db.rollback.side_effect = RuntimeError("rollback failed")

        with patch("mcpgateway.services.role_service.RoleService") as MockRoleService:
            role_svc = AsyncMock()
            role_svc.list_user_roles = AsyncMock(return_value=[])
            role_svc.get_role_by_name = AsyncMock(return_value=SimpleNamespace(name="dev", id="r1", scope="team"))
            role_svc.get_user_role_assignment = AsyncMock(return_value=None)
            role_svc.assign_role_to_user = AsyncMock(side_effect=RuntimeError("db error"))
            MockRoleService.return_value = role_svc

            await sso_service._sync_user_roles(
                "user@test.com",
                [{"role_name": "dev", "scope": "team"}],
                _make_provider(),
            )

        sso_service.db.rollback.assert_called()


# ---------------------------------------------------------------------------
# authenticate_or_create_user tests
# ---------------------------------------------------------------------------


class TestAuthenticateOrCreateUser:
    @pytest.mark.asyncio
    async def test_no_email_returns_none(self, sso_service):
        result = await sso_service.authenticate_or_create_user({"full_name": "No Email"})
        assert result is None

    @pytest.mark.asyncio
    async def test_whitespace_email_returns_none(self, sso_service):
        result = await sso_service.authenticate_or_create_user({"email": "   ", "provider": "github"})
        assert result is None

    @pytest.mark.asyncio
    async def test_existing_user(self, sso_service, mock_db):
        existing_user = SimpleNamespace(
            email="user@test.com",
            full_name="Old Name",
            auth_provider="local",
            email_verified=False,
            last_login=None,
            is_admin=False,
            admin_origin=None,
        )
        sso_service.auth_service.get_user_by_email = AsyncMock(return_value=existing_user)
        sso_service.get_provider = lambda _id: _make_provider()

        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_auto_admin_domains = []
            mock_settings.sso_github_admin_orgs = []
            mock_settings.sso_google_admin_domains = []
            mock_settings.sso_entra_admin_groups = []
            mock_settings.sso_entra_sync_roles_on_login = False
            result = await sso_service.authenticate_or_create_user(
                {
                    "email": "user@test.com",
                    "full_name": "New Name",
                    "provider": "github",
                }
            )

        assert result is None

    @pytest.mark.asyncio
    async def test_existing_user_same_provider_allowed(self, sso_service, mock_db):
        existing_user = SimpleNamespace(
            email="user@test.com",
            full_name="Old Name",
            auth_provider="github",
            email_verified=False,
            last_login=None,
            is_admin=False,
            admin_origin=None,
        )
        sso_service.auth_service.get_user_by_email = AsyncMock(return_value=existing_user)
        sso_service.get_provider = lambda _id: _make_provider()

        with patch("mcpgateway.services.sso_service.settings") as mock_settings, patch("mcpgateway.services.sso_service.create_jwt_token", new_callable=AsyncMock) as mock_jwt:
            mock_settings.sso_auto_admin_domains = []
            mock_settings.sso_github_admin_orgs = []
            mock_settings.sso_google_admin_domains = []
            mock_settings.sso_entra_admin_groups = []
            mock_settings.sso_entra_sync_roles_on_login = False
            mock_jwt.return_value = "jwt-token"
            result = await sso_service.authenticate_or_create_user(
                {
                    "email": "user@test.com",
                    "full_name": "New Name",
                    "provider": "github",
                    "email_verified": True,
                }
            )

        assert result == "jwt-token"
        assert existing_user.full_name == "New Name"
        assert existing_user.auth_provider == "github"

    @pytest.mark.asyncio
    async def test_existing_user_calls_apply_team_mapping(self, sso_service, mock_db):
        existing_user = SimpleNamespace(
            email="user@test.com",
            full_name="Old Name",
            auth_provider="github",
            email_verified=True,
            last_login=None,
            is_admin=False,
            admin_origin=None,
        )
        provider = _make_provider(team_mapping={"engineering": "team-1"})
        sso_service.auth_service.get_user_by_email = AsyncMock(return_value=existing_user)
        sso_service.get_provider = lambda _id: provider
        sso_service._apply_team_mapping = AsyncMock()

        with patch("mcpgateway.services.sso_service.settings") as mock_settings, patch("mcpgateway.services.sso_service.create_jwt_token", new_callable=AsyncMock) as mock_jwt:
            mock_settings.sso_auto_admin_domains = []
            mock_settings.sso_github_admin_orgs = []
            mock_settings.sso_google_admin_domains = []
            mock_settings.sso_entra_admin_groups = []
            mock_settings.sso_entra_sync_roles_on_login = False
            mock_jwt.return_value = "jwt-token"
            result = await sso_service.authenticate_or_create_user(
                {
                    "email": "user@test.com",
                    "full_name": "New Name",
                    "provider": "github",
                    "email_verified": True,
                    "groups": ["engineering"],
                }
            )

        assert result == "jwt-token"
        sso_service._apply_team_mapping.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_existing_user_rejects_unverified_claim_without_mutation(self, sso_service, mock_db):
        existing_user = SimpleNamespace(
            email="user@test.com",
            full_name="Old Name",
            auth_provider="github",
            email_verified=True,
            last_login=None,
            is_admin=False,
            admin_origin=None,
        )
        sso_service.auth_service.get_user_by_email = AsyncMock(return_value=existing_user)
        sso_service.get_provider = lambda _id: _make_provider()

        result = await sso_service.authenticate_or_create_user(
            {
                "email": "user@test.com",
                "full_name": "New Name",
                "provider": "github",
                "email_verified": False,
            }
        )

        assert result is None
        assert existing_user.email_verified is True

    @pytest.mark.asyncio
    async def test_existing_user_absent_email_verified_claim_is_allowed(self, sso_service, mock_db):
        """Existing-user login must succeed when the provider omits email_verified.

        Regression guard for the same root cause as #3253: providers like Entra ID
        that omit email_verified should not block returning users either.
        """
        existing_user = SimpleNamespace(
            email="user@test.com",
            full_name="Old Name",
            auth_provider="github",
            email_verified=True,
            last_login=None,
            is_admin=False,
            admin_origin=None,
        )
        sso_service.auth_service.get_user_by_email = AsyncMock(return_value=existing_user)
        sso_service.get_provider = lambda _id: _make_provider()

        with patch("mcpgateway.services.sso_service.settings") as mock_settings, patch("mcpgateway.services.sso_service.create_jwt_token", new_callable=AsyncMock) as mock_jwt:
            mock_settings.sso_auto_admin_domains = []
            mock_settings.sso_github_admin_orgs = []
            mock_settings.sso_google_admin_domains = []
            mock_settings.sso_entra_admin_groups = []
            mock_settings.sso_entra_sync_roles_on_login = False
            mock_jwt.return_value = "jwt-token"
            # No email_verified key -- simulates Entra ID / GitHub work accounts
            result = await sso_service.authenticate_or_create_user(
                {
                    "email": "user@test.com",
                    "full_name": "Old Name",
                    "provider": "github",
                }
            )

        assert result == "jwt-token"

    @pytest.mark.asyncio
    async def test_existing_user_untrusted_domain_rejected(self, sso_service, mock_db):
        existing_user = SimpleNamespace(
            email="user@untrusted.com",
            full_name="Old Name",
            auth_provider="github",
            email_verified=True,
            last_login=None,
            is_admin=False,
            admin_origin=None,
        )
        sso_service.auth_service.get_user_by_email = AsyncMock(return_value=existing_user)
        sso_service.get_provider = lambda _id: _make_provider(trusted_domains=["trusted.com"])

        result = await sso_service.authenticate_or_create_user(
            {
                "email": "user@untrusted.com",
                "full_name": "Old Name",
                "provider": "github",
                "email_verified": True,
            }
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_existing_user_mixed_case_idp_email_uses_canonical_claims(self, sso_service, mock_db):
        existing_user = SimpleNamespace(
            email="user@test.com",
            full_name="User Name",
            auth_provider="github",
            email_verified=True,
            last_login=None,
            is_admin=False,
            admin_origin=None,
        )
        sso_service.auth_service.get_user_by_email = AsyncMock(return_value=existing_user)
        sso_service.get_provider = lambda _id: _make_provider()

        with patch("mcpgateway.services.sso_service.settings") as mock_settings, patch("mcpgateway.services.sso_service.create_jwt_token", new_callable=AsyncMock) as mock_jwt:
            mock_settings.sso_auto_admin_domains = []
            mock_settings.sso_github_admin_orgs = []
            mock_settings.sso_google_admin_domains = []
            mock_settings.sso_entra_admin_groups = []
            mock_settings.sso_entra_sync_roles_on_login = False
            mock_jwt.return_value = "jwt-token"

            result = await sso_service.authenticate_or_create_user(
                {
                    "email": "User@Test.com",
                    "full_name": "User Name",
                    "provider": "github",
                    "email_verified": True,
                }
            )

        assert result == "jwt-token"
        sso_service.auth_service.get_user_by_email.assert_awaited_once_with("user@test.com")
        token_payload = mock_jwt.await_args.args[0]
        assert token_payload["sub"] == "user@test.com"
        assert token_payload["email"] == "user@test.com"
        assert token_payload["user"]["email"] == "user@test.com"

    @pytest.mark.asyncio
    async def test_existing_user_avoids_post_commit_attribute_reads(self, sso_service, mock_db):
        """Regression: callback path must not read ORM attributes after commit."""

        class _GuardedUser:
            def __init__(self):
                self.email = "user@test.com"
                self._full_name = "Old Name"
                self._auth_provider = "github"
                self._is_admin = False
                self.admin_origin = None
                self.email_verified = False
                self.last_login = None
                self.raise_on_read = False

            @property
            def full_name(self):
                if self.raise_on_read:
                    raise RuntimeError("post-commit full_name read")
                return self._full_name

            @full_name.setter
            def full_name(self, value):
                self._full_name = value

            @property
            def auth_provider(self):
                if self.raise_on_read:
                    raise RuntimeError("post-commit auth_provider read")
                return self._auth_provider

            @auth_provider.setter
            def auth_provider(self, value):
                self._auth_provider = value

            @property
            def is_admin(self):
                if self.raise_on_read:
                    raise RuntimeError("post-commit is_admin read")
                return self._is_admin

            @is_admin.setter
            def is_admin(self, value):
                self._is_admin = value

        class _GuardedProvider:
            def __init__(self):
                self._id = "github"
                self._provider_metadata = {"sync_roles": True, "role_mappings": {}}
                self.raise_on_read = False

            @property
            def id(self):
                if self.raise_on_read:
                    raise RuntimeError("post-commit provider.id read")
                return self._id

            @property
            def provider_metadata(self):
                if self.raise_on_read:
                    raise RuntimeError("post-commit provider.provider_metadata read")
                return self._provider_metadata

        existing_user = _GuardedUser()
        provider = _GuardedProvider()
        sso_service.auth_service.get_user_by_email = AsyncMock(return_value=existing_user)
        sso_service.get_provider = lambda _id: provider
        sso_service._map_groups_to_roles = AsyncMock(return_value=[])
        sso_service._sync_user_roles = AsyncMock()

        def _commit_side_effect():
            existing_user.raise_on_read = True
            provider.raise_on_read = True

        mock_db.commit.side_effect = _commit_side_effect

        with patch("mcpgateway.services.sso_service.settings") as mock_settings, patch("mcpgateway.services.sso_service.create_jwt_token", new_callable=AsyncMock) as mock_jwt:
            mock_settings.sso_auto_admin_domains = []
            mock_settings.sso_github_admin_orgs = []
            mock_settings.sso_google_admin_domains = []
            mock_settings.sso_entra_admin_groups = []
            mock_jwt.return_value = "jwt-token"
            result = await sso_service.authenticate_or_create_user(
                {
                    "email": "user@test.com",
                    "full_name": "Updated Name",
                    "provider": "github",
                    "email_verified": True,
                    "groups": ["dev"],
                }
            )

        assert result == "jwt-token"
        assert existing_user._full_name == "Updated Name"
        sso_service._map_groups_to_roles.assert_called_once()
        sso_service._sync_user_roles.assert_called_once()

    @pytest.mark.asyncio
    async def test_existing_user_admin_promotion(self, sso_service, mock_db):
        existing_user = SimpleNamespace(
            email="user@admin.com",
            full_name="Admin",
            auth_provider="github",
            email_verified=True,
            last_login=None,
            is_admin=False,
            admin_origin=None,
        )
        sso_service.auth_service.get_user_by_email = AsyncMock(return_value=existing_user)
        sso_service.get_provider = lambda _id: _make_provider()

        with patch("mcpgateway.services.sso_service.settings") as mock_settings, patch("mcpgateway.services.sso_service.create_jwt_token", new_callable=AsyncMock) as mock_jwt:
            mock_settings.sso_auto_admin_domains = ["admin.com"]
            mock_settings.sso_github_admin_orgs = []
            mock_settings.sso_google_admin_domains = []
            mock_settings.sso_entra_admin_groups = []
            mock_settings.sso_entra_sync_roles_on_login = False
            mock_jwt.return_value = "jwt-token"
            result = await sso_service.authenticate_or_create_user(
                {
                    "email": "user@admin.com",
                    "full_name": "Admin",
                    "provider": "github",
                    "email_verified": True,
                }
            )

        assert existing_user.is_admin is True
        assert existing_user.admin_origin == "sso"

    @pytest.mark.asyncio
    async def test_existing_user_admin_demotion(self, sso_service, mock_db):
        existing_user = SimpleNamespace(
            email="user@other.com",
            full_name="Ex-Admin",
            auth_provider="github",
            email_verified=True,
            last_login=None,
            is_admin=True,
            admin_origin="sso",
        )
        sso_service.auth_service.get_user_by_email = AsyncMock(return_value=existing_user)
        sso_service.get_provider = lambda _id: _make_provider()

        with patch("mcpgateway.services.sso_service.settings") as mock_settings, patch("mcpgateway.services.sso_service.create_jwt_token", new_callable=AsyncMock) as mock_jwt:
            mock_settings.sso_auto_admin_domains = []
            mock_settings.sso_github_admin_orgs = []
            mock_settings.sso_google_admin_domains = []
            mock_settings.sso_entra_admin_groups = []
            mock_settings.sso_entra_sync_roles_on_login = False
            mock_jwt.return_value = "jwt-token"
            result = await sso_service.authenticate_or_create_user(
                {
                    "email": "user@other.com",
                    "full_name": "Ex-Admin",
                    "provider": "github",
                    "email_verified": True,
                }
            )

        assert existing_user.is_admin is False
        assert existing_user.admin_origin is None

    @pytest.mark.asyncio
    async def test_new_user_auto_create(self, sso_service, mock_db):
        sso_service.auth_service.get_user_by_email = AsyncMock(return_value=None)
        new_user = SimpleNamespace(
            email="new@test.com",
            full_name="New User",
            auth_provider="github",
            is_admin=False,
            admin_origin=None,
        )
        sso_service.auth_service.create_user = AsyncMock(return_value=new_user)
        sso_service.get_provider = lambda _id: _make_provider()

        with patch("mcpgateway.services.sso_service.settings") as mock_settings, patch("mcpgateway.services.sso_service.create_jwt_token", new_callable=AsyncMock) as mock_jwt:
            mock_settings.sso_auto_admin_domains = []
            mock_settings.sso_github_admin_orgs = []
            mock_settings.sso_google_admin_domains = []
            mock_settings.sso_entra_admin_groups = []
            mock_settings.sso_require_admin_approval = False
            mock_jwt.return_value = "new-jwt"
            result = await sso_service.authenticate_or_create_user(
                {
                    "email": "new@test.com",
                    "full_name": "New User",
                    "provider": "github",
                    "email_verified": True,
                }
            )

        assert result == "new-jwt"

    @pytest.mark.asyncio
    async def test_new_github_user_without_email_verified_claim_is_allowed(self, sso_service, mock_db):
        """GitHub payloads without email_verified must NOT be rejected.

        GitHub's /user API does not include email_verified for most accounts.
        The service normalises the payload without the key so that
        _is_email_verified_claim treats the absence as a pass-through.
        Regression guard for https://github.com/IBM/mcp-context-forge/issues/3253
        (same root cause as Entra ID).
        """
        sso_service.auth_service.get_user_by_email = AsyncMock(return_value=None)
        new_user = SimpleNamespace(
            email="new@test.com",
            full_name="New User",
            auth_provider="github",
            is_admin=False,
            admin_origin=None,
        )
        sso_service.auth_service.create_user = AsyncMock(return_value=new_user)
        sso_service.get_provider = lambda _id: _make_provider()
        normalized_user_info = sso_service._normalize_user_info(
            _make_provider(id="github"),
            {
                "email": "new@test.com",
                "name": "New User",
                "login": "new-user",
                "id": 1234,
            },
        )

        with patch("mcpgateway.services.sso_service.settings") as mock_settings, patch("mcpgateway.services.sso_service.create_jwt_token", new_callable=AsyncMock) as mock_jwt:
            mock_settings.sso_auto_admin_domains = []
            mock_settings.sso_github_admin_orgs = []
            mock_settings.sso_google_admin_domains = []
            mock_settings.sso_entra_admin_groups = []
            mock_settings.sso_require_admin_approval = False
            mock_jwt.return_value = "new-jwt"
            result = await sso_service.authenticate_or_create_user(normalized_user_info)

        assert result == "new-jwt"

    @pytest.mark.asyncio
    async def test_new_entra_user_without_email_verified_claim_is_allowed(self, sso_service, mock_db):
        """First-time Entra ID login must succeed even though email_verified is absent.

        Regression test for https://github.com/IBM/mcp-context-forge/issues/3253:
        Microsoft Entra ID work/school accounts do not include email_verified in
        the userinfo response.  Absence of the claim should be treated as a
        pass-through, not a rejection.
        """
        sso_service.auth_service.get_user_by_email = AsyncMock(return_value=None)
        new_user = SimpleNamespace(
            email="user@company.com",
            full_name="Entra User",
            auth_provider="entra",
            is_admin=False,
            admin_origin=None,
        )
        sso_service.auth_service.create_user = AsyncMock(return_value=new_user)
        sso_service.get_provider = lambda _id: _make_provider(id="entra")
        normalized_user_info = sso_service._normalize_user_info(
            _make_provider(id="entra"),
            {
                "email": "user@company.com",
                "name": "Entra User",
                "preferred_username": "user@company.com",
                "sub": "entra-sub-123",
                # No email_verified -- typical Microsoft Entra ID response
            },
        )
        # Confirm normalization did not inject the key
        assert "email_verified" not in normalized_user_info

        with patch("mcpgateway.services.sso_service.settings") as mock_settings, patch("mcpgateway.services.sso_service.create_jwt_token", new_callable=AsyncMock) as mock_jwt:
            mock_settings.sso_auto_admin_domains = []
            mock_settings.sso_github_admin_orgs = []
            mock_settings.sso_google_admin_domains = []
            mock_settings.sso_entra_admin_groups = []
            mock_settings.sso_require_admin_approval = False
            mock_jwt.return_value = "entra-jwt"
            result = await sso_service.authenticate_or_create_user(normalized_user_info)

        assert result == "entra-jwt"

    @pytest.mark.asyncio
    async def test_new_user_with_role_assignments_triggers_sync(self, sso_service, mock_db):
        """New user flow should apply role assignments when mapping returns results."""
        sso_service.auth_service.get_user_by_email = AsyncMock(return_value=None)
        sso_service.auth_service.create_user = AsyncMock(
            return_value=SimpleNamespace(
                email="new@test.com",
                full_name="New User",
                auth_provider="github",
                is_admin=False,
                admin_origin=None,
            )
        )
        sso_service.get_provider = lambda _id: _make_provider(provider_metadata={"sync_roles": True, "role_mappings": {}})
        sso_service._map_groups_to_roles = AsyncMock(return_value=[{"role_name": "developer", "scope": "team", "scope_id": None}])
        sso_service._sync_user_roles = AsyncMock()

        with patch("mcpgateway.services.sso_service.settings") as mock_settings, patch("mcpgateway.services.sso_service.create_jwt_token", new_callable=AsyncMock) as mock_jwt:
            mock_settings.sso_auto_admin_domains = []
            mock_settings.sso_github_admin_orgs = []
            mock_settings.sso_google_admin_domains = []
            mock_settings.sso_entra_admin_groups = []
            mock_settings.sso_require_admin_approval = False
            mock_jwt.return_value = "new-jwt"
            result = await sso_service.authenticate_or_create_user(
                {
                    "email": "new@test.com",
                    "full_name": "New User",
                    "provider": "github",
                    "email_verified": True,
                    "groups": ["dev"],
                }
            )

        assert result == "new-jwt"
        sso_service._map_groups_to_roles.assert_called_once()
        sso_service._sync_user_roles.assert_called_once()

    @pytest.mark.asyncio
    async def test_new_user_avoids_post_create_provider_reads(self, sso_service, mock_db):
        """Regression: new-user path must not touch provider ORM fields after create_user."""

        class _GuardedProvider:
            def __init__(self):
                self.auto_create_users = True
                self.trusted_domains = None
                self._id = "github"
                self._provider_metadata = {"sync_roles": True, "role_mappings": {}}
                self.raise_on_read = False

            @property
            def id(self):
                if self.raise_on_read:
                    raise RuntimeError("post-create provider.id read")
                return self._id

            @property
            def provider_metadata(self):
                if self.raise_on_read:
                    raise RuntimeError("post-create provider.provider_metadata read")
                return self._provider_metadata

        provider = _GuardedProvider()
        sso_service.auth_service.get_user_by_email = AsyncMock(return_value=None)
        sso_service.get_provider = lambda _id: provider
        sso_service._map_groups_to_roles = AsyncMock(return_value=[])
        sso_service._sync_user_roles = AsyncMock()

        async def _create_user(**_kwargs):
            provider.raise_on_read = True
            return SimpleNamespace(
                email="new@test.com",
                full_name="New User",
                auth_provider="github",
                is_admin=False,
                admin_origin=None,
            )

        sso_service.auth_service.create_user = AsyncMock(side_effect=_create_user)

        with patch("mcpgateway.services.sso_service.settings") as mock_settings, patch("mcpgateway.services.sso_service.create_jwt_token", new_callable=AsyncMock) as mock_jwt:
            mock_settings.sso_auto_admin_domains = []
            mock_settings.sso_github_admin_orgs = []
            mock_settings.sso_google_admin_domains = []
            mock_settings.sso_entra_admin_groups = []
            mock_settings.sso_require_admin_approval = False
            mock_jwt.return_value = "new-jwt"
            result = await sso_service.authenticate_or_create_user(
                {
                    "email": "new@test.com",
                    "full_name": "New User",
                    "provider": "github",
                    "email_verified": True,
                    "groups": ["dev"],
                }
            )

        assert result == "new-jwt"
        sso_service._map_groups_to_roles.assert_called_once()

    @pytest.mark.asyncio
    async def test_new_user_no_auto_create(self, sso_service, mock_db):
        sso_service.auth_service.get_user_by_email = AsyncMock(return_value=None)
        sso_service.get_provider = lambda _id: _make_provider(auto_create_users=False)

        result = await sso_service.authenticate_or_create_user(
            {
                "email": "new@test.com",
                "full_name": "New User",
                "provider": "github",
            }
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_new_user_untrusted_domain(self, sso_service, mock_db):
        sso_service.auth_service.get_user_by_email = AsyncMock(return_value=None)
        sso_service.get_provider = lambda _id: _make_provider(trusted_domains=["trusted.com"])

        result = await sso_service.authenticate_or_create_user(
            {
                "email": "new@untrusted.com",
                "full_name": "New User",
                "provider": "github",
            }
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_new_user_admin_approval_pending(self, sso_service, mock_db):
        """Admin approval required + no existing pending -> creates pending request."""
        sso_service.auth_service.get_user_by_email = AsyncMock(return_value=None)
        sso_service.get_provider = lambda _id: _make_provider()
        mock_db.execute.return_value.scalar_one_or_none.return_value = None  # No existing pending

        with (
            patch("mcpgateway.services.sso_service.settings") as mock_settings,
            patch("mcpgateway.services.sso_service.select", return_value=MagicMock()) as mock_select,
            patch("mcpgateway.services.sso_service.PendingUserApproval"),
        ):
            mock_settings.sso_require_admin_approval = True
            result = await sso_service.authenticate_or_create_user(
                {
                    "email": "new@test.com",
                    "full_name": "New User",
                    "provider": "github",
                    "email_verified": True,
                }
            )

        assert result is None
        mock_db.add.assert_called()  # Pending request created

    @pytest.mark.asyncio
    async def test_new_user_admin_approval_still_pending(self, sso_service, mock_db):
        """Existing pending approval that hasn't expired."""
        sso_service.auth_service.get_user_by_email = AsyncMock(return_value=None)
        sso_service.get_provider = lambda _id: _make_provider()
        pending = SimpleNamespace(status="pending", is_expired=lambda: False)
        mock_db.execute.return_value.scalar_one_or_none.return_value = pending

        with patch("mcpgateway.services.sso_service.settings") as mock_settings, patch("mcpgateway.services.sso_service.select", return_value=MagicMock()):
            mock_settings.sso_require_admin_approval = True
            result = await sso_service.authenticate_or_create_user(
                {
                    "email": "new@test.com",
                    "full_name": "New User",
                    "provider": "github",
                    "email_verified": True,
                }
            )

        assert result is None

    @pytest.mark.asyncio
    async def test_new_user_admin_approval_expired_pending_renews_request(self, sso_service, mock_db):
        """Expired pending approvals are renewed and still denied until admin action."""
        sso_service.auth_service.get_user_by_email = AsyncMock(return_value=None)
        sso_service.get_provider = lambda _id: _make_provider()
        pending = SimpleNamespace(
            status="pending",
            is_expired=lambda: True,
            requested_at=None,
            expires_at=None,
            auth_provider="github",
            sso_metadata={},
            approved_by="admin@example.com",
            approved_at=object(),
            rejection_reason="reason",
            admin_notes="notes",
        )
        mock_db.execute.return_value.scalar_one_or_none.return_value = pending

        with patch("mcpgateway.services.sso_service.settings") as mock_settings, patch("mcpgateway.services.sso_service.select", return_value=MagicMock()):
            mock_settings.sso_require_admin_approval = True
            result = await sso_service.authenticate_or_create_user(
                {
                    "email": "new@test.com",
                    "full_name": "New User",
                    "provider": "github",
                    "email_verified": True,
                }
            )

        assert result is None
        assert pending.status == "pending"
        assert pending.approved_by is None
        assert pending.approved_at is None
        assert pending.rejection_reason is None
        assert pending.admin_notes is None
        assert mock_db.commit.call_count >= 2

    @pytest.mark.asyncio
    async def test_new_user_rejects_unverified_email_claim(self, sso_service, mock_db):
        """SSO logins with explicit unverified email claims are rejected."""
        sso_service.auth_service.get_user_by_email = AsyncMock(return_value=None)
        sso_service.get_provider = lambda _id: _make_provider()

        result = await sso_service.authenticate_or_create_user(
            {
                "email": "new@test.com",
                "email_verified": False,
                "full_name": "New User",
                "provider": "github",
            }
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_new_user_admin_approval_rejected(self, sso_service, mock_db):
        """Existing pending approval that was rejected."""
        sso_service.auth_service.get_user_by_email = AsyncMock(return_value=None)
        sso_service.get_provider = lambda _id: _make_provider()
        pending = SimpleNamespace(status="rejected", is_expired=lambda: False)
        mock_db.execute.return_value.scalar_one_or_none.return_value = pending

        with patch("mcpgateway.services.sso_service.settings") as mock_settings, patch("mcpgateway.services.sso_service.select", return_value=MagicMock()):
            mock_settings.sso_require_admin_approval = True
            result = await sso_service.authenticate_or_create_user(
                {
                    "email": "new@test.com",
                    "full_name": "New User",
                    "provider": "github",
                }
            )

        assert result is None

    @pytest.mark.asyncio
    async def test_new_user_admin_approval_approved_but_expired(self, sso_service, mock_db):
        sso_service.auth_service.get_user_by_email = AsyncMock(return_value=None)
        sso_service.get_provider = lambda _id: _make_provider()
        pending = SimpleNamespace(status="approved", is_expired=lambda: True)
        mock_db.execute.return_value.scalar_one_or_none.return_value = pending

        with patch("mcpgateway.services.sso_service.settings") as mock_settings, patch("mcpgateway.services.sso_service.select", return_value=MagicMock()):
            mock_settings.sso_require_admin_approval = True
            result = await sso_service.authenticate_or_create_user(
                {
                    "email": "new@test.com",
                    "full_name": "New User",
                    "provider": "github",
                    "email_verified": True,
                }
            )

        assert result is None
        assert pending.status == "expired"

    @pytest.mark.asyncio
    async def test_new_user_admin_approval_status_expired_renews_request(self, sso_service, mock_db):
        sso_service.auth_service.get_user_by_email = AsyncMock(return_value=None)
        sso_service.get_provider = lambda _id: _make_provider()
        pending = SimpleNamespace(
            status="expired",
            is_expired=lambda: False,
            requested_at=None,
            expires_at=None,
            auth_provider="google",
            sso_metadata={"old": "value"},
            approved_by="admin@example.com",
            approved_at=object(),
            rejection_reason="reason",
            admin_notes="notes",
        )
        mock_db.execute.return_value.scalar_one_or_none.return_value = pending

        with patch("mcpgateway.services.sso_service.settings") as mock_settings, patch("mcpgateway.services.sso_service.select", return_value=MagicMock()):
            mock_settings.sso_require_admin_approval = True
            result = await sso_service.authenticate_or_create_user(
                {
                    "email": "new@test.com",
                    "full_name": "New User",
                    "provider": "github",
                    "email_verified": True,
                }
            )

        assert result is None
        assert pending.status == "pending"
        assert pending.auth_provider == "github"
        assert pending.approved_by is None
        assert pending.approved_at is None
        assert pending.rejection_reason is None
        assert pending.admin_notes is None

    @pytest.mark.asyncio
    async def test_new_user_admin_approval_completed_denied(self, sso_service, mock_db):
        sso_service.auth_service.get_user_by_email = AsyncMock(return_value=None)
        sso_service.get_provider = lambda _id: _make_provider()
        pending = SimpleNamespace(status="completed", is_expired=lambda: False)
        mock_db.execute.return_value.scalar_one_or_none.return_value = pending

        with patch("mcpgateway.services.sso_service.settings") as mock_settings, patch("mcpgateway.services.sso_service.select", return_value=MagicMock()):
            mock_settings.sso_require_admin_approval = True
            result = await sso_service.authenticate_or_create_user(
                {
                    "email": "new@test.com",
                    "full_name": "New User",
                    "provider": "github",
                }
            )

        assert result is None

    @pytest.mark.asyncio
    async def test_new_user_admin_approval_unknown_status_denied(self, sso_service, mock_db):
        sso_service.auth_service.get_user_by_email = AsyncMock(return_value=None)
        sso_service.get_provider = lambda _id: _make_provider()
        pending = SimpleNamespace(status="mystery", is_expired=lambda: False)
        mock_db.execute.return_value.scalar_one_or_none.return_value = pending

        with (
            patch("mcpgateway.services.sso_service.settings") as mock_settings,
            patch("mcpgateway.services.sso_service.select", return_value=MagicMock()),
            patch("mcpgateway.services.sso_service.logger") as mock_logger,
        ):
            mock_settings.sso_require_admin_approval = True
            result = await sso_service.authenticate_or_create_user(
                {
                    "email": "new@test.com",
                    "full_name": "New User",
                    "provider": "github",
                }
            )

        assert result is None
        mock_logger.warning.assert_called_once()

    @pytest.mark.asyncio
    async def test_new_user_admin_approval_approved(self, sso_service, mock_db):
        """Existing pending approval that was approved -> user gets created."""
        sso_service.auth_service.get_user_by_email = AsyncMock(return_value=None)
        sso_service.get_provider = lambda _id: _make_provider()
        new_user = SimpleNamespace(
            email="new@test.com",
            full_name="New User",
            auth_provider="github",
            is_admin=False,
            admin_origin=None,
        )
        sso_service.auth_service.create_user = AsyncMock(return_value=new_user)

        # First call returns "approved" pending, second call returns pending for completion
        approved = SimpleNamespace(status="approved", is_expired=lambda: False)
        mock_db.execute.return_value.scalar_one_or_none.side_effect = [approved, approved]

        with (
            patch("mcpgateway.services.sso_service.settings") as mock_settings,
            patch("mcpgateway.services.sso_service.select", return_value=MagicMock()),
            patch("mcpgateway.services.sso_service.create_jwt_token", new_callable=AsyncMock) as mock_jwt,
        ):
            mock_settings.sso_require_admin_approval = True
            mock_settings.sso_auto_admin_domains = []
            mock_settings.sso_github_admin_orgs = []
            mock_settings.sso_google_admin_domains = []
            mock_settings.sso_entra_admin_groups = []
            mock_jwt.return_value = "approved-jwt"
            result = await sso_service.authenticate_or_create_user(
                {
                    "email": "new@test.com",
                    "full_name": "New User",
                    "provider": "github",
                    "email_verified": True,
                }
            )

        assert result == "approved-jwt"

    @pytest.mark.asyncio
    async def test_new_user_create_fails(self, sso_service, mock_db):
        """create_user returns None -> returns None."""
        sso_service.auth_service.get_user_by_email = AsyncMock(return_value=None)
        sso_service.auth_service.create_user = AsyncMock(return_value=None)
        sso_service.get_provider = lambda _id: _make_provider()

        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_require_admin_approval = False
            mock_settings.sso_auto_admin_domains = []
            mock_settings.sso_github_admin_orgs = []
            mock_settings.sso_google_admin_domains = []
            mock_settings.sso_entra_admin_groups = []
            result = await sso_service.authenticate_or_create_user(
                {
                    "email": "new@test.com",
                    "full_name": "New User",
                    "provider": "github",
                    "email_verified": True,
                }
            )

        assert result is None

    @pytest.mark.asyncio
    async def test_existing_user_with_role_sync(self, sso_service, mock_db):
        """Existing user with provider metadata sync_roles=True triggers role sync."""
        existing_user = SimpleNamespace(
            email="user@test.com",
            full_name="Name",
            auth_provider="github",
            email_verified=True,
            last_login=None,
            is_admin=False,
            admin_origin=None,
        )
        sso_service.auth_service.get_user_by_email = AsyncMock(return_value=existing_user)
        sso_service.get_provider = lambda _id: _make_provider(provider_metadata={"sync_roles": True, "role_mappings": {}})
        sso_service._map_groups_to_roles = AsyncMock(return_value=[])
        sso_service._sync_user_roles = AsyncMock()

        with patch("mcpgateway.services.sso_service.settings") as mock_settings, patch("mcpgateway.services.sso_service.create_jwt_token", new_callable=AsyncMock) as mock_jwt:
            mock_settings.sso_auto_admin_domains = []
            mock_settings.sso_github_admin_orgs = []
            mock_settings.sso_google_admin_domains = []
            mock_settings.sso_entra_admin_groups = []
            mock_jwt.return_value = "jwt"
            result = await sso_service.authenticate_or_create_user(
                {
                    "email": "user@test.com",
                    "full_name": "Name",
                    "provider": "github",
                    "email_verified": True,
                    "groups": ["dev"],
                }
            )

        sso_service._map_groups_to_roles.assert_called_once()
        sso_service._sync_user_roles.assert_called_once()


# ---------------------------------------------------------------------------
# _apply_team_mapping tests
# ---------------------------------------------------------------------------


class TestApplyTeamMapping:
    """Tests for _apply_team_mapping and _resolve_team_mapping_target."""

    @pytest.mark.asyncio
    async def test_apply_team_mapping_assigns_matching_group(self, sso_service):
        provider = _make_provider(team_mapping={"Engineering": {"team_id": "team-1", "role": "owner"}})
        team_service = MagicMock()
        team_service.add_member_to_team = AsyncMock()

        with patch("mcpgateway.services.team_management_service.TeamManagementService", return_value=team_service):
            await sso_service._apply_team_mapping(
                user_email="user@test.com",
                user_info={"groups": ["engineering"]},
                provider=provider,
            )

        team_service.add_member_to_team.assert_awaited_once_with(
            team_id="team-1",
            user_email="user@test.com",
            role="owner",
            invited_by="user@test.com",
            grant_source="sso",
        )

    def test_resolve_team_mapping_target_string_and_invalid(self, sso_service):
        team_id, role = sso_service._resolve_team_mapping_target("team-raw")
        assert team_id == "team-raw"
        assert role == "member"

        team_id, role = sso_service._resolve_team_mapping_target(123)
        assert team_id is None
        assert role == "member"

    @pytest.mark.asyncio
    async def test_apply_team_mapping_returns_early_for_missing_provider_or_groups(self, sso_service):
        await sso_service._apply_team_mapping("user@test.com", {"groups": ["engineering"]}, provider=None)
        await sso_service._apply_team_mapping("user@test.com", {"groups": {"not": "a-list"}}, provider=_make_provider(team_mapping={"engineering": "team-1"}))

    @pytest.mark.asyncio
    async def test_apply_team_mapping_supports_string_group_and_skips_non_string_mapping_key(self, sso_service):
        provider = _make_provider(team_mapping={1: "team-ignored", "engineering": "team-1"})
        team_service = MagicMock()
        team_service.add_member_to_team = AsyncMock()

        with patch("mcpgateway.services.team_management_service.TeamManagementService", return_value=team_service):
            await sso_service._apply_team_mapping("user@test.com", {"groups": "engineering"}, provider=provider)

        team_service.add_member_to_team.assert_awaited_once_with(
            team_id="team-1",
            user_email="user@test.com",
            role="member",
            invited_by="user@test.com",
            grant_source="sso",
        )

    @pytest.mark.asyncio
    async def test_apply_team_mapping_invalid_target_logs_warning(self, sso_service):
        provider = _make_provider(team_mapping={"engineering": {}})
        team_service = MagicMock()
        team_service.add_member_to_team = AsyncMock()

        with patch("mcpgateway.services.team_management_service.TeamManagementService", return_value=team_service):
            await sso_service._apply_team_mapping("user@test.com", {"groups": ["engineering"]}, provider=provider)

        team_service.add_member_to_team.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_apply_team_mapping_skips_unmatched_group(self, sso_service):
        provider = _make_provider(team_mapping={"sales": "team-9"})
        team_service = MagicMock()
        team_service.add_member_to_team = AsyncMock()

        with patch("mcpgateway.services.team_management_service.TeamManagementService", return_value=team_service):
            await sso_service._apply_team_mapping("user@test.com", {"groups": ["engineering"]}, provider=provider)

        team_service.add_member_to_team.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_apply_team_mapping_removes_stale_sso_memberships(self, sso_service):
        """Test that SSO memberships are removed when groups are revoked."""
        provider = _make_provider(team_mapping={"engineering": "team-1"})

        # Mock existing SSO membership in team-2 (user was in "finance" group before)
        mock_stale_membership = MagicMock()
        mock_stale_membership.team_id = "team-2"
        mock_stale_membership.user_email = "user@test.com"

        # Mock DB query result
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_stale_membership]
        sso_service.db.execute = MagicMock(return_value=mock_result)

        team_service = MagicMock()
        team_service.add_member_to_team = AsyncMock()
        team_service.remove_member_from_team = AsyncMock()

        with patch("mcpgateway.services.team_management_service.TeamManagementService", return_value=team_service):
            await sso_service._apply_team_mapping(
                user_email="user@test.com",
                user_info={"groups": ["engineering"]},  # Only in engineering now
                provider=provider,
            )

        # Should remove stale membership from team-2
        team_service.remove_member_from_team.assert_awaited_once_with(
            team_id="team-2",
            user_email="user@test.com",
        )

        # Should add to team-1
        team_service.add_member_to_team.assert_awaited_once_with(
            team_id="team-1",
            user_email="user@test.com",
            role="member",
            invited_by="user@test.com",
            grant_source="sso",
        )

    @pytest.mark.asyncio
    async def test_apply_team_mapping_preserves_current_sso_memberships(self, sso_service):
        """Test that current SSO memberships are preserved."""
        provider = _make_provider(team_mapping={"engineering": "team-1", "finance": "team-2"})

        # Mock existing SSO memberships (user is in both teams)
        mock_membership1 = MagicMock()
        mock_membership1.team_id = "team-1"
        mock_membership2 = MagicMock()
        mock_membership2.team_id = "team-2"

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_membership1, mock_membership2]
        sso_service.db.execute = MagicMock(return_value=mock_result)

        team_service = MagicMock()
        team_service.add_member_to_team = AsyncMock()
        team_service.remove_member_from_team = AsyncMock()

        with patch("mcpgateway.services.team_management_service.TeamManagementService", return_value=team_service):
            await sso_service._apply_team_mapping(
                user_email="user@test.com",
                user_info={"groups": ["engineering", "finance"]},  # Still in both
                provider=provider,
            )

        # Should NOT remove any memberships
        team_service.remove_member_from_team.assert_not_awaited()

        # Should attempt to add (will hit MemberAlreadyExistsError in real scenario)
        assert team_service.add_member_to_team.await_count == 2

    @pytest.mark.asyncio
    async def test_apply_team_mapping_removes_all_when_groups_empty(self, sso_service):
        """Test that all SSO memberships are removed when user has no groups."""
        provider = _make_provider(team_mapping={"engineering": "team-1"})

        # Mock existing SSO memberships
        mock_membership = MagicMock()
        mock_membership.team_id = "team-1"

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_membership]
        sso_service.db.execute = MagicMock(return_value=mock_result)

        team_service = MagicMock()
        team_service.add_member_to_team = AsyncMock()
        team_service.remove_member_from_team = AsyncMock()

        with patch("mcpgateway.services.team_management_service.TeamManagementService", return_value=team_service):
            await sso_service._apply_team_mapping(
                user_email="user@test.com",
                user_info={"groups": []},  # No groups
                provider=provider,
            )

        # Should remove the membership
        team_service.remove_member_from_team.assert_awaited_once_with(
            team_id="team-1",
            user_email="user@test.com",
        )

        # Should NOT add any memberships
        team_service.add_member_to_team.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_apply_team_mapping_handles_removal_errors_gracefully(self, sso_service):
        """Test that removal errors are logged but don't stop processing."""
        provider = _make_provider(team_mapping={"engineering": "team-1"})

        # Mock existing SSO membership
        mock_membership = MagicMock()
        mock_membership.team_id = "team-2"

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_membership]
        sso_service.db.execute = MagicMock(return_value=mock_result)

        team_service = MagicMock()
        team_service.add_member_to_team = AsyncMock()
        team_service.remove_member_from_team = AsyncMock(side_effect=Exception("Removal failed"))

        with patch("mcpgateway.services.team_management_service.TeamManagementService", return_value=team_service):
            # Should not raise exception
            await sso_service._apply_team_mapping(
                user_email="user@test.com",
                user_info={"groups": ["engineering"]},
                provider=provider,
            )

        # Should still attempt to add new membership despite removal error
        team_service.add_member_to_team.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_apply_team_mapping_queries_sso_memberships_correctly(self, sso_service):
        """Test that the DB query filters by grant_source='sso' and is_active=True."""
        provider = _make_provider(team_mapping={"engineering": "team-1"})

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        sso_service.db.execute = MagicMock(return_value=mock_result)

        team_service = MagicMock()
        team_service.add_member_to_team = AsyncMock()

        with patch("mcpgateway.services.team_management_service.TeamManagementService", return_value=team_service):
            await sso_service._apply_team_mapping(
                user_email="user@test.com",
                user_info={"groups": ["engineering"]},
                provider=provider,
            )

        # Verify DB query was called
        sso_service.db.execute.assert_called_once()

        # Verify the query filters by user_email, grant_source="sso", and is_active=True
        call_args = sso_service.db.execute.call_args
        stmt = call_args[0][0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "user@test.com" in compiled
        assert "sso" in compiled
        assert "is_active" in compiled

    @pytest.mark.asyncio
    async def test_apply_team_mapping_skips_empty_mapping_keys(self, sso_service):
        """Test that whitespace-only mapping keys are skipped during desired-team computation."""
        provider = _make_provider(team_mapping={"  ": "team-1", "engineering": "team-2"})

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        sso_service.db.execute = MagicMock(return_value=mock_result)

        team_service = MagicMock()
        team_service.add_member_to_team = AsyncMock()

        with patch("mcpgateway.services.team_management_service.TeamManagementService", return_value=team_service):
            await sso_service._apply_team_mapping(
                user_email="user@test.com",
                user_info={"groups": ["engineering"]},
                provider=provider,
            )

        # Only the valid "engineering" key should produce an add call
        team_service.add_member_to_team.assert_awaited_once_with(
            team_id="team-2",
            user_email="user@test.com",
            role="member",
            invited_by="user@test.com",
            grant_source="sso",
        )

    @pytest.mark.asyncio
    async def test_apply_team_mapping_handles_expected_errors(self, sso_service):
        # First-Party
        from mcpgateway.services.team_management_service import MemberAlreadyExistsError, TeamManagementError

        provider = _make_provider(
            team_mapping={
                "engineering": "team-1",
                "platform": "team-2",
                "ops": "team-3",
            }
        )
        team_service = MagicMock()
        team_service.add_member_to_team = AsyncMock(
            side_effect=[
                MemberAlreadyExistsError("already-member"),
                TeamManagementError("team-error"),
                RuntimeError("unexpected-error"),
            ]
        )

        with patch("mcpgateway.services.team_management_service.TeamManagementService", return_value=team_service):
            await sso_service._apply_team_mapping(
                "user@test.com",
                {"groups": ["engineering", "platform", "ops", "other"]},
                provider=provider,
            )

        assert team_service.add_member_to_team.await_count == 3

    @pytest.mark.asyncio
    async def test_entra_admin_group_checked_before_role_mappings(self, sso_service):
        """Entra admin groups produce platform_admin even without role_mappings."""
        provider = _make_provider(id="entra", provider_metadata={})

        with patch("mcpgateway.services.sso_service.settings") as mock_settings, patch("mcpgateway.services.role_service.RoleService") as MockRoleService:
            mock_settings.sso_entra_admin_groups = ["admin-grp"]
            mock_settings.sso_entra_default_role = None
            mock_settings.sso_entra_role_mappings = {}
            mock_settings.default_admin_role = "platform_admin"
            role_svc = AsyncMock()
            MockRoleService.return_value = role_svc
            result = await sso_service._map_groups_to_roles("user@test.com", ["admin-grp", "other"], provider)


class TestADFSProvider:
    """Tests for ADFS-specific functionality."""

    # All ADFS _get_user_info tests must include "aud" matching the provider's
    # client_id ("cid") and a future "exp" so that the fallback claim validation
    # (aud/iss/exp/nonce) in _get_user_info passes.

    @pytest.mark.asyncio
    async def test_get_user_info_adfs_with_id_token(self, sso_service):
        """ADFS provider extracts user info from id_token."""
        provider = _make_provider(id="adfs", name="adfs", provider_type="oidc")

        id_token_claims = {
            "email": "user@adfs.com",
            "upn": "user@adfs.com",
            "name": "ADFS User",
            "sub": "adfs-sub-123",
            "oid": "adfs-oid-456",
            "groups": ["group1", "group2"],
            "aud": "cid",
            "exp": 9999999999,
        }

        sso_service._decode_jwt_claims = MagicMock(return_value=id_token_claims)

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock):
            token_data = {"id_token": "fake.jwt.token", "access_token": "access123"}
            result = await sso_service._get_user_info(provider, "access123", token_data=token_data)

        assert result["email"] == "user@adfs.com"
        assert result["full_name"] == "ADFS User"
        assert "group1" in result["groups"]

    @pytest.mark.asyncio
    async def test_get_user_info_adfs_missing_id_token(self, sso_service):
        """ADFS provider raises error when id_token is missing."""
        from mcpgateway.services.sso_service import SSOProviderConfigError

        provider = _make_provider(id="adfs", name="adfs", provider_type="oidc")
        token_data = {"access_token": "access123"}  # Missing id_token

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock):
            with pytest.raises(SSOProviderConfigError):
                await sso_service._get_user_info(provider, "access123", token_data=token_data)

    @pytest.mark.asyncio
    async def test_get_user_info_adfs_failed_decode(self, sso_service):
        """ADFS provider returns None when id_token decode fails."""
        provider = _make_provider(id="adfs", name="adfs", provider_type="oidc")

        sso_service._decode_jwt_claims = MagicMock(return_value=None)

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock):
            token_data = {"id_token": "invalid.jwt.token", "access_token": "access123"}
            result = await sso_service._get_user_info(provider, "access123", token_data=token_data)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_user_info_adfs_entra_federation_detected(self, sso_service):
        """ADFS federating to Entra ID is detected via issuer claim."""
        provider = _make_provider(id="adfs", name="adfs", provider_type="oidc")

        id_token_claims = {
            "email": "user@company.com",
            "preferred_username": "user@company.com",
            "name": "Federated User",
            "sub": "entra-sub-123",
            "iss": "https://login.microsoftonline.com/tenant-id/v2.0",
            "aud": "cid",
            "exp": 9999999999,
        }

        sso_service._decode_jwt_claims = MagicMock(return_value=id_token_claims)

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock):
            token_data = {"id_token": "fake.jwt.token", "access_token": "access123"}
            result = await sso_service._get_user_info(provider, "access123", token_data=token_data)

        assert result["email"] == "user@company.com"

    @pytest.mark.asyncio
    async def test_get_user_info_adfs_windows_net_issuer(self, sso_service):
        """ADFS with sts.windows.net issuer is also detected as Entra federation."""
        provider = _make_provider(id="adfs", name="adfs", provider_type="oidc")

        id_token_claims = {
            "email": "user@company.com",
            "name": "User",
            "sub": "sub-123",
            "iss": "https://sts.windows.net/tenant-id/",
            "aud": "cid",
            "exp": 9999999999,
        }

        sso_service._decode_jwt_claims = MagicMock(return_value=id_token_claims)

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock):
            token_data = {"id_token": "fake.jwt.token", "access_token": "access123"}
            result = await sso_service._get_user_info(provider, "access123", token_data=token_data)

        assert result is not None
        assert result.get("email") == "user@company.com"

    @pytest.mark.asyncio
    async def test_get_user_info_adfs_rejects_wrong_audience(self, sso_service):
        """ADFS fallback rejects id_token with wrong audience."""
        provider = _make_provider(id="adfs", name="adfs", provider_type="oidc")

        id_token_claims = {
            "email": "user@adfs.com",
            "sub": "adfs-sub-123",
            "aud": "wrong-client-id",
            "exp": 9999999999,
        }

        sso_service._decode_jwt_claims = MagicMock(return_value=id_token_claims)

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock):
            token_data = {"id_token": "fake.jwt.token", "access_token": "access123"}
            result = await sso_service._get_user_info(provider, "access123", token_data=token_data)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_user_info_adfs_rejects_expired_token(self, sso_service):
        """ADFS fallback rejects expired id_token."""
        provider = _make_provider(id="adfs", name="adfs", provider_type="oidc")

        id_token_claims = {
            "email": "user@adfs.com",
            "sub": "adfs-sub-123",
            "aud": "cid",
            "exp": 1000000000,  # expired
        }

        sso_service._decode_jwt_claims = MagicMock(return_value=id_token_claims)

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock):
            token_data = {"id_token": "fake.jwt.token", "access_token": "access123"}
            result = await sso_service._get_user_info(provider, "access123", token_data=token_data)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_user_info_adfs_rejects_missing_exp(self, sso_service):
        """ADFS fallback rejects id_token with missing exp claim."""
        provider = _make_provider(id="adfs", name="adfs", provider_type="oidc")

        id_token_claims = {
            "email": "user@adfs.com",
            "sub": "adfs-sub-123",
            "aud": "cid",
            # no exp claim
        }

        sso_service._decode_jwt_claims = MagicMock(return_value=id_token_claims)

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock):
            token_data = {"id_token": "fake.jwt.token", "access_token": "access123"}
            result = await sso_service._get_user_info(provider, "access123", token_data=token_data)

        assert result is None  # rejected due to missing exp

    @pytest.mark.asyncio
    async def test_get_user_info_adfs_rejects_issuer_mismatch(self, sso_service):
        """ADFS fallback rejects id_token with mismatched issuer."""
        provider = _make_provider(id="adfs", name="adfs", provider_type="oidc", issuer="https://adfs.example.com/adfs")

        id_token_claims = {
            "email": "user@adfs.com",
            "sub": "adfs-sub-123",
            "aud": "cid",
            "exp": 9999999999,
            "iss": "https://evil.example.com",
        }

        sso_service._decode_jwt_claims = MagicMock(return_value=id_token_claims)

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock):
            token_data = {"id_token": "fake.jwt.token", "access_token": "access123"}
            result = await sso_service._get_user_info(provider, "access123", token_data=token_data)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_user_info_adfs_rejects_nonce_mismatch(self, sso_service):
        """ADFS fallback rejects id_token with mismatched nonce."""
        provider = _make_provider(id="adfs", name="adfs", provider_type="oidc")

        id_token_claims = {
            "email": "user@adfs.com",
            "sub": "adfs-sub-123",
            "aud": "cid",
            "exp": 9999999999,
            "nonce": "wrong-nonce",
        }

        sso_service._decode_jwt_claims = MagicMock(return_value=id_token_claims)

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock):
            token_data = {"id_token": "fake.jwt.token", "access_token": "access123"}
            result = await sso_service._get_user_info(provider, "access123", token_data=token_data, expected_nonce="correct-nonce")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_user_info_adfs_accepts_list_audience(self, sso_service):
        """ADFS fallback accepts id_token with list-valued aud containing client_id."""
        provider = _make_provider(id="adfs", name="adfs", provider_type="oidc")

        id_token_claims = {
            "email": "user@adfs.com",
            "name": "ADFS User",
            "sub": "adfs-sub-123",
            "aud": ["other-client", "cid"],
            "exp": 9999999999,
        }

        sso_service._decode_jwt_claims = MagicMock(return_value=id_token_claims)

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock):
            token_data = {"id_token": "fake.jwt.token", "access_token": "access123"}
            result = await sso_service._get_user_info(provider, "access123", token_data=token_data)

        assert result is not None
        assert result["email"] == "user@adfs.com"

    @pytest.mark.asyncio
    async def test_get_user_info_adfs_uses_verified_claims_when_available(self, sso_service):
        """ADFS prefers verified id_token claims over unverified decode."""
        provider = _make_provider(id="adfs", name="adfs", provider_type="oidc")

        verified_claims = {
            "email": "verified@adfs.com",
            "name": "Verified User",
            "sub": "verified-sub",
        }

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock):
            token_data = {"id_token": "fake.jwt.token", "access_token": "access123", "_verified_id_token_claims": verified_claims}
            result = await sso_service._get_user_info(provider, "access123", token_data=token_data)

        assert result is not None
        assert result["email"] == "verified@adfs.com"
        assert result["full_name"] == "Verified User"

    @pytest.mark.asyncio
    async def test_get_user_info_adfs_verification_fallback_warning(self, sso_service):
        """ADFS logs warning when OIDC verification fails and falls back to decode."""
        provider = _make_provider(id="adfs", name="adfs", provider_type="oidc")

        id_token_claims = {
            "email": "user@adfs.com",
            "name": "ADFS User",
            "sub": "adfs-sub-123",
            "aud": "cid",
            "exp": 9999999999,
            "nonce": "test-nonce",
        }

        sso_service._decode_jwt_claims = MagicMock(return_value=id_token_claims)

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock):
            # Pass expected_nonce to trigger the OIDC verification path (which will fail on the fake token)
            # and then fall through to the ADFS decode fallback
            with patch.object(sso_service, "_verify_oidc_id_token", new_callable=AsyncMock, return_value=None):
                token_data = {"id_token": "fake.jwt.token", "access_token": "access123"}
                result = await sso_service._get_user_info(provider, "access123", token_data=token_data, expected_nonce="test-nonce")

        assert result is not None
        assert result["email"] == "user@adfs.com"
