# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_oauth_manager.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for OAuthManager service.
"""

# Standard
import json
import logging
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import httpx
import pytest

# First-Party
from mcpgateway.services.oauth_manager import OAuthError, OAuthManager, parse_expires_in


@pytest.fixture
def oauth_manager():
    with patch("mcpgateway.services.oauth_manager.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(
            auth_encryption_secret=MagicMock(get_secret_value=MagicMock(return_value="test-secret")),
            cache_type="memory",
            redis_url=None,
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


# ---------- parse_expires_in ----------


@pytest.mark.parametrize(
    "value,expected",
    [
        (3600, 3600),
        ("3600", 3600),
        (3600.0, 3600),
        (0, 0),
    ],
)
def test_parse_expires_in_valid(value, expected):
    assert parse_expires_in({"expires_in": value}) == expected


def test_parse_expires_in_missing_returns_none():
    assert parse_expires_in({}) is None


def test_parse_expires_in_explicit_null_returns_none():
    assert parse_expires_in({"expires_in": None}) is None


@pytest.mark.parametrize("bad_value", [-1, -3600, "-1", -0.5, -3600.7])
def test_parse_expires_in_negative_raises(bad_value):
    """Negative numerics raise even when int() would silently truncate (-0.5 -> 0)."""
    with pytest.raises(OAuthError, match="negative"):
        parse_expires_in({"expires_in": bad_value})


@pytest.mark.parametrize("bad_value", ["garbage", "3600s", ""])
def test_parse_expires_in_garbage_string_raises(bad_value):
    with pytest.raises(OAuthError, match="Invalid expires_in"):
        parse_expires_in({"expires_in": bad_value})


@pytest.mark.parametrize("bad_value", [3600.5, 0.5, 3600.7])
def test_parse_expires_in_non_integer_float_raises(bad_value):
    """RFC 6749 §5.1 specifies integer seconds; non-integer floats are rejected."""
    with pytest.raises(OAuthError, match="non-integer"):
        parse_expires_in({"expires_in": bad_value})


@pytest.mark.parametrize("bad_value", [True, False, [3600], {"seconds": 3600}, object()])
def test_parse_expires_in_non_scalar_raises(bad_value):
    with pytest.raises(OAuthError, match="Invalid expires_in"):
        parse_expires_in({"expires_in": bad_value})


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
async def test_get_access_token_authorization_code_requires_consent(oauth_manager):
    with patch.object(oauth_manager, "_client_credentials_flow", new_callable=AsyncMock) as mock_client_flow:
        with pytest.raises(OAuthError, match="requires user consent"):
            await oauth_manager.get_access_token({"grant_type": "authorization_code"})
    mock_client_flow.assert_not_called()


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
        result = await oauth_manager._client_credentials_flow({"client_id": "cid", "client_secret": "short", "token_url": "https://auth/token"})
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
        result = await oauth_manager._client_credentials_flow({"client_id": "cid", "client_secret": "short", "token_url": "https://auth/token"})
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
        result = await oauth_manager._client_credentials_flow({"client_id": "cid", "client_secret": "short", "token_url": "https://auth/token", "scopes": ["read", "write"]})
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
        result = await oauth_manager._client_credentials_flow({"client_id": "cid", "client_secret": long_secret, "token_url": "https://auth/token"})
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
        result = await oauth_manager._client_credentials_flow({"client_id": "cid", "client_secret": "x" * 60, "token_url": "https://auth/token"})
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
        result = await oauth_manager._client_credentials_flow({"client_id": "cid", "client_secret": "x" * 60, "token_url": "https://auth/token"})
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
            await oauth_manager._client_credentials_flow({"client_id": "cid", "client_secret": "short", "token_url": "https://auth/token"})


@pytest.mark.asyncio
async def test_client_credentials_flow_http_error(oauth_manager):
    mock_client = AsyncMock()
    mock_client.post.side_effect = httpx.HTTPError("connection failed")
    with patch.object(oauth_manager, "_get_client", new_callable=AsyncMock, return_value=mock_client):
        with pytest.raises(OAuthError, match="Failed to obtain access token"):
            await oauth_manager._client_credentials_flow({"client_id": "cid", "client_secret": "short", "token_url": "https://auth/token"})


@pytest.mark.asyncio
async def test_client_credentials_flow_json_parse_failure(oauth_manager):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.headers = {"content-type": "text/html"}
    mock_response.json.side_effect = json.JSONDecodeError("bad json", "raw_response_text", 0)
    mock_response.text = "raw_response_text"

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    with patch.object(oauth_manager, "_get_client", new_callable=AsyncMock, return_value=mock_client):
        with pytest.raises(OAuthError, match="No access_token"):
            await oauth_manager._client_credentials_flow({"client_id": "cid", "client_secret": "short", "token_url": "https://auth/token"})


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
        result = await oauth_manager._password_flow({"client_id": "cid", "client_secret": "short", "token_url": "https://auth/token", "username": "user", "password": "pass"})
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
        result = await oauth_manager._password_flow({"client_id": "cid", "token_url": "https://auth/token", "username": "user", "password": "pass", "scopes": ["openid"]})
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
        result = await oauth_manager._password_flow({"client_id": "cid", "client_secret": "x" * 60, "token_url": "https://auth/token", "username": "user", "password": "pass"})
    assert result == "tok"


@pytest.mark.asyncio
async def test_password_flow_decrypts_encrypted_password(oauth_manager):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.headers = {"content-type": "application/json"}
    mock_response.json.return_value = {"access_token": "tok"}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    mock_enc = MagicMock()
    mock_enc.is_encrypted.side_effect = lambda value: value == "enc-password"
    mock_enc.decrypt_secret_async = AsyncMock(return_value="plain-password")

    with (
        patch.object(oauth_manager, "_get_client", new_callable=AsyncMock, return_value=mock_client),
        patch("mcpgateway.services.oauth_manager.get_settings") as mock_gs,
        patch("mcpgateway.services.oauth_manager.get_encryption_service", return_value=mock_enc),
    ):
        mock_gs.return_value = MagicMock(auth_encryption_secret="key")
        result = await oauth_manager._password_flow({"client_id": "cid", "token_url": "https://auth/token", "username": "user", "password": "enc-password"})

    assert result == "tok"
    posted_data = mock_client.post.await_args.kwargs["data"]
    assert posted_data["password"] == "plain-password"


@pytest.mark.asyncio
async def test_password_flow_encrypted_password_decrypt_returns_none(oauth_manager):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.headers = {"content-type": "application/json"}
    mock_response.json.return_value = {"access_token": "tok"}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    mock_enc = MagicMock()
    mock_enc.is_encrypted.side_effect = lambda value: value == "enc-password"
    mock_enc.decrypt_secret_async = AsyncMock(return_value=None)

    with (
        patch.object(oauth_manager, "_get_client", new_callable=AsyncMock, return_value=mock_client),
        patch("mcpgateway.services.oauth_manager.get_settings") as mock_gs,
        patch("mcpgateway.services.oauth_manager.get_encryption_service", return_value=mock_enc),
    ):
        mock_gs.return_value = MagicMock(auth_encryption_secret="key")
        result = await oauth_manager._password_flow({"client_id": "cid", "token_url": "https://auth/token", "username": "user", "password": "enc-password"})

    assert result == "tok"
    posted_data = mock_client.post.await_args.kwargs["data"]
    assert posted_data["password"] == "enc-password"


@pytest.mark.asyncio
async def test_password_flow_encrypted_password_decrypt_exception(oauth_manager):
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
        result = await oauth_manager._password_flow({"client_id": "cid", "token_url": "https://auth/token", "username": "user", "password": "enc-password"})

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
    mock_response.headers = {"content-type": "application/json"}
    mock_response.json.return_value = {"access_token": "new-tok", "refresh_token": "new-rt"}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    with patch.object(oauth_manager, "_get_client", new_callable=AsyncMock, return_value=mock_client):
        result = await oauth_manager.refresh_token("old-rt", {"client_id": "cid", "client_secret": "sec", "token_url": "https://auth/token"})
    assert result["access_token"] == "new-tok"


@pytest.mark.asyncio
async def test_refresh_token_form_encoded_response(oauth_manager):
    """Token endpoints that return application/x-www-form-urlencoded are parsed correctly."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"content-type": "application/x-www-form-urlencoded; charset=utf-8"}
    mock_response.text = "access_token=new-tok&token_type=bearer&refresh_token=new-rt&scope=repo"

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    with patch.object(oauth_manager, "_get_client", new_callable=AsyncMock, return_value=mock_client):
        result = await oauth_manager.refresh_token("old-rt", {"client_id": "cid", "client_secret": "sec", "token_url": "https://auth/token"})

    assert result["access_token"] == "new-tok"
    assert result["refresh_token"] == "new-rt"
    assert result["token_type"] == "bearer"
    # JSON parser must not be invoked for form-encoded responses
    mock_response.json.assert_not_called()


@pytest.mark.asyncio
async def test_refresh_token_form_encoded_mixed_case_content_type(oauth_manager):
    """Per RFC 7231, media types are case-insensitive — mixed-case Content-Type must still parse."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"content-type": "Application/X-WWW-Form-Urlencoded; Charset=UTF-8"}
    mock_response.text = "access_token=new-tok&token_type=bearer"

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    with patch.object(oauth_manager, "_get_client", new_callable=AsyncMock, return_value=mock_client):
        result = await oauth_manager.refresh_token("old-rt", {"client_id": "cid", "client_secret": "sec", "token_url": "https://auth/token"})

    assert result["access_token"] == "new-tok"
    mock_response.json.assert_not_called()


@pytest.mark.asyncio
async def test_refresh_token_form_encoded_url_decodes_values(oauth_manager):
    """Form-encoded values must be URL-decoded so callers see the spec-compliant value."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"content-type": "application/x-www-form-urlencoded"}
    mock_response.text = "access_token=new-tok&scope=repo%3Astatus+repo%3Adeployment"

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    with patch.object(oauth_manager, "_get_client", new_callable=AsyncMock, return_value=mock_client):
        result = await oauth_manager.refresh_token("old-rt", {"client_id": "cid", "client_secret": "sec", "token_url": "https://auth/token"})

    assert result["scope"] == "repo:status repo:deployment"


@pytest.mark.asyncio
async def test_refresh_token_non_json_non_form_raises(oauth_manager, caplog):
    """An unexpected response body falls back to raw capture, logs, and raises when access_token is absent."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"content-type": "text/plain"}
    mock_response.text = "something unexpected"
    mock_response.json.side_effect = json.JSONDecodeError("not JSON", "something unexpected", 0)

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    with patch.object(oauth_manager, "_get_client", new_callable=AsyncMock, return_value=mock_client):
        with caplog.at_level(logging.WARNING, logger="mcpgateway.services.oauth_manager"):
            with pytest.raises(OAuthError, match=r"No access_token.*raw_response.*something unexpected"):
                await oauth_manager.refresh_token("old-rt", {"client_id": "cid", "client_secret": "sec", "token_url": "https://auth/token"})

    # JSON path was attempted before the fallback ran
    assert mock_response.json.called
    # Parse failure was logged with diagnostic context
    assert any("Failed to parse OAuth token response as JSON" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_refresh_token_json_branch_parse_failure_logs_and_falls_back(oauth_manager, caplog):
    """A malformed body served as application/json must hit the JSON-branch fallback and log."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"content-type": "application/json"}
    mock_response.text = "<html>not json</html>"
    mock_response.json.side_effect = json.JSONDecodeError("Expecting value", "<html>not json</html>", 0)

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    with patch.object(oauth_manager, "_get_client", new_callable=AsyncMock, return_value=mock_client):
        with caplog.at_level(logging.WARNING, logger="mcpgateway.services.oauth_manager"):
            with pytest.raises(OAuthError, match=r"raw_response.*not json"):
                await oauth_manager.refresh_token("old-rt", {"client_id": "cid", "client_secret": "sec", "token_url": "https://auth/token"})

    assert mock_response.json.called
    assert any("Failed to parse OAuth token response as JSON" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_refresh_token_json_branch_unicode_decode_error_falls_back(oauth_manager, caplog):
    """A UnicodeDecodeError from response.json() (bad charset) must hit the same fallback as JSONDecodeError."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"content-type": "application/json"}
    mock_response.text = "<binary garbage>"
    mock_response.json.side_effect = UnicodeDecodeError("utf-8", b"\xff\xfe", 0, 1, "invalid start byte")

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    with patch.object(oauth_manager, "_get_client", new_callable=AsyncMock, return_value=mock_client):
        with caplog.at_level(logging.WARNING, logger="mcpgateway.services.oauth_manager"):
            with pytest.raises(OAuthError, match=r"raw_response.*binary garbage"):
                await oauth_manager.refresh_token("old-rt", {"client_id": "cid", "client_secret": "sec", "token_url": "https://auth/token"})

    assert mock_response.json.called
    assert any("Failed to parse OAuth token response as JSON" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_refresh_token_missing_content_type_header_uses_json_branch(oauth_manager):
    """When the content-type header is absent, the JSON branch must still parse a valid JSON body."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {}
    mock_response.json.return_value = {"access_token": "json-tok", "refresh_token": "json-rt"}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    with patch.object(oauth_manager, "_get_client", new_callable=AsyncMock, return_value=mock_client):
        result = await oauth_manager.refresh_token("old-rt", {"client_id": "cid", "client_secret": "sec", "token_url": "https://auth/token"})

    assert result["access_token"] == "json-tok"
    assert mock_response.json.called


@pytest.mark.asyncio
async def test_refresh_token_empty_form_body_raises_with_payload(oauth_manager):
    """An empty form-encoded body parses to an empty dict, surfaces via OAuthError with the payload."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"content-type": "application/x-www-form-urlencoded"}
    mock_response.text = ""

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    with patch.object(oauth_manager, "_get_client", new_callable=AsyncMock, return_value=mock_client):
        with pytest.raises(OAuthError, match=r"No access_token in refresh response: \{\}"):
            await oauth_manager.refresh_token("old-rt", {"client_id": "cid", "client_secret": "sec", "token_url": "https://auth/token"})
    mock_response.json.assert_not_called()


@pytest.mark.asyncio
async def test_refresh_token_error_redacts_secrets_in_token_response(oauth_manager):
    """A response missing access_token but carrying other tokens must not leak them via OAuthError."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"content-type": "application/json"}
    mock_response.json.return_value = {"id_token": "secret-id-jwt", "refresh_token": "secret-rt", "token_type": "bearer"}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    with patch.object(oauth_manager, "_get_client", new_callable=AsyncMock, return_value=mock_client):
        with pytest.raises(OAuthError) as exc_info:
            await oauth_manager.refresh_token("old-rt", {"client_id": "cid", "client_secret": "sec", "token_url": "https://auth/token"})

    msg = str(exc_info.value)
    assert "[REDACTED]" in msg
    assert "secret-id-jwt" not in msg
    assert "secret-rt" not in msg
    # Non-sensitive fields are preserved for diagnostics.
    assert "bearer" in msg


@pytest.mark.asyncio
async def test_refresh_token_error_truncates_long_raw_response(oauth_manager):
    """A long unparseable body must be truncated in the OAuthError to bound log size."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"content-type": "text/plain"}
    long_body = "X" * 1024
    mock_response.text = long_body
    mock_response.content = long_body.encode()
    mock_response.json.side_effect = json.JSONDecodeError("not JSON", long_body, 0)

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    with patch.object(oauth_manager, "_get_client", new_callable=AsyncMock, return_value=mock_client):
        with pytest.raises(OAuthError) as exc_info:
            await oauth_manager.refresh_token("old-rt", {"client_id": "cid", "client_secret": "sec", "token_url": "https://auth/token"})

    msg = str(exc_info.value)
    assert "[truncated, 1024 chars total]" in msg
    # The full body must NOT appear; only the leading slice does.
    assert long_body not in msg


@pytest.mark.asyncio
async def test_refresh_token_form_garbage_body_falls_back_to_raw_response(oauth_manager):
    """A form-encoded content-type with an HTML body (parses to {}) must surface the body via raw_response."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"content-type": "application/x-www-form-urlencoded"}
    mock_response.text = "<html><body>upstream error</body></html>"
    mock_response.content = mock_response.text.encode()

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    with patch.object(oauth_manager, "_get_client", new_callable=AsyncMock, return_value=mock_client):
        with pytest.raises(OAuthError, match=r"raw_response.*upstream error"):
            await oauth_manager.refresh_token("old-rt", {"client_id": "cid", "client_secret": "sec", "token_url": "https://auth/token"})
    mock_response.json.assert_not_called()


@pytest.mark.asyncio
async def test_refresh_token_decrypts_encrypted_client_secret(oauth_manager):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"access_token": "new-tok", "refresh_token": "new-rt"}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    mock_enc = MagicMock()
    mock_enc.is_encrypted.side_effect = lambda value: value == "enc-secret"
    mock_enc.decrypt_secret_async = AsyncMock(return_value="plain-secret")

    with (
        patch.object(oauth_manager, "_get_client", new_callable=AsyncMock, return_value=mock_client),
        patch("mcpgateway.services.oauth_manager.get_settings") as mock_gs,
        patch("mcpgateway.services.oauth_manager.get_encryption_service", return_value=mock_enc),
    ):
        mock_gs.return_value = MagicMock(auth_encryption_secret="key")
        result = await oauth_manager.refresh_token(
            "old-rt",
            {"client_id": "cid", "client_secret": "enc-secret", "token_url": "https://auth/token"},
        )

    assert result["access_token"] == "new-tok"
    posted_data = mock_client.post.await_args.kwargs["data"]
    assert posted_data["client_secret"] == "plain-secret"


@pytest.mark.asyncio
async def test_refresh_token_encrypted_client_secret_decrypt_returns_none(oauth_manager):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"access_token": "new-tok", "refresh_token": "new-rt"}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    mock_enc = MagicMock()
    mock_enc.is_encrypted.side_effect = lambda value: value == "enc-secret"
    mock_enc.decrypt_secret_async = AsyncMock(return_value=None)

    with (
        patch.object(oauth_manager, "_get_client", new_callable=AsyncMock, return_value=mock_client),
        patch("mcpgateway.services.oauth_manager.get_settings") as mock_gs,
        patch("mcpgateway.services.oauth_manager.get_encryption_service", return_value=mock_enc),
    ):
        mock_gs.return_value = MagicMock(auth_encryption_secret="key")
        result = await oauth_manager.refresh_token(
            "old-rt",
            {"client_id": "cid", "client_secret": "enc-secret", "token_url": "https://auth/token"},
        )

    assert result["access_token"] == "new-tok"
    posted_data = mock_client.post.await_args.kwargs["data"]
    assert posted_data["client_secret"] == "enc-secret"


@pytest.mark.asyncio
async def test_refresh_token_encrypted_client_secret_decrypt_exception(oauth_manager):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"access_token": "new-tok", "refresh_token": "new-rt"}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    with (
        patch.object(oauth_manager, "_get_client", new_callable=AsyncMock, return_value=mock_client),
        patch("mcpgateway.services.oauth_manager.get_settings") as mock_gs,
        patch("mcpgateway.services.oauth_manager.get_encryption_service", side_effect=RuntimeError("enc fail")),
    ):
        mock_gs.return_value = MagicMock(auth_encryption_secret="key")
        result = await oauth_manager.refresh_token(
            "old-rt",
            {"client_id": "cid", "client_secret": "enc-secret", "token_url": "https://auth/token"},
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
    mock_response.headers = {"content-type": "application/json"}
    mock_response.text = '{"error": "invalid_grant"}'
    mock_response.content = mock_response.text.encode()
    mock_response.json.return_value = {"error": "invalid_grant"}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    with patch.object(oauth_manager, "_get_client", new_callable=AsyncMock, return_value=mock_client):
        with pytest.raises(OAuthError, match=r"Refresh token invalid.*invalid_grant"):
            await oauth_manager.refresh_token("old-rt", {"client_id": "cid", "token_url": "https://auth/token"})


@pytest.mark.asyncio
async def test_refresh_token_401_error(oauth_manager):
    mock_response = MagicMock()
    mock_response.status_code = 401
    mock_response.headers = {"content-type": "application/json"}
    mock_response.text = '{"error": "unauthorized_client"}'
    mock_response.content = mock_response.text.encode()
    mock_response.json.return_value = {"error": "unauthorized_client"}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    with patch.object(oauth_manager, "_get_client", new_callable=AsyncMock, return_value=mock_client):
        with pytest.raises(OAuthError, match=r"Refresh token invalid.*unauthorized_client"):
            await oauth_manager.refresh_token("old-rt", {"client_id": "cid", "token_url": "https://auth/token"})


@pytest.mark.asyncio
async def test_refresh_token_4xx_redacts_echoed_refresh_token(oauth_manager):
    """If a provider echoes the refresh_token in the error body, OAuthError must not leak it."""
    mock_response = MagicMock()
    mock_response.status_code = 400
    mock_response.headers = {"content-type": "application/x-www-form-urlencoded"}
    mock_response.text = "error=invalid_grant&refresh_token=leaked-rt-value&client_secret=leaked-secret"
    mock_response.content = mock_response.text.encode()

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    with patch.object(oauth_manager, "_get_client", new_callable=AsyncMock, return_value=mock_client):
        with pytest.raises(OAuthError) as exc_info:
            await oauth_manager.refresh_token("old-rt", {"client_id": "cid", "token_url": "https://auth/token"})

    msg = str(exc_info.value)
    assert "[REDACTED]" in msg
    assert "leaked-rt-value" not in msg
    assert "leaked-secret" not in msg
    # Non-sensitive fields preserved for diagnostics.
    assert "invalid_grant" in msg


@pytest.mark.asyncio
async def test_refresh_token_4xx_form_encoded_html_with_equals_redacts_embedded_token(oauth_manager):
    """Form-encoded content-type with HTML containing '=' must not leak embedded tokens via OAuthError."""
    mock_response = MagicMock()
    mock_response.status_code = 400
    mock_response.headers = {"content-type": "application/x-www-form-urlencoded"}
    # parse_qsl would otherwise split this into garbage key/value pairs and surface
    # the embedded token verbatim. The key-shape check should reject the parse and
    # fall back to raw_response, which then truncates.
    long_body = '<html><meta charset="utf-8"><a href="https://evil.example/?token=secret-token-value-do-not-leak">' + ("X" * 1024) + "</a></html>"
    mock_response.text = long_body
    mock_response.content = long_body.encode()

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    with patch.object(oauth_manager, "_get_client", new_callable=AsyncMock, return_value=mock_client):
        with pytest.raises(OAuthError) as exc_info:
            await oauth_manager.refresh_token("old-rt", {"client_id": "cid", "token_url": "https://auth/token"})

    msg = str(exc_info.value)
    assert "secret-token-value-do-not-leak" not in msg
    assert "[truncated," in msg
    mock_response.json.assert_not_called()


@pytest.mark.asyncio
async def test_refresh_token_4xx_truncates_long_html_error_body(oauth_manager):
    """A 1KB HTML error page must be truncated in the OAuthError to bound log size."""
    mock_response = MagicMock()
    mock_response.status_code = 400
    mock_response.headers = {"content-type": "text/html"}
    long_body = "<html>" + ("E" * 1024) + "</html>"
    mock_response.text = long_body
    mock_response.content = long_body.encode()
    mock_response.json.side_effect = json.JSONDecodeError("not JSON", long_body, 0)

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    with patch.object(oauth_manager, "_get_client", new_callable=AsyncMock, return_value=mock_client):
        with pytest.raises(OAuthError) as exc_info:
            await oauth_manager.refresh_token("old-rt", {"client_id": "cid", "token_url": "https://auth/token"})

    msg = str(exc_info.value)
    assert "[truncated," in msg
    assert long_body not in msg


@pytest.mark.asyncio
async def test_refresh_token_no_access_token_in_response(oauth_manager):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"error": "missing_token"}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    with patch.object(oauth_manager, "_get_client", new_callable=AsyncMock, return_value=mock_client):
        with pytest.raises(OAuthError, match="No access_token"):
            await oauth_manager.refresh_token("old-rt", {"client_id": "cid", "token_url": "https://auth/token"})


@pytest.mark.asyncio
async def test_refresh_token_http_error(oauth_manager):
    mock_client = AsyncMock()
    mock_client.post.side_effect = httpx.HTTPError("timeout")
    with patch.object(oauth_manager, "_get_client", new_callable=AsyncMock, return_value=mock_client):
        with pytest.raises(OAuthError, match="Failed to refresh token"):
            await oauth_manager.refresh_token("old-rt", {"client_id": "cid", "token_url": "https://auth/token"})


@pytest.mark.asyncio
async def test_refresh_token_http_error_retries_with_backoff(oauth_manager):
    """HTTP errors trigger retry backoff before final failure."""
    oauth_manager.max_retries = 2
    mock_client = AsyncMock()
    mock_client.post.side_effect = httpx.HTTPError("timeout")

    with (
        patch.object(oauth_manager, "_get_client", new_callable=AsyncMock, return_value=mock_client),
        patch("mcpgateway.services.oauth_manager.asyncio.sleep", new=AsyncMock()) as sleep_mock,
    ):
        with pytest.raises(OAuthError, match="Failed to refresh token after 2 attempts"):
            await oauth_manager.refresh_token("old-rt", {"client_id": "cid", "token_url": "https://auth/token"})

    sleep_mock.assert_awaited_once_with(1)


@pytest.mark.asyncio
async def test_refresh_token_with_resource_string(oauth_manager):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"access_token": "new-tok"}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    with patch.object(oauth_manager, "_get_client", new_callable=AsyncMock, return_value=mock_client):
        result = await oauth_manager.refresh_token("old-rt", {"client_id": "cid", "token_url": "https://auth/token", "resource": "https://mcp.example.com"})
    assert result["access_token"] == "new-tok"


@pytest.mark.asyncio
async def test_refresh_token_with_resource_list(oauth_manager):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"access_token": "new-tok"}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    with patch.object(oauth_manager, "_get_client", new_callable=AsyncMock, return_value=mock_client):
        result = await oauth_manager.refresh_token("old-rt", {"client_id": "cid", "token_url": "https://auth/token", "resource": ["https://a.com", "https://b.com"]})
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


def test_generate_state_is_opaque_and_no_email_leak(oauth_manager):
    state = oauth_manager._generate_state("gw-1", "user@test.com")
    assert isinstance(state, str)
    assert "user@test.com" not in state
    assert "gw-1" not in state


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


def test_create_authorization_url_with_pkce_omits_resource_for_entra_v2_sovereign_scope_flow(oauth_manager):
    url = oauth_manager._create_authorization_url_with_pkce(
        {
            "client_id": "cid",
            "redirect_uri": "https://cb",
            "authorization_url": "https://login.microsoftonline.us/tenant-id/oauth2/v2.0/authorize",
            "scopes": ["openid", "profile"],
            "resource": "https://mcp.example.com",
        },
        state="st",
        code_challenge="ch",
        code_challenge_method="S256",
    )
    assert "scope=openid+profile" in url or "scope=openid%20profile" in url
    assert "resource=" not in url


def test_create_authorization_url_with_pkce_omits_resource_for_entra_v2_china_scope_flow(oauth_manager):
    url = oauth_manager._create_authorization_url_with_pkce(
        {
            "client_id": "cid",
            "redirect_uri": "https://cb",
            "authorization_url": "https://login.partner.microsoftonline.cn/tenant-id/oauth2/v2.0/authorize",
            "scopes": ["openid", "profile"],
            "resource": "https://mcp.example.com",
        },
        state="st",
        code_challenge="ch",
        code_challenge_method="S256",
    )
    assert "scope=openid+profile" in url or "scope=openid%20profile" in url
    assert "resource=" not in url


def test_create_authorization_url_keeps_resource_for_lookalike_host(oauth_manager):
    """Ensure a host like login.microsoftonline.evil.com is NOT treated as Entra."""
    url = oauth_manager._create_authorization_url_with_pkce(
        {
            "client_id": "cid",
            "redirect_uri": "https://cb",
            "authorization_url": "https://login.microsoftonline.evil.com/tenant-id/oauth2/v2.0/authorize",
            "scopes": ["openid"],
            "resource": "https://mcp.example.com",
        },
        state="st",
        code_challenge="ch",
        code_challenge_method="S256",
    )
    assert "resource=" in url


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


@pytest.mark.asyncio
async def test_resolve_gateway_id_from_state_uses_legacy_fallback(oauth_manager):
    # First-Party
    import mcpgateway.services.oauth_manager as om

    with (
        patch("mcpgateway.services.oauth_manager.get_settings", return_value=MagicMock(cache_type="memory")),
        patch.dict(om._oauth_states, {}, clear=True),
        patch.dict(om._oauth_state_lookup, {}, clear=True),
        patch.object(oauth_manager, "_extract_legacy_state_payload", return_value={"gateway_id": "legacy-gw"}) as mock_legacy,
    ):
        result = await oauth_manager.resolve_gateway_id_from_state("legacy-state", allow_legacy_fallback=True)

    assert result == "legacy-gw"
    mock_legacy.assert_called_once_with("legacy-state")


@pytest.mark.asyncio
async def test_resolve_gateway_id_from_state_skips_legacy_fallback_when_disabled(oauth_manager):
    # First-Party
    import mcpgateway.services.oauth_manager as om

    with (
        patch("mcpgateway.services.oauth_manager.get_settings", return_value=MagicMock(cache_type="memory")),
        patch.dict(om._oauth_states, {}, clear=True),
        patch.dict(om._oauth_state_lookup, {}, clear=True),
        patch.object(oauth_manager, "_extract_legacy_state_payload", return_value={"gateway_id": "legacy-gw"}) as mock_legacy,
    ):
        result = await oauth_manager.resolve_gateway_id_from_state("legacy-state", allow_legacy_fallback=False)

    assert result is None
    mock_legacy.assert_not_called()


# ---------- OAuthError ----------


def test_oauth_error():
    err = OAuthError("something failed")
    assert str(err) == "something failed"
    assert isinstance(err, Exception)


# ---------- _get_redis_client ----------


@pytest.mark.asyncio
async def test_get_redis_client_already_initialized():
    # First-Party
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
    # First-Party
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


# ---------- _safe_response_text / _redact_token_response ----------


class _FakeResponseTextRaises:
    """Minimal stand-in for httpx.Response whose .text raises on access."""

    def __init__(self, exc: BaseException, content: bytes):
        self._exc = exc
        self.content = content

    @property
    def text(self) -> str:
        raise self._exc


def test_safe_response_text_returns_placeholder_on_unicode_error():
    fake = _FakeResponseTextRaises(
        UnicodeDecodeError("utf-8", b"\xff\xfe", 0, 1, "invalid start byte"),
        b"\xff\xfe\x00\x01",
    )
    assert OAuthManager._safe_response_text(fake) == "<undecodable body, 4 bytes>"


def test_safe_response_text_returns_placeholder_on_lookup_error():
    fake = _FakeResponseTextRaises(LookupError("unknown encoding"), b"abc")
    assert OAuthManager._safe_response_text(fake) == "<undecodable body, 3 bytes>"


def test_parse_token_response_form_branch_handles_undecodable_body():
    """Form branch must not crash when response.text raises UnicodeDecodeError."""
    fake = _FakeResponseTextRaises(
        UnicodeDecodeError("utf-8", b"\xff\xfe", 0, 1, "invalid start byte"),
        b"\xff\xfe",
    )
    fake.headers = {"content-type": "application/x-www-form-urlencoded"}
    fake.status_code = 200
    result = OAuthManager._parse_token_response(fake)
    assert result == {"raw_response": "<undecodable body, 2 bytes>"}


def test_redact_token_response_redacts_known_secret_keys():
    payload = {
        "access_token": "AT",
        "refresh_token": "RT",
        "id_token": "ID",
        "client_secret": "CS",  # pragma: allowlist secret
        "password": "PW",  # pragma: allowlist secret
        "token_type": "bearer",
        "scope": "repo",
    }
    out = OAuthManager._redact_token_response(payload)
    for key in ("access_token", "refresh_token", "id_token", "client_secret", "password"):
        assert out[key] == "[REDACTED]"
    assert out["token_type"] == "bearer"
    assert out["scope"] == "repo"


def test_redact_token_response_truncates_long_raw_response():
    payload = {"raw_response": "X" * 1000}
    out = OAuthManager._redact_token_response(payload)
    assert out["raw_response"].startswith("X" * 256)
    assert "[truncated, 1000 chars total]" in out["raw_response"]
    assert "X" * 1000 not in out["raw_response"]


def test_redact_token_response_scrubs_embedded_url_param_secrets():
    """key=value leaks inside arbitrary string values (e.g. URLs in HTML) are redacted in place."""
    payload = {
        "raw_response": '<a href="https://evil.example/?access_token=AT123&code=C456&api_key=K789">click</a>',
        "error_description": "Try again with token=alsoLeaked",
    }
    out = OAuthManager._redact_token_response(payload)
    for leaked in ("AT123", "C456", "K789", "alsoLeaked"):
        assert leaked not in out["raw_response"] + out["error_description"]
    assert "access_token=[REDACTED]" in out["raw_response"]
    assert "code=[REDACTED]" in out["raw_response"]
    assert "api_key=[REDACTED]" in out["raw_response"]
    assert "token=[REDACTED]" in out["error_description"]


def test_redact_token_response_truncates_long_arbitrary_string_value():
    """Defense-in-depth: any long string value (not just raw_response) is capped."""
    payload = {"error_description": "stack trace: " + ("Y" * 1024), "error": "server_error"}
    out = OAuthManager._redact_token_response(payload)
    assert "[truncated," in out["error_description"]
    assert len(out["error_description"]) < 400  # cap (256) + truncation suffix
    assert out["error"] == "server_error"


def test_parse_token_response_form_with_garbage_keys_falls_back_to_raw_response():
    """An HTML body containing '=' must not leak through parse_qsl as garbage keys."""
    fake = MagicMock()
    fake.headers = {"content-type": "application/x-www-form-urlencoded"}
    fake.status_code = 400
    fake.text = '<html><meta charset="utf-8"><body>error</body></html>'
    fake.content = fake.text.encode()
    result = OAuthManager._parse_token_response(fake)
    assert result == {"raw_response": fake.text}


def test_redact_token_response_leaves_short_raw_response_intact():
    payload = {"raw_response": "short body"}
    out = OAuthManager._redact_token_response(payload)
    assert out == {"raw_response": "short body"}


def test_redact_token_response_returns_new_dict():
    """Caller-side guarantee: redaction must not mutate the input."""
    payload = {"access_token": "AT", "scope": "repo"}
    OAuthManager._redact_token_response(payload)
    assert payload["access_token"] == "AT"
