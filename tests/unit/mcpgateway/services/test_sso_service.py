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
    async def test_update_provider(self, sso_service, mock_db):
        existing = _make_provider()
        sso_service.get_provider = lambda _id: existing
        result = await sso_service.update_provider("github", {"client_id": "new-cid", "client_secret": "new-sec"})
        assert result.client_id == "new-cid"
        assert result.client_secret_encrypted == "encrypted"

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

    def test_get_authorization_url_not_found(self, sso_service):
        sso_service.get_provider = lambda _id: None
        url = sso_service.get_authorization_url("missing", "https://app/callback")
        assert url is None

    def test_get_authorization_url_disabled(self, sso_service):
        provider = _make_provider(is_enabled=False)
        sso_service.get_provider = lambda _id: provider
        url = sso_service.get_authorization_url("disabled", "https://app/callback")
        assert url is None


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

        async def _user_info(p, access, token_data=None):
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

        async def _user_info(p, access, token_data=None):
            return {"email": "user@example.com", "provider": "github"}

        sso_service._exchange_code_for_tokens = _exchange
        sso_service._get_user_info = _user_info

        result = await sso_service.handle_oauth_callback_with_tokens("github", "code", "test-state")
        assert result is not None
        user_info, token_data = result
        assert user_info["email"] == "user@example.com"
        assert token_data["id_token"] == "id_tok"

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
    async def test_handle_oauth_callback_user_info_fails(self, sso_service, mock_db):
        auth_session = _make_auth_session()
        mock_db.execute.return_value.scalar_one_or_none.return_value = auth_session

        async def _exchange(p, sess, c):
            return {"access_token": "tok"}

        async def _user_info(p, access, token_data=None):
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
            result = await sso_service._exchange_code_for_tokens(provider, auth_session, "bad-code")

        assert result is None


# ---------------------------------------------------------------------------
# User info tests
# ---------------------------------------------------------------------------


class TestGetUserInfo:
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

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock) as mock_get_client, \
             patch("mcpgateway.services.sso_service.settings") as mock_settings:
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

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock) as mock_get_client, \
             patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_get_client.return_value = mock_client
            mock_settings.sso_github_admin_orgs = ["my-org"]
            result = await sso_service._get_user_info(provider, "access_token")

        assert result is not None
        # organizations should be empty list on failure
        assert "organizations" in result

    @pytest.mark.asyncio
    async def test_get_user_info_entra_with_id_token(self, sso_service):
        """Entra ID provider extracts groups/roles from id_token."""
        import base64
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

        token_data = {"access_token": "at", "id_token": fake_id_token}

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock) as mock_get_client, \
             patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_get_client.return_value = mock_client
            mock_settings.sso_github_admin_orgs = []
            result = await sso_service._get_user_info(provider, "at", token_data)

        assert result is not None
        assert result["provider"] == "entra"
        assert "group-id-1" in result["groups"]
        assert "App.Admin" in result["groups"]

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
        """GitHub orgs fetch raises exception → orgs set to empty list."""
        user_response = MagicMock()
        user_response.status_code = 200
        user_response.json.return_value = {"login": "testuser", "email": "test@github.com"}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[user_response, RuntimeError("network")])

        provider = _make_provider()

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock) as mock_get_client, \
             patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_get_client.return_value = mock_client
            mock_settings.sso_github_admin_orgs = ["my-org"]
            result = await sso_service._get_user_info(provider, "access_token")

        assert result is not None
        assert result.get("organizations", []) == []

    @pytest.mark.asyncio
    async def test_get_user_info_entra_group_overage(self, sso_service):
        """Entra ID group overage detection (>200 groups)."""
        import base64
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
        token_data = {"access_token": "at", "id_token": fake_id_token}

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock) as mock_get_client, \
             patch("mcpgateway.services.sso_service.settings") as mock_settings:
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
        import base64
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
        token_data = {"access_token": "at", "id_token": fake_id_token}

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock) as mock_get_client, \
             patch("mcpgateway.services.sso_service.settings") as mock_settings:
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
        import base64
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
        token_data = {"access_token": "at", "id_token": fake_id_token}

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock) as mock_get_client, \
             patch("mcpgateway.services.sso_service.settings") as mock_settings:
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
    async def test_fetch_entra_groups_from_graph_api_handles_401(self, sso_service):
        """Graph API failures should degrade safely and return None."""
        graph_response = MagicMock()
        graph_response.status_code = 401

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=graph_response)

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock) as mock_get_client, \
             patch("mcpgateway.services.sso_service.settings") as mock_settings:
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

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock) as mock_get_client, \
             patch("mcpgateway.services.sso_service.settings") as mock_settings:
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

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock) as mock_get_client, \
             patch("mcpgateway.services.sso_service.settings") as mock_settings:
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

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock) as mock_get_client, \
             patch("mcpgateway.services.sso_service.settings") as mock_settings:
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

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock) as mock_get_client, \
             patch("mcpgateway.services.sso_service.settings") as mock_settings:
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

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock) as mock_get_client, \
             patch("mcpgateway.services.sso_service.settings") as mock_settings:
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

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock) as mock_get_client, \
             patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_get_client.return_value = mock_client
            mock_settings.sso_entra_graph_api_enabled = True
            mock_settings.sso_entra_graph_api_timeout = 10
            mock_settings.sso_entra_graph_api_max_groups = 2
            groups = await sso_service._fetch_entra_groups_from_graph_api("at", "user@contoso.com")

        assert groups == ["g1", "g2"]

    @pytest.mark.asyncio
    async def test_fetch_entra_groups_from_graph_api_disabled(self, sso_service):
        """Disabled Graph fallback should skip network calls."""
        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock) as mock_get_client, \
             patch("mcpgateway.services.sso_service.settings") as mock_settings:
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

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock) as mock_get_client, \
             patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_get_client.return_value = mock_client
            mock_settings.sso_entra_graph_api_enabled = True
            mock_settings.sso_entra_graph_api_timeout = 1
            mock_settings.sso_entra_graph_api_max_groups = 0
            groups = await sso_service._fetch_entra_groups_from_graph_api("at", "user@contoso.com")

        assert groups is None

    @pytest.mark.asyncio
    async def test_fetch_entra_groups_from_graph_api_respects_provider_metadata_override(self, sso_service):
        """Provider metadata should override global Graph fallback defaults."""
        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock) as mock_get_client, \
             patch("mcpgateway.services.sso_service.settings") as mock_settings:
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
        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock) as mock_get_client, \
             patch("mcpgateway.services.sso_service.settings") as mock_settings:
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

    @pytest.mark.asyncio
    async def test_get_user_info_entra_group_overage_graph_fallback_failure(self, sso_service):
        """Overage with failed Graph fallback should continue with safe defaults."""
        import base64
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
        token_data = {"access_token": "at", "id_token": fake_id_token}

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock) as mock_get_client, \
             patch("mcpgateway.services.sso_service.settings") as mock_settings:
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
        import base64
        import orjson

        user_response = MagicMock()
        user_response.status_code = 200
        user_response.json.return_value = {"email": "user@kc.com", "name": "KC User", "preferred_username": "kcuser", "sub": "kc-123"}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=user_response)

        provider = _make_provider(
            id="keycloak", name="keycloak", provider_type="oidc",
            provider_metadata={"map_realm_roles": True, "map_client_roles": True},
        )

        payload = orjson.dumps({"realm_access": {"roles": ["admin"]}, "resource_access": {"app": {"roles": ["edit"]}}, "groups": ["/team"]})
        payload_b64 = base64.urlsafe_b64encode(payload).decode().rstrip("=")
        fake_id_token = f"eyJhbGciOiJSUzI1NiJ9.{payload_b64}.sig"
        token_data = {"access_token": "at", "id_token": fake_id_token}

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock) as mock_get_client, \
             patch("mcpgateway.services.sso_service.settings") as mock_settings:
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
        import base64
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
        token_data = {"access_token": "at", "id_token": fake_id_token}

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock) as mock_get_client, \
             patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_get_client.return_value = mock_client
            mock_settings.sso_github_admin_orgs = []
            result = await sso_service._get_user_info(provider, "at", token_data)

        assert result is not None
        assert result["provider"] == "keycloak"
        assert result["email"] == "user@kc.com"
        assert "admin" in result["groups"]
        assert "/team" in result["groups"]


# ---------------------------------------------------------------------------
# Normalization tests
# ---------------------------------------------------------------------------


class TestNormalization:
    def test_normalize_github(self, sso_service):
        provider = _make_provider(id="github")
        result = sso_service._normalize_user_info(provider, {
            "login": "ghuser", "email": "gh@test.com", "name": "GH User",
            "avatar_url": "https://avatar", "id": 123, "organizations": ["org1"],
        })
        assert result["provider"] == "github"
        assert result["username"] == "ghuser"
        assert result["organizations"] == ["org1"]

    def test_normalize_google(self, sso_service):
        provider = _make_provider(id="google", name="google")
        result = sso_service._normalize_user_info(provider, {
            "email": "user@gmail.com", "name": "Google User",
            "picture": "https://pic", "sub": "google-123",
        })
        assert result["provider"] == "google"
        assert result["username"] == "user"
        assert result["provider_id"] == "google-123"

    def test_normalize_entra(self, sso_service):
        provider = _make_provider(id="entra", name="entra", provider_metadata={})
        result = sso_service._normalize_user_info(provider, {
            "email": "user@contoso.com", "name": "Entra User",
            "sub": "entra-oid", "groups": ["grp1"], "roles": ["role1"],
        })
        assert result["provider"] == "entra"
        assert "grp1" in result["groups"]
        assert "role1" in result["groups"]

    def test_normalize_generic(self, sso_service):
        provider = _make_provider(id="custom", name="custom")
        result = sso_service._normalize_user_info(provider, {
            "email": "user@custom.com", "name": "Custom User", "sub": "c123",
        })
        assert result["provider"] == "custom"
        assert result["email"] == "user@custom.com"

    def test_normalize_okta(self, sso_service):
        provider = _make_provider(id="okta", name="okta")
        result = sso_service._normalize_user_info(provider, {
            "email": "user@okta.com", "name": "Okta User",
            "preferred_username": "oktauser", "sub": "okta-123",
        })
        assert result["provider"] == "okta"
        assert result["username"] == "oktauser"

    def test_normalize_keycloak(self, sso_service):
        provider = _make_provider(
            id="keycloak", name="keycloak",
            provider_metadata={"map_realm_roles": True, "map_client_roles": True},
        )
        result = sso_service._normalize_user_info(provider, {
            "email": "user@kc.com", "name": "KC User",
            "preferred_username": "kcuser", "sub": "kc-123",
            "realm_access": {"roles": ["admin", "user"]},
            "resource_access": {"my-app": {"roles": ["editor"]}},
            "groups": ["/team-a"],
        })
        assert result["provider"] == "keycloak"
        assert "admin" in result["groups"]
        assert "my-app:editor" in result["groups"]
        assert "/team-a" in result["groups"]


# ---------------------------------------------------------------------------
# JWT decode tests
# ---------------------------------------------------------------------------


class TestDecodeJWTClaims:
    def test_valid_jwt(self, sso_service):
        import base64
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
            result = sso_service._should_user_be_admin(
                "user@github.com", {"organizations": ["my-org"]}, provider
            )
        assert result is True

    def test_admin_by_entra_group(self, sso_service):
        provider = _make_provider(id="entra")
        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_auto_admin_domains = []
            mock_settings.sso_github_admin_orgs = []
            mock_settings.sso_google_admin_domains = []
            mock_settings.sso_entra_admin_groups = ["admin-group-id"]
            result = sso_service._should_user_be_admin(
                "user@contoso.com", {"groups": ["admin-group-id"]}, provider
            )
        assert result is True

    def test_admin_by_google_domain(self, sso_service):
        provider = _make_provider(id="google")
        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_auto_admin_domains = []
            mock_settings.sso_github_admin_orgs = []
            mock_settings.sso_google_admin_domains = ["google-admin.com"]
            mock_settings.sso_entra_admin_groups = []
            result = sso_service._should_user_be_admin(
                "user@google-admin.com", {}, provider
            )
        assert result is True


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
        with patch("mcpgateway.services.sso_service.settings") as mock_settings, \
             patch("mcpgateway.services.role_service.RoleService") as mock_role_svc:
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

        with patch("mcpgateway.services.sso_service.settings") as mock_settings, \
             patch("mcpgateway.services.role_service.RoleService") as MockRoleService:
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

        with patch("mcpgateway.services.sso_service.settings") as mock_settings, \
             patch("mcpgateway.services.role_service.RoleService") as MockRoleService:
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

        with patch("mcpgateway.services.sso_service.settings") as mock_settings, \
             patch("mcpgateway.services.role_service.RoleService") as MockRoleService:
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

        with patch("mcpgateway.services.sso_service.settings") as mock_settings, \
             patch("mcpgateway.services.role_service.RoleService") as MockRoleService, \
             patch("mcpgateway.services.personal_team_service.PersonalTeamService") as MockPersonalTeamService:
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

        with patch("mcpgateway.services.sso_service.settings") as mock_settings, \
             patch("mcpgateway.services.role_service.RoleService") as MockRoleService, \
             patch("mcpgateway.services.personal_team_service.PersonalTeamService") as MockPersonalTeamService:
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

        with patch("mcpgateway.services.sso_service.settings") as mock_settings, \
             patch("mcpgateway.services.role_service.RoleService") as MockRoleService, \
             patch("mcpgateway.services.personal_team_service.PersonalTeamService") as MockPersonalTeamService:
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

        with patch("mcpgateway.services.sso_service.settings") as mock_settings, \
             patch("mcpgateway.services.role_service.RoleService") as MockRoleService, \
             patch("mcpgateway.services.personal_team_service.PersonalTeamService") as MockPersonalTeamService:
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

        with patch("mcpgateway.services.sso_service.settings") as mock_settings, \
             patch("mcpgateway.services.role_service.RoleService") as MockRoleService, \
             patch("mcpgateway.services.personal_team_service.PersonalTeamService") as MockPersonalTeamService:
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
# authenticate_or_create_user tests
# ---------------------------------------------------------------------------


class TestAuthenticateOrCreateUser:
    @pytest.mark.asyncio
    async def test_no_email_returns_none(self, sso_service):
        result = await sso_service.authenticate_or_create_user({"full_name": "No Email"})
        assert result is None

    @pytest.mark.asyncio
    async def test_existing_user(self, sso_service, mock_db):
        existing_user = SimpleNamespace(
            email="user@test.com", full_name="Old Name", auth_provider="local",
            email_verified=False, last_login=None, is_admin=False, admin_origin=None,
        )
        sso_service.auth_service.get_user_by_email = AsyncMock(return_value=existing_user)
        sso_service.get_provider = lambda _id: _make_provider()

        with patch("mcpgateway.services.sso_service.settings") as mock_settings, \
             patch("mcpgateway.services.sso_service.create_jwt_token", new_callable=AsyncMock) as mock_jwt:
            mock_settings.sso_auto_admin_domains = []
            mock_settings.sso_github_admin_orgs = []
            mock_settings.sso_google_admin_domains = []
            mock_settings.sso_entra_admin_groups = []
            mock_settings.sso_entra_sync_roles_on_login = False
            mock_jwt.return_value = "jwt-token"
            result = await sso_service.authenticate_or_create_user({
                "email": "user@test.com", "full_name": "New Name", "provider": "github",
            })

        assert result == "jwt-token"
        assert existing_user.full_name == "New Name"
        assert existing_user.auth_provider == "github"

    @pytest.mark.asyncio
    async def test_existing_user_mixed_case_idp_email_uses_canonical_claims(self, sso_service, mock_db):
        existing_user = SimpleNamespace(
            email="user@test.com", full_name="User Name", auth_provider="github",
            email_verified=True, last_login=None, is_admin=False, admin_origin=None,
        )
        sso_service.auth_service.get_user_by_email = AsyncMock(return_value=existing_user)
        sso_service.get_provider = lambda _id: _make_provider()

        with patch("mcpgateway.services.sso_service.settings") as mock_settings, \
             patch("mcpgateway.services.sso_service.create_jwt_token", new_callable=AsyncMock) as mock_jwt:
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

        with patch("mcpgateway.services.sso_service.settings") as mock_settings, \
             patch("mcpgateway.services.sso_service.create_jwt_token", new_callable=AsyncMock) as mock_jwt:
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
            email="user@admin.com", full_name="Admin", auth_provider="github",
            email_verified=True, last_login=None, is_admin=False, admin_origin=None,
        )
        sso_service.auth_service.get_user_by_email = AsyncMock(return_value=existing_user)
        sso_service.get_provider = lambda _id: _make_provider()

        with patch("mcpgateway.services.sso_service.settings") as mock_settings, \
             patch("mcpgateway.services.sso_service.create_jwt_token", new_callable=AsyncMock) as mock_jwt:
            mock_settings.sso_auto_admin_domains = ["admin.com"]
            mock_settings.sso_github_admin_orgs = []
            mock_settings.sso_google_admin_domains = []
            mock_settings.sso_entra_admin_groups = []
            mock_settings.sso_entra_sync_roles_on_login = False
            mock_jwt.return_value = "jwt-token"
            result = await sso_service.authenticate_or_create_user({
                "email": "user@admin.com", "full_name": "Admin", "provider": "github",
            })

        assert existing_user.is_admin is True
        assert existing_user.admin_origin == "sso"

    @pytest.mark.asyncio
    async def test_existing_user_admin_demotion(self, sso_service, mock_db):
        existing_user = SimpleNamespace(
            email="user@other.com", full_name="Ex-Admin", auth_provider="github",
            email_verified=True, last_login=None, is_admin=True, admin_origin="sso",
        )
        sso_service.auth_service.get_user_by_email = AsyncMock(return_value=existing_user)
        sso_service.get_provider = lambda _id: _make_provider()

        with patch("mcpgateway.services.sso_service.settings") as mock_settings, \
             patch("mcpgateway.services.sso_service.create_jwt_token", new_callable=AsyncMock) as mock_jwt:
            mock_settings.sso_auto_admin_domains = []
            mock_settings.sso_github_admin_orgs = []
            mock_settings.sso_google_admin_domains = []
            mock_settings.sso_entra_admin_groups = []
            mock_settings.sso_entra_sync_roles_on_login = False
            mock_jwt.return_value = "jwt-token"
            result = await sso_service.authenticate_or_create_user({
                "email": "user@other.com", "full_name": "Ex-Admin", "provider": "github",
            })

        assert existing_user.is_admin is False
        assert existing_user.admin_origin is None

    @pytest.mark.asyncio
    async def test_new_user_auto_create(self, sso_service, mock_db):
        sso_service.auth_service.get_user_by_email = AsyncMock(return_value=None)
        new_user = SimpleNamespace(
            email="new@test.com", full_name="New User", auth_provider="github",
            is_admin=False, admin_origin=None,
        )
        sso_service.auth_service.create_user = AsyncMock(return_value=new_user)
        sso_service.get_provider = lambda _id: _make_provider()

        with patch("mcpgateway.services.sso_service.settings") as mock_settings, \
             patch("mcpgateway.services.sso_service.create_jwt_token", new_callable=AsyncMock) as mock_jwt:
            mock_settings.sso_auto_admin_domains = []
            mock_settings.sso_github_admin_orgs = []
            mock_settings.sso_google_admin_domains = []
            mock_settings.sso_entra_admin_groups = []
            mock_settings.sso_require_admin_approval = False
            mock_jwt.return_value = "new-jwt"
            result = await sso_service.authenticate_or_create_user({
                "email": "new@test.com", "full_name": "New User", "provider": "github",
            })

        assert result == "new-jwt"

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

        with patch("mcpgateway.services.sso_service.settings") as mock_settings, \
             patch("mcpgateway.services.sso_service.create_jwt_token", new_callable=AsyncMock) as mock_jwt:
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

        with patch("mcpgateway.services.sso_service.settings") as mock_settings, \
             patch("mcpgateway.services.sso_service.create_jwt_token", new_callable=AsyncMock) as mock_jwt:
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
                    "groups": ["dev"],
                }
            )

        assert result == "new-jwt"
        sso_service._map_groups_to_roles.assert_called_once()

    @pytest.mark.asyncio
    async def test_new_user_no_auto_create(self, sso_service, mock_db):
        sso_service.auth_service.get_user_by_email = AsyncMock(return_value=None)
        sso_service.get_provider = lambda _id: _make_provider(auto_create_users=False)

        result = await sso_service.authenticate_or_create_user({
            "email": "new@test.com", "full_name": "New User", "provider": "github",
        })
        assert result is None

    @pytest.mark.asyncio
    async def test_new_user_untrusted_domain(self, sso_service, mock_db):
        sso_service.auth_service.get_user_by_email = AsyncMock(return_value=None)
        sso_service.get_provider = lambda _id: _make_provider(trusted_domains=["trusted.com"])

        result = await sso_service.authenticate_or_create_user({
            "email": "new@untrusted.com", "full_name": "New User", "provider": "github",
        })
        assert result is None

    @pytest.mark.asyncio
    async def test_new_user_admin_approval_pending(self, sso_service, mock_db):
        """Admin approval required + no existing pending → creates pending request."""
        sso_service.auth_service.get_user_by_email = AsyncMock(return_value=None)
        sso_service.get_provider = lambda _id: _make_provider()
        mock_db.execute.return_value.scalar_one_or_none.return_value = None  # No existing pending

        with patch("mcpgateway.services.sso_service.settings") as mock_settings, \
             patch("mcpgateway.services.sso_service.select", return_value=MagicMock()) as mock_select, \
             patch("mcpgateway.services.sso_service.PendingUserApproval"):
            mock_settings.sso_require_admin_approval = True
            result = await sso_service.authenticate_or_create_user({
                "email": "new@test.com", "full_name": "New User", "provider": "github",
            })

        assert result is None
        mock_db.add.assert_called()  # Pending request created

    @pytest.mark.asyncio
    async def test_new_user_admin_approval_still_pending(self, sso_service, mock_db):
        """Existing pending approval that hasn't expired."""
        sso_service.auth_service.get_user_by_email = AsyncMock(return_value=None)
        sso_service.get_provider = lambda _id: _make_provider()
        pending = SimpleNamespace(status="pending", is_expired=lambda: False)
        mock_db.execute.return_value.scalar_one_or_none.return_value = pending

        with patch("mcpgateway.services.sso_service.settings") as mock_settings, \
             patch("mcpgateway.services.sso_service.select", return_value=MagicMock()):
            mock_settings.sso_require_admin_approval = True
            result = await sso_service.authenticate_or_create_user({
                "email": "new@test.com", "full_name": "New User", "provider": "github",
            })

        assert result is None

    @pytest.mark.asyncio
    async def test_new_user_admin_approval_rejected(self, sso_service, mock_db):
        """Existing pending approval that was rejected."""
        sso_service.auth_service.get_user_by_email = AsyncMock(return_value=None)
        sso_service.get_provider = lambda _id: _make_provider()
        pending = SimpleNamespace(status="rejected", is_expired=lambda: False)
        mock_db.execute.return_value.scalar_one_or_none.return_value = pending

        with patch("mcpgateway.services.sso_service.settings") as mock_settings, \
             patch("mcpgateway.services.sso_service.select", return_value=MagicMock()):
            mock_settings.sso_require_admin_approval = True
            result = await sso_service.authenticate_or_create_user({
                "email": "new@test.com", "full_name": "New User", "provider": "github",
            })

        assert result is None

    @pytest.mark.asyncio
    async def test_new_user_admin_approval_approved(self, sso_service, mock_db):
        """Existing pending approval that was approved → user gets created."""
        sso_service.auth_service.get_user_by_email = AsyncMock(return_value=None)
        sso_service.get_provider = lambda _id: _make_provider()
        new_user = SimpleNamespace(
            email="new@test.com", full_name="New User", auth_provider="github",
            is_admin=False, admin_origin=None,
        )
        sso_service.auth_service.create_user = AsyncMock(return_value=new_user)

        # First call returns "approved" pending, second call returns pending for completion
        approved = SimpleNamespace(status="approved", is_expired=lambda: False)
        mock_db.execute.return_value.scalar_one_or_none.side_effect = [approved, approved]

        with patch("mcpgateway.services.sso_service.settings") as mock_settings, \
             patch("mcpgateway.services.sso_service.select", return_value=MagicMock()), \
             patch("mcpgateway.services.sso_service.create_jwt_token", new_callable=AsyncMock) as mock_jwt:
            mock_settings.sso_require_admin_approval = True
            mock_settings.sso_auto_admin_domains = []
            mock_settings.sso_github_admin_orgs = []
            mock_settings.sso_google_admin_domains = []
            mock_settings.sso_entra_admin_groups = []
            mock_jwt.return_value = "approved-jwt"
            result = await sso_service.authenticate_or_create_user({
                "email": "new@test.com", "full_name": "New User", "provider": "github",
            })

        assert result == "approved-jwt"

    @pytest.mark.asyncio
    async def test_new_user_create_fails(self, sso_service, mock_db):
        """create_user returns None → returns None."""
        sso_service.auth_service.get_user_by_email = AsyncMock(return_value=None)
        sso_service.auth_service.create_user = AsyncMock(return_value=None)
        sso_service.get_provider = lambda _id: _make_provider()

        with patch("mcpgateway.services.sso_service.settings") as mock_settings:
            mock_settings.sso_require_admin_approval = False
            mock_settings.sso_auto_admin_domains = []
            mock_settings.sso_github_admin_orgs = []
            mock_settings.sso_google_admin_domains = []
            mock_settings.sso_entra_admin_groups = []
            result = await sso_service.authenticate_or_create_user({
                "email": "new@test.com", "full_name": "New User", "provider": "github",
            })

        assert result is None

    @pytest.mark.asyncio
    async def test_existing_user_with_role_sync(self, sso_service, mock_db):
        """Existing user with provider metadata sync_roles=True triggers role sync."""
        existing_user = SimpleNamespace(
            email="user@test.com", full_name="Name", auth_provider="github",
            email_verified=True, last_login=None, is_admin=False, admin_origin=None,
        )
        sso_service.auth_service.get_user_by_email = AsyncMock(return_value=existing_user)
        sso_service.get_provider = lambda _id: _make_provider(provider_metadata={"sync_roles": True, "role_mappings": {}})
        sso_service._map_groups_to_roles = AsyncMock(return_value=[])
        sso_service._sync_user_roles = AsyncMock()

        with patch("mcpgateway.services.sso_service.settings") as mock_settings, \
             patch("mcpgateway.services.sso_service.create_jwt_token", new_callable=AsyncMock) as mock_jwt:
            mock_settings.sso_auto_admin_domains = []
            mock_settings.sso_github_admin_orgs = []
            mock_settings.sso_google_admin_domains = []
            mock_settings.sso_entra_admin_groups = []
            mock_jwt.return_value = "jwt"
            result = await sso_service.authenticate_or_create_user({
                "email": "user@test.com", "full_name": "Name", "provider": "github", "groups": ["dev"],
            })

        sso_service._map_groups_to_roles.assert_called_once()
        sso_service._sync_user_roles.assert_called_once()


# ---------------------------------------------------------------------------
# _sync_user_roles tests
# ---------------------------------------------------------------------------


class TestSyncUserRoles:
    @pytest.mark.asyncio
    async def test_revokes_removed_roles(self, sso_service):
        """Roles no longer in desired set are revoked."""
        old_role = SimpleNamespace(
            role=SimpleNamespace(name="old-role", id="r-old"),
            scope="team", scope_id=None, granted_by="sso_system", role_id="r-old",
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
# Entra legacy role mapping fallback
# ---------------------------------------------------------------------------


class TestEntraLegacyRoleMappings:
    @pytest.mark.asyncio
    async def test_entra_legacy_role_mappings_fallback(self, sso_service):
        """When no role_mappings in metadata, falls back to sso_entra_role_mappings."""
        mock_role = SimpleNamespace(name="developer", scope="team", id="r1")
        provider = _make_provider(id="entra", provider_metadata={})

        with patch("mcpgateway.services.sso_service.settings") as mock_settings, \
             patch("mcpgateway.services.role_service.RoleService") as MockRoleService:
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

        with patch("mcpgateway.services.sso_service.settings") as mock_settings, \
             patch("mcpgateway.services.role_service.RoleService") as MockRoleService:
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

        with patch("mcpgateway.services.sso_service.settings") as mock_settings, \
             patch("mcpgateway.services.role_service.RoleService") as MockRoleService:
            mock_settings.sso_entra_admin_groups = ["admin-grp"]
            mock_settings.sso_entra_default_role = None
            mock_settings.sso_entra_role_mappings = {}
            mock_settings.default_admin_role = "platform_admin"
            role_svc = AsyncMock()
            MockRoleService.return_value = role_svc
            result = await sso_service._map_groups_to_roles("user@test.com", ["admin-grp", "other"], provider)

        assert any(r["role_name"] == "platform_admin" for r in result)
