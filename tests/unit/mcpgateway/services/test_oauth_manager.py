# -*- coding: utf-8 -*-
"""Unit tests for OAuthManager service."""

# Standard
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import httpx
import pytest

# First-Party
from mcpgateway.services.oauth_manager import OAuthError, OAuthManager


@pytest.fixture
def oauth_manager():
    with patch("mcpgateway.services.oauth_manager.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(
            auth_encryption_secret=MagicMock(get_secret_value=MagicMock(return_value="test-secret")),
            cache_type="memory",
            redis_url=None,
            oauth_default_timeout=3600,
        )
        mgr = OAuthManager(request_timeout=10, max_retries=1)
    return mgr


# ---------- Construction ----------


def test_init_defaults():
    with patch("mcpgateway.services.oauth_manager.get_settings"):
        mgr = OAuthManager()
    assert mgr.request_timeout == 30
    assert mgr.max_retries == 3
    assert mgr.token_storage is None


def test_init_custom():
    with patch("mcpgateway.services.oauth_manager.get_settings"):
        mgr = OAuthManager(request_timeout=60, max_retries=5, token_storage="store")
    assert mgr.request_timeout == 60
    assert mgr.max_retries == 5
    assert mgr.token_storage == "store"


# ---------- _generate_pkce_params ----------


def test_generate_pkce_params(oauth_manager):
    params = oauth_manager._generate_pkce_params()
    assert "code_verifier" in params
    assert "code_challenge" in params
    assert params["code_challenge_method"] == "S256"
    assert len(params["code_verifier"]) > 20
    assert len(params["code_challenge"]) > 20


# ---------- get_access_token ----------


@pytest.mark.asyncio
async def test_get_access_token_client_credentials(oauth_manager):
    with patch.object(oauth_manager, "_client_credentials_flow", new_callable=AsyncMock, return_value="tok-123"):
        result = await oauth_manager.get_access_token({"grant_type": "client_credentials"})
    assert result == "tok-123"


@pytest.mark.asyncio
async def test_get_access_token_password(oauth_manager):
    with patch.object(oauth_manager, "_password_flow", new_callable=AsyncMock, return_value="pwd-tok"):
        result = await oauth_manager.get_access_token({"grant_type": "password"})
    assert result == "pwd-tok"


@pytest.mark.asyncio
async def test_get_access_token_authorization_code_fallback(oauth_manager):
    with patch.object(oauth_manager, "_client_credentials_flow", new_callable=AsyncMock, return_value="fallback-tok"):
        result = await oauth_manager.get_access_token({"grant_type": "authorization_code"})
    assert result == "fallback-tok"


@pytest.mark.asyncio
async def test_get_access_token_authorization_code_failure(oauth_manager):
    with patch.object(oauth_manager, "_client_credentials_flow", new_callable=AsyncMock, side_effect=Exception("no creds")):
        with pytest.raises(OAuthError, match="Authorization code flow cannot be used"):
            await oauth_manager.get_access_token({"grant_type": "authorization_code"})


@pytest.mark.asyncio
async def test_get_access_token_unsupported(oauth_manager):
    with pytest.raises(ValueError, match="Unsupported grant type"):
        await oauth_manager.get_access_token({"grant_type": "implicit"})


# ---------- _client_credentials_flow ----------


@pytest.mark.asyncio
async def test_client_credentials_flow_success_json(oauth_manager):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.headers = {"content-type": "application/json"}
    mock_response.json.return_value = {"access_token": "json-tok"}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    with patch.object(oauth_manager, "_get_client", new_callable=AsyncMock, return_value=mock_client):
        result = await oauth_manager._client_credentials_flow(
            {"client_id": "cid", "client_secret": "short", "token_url": "https://auth/token"}
        )
    assert result == "json-tok"


@pytest.mark.asyncio
async def test_client_credentials_flow_success_form_encoded(oauth_manager):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.headers = {"content-type": "application/x-www-form-urlencoded"}
    mock_response.text = "access_token=form-tok&token_type=bearer"

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    with patch.object(oauth_manager, "_get_client", new_callable=AsyncMock, return_value=mock_client):
        result = await oauth_manager._client_credentials_flow(
            {"client_id": "cid", "client_secret": "short", "token_url": "https://auth/token"}
        )
    assert result == "form-tok"


@pytest.mark.asyncio
async def test_client_credentials_flow_with_scopes(oauth_manager):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.headers = {"content-type": "application/json"}
    mock_response.json.return_value = {"access_token": "scoped-tok"}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    with patch.object(oauth_manager, "_get_client", new_callable=AsyncMock, return_value=mock_client):
        result = await oauth_manager._client_credentials_flow(
            {"client_id": "cid", "client_secret": "short", "token_url": "https://auth/token", "scopes": ["read", "write"]}
        )
    assert result == "scoped-tok"


@pytest.mark.asyncio
async def test_client_credentials_flow_decrypt_secret(oauth_manager):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.headers = {"content-type": "application/json"}
    mock_response.json.return_value = {"access_token": "dec-tok"}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    mock_enc = MagicMock()
    mock_enc.decrypt_secret_async = AsyncMock(return_value="decrypted-secret")

    with (
        patch.object(oauth_manager, "_get_client", new_callable=AsyncMock, return_value=mock_client),
        patch("mcpgateway.services.oauth_manager.get_settings") as mock_gs,
        patch("mcpgateway.services.oauth_manager.get_encryption_service", return_value=mock_enc),
    ):
        mock_gs.return_value = MagicMock(auth_encryption_secret="key")
        # Secret longer than 50 chars triggers decryption
        long_secret = "x" * 60
        result = await oauth_manager._client_credentials_flow(
            {"client_id": "cid", "client_secret": long_secret, "token_url": "https://auth/token"}
        )
    assert result == "dec-tok"


@pytest.mark.asyncio
async def test_client_credentials_flow_decrypt_returns_none(oauth_manager):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.headers = {"content-type": "application/json"}
    mock_response.json.return_value = {"access_token": "tok"}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    mock_enc = MagicMock()
    mock_enc.decrypt_secret_async = AsyncMock(return_value=None)

    with (
        patch.object(oauth_manager, "_get_client", new_callable=AsyncMock, return_value=mock_client),
        patch("mcpgateway.services.oauth_manager.get_settings") as mock_gs,
        patch("mcpgateway.services.oauth_manager.get_encryption_service", return_value=mock_enc),
    ):
        mock_gs.return_value = MagicMock(auth_encryption_secret="key")
        result = await oauth_manager._client_credentials_flow(
            {"client_id": "cid", "client_secret": "x" * 60, "token_url": "https://auth/token"}
        )
    assert result == "tok"


@pytest.mark.asyncio
async def test_client_credentials_flow_decrypt_exception(oauth_manager):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.headers = {"content-type": "application/json"}
    mock_response.json.return_value = {"access_token": "tok"}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    with (
        patch.object(oauth_manager, "_get_client", new_callable=AsyncMock, return_value=mock_client),
        patch("mcpgateway.services.oauth_manager.get_settings") as mock_gs,
        patch("mcpgateway.services.oauth_manager.get_encryption_service", side_effect=RuntimeError("enc fail")),
    ):
        mock_gs.return_value = MagicMock(auth_encryption_secret="key")
        result = await oauth_manager._client_credentials_flow(
            {"client_id": "cid", "client_secret": "x" * 60, "token_url": "https://auth/token"}
        )
    assert result == "tok"


@pytest.mark.asyncio
async def test_client_credentials_flow_no_access_token(oauth_manager):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.headers = {"content-type": "application/json"}
    mock_response.json.return_value = {"error": "invalid_grant"}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    with patch.object(oauth_manager, "_get_client", new_callable=AsyncMock, return_value=mock_client):
        with pytest.raises(OAuthError, match="No access_token"):
            await oauth_manager._client_credentials_flow(
                {"client_id": "cid", "client_secret": "short", "token_url": "https://auth/token"}
            )


@pytest.mark.asyncio
async def test_client_credentials_flow_http_error(oauth_manager):
    mock_client = AsyncMock()
    mock_client.post.side_effect = httpx.HTTPError("connection failed")
    with patch.object(oauth_manager, "_get_client", new_callable=AsyncMock, return_value=mock_client):
        with pytest.raises(OAuthError, match="Failed to obtain access token"):
            await oauth_manager._client_credentials_flow(
                {"client_id": "cid", "client_secret": "short", "token_url": "https://auth/token"}
            )


@pytest.mark.asyncio
async def test_client_credentials_flow_json_parse_failure(oauth_manager):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.headers = {"content-type": "text/html"}
    mock_response.json.side_effect = ValueError("bad json")
    mock_response.text = "raw_response_text"

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    with patch.object(oauth_manager, "_get_client", new_callable=AsyncMock, return_value=mock_client):
        with pytest.raises(OAuthError, match="No access_token"):
            await oauth_manager._client_credentials_flow(
                {"client_id": "cid", "client_secret": "short", "token_url": "https://auth/token"}
            )


# ---------- _password_flow ----------


@pytest.mark.asyncio
async def test_password_flow_success(oauth_manager):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.headers = {"content-type": "application/json"}
    mock_response.json.return_value = {"access_token": "pwd-tok"}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    with patch.object(oauth_manager, "_get_client", new_callable=AsyncMock, return_value=mock_client):
        result = await oauth_manager._password_flow(
            {"client_id": "cid", "client_secret": "short", "token_url": "https://auth/token", "username": "user", "password": "pass"}
        )
    assert result == "pwd-tok"


@pytest.mark.asyncio
async def test_password_flow_no_username():
    with patch("mcpgateway.services.oauth_manager.get_settings"):
        mgr = OAuthManager(max_retries=1)
    with pytest.raises(OAuthError, match="Username and password are required"):
        await mgr._password_flow({"token_url": "https://auth/token"})


@pytest.mark.asyncio
async def test_password_flow_form_encoded(oauth_manager):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.headers = {"content-type": "application/x-www-form-urlencoded"}
    mock_response.text = "access_token=form-pwd-tok&token_type=bearer"

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    with patch.object(oauth_manager, "_get_client", new_callable=AsyncMock, return_value=mock_client):
        result = await oauth_manager._password_flow(
            {"client_id": "cid", "token_url": "https://auth/token", "username": "user", "password": "pass", "scopes": ["openid"]}
        )
    assert result == "form-pwd-tok"


@pytest.mark.asyncio
async def test_password_flow_decrypt_secret(oauth_manager):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.headers = {"content-type": "application/json"}
    mock_response.json.return_value = {"access_token": "tok"}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    mock_enc = MagicMock()
    mock_enc.decrypt_secret_async = AsyncMock(return_value="decrypted")

    with (
        patch.object(oauth_manager, "_get_client", new_callable=AsyncMock, return_value=mock_client),
        patch("mcpgateway.services.oauth_manager.get_settings") as mock_gs,
        patch("mcpgateway.services.oauth_manager.get_encryption_service", return_value=mock_enc),
    ):
        mock_gs.return_value = MagicMock(auth_encryption_secret="key")
        result = await oauth_manager._password_flow(
            {"client_id": "cid", "client_secret": "x" * 60, "token_url": "https://auth/token", "username": "user", "password": "pass"}
        )
    assert result == "tok"


# ---------- exchange_code_for_token ----------


@pytest.mark.asyncio
async def test_exchange_code_for_token_success(oauth_manager):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.headers = {"content-type": "application/json"}
    mock_response.json.return_value = {"access_token": "code-tok"}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    with patch.object(oauth_manager, "_get_client", new_callable=AsyncMock, return_value=mock_client):
        result = await oauth_manager.exchange_code_for_token(
            {"client_id": "cid", "client_secret": "short", "token_url": "https://auth/token", "redirect_uri": "https://cb"},
            code="auth-code",
            state="state-123",
        )
    assert result == "code-tok"


@pytest.mark.asyncio
async def test_exchange_code_for_token_no_secret(oauth_manager):
    """Public client without client_secret."""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.headers = {"content-type": "application/json"}
    mock_response.json.return_value = {"access_token": "public-tok"}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    with patch.object(oauth_manager, "_get_client", new_callable=AsyncMock, return_value=mock_client):
        result = await oauth_manager.exchange_code_for_token(
            {"client_id": "cid", "token_url": "https://auth/token", "redirect_uri": "https://cb"},
            code="auth-code",
            state="state-123",
        )
    assert result == "public-tok"


# ---------- refresh_token ----------


@pytest.mark.asyncio
async def test_refresh_token_success(oauth_manager):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"access_token": "new-tok", "refresh_token": "new-rt"}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    with patch.object(oauth_manager, "_get_client", new_callable=AsyncMock, return_value=mock_client):
        result = await oauth_manager.refresh_token(
            "old-rt", {"client_id": "cid", "client_secret": "sec", "token_url": "https://auth/token"}
        )
    assert result["access_token"] == "new-tok"


@pytest.mark.asyncio
async def test_refresh_token_no_refresh_token(oauth_manager):
    with pytest.raises(OAuthError, match="No refresh token"):
        await oauth_manager.refresh_token("", {"token_url": "https://auth/token"})


@pytest.mark.asyncio
async def test_refresh_token_no_token_url(oauth_manager):
    with pytest.raises(OAuthError, match="No token URL"):
        await oauth_manager.refresh_token("rt", {})


@pytest.mark.asyncio
async def test_refresh_token_no_client_id(oauth_manager):
    with pytest.raises(OAuthError, match="No client_id"):
        await oauth_manager.refresh_token("rt", {"token_url": "https://auth/token"})


@pytest.mark.asyncio
async def test_refresh_token_400_error(oauth_manager):
    mock_response = MagicMock()
    mock_response.status_code = 400
    mock_response.text = "invalid_grant"

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    with patch.object(oauth_manager, "_get_client", new_callable=AsyncMock, return_value=mock_client):
        with pytest.raises(OAuthError, match="Refresh token invalid"):
            await oauth_manager.refresh_token(
                "old-rt", {"client_id": "cid", "token_url": "https://auth/token"}
            )


@pytest.mark.asyncio
async def test_refresh_token_401_error(oauth_manager):
    mock_response = MagicMock()
    mock_response.status_code = 401
    mock_response.text = "unauthorized"

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    with patch.object(oauth_manager, "_get_client", new_callable=AsyncMock, return_value=mock_client):
        with pytest.raises(OAuthError, match="Refresh token invalid"):
            await oauth_manager.refresh_token(
                "old-rt", {"client_id": "cid", "token_url": "https://auth/token"}
            )


@pytest.mark.asyncio
async def test_refresh_token_no_access_token_in_response(oauth_manager):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"error": "missing_token"}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    with patch.object(oauth_manager, "_get_client", new_callable=AsyncMock, return_value=mock_client):
        with pytest.raises(OAuthError, match="No access_token"):
            await oauth_manager.refresh_token(
                "old-rt", {"client_id": "cid", "token_url": "https://auth/token"}
            )


@pytest.mark.asyncio
async def test_refresh_token_http_error(oauth_manager):
    mock_client = AsyncMock()
    mock_client.post.side_effect = httpx.HTTPError("timeout")
    with patch.object(oauth_manager, "_get_client", new_callable=AsyncMock, return_value=mock_client):
        with pytest.raises(OAuthError, match="Failed to refresh token"):
            await oauth_manager.refresh_token(
                "old-rt", {"client_id": "cid", "token_url": "https://auth/token"}
            )


@pytest.mark.asyncio
async def test_refresh_token_with_resource_string(oauth_manager):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"access_token": "new-tok"}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    with patch.object(oauth_manager, "_get_client", new_callable=AsyncMock, return_value=mock_client):
        result = await oauth_manager.refresh_token(
            "old-rt", {"client_id": "cid", "token_url": "https://auth/token", "resource": "https://mcp.example.com"}
        )
    assert result["access_token"] == "new-tok"


@pytest.mark.asyncio
async def test_refresh_token_with_resource_list(oauth_manager):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"access_token": "new-tok"}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    with patch.object(oauth_manager, "_get_client", new_callable=AsyncMock, return_value=mock_client):
        result = await oauth_manager.refresh_token(
            "old-rt", {"client_id": "cid", "token_url": "https://auth/token", "resource": ["https://a.com", "https://b.com"]}
        )
    assert result["access_token"] == "new-tok"


@pytest.mark.asyncio
async def test_exchange_code_for_tokens_omits_resource_for_entra_v2_scope_flow(oauth_manager):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.headers = {"content-type": "application/json"}
    mock_response.json.return_value = {"access_token": "new-tok"}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    with patch.object(oauth_manager, "_get_client", new_callable=AsyncMock, return_value=mock_client):
        result = await oauth_manager._exchange_code_for_tokens(
            {
                "client_id": "cid",
                "token_url": "https://login.microsoftonline.com/tenant-id/oauth2/v2.0/token",
                "authorization_url": "https://login.microsoftonline.com/tenant-id/oauth2/v2.0/authorize",
                "redirect_uri": "https://gateway.example.com/oauth/callback",
                "scopes": ["openid", "profile"],
                "resource": "https://mcp.example.com",
            },
            code="auth-code",
        )

    assert result["access_token"] == "new-tok"
    request_data = mock_client.post.call_args[1]["data"]
    assert "resource" not in request_data


@pytest.mark.asyncio
async def test_refresh_token_omits_resource_for_entra_v2_scope_flow(oauth_manager):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"access_token": "new-tok"}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    with patch.object(oauth_manager, "_get_client", new_callable=AsyncMock, return_value=mock_client):
        result = await oauth_manager.refresh_token(
            "old-rt",
            {
                "client_id": "cid",
                "token_url": "https://login.microsoftonline.com/tenant-id/oauth2/v2.0/token",
                "authorization_url": "https://login.microsoftonline.com/tenant-id/oauth2/v2.0/authorize",
                "scopes": ["openid", "profile"],
                "resource": "https://mcp.example.com",
            },
        )

    assert result["access_token"] == "new-tok"
    request_data = mock_client.post.call_args[1]["data"]
    assert "resource" not in request_data


@pytest.mark.asyncio
async def test_refresh_token_500_retries_then_fails():
    with patch("mcpgateway.services.oauth_manager.get_settings") as mock_gs:
        mock_gs.return_value = MagicMock(
            auth_encryption_secret=None,
            cache_type="memory",
            redis_url=None,
        )
        mgr = OAuthManager(max_retries=2, request_timeout=1)

    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.text = "Internal Server Error"

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    with patch.object(mgr, "_get_client", new_callable=AsyncMock, return_value=mock_client):
        with pytest.raises(OAuthError, match="Failed to refresh token after all retry"):
            await mgr.refresh_token("rt", {"client_id": "cid", "token_url": "https://auth/token"})


# ---------- _extract_user_id ----------


def test_extract_user_id_sub(oauth_manager):
    assert oauth_manager._extract_user_id({"sub": "user-sub"}, {}) == "user-sub"


def test_extract_user_id_user_id(oauth_manager):
    assert oauth_manager._extract_user_id({"user_id": "uid"}, {}) == "uid"


def test_extract_user_id_id(oauth_manager):
    assert oauth_manager._extract_user_id({"id": "123"}, {}) == "123"


def test_extract_user_id_client_id(oauth_manager):
    assert oauth_manager._extract_user_id({}, {"client_id": "cid"}) == "cid"


def test_extract_user_id_fallback(oauth_manager):
    assert oauth_manager._extract_user_id({}, {}) == "unknown_user"


# ---------- get_access_token_for_user ----------


@pytest.mark.asyncio
async def test_get_access_token_for_user_no_storage(oauth_manager):
    result = await oauth_manager.get_access_token_for_user("gw1", "user@test.com")
    assert result is None


@pytest.mark.asyncio
async def test_get_access_token_for_user_with_storage():
    with patch("mcpgateway.services.oauth_manager.get_settings"):
        mgr = OAuthManager()
    mock_storage = AsyncMock()
    mock_storage.get_user_token.return_value = "stored-tok"
    mgr.token_storage = mock_storage
    result = await mgr.get_access_token_for_user("gw1", "user@test.com")
    assert result == "stored-tok"


# ---------- _generate_state ----------


def test_generate_state(oauth_manager):
    state = oauth_manager._generate_state("gw-1", "user@test.com")
    assert isinstance(state, str)
    assert len(state) > 20


def test_generate_state_no_email(oauth_manager):
    state = oauth_manager._generate_state("gw-1")
    assert isinstance(state, str)


# ---------- _create_authorization_url_with_pkce ----------


def test_create_authorization_url_with_pkce(oauth_manager):
    url = oauth_manager._create_authorization_url_with_pkce(
        {"client_id": "cid", "redirect_uri": "https://cb", "authorization_url": "https://auth", "scopes": ["openid"]},
        state="state-123",
        code_challenge="challenge",
        code_challenge_method="S256",
    )
    assert "https://auth?" in url
    assert "code_challenge=challenge" in url
    assert "state=state-123" in url
    assert "scope=openid" in url


def test_create_authorization_url_with_pkce_resource_string(oauth_manager):
    url = oauth_manager._create_authorization_url_with_pkce(
        {"client_id": "cid", "redirect_uri": "https://cb", "authorization_url": "https://auth", "resource": "https://mcp.example.com"},
        state="st",
        code_challenge="ch",
        code_challenge_method="S256",
    )
    assert "resource=" in url


def test_create_authorization_url_with_pkce_resource_list(oauth_manager):
    url = oauth_manager._create_authorization_url_with_pkce(
        {"client_id": "cid", "redirect_uri": "https://cb", "authorization_url": "https://auth", "resource": ["https://a.com", "https://b.com"]},
        state="st",
        code_challenge="ch",
        code_challenge_method="S256",
    )
    assert "resource=" in url


def test_create_authorization_url_with_pkce_omits_resource_for_entra_v2_scope_flow(oauth_manager):
    url = oauth_manager._create_authorization_url_with_pkce(
        {
            "client_id": "cid",
            "redirect_uri": "https://cb",
            "authorization_url": "https://login.microsoftonline.com/tenant-id/oauth2/v2.0/authorize",
            "scopes": ["openid", "profile"],
            "resource": "https://mcp.example.com",
        },
        state="st",
        code_challenge="ch",
        code_challenge_method="S256",
    )
    assert "scope=openid+profile" in url or "scope=openid%20profile" in url
    assert "resource=" not in url


def test_create_authorization_url_with_pkce_omits_resource_when_flag_enabled(oauth_manager):
    url = oauth_manager._create_authorization_url_with_pkce(
        {
            "client_id": "cid",
            "redirect_uri": "https://cb",
            "authorization_url": "https://auth.example.com/authorize",
            "scopes": ["openid"],
            "resource": "https://mcp.example.com",
            "omit_resource": True,
        },
        state="st",
        code_challenge="ch",
        code_challenge_method="S256",
    )
    assert "resource=" not in url


def test_create_authorization_url_with_pkce_no_scopes(oauth_manager):
    url = oauth_manager._create_authorization_url_with_pkce(
        {"client_id": "cid", "redirect_uri": "https://cb", "authorization_url": "https://auth"},
        state="st",
        code_challenge="ch",
        code_challenge_method="S256",
    )
    assert "scope" not in url


# ---------- OAuthError ----------


def test_oauth_error():
    err = OAuthError("something failed")
    assert str(err) == "something failed"
    assert isinstance(err, Exception)


# ---------- _get_redis_client ----------


@pytest.mark.asyncio
async def test_get_redis_client_already_initialized():
    import mcpgateway.services.oauth_manager as om

    original_init = om._REDIS_INITIALIZED
    original_client = om._redis_client
    try:
        om._REDIS_INITIALIZED = True
        om._redis_client = "cached"
        result = await om._get_redis_client()
        assert result == "cached"
    finally:
        om._REDIS_INITIALIZED = original_init
        om._redis_client = original_client


@pytest.mark.asyncio
async def test_get_redis_client_no_redis():
    import mcpgateway.services.oauth_manager as om

    original_init = om._REDIS_INITIALIZED
    original_client = om._redis_client
    try:
        om._REDIS_INITIALIZED = False
        om._redis_client = None
        with patch("mcpgateway.services.oauth_manager.get_settings") as mock_gs:
            mock_gs.return_value = MagicMock(cache_type="memory", redis_url=None)
            result = await om._get_redis_client()
        assert result is None
    finally:
        om._REDIS_INITIALIZED = original_init
        om._redis_client = original_client
