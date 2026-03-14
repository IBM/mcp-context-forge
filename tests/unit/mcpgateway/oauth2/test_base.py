# -*- coding: utf-8 -*-
"""Unit tests for OAuth2 base library."""

# Standard
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.oauth2 import (
    OAuth2BaseLibrary,
    OAuth2DiscoveryError,
    OAuth2TokenExchangeError,
    OAuth2TokenRefreshError,
    OAuth2TokenValidationError,
    OAuth2ValidationConfig,
    RefreshTokenRequest,
    TokenExchangeRequest,
    apply_scope_modifications,
    extract_claims,
    normalize_scopes,
    scopes_to_string,
)


def test_normalize_scopes():
    assert normalize_scopes(None) == []
    assert normalize_scopes("openid email profile") == ["openid", "email", "profile"]
    assert normalize_scopes(["a", "", "b"]) == ["a", "b"]


def test_scope_helpers():
    assert scopes_to_string(["read", "write"]) == "read write"
    assert apply_scope_modifications(["read"], add=["write"], remove=["read"]) == ["write"]


def test_extract_claims():
    payload = {"sub": "u1", "scope": "openid email", "roles": ["admin"], "email": "u@example.com"}
    claims = extract_claims(payload)
    assert claims["sub"] == "u1"
    assert claims["scope"] == ["openid", "email"]
    assert claims["roles"] == ["admin"]


@pytest.fixture
def oauth2_lib():
    return OAuth2BaseLibrary()


@pytest.mark.asyncio
async def test_discover_authorization_server_metadata_success(oauth2_lib):
    mock_response = MagicMock(status_code=200)
    mock_response.json.return_value = {"issuer": "https://issuer.example", "token_endpoint": "https://issuer.example/token"}
    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response
    with patch("mcpgateway.oauth2.base.get_http_client", new_callable=AsyncMock, return_value=mock_client):
        metadata = await oauth2_lib.discover_authorization_server_metadata("https://issuer.example")
    assert metadata["token_endpoint"] == "https://issuer.example/token"


@pytest.mark.asyncio
async def test_discover_authorization_server_metadata_issuer_mismatch(oauth2_lib):
    mock_response = MagicMock(status_code=200)
    mock_response.json.return_value = {"issuer": "https://other.example"}
    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response
    with patch("mcpgateway.oauth2.base.get_http_client", new_callable=AsyncMock, return_value=mock_client):
        with pytest.raises(OAuth2DiscoveryError, match="issuer mismatch"):
            await oauth2_lib.discover_authorization_server_metadata("https://issuer.example")


@pytest.mark.asyncio
async def test_discover_protected_resource_metadata_success(oauth2_lib):
    mock_response = MagicMock(status_code=200)
    mock_response.json.return_value = {"resource": "https://rs.example"}
    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response
    with patch("mcpgateway.oauth2.base.get_http_client", new_callable=AsyncMock, return_value=mock_client):
        data = await oauth2_lib.discover_protected_resource_metadata("https://rs.example")
    assert data["resource"] == "https://rs.example"


@pytest.mark.asyncio
async def test_validate_token_jwt_success(oauth2_lib):
    config = OAuth2ValidationConfig(issuer="https://issuer.example", audience="api://default", jwks_uri="https://issuer.example/jwks")
    with (
        patch("mcpgateway.oauth2.base.jwt.PyJWKClient") as mock_jwk_client,
        patch("mcpgateway.oauth2.base.jwt.decode", return_value={"sub": "u1", "scope": "openid profile"}) as mock_decode,
    ):
        mock_key = MagicMock()
        mock_key.key = "test-key"
        mock_jwk_client.return_value.get_signing_key_from_jwt.return_value = mock_key
        result = await oauth2_lib.validate_token("jwt-token", config)
    assert result.active is True
    assert result.source == "jwt"
    assert result.scopes == ["openid", "profile"]
    mock_decode.assert_called_once()


@pytest.mark.asyncio
async def test_validate_token_introspection_inactive(oauth2_lib):
    config = OAuth2ValidationConfig(introspection_endpoint="https://issuer.example/introspect", client_id="cid", client_secret="sec")
    mock_response = MagicMock(status_code=200)
    mock_response.json.return_value = {"active": False, "scope": "a b"}
    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    with patch("mcpgateway.oauth2.base.get_http_client", new_callable=AsyncMock, return_value=mock_client):
        result = await oauth2_lib.validate_token("opaque-token", config)
    assert result.active is False
    assert result.source == "introspection"
    assert result.scopes == ["a", "b"]


@pytest.mark.asyncio
async def test_validate_token_missing_config(oauth2_lib):
    with pytest.raises(OAuth2TokenValidationError, match="No token validation mechanism"):
        await oauth2_lib.validate_token("t", OAuth2ValidationConfig())


@pytest.mark.asyncio
async def test_exchange_token_success(oauth2_lib):
    req = TokenExchangeRequest(
        token_endpoint="https://issuer.example/token",
        client_id="cid",
        client_secret="sec",
        subject_token="subject",
        scope=["read"],
        audience=["aud1"],
        resource=["https://rs.example"],
    )
    mock_response = MagicMock(status_code=200)
    mock_response.json.return_value = {"access_token": "new-token", "issued_token_type": "urn:ietf:params:oauth:token-type:access_token"}
    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    with patch("mcpgateway.oauth2.base.get_http_client", new_callable=AsyncMock, return_value=mock_client):
        body = await oauth2_lib.exchange_token(req)
    assert body["access_token"] == "new-token"


@pytest.mark.asyncio
async def test_exchange_token_missing_access_token(oauth2_lib):
    req = TokenExchangeRequest(token_endpoint="https://issuer.example/token", client_id="cid", subject_token="subject")
    mock_response = MagicMock(status_code=200)
    mock_response.json.return_value = {"token_type": "Bearer"}
    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    with patch("mcpgateway.oauth2.base.get_http_client", new_callable=AsyncMock, return_value=mock_client):
        with pytest.raises(OAuth2TokenExchangeError, match="missing access_token"):
            await oauth2_lib.exchange_token(req)


@pytest.mark.asyncio
async def test_refresh_token_success(oauth2_lib):
    req = RefreshTokenRequest(token_endpoint="https://issuer.example/token", client_id="cid", client_secret="sec", refresh_token="rt-1", scope=["read"], resource=["https://rs.example"])
    mock_response = MagicMock(status_code=200)
    mock_response.json.return_value = {"access_token": "new-token", "refresh_token": "new-rt"}
    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    with patch("mcpgateway.oauth2.base.get_http_client", new_callable=AsyncMock, return_value=mock_client):
        body = await oauth2_lib.refresh_token(req)
    assert body["access_token"] == "new-token"


@pytest.mark.asyncio
async def test_refresh_token_missing_access_token(oauth2_lib):
    req = RefreshTokenRequest(token_endpoint="https://issuer.example/token", client_id="cid", refresh_token="rt-1")
    mock_response = MagicMock(status_code=200)
    mock_response.json.return_value = {"token_type": "Bearer"}
    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    with patch("mcpgateway.oauth2.base.get_http_client", new_callable=AsyncMock, return_value=mock_client):
        with pytest.raises(OAuth2TokenRefreshError, match="missing access_token"):
            await oauth2_lib.refresh_token(req)


def test_build_authorization_url_with_resource(oauth2_lib):
    url = oauth2_lib.build_authorization_url(
        authorization_endpoint="https://issuer.example/auth",
        client_id="cid",
        redirect_uri="https://app.example/cb",
        scope=["openid", "profile"],
        state="st",
        code_challenge="challenge",
        code_challenge_method="S256",
        resource=["https://resource-a.example", "https://resource-b.example"],
    )
    assert "resource=https%3A%2F%2Fresource-a.example" in url
    assert "resource=https%3A%2F%2Fresource-b.example" in url
