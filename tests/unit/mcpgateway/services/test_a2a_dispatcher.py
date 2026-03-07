# Copyright (c) 2025 IBM Corp. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for A2A transport dispatch utilities (mcpgateway/services/a2a_dispatcher.py)."""

# Standard
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.services.a2a_dispatcher import (
    A2AAuthContext,
    A2ADispatchResult,
    build_dispatch_headers,
    dispatch_a2a_transport,
    prepare_rpc_params,
    resolve_a2a_auth,
)
from mcpgateway.services.a2a_errors import A2AAgentError


# ---------------------------------------------------------------------------
# prepare_rpc_params
# ---------------------------------------------------------------------------
class TestPrepareRpcParams:
    """Tests for prepare_rpc_params()."""

    def test_default_method_is_send_message(self):
        method, _ = prepare_rpc_params({"params": {"foo": 1}}, "a2a-jsonrpc")
        assert method == "SendMessage"

    def test_explicit_method_preserved(self):
        method, _ = prepare_rpc_params({"method": "GetTask", "params": {"id": "t1"}}, "a2a-jsonrpc")
        assert method == "GetTask"

    def test_params_extracted(self):
        _, params = prepare_rpc_params({"method": "GetTask", "params": {"id": "t1"}}, "a2a-jsonrpc")
        assert params == {"id": "t1"}

    def test_params_defaults_to_full_dict_when_no_params_key(self):
        input_dict = {"method": "SendMessage", "message": {"role": "user"}}
        _, params = prepare_rpc_params(input_dict, "a2a-jsonrpc")
        assert params == input_dict

    def test_non_dict_parameters(self):
        method, params = prepare_rpc_params("raw-string", "a2a-jsonrpc")
        assert method == "SendMessage"
        assert params == "raw-string"

    def test_query_convenience_wrapping(self):
        """Flat {query: "..."} gets wrapped into an A2A message."""
        _, params = prepare_rpc_params({"query": "hello"}, "a2a-jsonrpc")
        assert "message" in params
        msg = params["message"]
        assert msg["role"] == "user"
        assert msg["parts"] == [{"text": "hello"}]
        assert msg["messageId"].startswith("tool-")

    def test_query_not_wrapped_when_params_key_present(self):
        """When 'params' key exists, don't wrap."""
        _, params = prepare_rpc_params({"query": "hello", "params": {"x": 1}}, "a2a-jsonrpc")
        assert params == {"x": 1}

    def test_query_not_wrapped_when_message_key_present(self):
        """When 'message' key exists, don't wrap."""
        input_dict = {"query": "hello", "message": {"role": "user"}}
        _, params = prepare_rpc_params(input_dict, "a2a-jsonrpc")
        assert params == input_dict

    def test_query_not_wrapped_for_non_a2a_transport(self):
        """Only wrap for a2a-* transports."""
        _, params = prepare_rpc_params({"query": "hello"}, "rest-passthrough")
        assert "message" not in params

    def test_query_wrapping_for_a2a_rest(self):
        _, params = prepare_rpc_params({"query": "hello"}, "a2a-rest")
        assert "message" in params

    def test_query_wrapping_for_a2a_grpc(self):
        _, params = prepare_rpc_params({"query": "hello"}, "a2a-grpc")
        assert "message" in params

    def test_normalize_parts_fn_called(self):
        """normalize_parts_fn is applied to rpc_params."""
        normalizer = MagicMock(side_effect=lambda p: {**p, "normalized": True})
        _, params = prepare_rpc_params({"params": {"foo": 1}}, "a2a-jsonrpc", normalize_parts_fn=normalizer)
        normalizer.assert_called_once()
        assert params.get("normalized") is True

    def test_normalize_parts_fn_not_called_for_non_dict(self):
        normalizer = MagicMock()
        prepare_rpc_params("string-params", "a2a-jsonrpc", normalize_parts_fn=normalizer)
        normalizer.assert_not_called()

    @patch("mcpgateway.config.settings")
    def test_v03_method_rejected_when_compat_off(self, mock_settings):
        mock_settings.mcpgateway_a2a_v1_compat_mode = False
        with pytest.raises(A2AAgentError, match="v0.3 method name"):
            prepare_rpc_params({"method": "message/send"}, "a2a-jsonrpc")

    @patch("mcpgateway.config.settings")
    def test_v03_method_accepted_when_compat_on(self, mock_settings):
        mock_settings.mcpgateway_a2a_v1_compat_mode = True
        method, _ = prepare_rpc_params({"method": "message/send"}, "a2a-jsonrpc")
        assert method == "message/send"

    def test_pascal_case_method_always_accepted(self):
        """PascalCase methods should never be rejected regardless of compat mode."""
        method, _ = prepare_rpc_params({"method": "SendMessage"}, "a2a-jsonrpc")
        assert method == "SendMessage"


# ---------------------------------------------------------------------------
# build_dispatch_headers
# ---------------------------------------------------------------------------
class TestBuildDispatchHeaders:
    """Tests for build_dispatch_headers()."""

    def test_content_type_always_present(self):
        headers = build_dispatch_headers({}, "a2a-jsonrpc", "1.0")
        assert headers["Content-Type"] == "application/json"

    def test_auth_headers_merged(self):
        headers = build_dispatch_headers({"Authorization": "Bearer tok"}, "a2a-jsonrpc", "1.0")
        assert headers["Authorization"] == "Bearer tok"

    def test_a2a_version_for_rest_only(self):
        rest_headers = build_dispatch_headers({}, "a2a-rest", "1.0")
        assert rest_headers.get("A2A-Version") == "1.0"

        jsonrpc_headers = build_dispatch_headers({}, "a2a-jsonrpc", "1.0")
        assert "A2A-Version" not in jsonrpc_headers

    def test_correlation_id(self):
        headers = build_dispatch_headers({}, "a2a-jsonrpc", "1.0", correlation_id="corr-123")
        assert headers["X-Correlation-ID"] == "corr-123"

    def test_no_correlation_id_when_none(self):
        headers = build_dispatch_headers({}, "a2a-jsonrpc", "1.0")
        assert "X-Correlation-ID" not in headers

    def test_extra_headers_merged(self):
        headers = build_dispatch_headers({}, "a2a-jsonrpc", "1.0", extra_headers={"X-Custom": "val"})
        assert headers["X-Custom"] == "val"

    def test_extra_headers_override_defaults(self):
        headers = build_dispatch_headers({}, "a2a-jsonrpc", "1.0", extra_headers={"Content-Type": "text/plain"})
        assert headers["Content-Type"] == "text/plain"


# ---------------------------------------------------------------------------
# dispatch_a2a_transport
# ---------------------------------------------------------------------------
class TestDispatchA2ATransport:
    """Tests for dispatch_a2a_transport()."""

    @pytest.fixture
    def mock_client(self):
        client = MagicMock()
        response = MagicMock()
        response.status_code = 200
        client.post = AsyncMock(return_value=response)
        client.request = AsyncMock(return_value=response)
        return client

    @pytest.mark.asyncio
    async def test_jsonrpc_transport(self, mock_client):
        result = await dispatch_a2a_transport(
            endpoint_url="https://example.com/a2a",
            normalized_agent_type="a2a-jsonrpc",
            rpc_method="SendMessage",
            rpc_params={"message": {"role": "user"}},
            headers={"Content-Type": "application/json"},
            auth_headers={},
            http_client=mock_client,
        )
        assert result.transport == "a2a-jsonrpc"
        assert result.http_response is not None
        assert result.grpc_data is None

        call_kwargs = mock_client.post.call_args
        request_data = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert request_data["jsonrpc"] == "2.0"
        assert request_data["method"] == "SendMessage"
        assert "id" in request_data

    @pytest.mark.asyncio
    async def test_rest_transport(self, mock_client):
        build_fn = MagicMock(return_value=("POST", "https://example.com/message:send", {"msg": "hi"}, None))
        result = await dispatch_a2a_transport(
            endpoint_url="https://example.com/a2a",
            normalized_agent_type="a2a-rest",
            rpc_method="SendMessage",
            rpc_params={"message": {"role": "user"}},
            headers={},
            auth_headers={},
            http_client=mock_client,
            build_rest_request_fn=build_fn,
        )
        assert result.transport == "a2a-rest"
        assert result.http_response is not None
        build_fn.assert_called_once()

    @pytest.mark.asyncio
    async def test_rest_transport_requires_build_fn(self, mock_client):
        with pytest.raises(ValueError, match="build_rest_request_fn required"):
            await dispatch_a2a_transport(
                endpoint_url="https://example.com/a2a",
                normalized_agent_type="a2a-rest",
                rpc_method="SendMessage",
                rpc_params={},
                headers={},
                auth_headers={},
                http_client=mock_client,
            )

    @pytest.mark.asyncio
    async def test_passthrough_transport(self, mock_client):
        result = await dispatch_a2a_transport(
            endpoint_url="https://example.com/api",
            normalized_agent_type="rest-passthrough",
            rpc_method="SendMessage",
            rpc_params={"x": 1},
            headers={},
            auth_headers={},
            http_client=mock_client,
            parameters={"raw": "payload"},
        )
        assert result.transport == "rest-passthrough"
        # Should use parameters (not rpc_params) when provided
        call_kwargs = mock_client.post.call_args
        sent_json = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert sent_json == {"raw": "payload"}

    @pytest.mark.asyncio
    async def test_custom_transport(self, mock_client):
        result = await dispatch_a2a_transport(
            endpoint_url="https://example.com/custom",
            normalized_agent_type="custom",
            rpc_method="SendMessage",
            rpc_params={},
            headers={},
            auth_headers={},
            http_client=mock_client,
            parameters={"interaction_type": "analyze"},
            protocol_version="1.0",
        )
        assert result.transport == "custom"
        call_kwargs = mock_client.post.call_args
        sent_json = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert sent_json["interaction_type"] == "analyze"
        assert sent_json["protocol_version"] == "1.0"

    @pytest.mark.asyncio
    async def test_grpc_transport(self):
        grpc_fn = AsyncMock(return_value={"result": "ok"})
        mock_client = MagicMock()
        result = await dispatch_a2a_transport(
            endpoint_url="grpc://example.com:50051",
            normalized_agent_type="a2a-grpc",
            rpc_method="SendMessage",
            rpc_params={"message": {"role": "user"}},
            headers={},
            auth_headers={"Authorization": "Bearer tok"},
            http_client=mock_client,
            invoke_grpc_fn=grpc_fn,
            correlation_id="corr-1",
        )
        assert result.transport == "a2a-grpc"
        assert result.grpc_data == {"result": "ok"}
        assert result.http_response is None
        grpc_fn.assert_called_once()

    @pytest.mark.asyncio
    async def test_grpc_transport_requires_invoke_fn(self, mock_client):
        with pytest.raises(ValueError, match="invoke_grpc_fn required"):
            await dispatch_a2a_transport(
                endpoint_url="grpc://example.com",
                normalized_agent_type="a2a-grpc",
                rpc_method="SendMessage",
                rpc_params={},
                headers={},
                auth_headers={},
                http_client=mock_client,
            )

    @pytest.mark.asyncio
    async def test_unsupported_transport_raises(self, mock_client):
        with pytest.raises(A2AAgentError, match="Unsupported A2A transport"):
            await dispatch_a2a_transport(
                endpoint_url="https://example.com",
                normalized_agent_type="unknown-transport",
                rpc_method="SendMessage",
                rpc_params={},
                headers={},
                auth_headers={},
                http_client=mock_client,
            )

    @pytest.mark.asyncio
    async def test_timeout_applied_to_jsonrpc(self, mock_client):
        """When timeout is provided, asyncio.wait_for wraps the call."""
        result = await dispatch_a2a_transport(
            endpoint_url="https://example.com/a2a",
            normalized_agent_type="a2a-jsonrpc",
            rpc_method="SendMessage",
            rpc_params={},
            headers={},
            auth_headers={},
            http_client=mock_client,
            timeout=30.0,
        )
        assert result.http_response is not None

    @pytest.mark.asyncio
    async def test_dispatch_rejects_invalid_url_scheme(self, mock_client):
        """dispatch_a2a_transport raises A2AAgentError for file:// URLs."""
        with pytest.raises(A2AAgentError, match="Unsupported URL scheme"):
            await dispatch_a2a_transport(
                endpoint_url="file:///etc/passwd",
                normalized_agent_type="a2a-jsonrpc",
                rpc_method="SendMessage",
                rpc_params={},
                headers={},
                auth_headers={},
                http_client=mock_client,
            )


# ---------------------------------------------------------------------------
# A2AAuthContext / A2ADispatchResult dataclasses
# ---------------------------------------------------------------------------
class TestDataclasses:
    """Tests for A2AAuthContext and A2ADispatchResult dataclasses."""

    def test_auth_context_defaults(self):
        ctx = A2AAuthContext()
        assert ctx.headers == {}
        assert ctx.endpoint_url == ""
        assert ctx.query_params_decrypted is None

    def test_auth_context_with_values(self):
        ctx = A2AAuthContext(
            headers={"Authorization": "Bearer tok"},
            endpoint_url="https://example.com",
            query_params_decrypted={"key": "val"},
        )
        assert ctx.headers["Authorization"] == "Bearer tok"
        assert ctx.endpoint_url == "https://example.com"
        assert ctx.query_params_decrypted == {"key": "val"}

    def test_dispatch_result_defaults(self):
        result = A2ADispatchResult()
        assert result.http_response is None
        assert result.grpc_data is None
        assert result.transport == ""

    def test_dispatch_result_with_http(self):
        mock_resp = MagicMock()
        result = A2ADispatchResult(http_response=mock_resp, transport="a2a-jsonrpc")
        assert result.http_response is mock_resp
        assert result.grpc_data is None

    def test_dispatch_result_with_grpc(self):
        result = A2ADispatchResult(grpc_data={"result": "ok"}, transport="a2a-grpc")
        assert result.grpc_data == {"result": "ok"}
        assert result.http_response is None


# ---------------------------------------------------------------------------
# resolve_a2a_auth
# ---------------------------------------------------------------------------
class TestResolveA2AAuth:
    """Tests for resolve_a2a_auth()."""

    @pytest.mark.asyncio
    async def test_no_auth(self):
        """All auth params are None — returns empty headers, original URL."""
        ctx = await resolve_a2a_auth(
            endpoint_url="https://example.com/a2a",
            auth_type=None,
            auth_value=None,
            auth_query_params=None,
            oauth_config=None,
        )
        assert ctx.headers == {}
        assert ctx.endpoint_url == "https://example.com/a2a"
        assert ctx.query_params_decrypted is None

    @pytest.mark.asyncio
    @patch("mcpgateway.utils.url_auth.apply_query_param_auth", return_value="https://example.com/a2a?key=decrypted")
    @patch("mcpgateway.utils.services_auth.decode_auth", return_value={"api_key": "decrypted"})
    async def test_query_param_auth(self, mock_decode, mock_apply):
        """auth_type='query_param' with encrypted query params — URL is modified."""
        ctx = await resolve_a2a_auth(
            endpoint_url="https://example.com/a2a",
            auth_type="query_param",
            auth_value=None,
            auth_query_params={"api_key": "encrypted-value"},
            oauth_config=None,
        )
        mock_decode.assert_called_once_with("encrypted-value")
        mock_apply.assert_called_once()
        assert ctx.endpoint_url == "https://example.com/a2a?key=decrypted"
        assert ctx.query_params_decrypted == {"api_key": "decrypted"}

    @pytest.mark.asyncio
    @patch("mcpgateway.utils.services_auth.decode_auth", side_effect=Exception("decrypt failed"))
    async def test_query_param_decrypt_failure(self, mock_decode):
        """Decrypt fails — logs warning, URL unchanged."""
        ctx = await resolve_a2a_auth(
            endpoint_url="https://example.com/a2a",
            auth_type="query_param",
            auth_value=None,
            auth_query_params={"api_key": "bad-encrypted"},
            oauth_config=None,
            agent_name="test-agent",
        )
        # URL should remain unchanged since decryption failed and no params decrypted.
        assert ctx.endpoint_url == "https://example.com/a2a"
        assert ctx.query_params_decrypted == {}

    @pytest.mark.asyncio
    @patch("mcpgateway.utils.services_auth.decode_auth", return_value={"Authorization": "Basic dXNlcjpwYXNz"})
    async def test_basic_auth_encrypted(self, mock_decode):
        """auth_type='basic', encrypted string auth_value — decrypts to headers."""
        ctx = await resolve_a2a_auth(
            endpoint_url="https://example.com/a2a",
            auth_type="basic",
            auth_value="encrypted-basic-value",
            auth_query_params=None,
            oauth_config=None,
        )
        mock_decode.assert_called_once_with("encrypted-basic-value")
        assert ctx.headers == {"Authorization": "Basic dXNlcjpwYXNz"}

    @pytest.mark.asyncio
    @patch("mcpgateway.utils.services_auth.decode_auth", return_value={"Authorization": "Bearer my-token"})
    async def test_bearer_auth_encrypted(self, mock_decode):
        """auth_type='bearer', encrypted string — decrypts to Bearer header."""
        ctx = await resolve_a2a_auth(
            endpoint_url="https://example.com/a2a",
            auth_type="bearer",
            auth_value="encrypted-bearer-value",
            auth_query_params=None,
            oauth_config=None,
        )
        mock_decode.assert_called_once_with("encrypted-bearer-value")
        assert ctx.headers == {"Authorization": "Bearer my-token"}

    @pytest.mark.asyncio
    async def test_authheaders_dict_value(self):
        """auth_type='authheaders', dict auth_value — used directly as headers."""
        auth_dict = {"X-Custom-Auth": "secret123", "X-API-Key": "key456"}
        ctx = await resolve_a2a_auth(
            endpoint_url="https://example.com/a2a",
            auth_type="authheaders",
            auth_value=auth_dict,
            auth_query_params=None,
            oauth_config=None,
        )
        assert ctx.headers == {"X-Custom-Auth": "secret123", "X-API-Key": "key456"}

    @pytest.mark.asyncio
    @patch("mcpgateway.utils.services_auth.decode_auth", side_effect=Exception("decrypt failed"))
    async def test_basic_auth_fallback_raw_enabled(self, mock_decode):
        """Decrypt fails, fallback_raw_auth=True — uses raw value with 'Basic' prefix."""
        ctx = await resolve_a2a_auth(
            endpoint_url="https://example.com/a2a",
            auth_type="basic",
            auth_value="dXNlcjpwYXNz",
            auth_query_params=None,
            oauth_config=None,
            fallback_raw_auth=True,
        )
        assert ctx.headers == {"Authorization": "Basic dXNlcjpwYXNz"}

    @pytest.mark.asyncio
    @patch("mcpgateway.utils.services_auth.decode_auth", side_effect=Exception("decrypt failed"))
    async def test_bearer_auth_fallback_raw_enabled(self, mock_decode):
        """Decrypt fails, fallback_raw_auth=True — uses raw value with 'Bearer' prefix."""
        ctx = await resolve_a2a_auth(
            endpoint_url="https://example.com/a2a",
            auth_type="bearer",
            auth_value="raw-token-value",
            auth_query_params=None,
            oauth_config=None,
            fallback_raw_auth=True,
        )
        assert ctx.headers == {"Authorization": "Bearer raw-token-value"}

    @pytest.mark.asyncio
    @patch("mcpgateway.utils.services_auth.decode_auth", side_effect=Exception("decrypt failed"))
    async def test_basic_auth_fallback_raw_disabled(self, mock_decode):
        """Decrypt fails, fallback_raw_auth=False — raises error_cls."""
        with pytest.raises(A2AAgentError, match="Failed to decrypt authentication"):
            await resolve_a2a_auth(
                endpoint_url="https://example.com/a2a",
                auth_type="basic",
                auth_value="bad-encrypted",
                auth_query_params=None,
                oauth_config=None,
                error_cls=A2AAgentError,
                fallback_raw_auth=False,
            )

    @pytest.mark.asyncio
    async def test_api_key_auth(self):
        """auth_type='api_key' with string value — adds Bearer header."""
        ctx = await resolve_a2a_auth(
            endpoint_url="https://example.com/a2a",
            auth_type="api_key",
            auth_value="my-api-key-123",
            auth_query_params=None,
            oauth_config=None,
        )
        assert ctx.headers == {"Authorization": "Bearer my-api-key-123"}

    @pytest.mark.asyncio
    async def test_token_auth(self):
        """auth_type='token' with string value — adds Bearer header."""
        ctx = await resolve_a2a_auth(
            endpoint_url="https://example.com/a2a",
            auth_type="token",
            auth_value="my-token-456",
            auth_query_params=None,
            oauth_config=None,
        )
        assert ctx.headers == {"Authorization": "Bearer my-token-456"}

    @pytest.mark.asyncio
    @patch("mcpgateway.services.oauth_manager.OAuthManager")
    async def test_oauth_auth(self, mock_oauth_cls):
        """auth_type='oauth' with oauth_config — calls OAuthManager, adds Bearer header."""
        mock_instance = MagicMock()
        mock_instance.get_access_token = AsyncMock(return_value="oauth-access-token")
        mock_oauth_cls.return_value = mock_instance

        oauth_config = {"token_url": "https://auth.example.com/token", "client_id": "cid"}
        ctx = await resolve_a2a_auth(
            endpoint_url="https://example.com/a2a",
            auth_type="oauth",
            auth_value=None,
            auth_query_params=None,
            oauth_config=oauth_config,
        )
        mock_instance.get_access_token.assert_called_once_with(oauth_config)
        assert ctx.headers["Authorization"] == "Bearer oauth-access-token"

    @pytest.mark.asyncio
    @patch("mcpgateway.services.oauth_manager.OAuthManager")
    async def test_oauth_failure(self, mock_oauth_cls):
        """OAuthManager raises — raises error_cls."""
        mock_instance = MagicMock()
        mock_instance.get_access_token = AsyncMock(side_effect=Exception("token fetch failed"))
        mock_oauth_cls.return_value = mock_instance

        oauth_config = {"token_url": "https://auth.example.com/token"}
        with pytest.raises(A2AAgentError, match="OAuth authentication failed"):
            await resolve_a2a_auth(
                endpoint_url="https://example.com/a2a",
                auth_type="oauth",
                auth_value=None,
                auth_query_params=None,
                oauth_config=oauth_config,
                error_cls=A2AAgentError,
            )
