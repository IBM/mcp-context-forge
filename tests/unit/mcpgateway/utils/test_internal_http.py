# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/utils/test_internal_http.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for internal loopback HTTP helpers.
"""

# Standard
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.utils.internal_http import (
    _is_ssl_enabled,
    internal_loopback_base_url,
    internal_loopback_verify,
    post_internal_mcp_rpc_in_process,
    post_rpc_in_process,
)


class TestIsSSLEnabled:
    """Tests for _is_ssl_enabled() edge cases."""

    def test_ssl_true(self, monkeypatch):
        monkeypatch.setenv("SSL", "true")
        assert _is_ssl_enabled() is True

    def test_ssl_false(self, monkeypatch):
        monkeypatch.setenv("SSL", "false")
        assert _is_ssl_enabled() is False

    def test_ssl_unset(self, monkeypatch):
        monkeypatch.delenv("SSL", raising=False)
        assert _is_ssl_enabled() is False

    def test_ssl_empty_string(self, monkeypatch):
        monkeypatch.setenv("SSL", "")
        assert _is_ssl_enabled() is False

    def test_ssl_uppercase_not_truthy(self, monkeypatch):
        """Shell launchers use exact [[ "${SSL}" == "true" ]], so uppercase is not truthy."""
        monkeypatch.setenv("SSL", "TRUE")
        assert _is_ssl_enabled() is False

    def test_ssl_mixed_case_not_truthy(self, monkeypatch):
        """Only exact lowercase 'true' enables SSL, matching run-gunicorn.sh / run-granian.sh."""
        monkeypatch.setenv("SSL", "True")
        assert _is_ssl_enabled() is False

    def test_ssl_with_whitespace_not_truthy(self, monkeypatch):
        """Whitespace-padded values are not truthy, matching gunicorn.config.py and shell launchers."""
        monkeypatch.setenv("SSL", " true ")
        assert _is_ssl_enabled() is False

    def test_ssl_one_is_not_truthy(self, monkeypatch):
        """Only 'true' is accepted — '1' is not, matching gunicorn.config.py."""
        monkeypatch.setenv("SSL", "1")
        assert _is_ssl_enabled() is False

    def test_ssl_yes_is_not_truthy(self, monkeypatch):
        monkeypatch.setenv("SSL", "yes")
        assert _is_ssl_enabled() is False


class TestInternalLoopbackBaseUrl:
    """Tests for internal_loopback_base_url()."""

    def test_https_when_ssl_enabled(self, monkeypatch):
        monkeypatch.setenv("SSL", "true")
        monkeypatch.setattr("mcpgateway.utils.internal_http.settings.port", 4444)
        assert internal_loopback_base_url() == "https://127.0.0.1:4444"

    def test_http_when_ssl_disabled(self, monkeypatch):
        monkeypatch.setenv("SSL", "false")
        monkeypatch.setattr("mcpgateway.utils.internal_http.settings.port", 8000)
        assert internal_loopback_base_url() == "http://127.0.0.1:8000"

    def test_http_when_ssl_unset(self, monkeypatch):
        monkeypatch.delenv("SSL", raising=False)
        monkeypatch.setattr("mcpgateway.utils.internal_http.settings.port", 4444)
        assert internal_loopback_base_url() == "http://127.0.0.1:4444"

    def test_uses_configured_port(self, monkeypatch):
        monkeypatch.setenv("SSL", "false")
        monkeypatch.setattr("mcpgateway.utils.internal_http.settings.port", 9999)
        assert internal_loopback_base_url() == "http://127.0.0.1:9999"


class TestInternalLoopbackVerify:
    """Tests for internal_loopback_verify()."""

    def test_verify_disabled_when_ssl_enabled(self, monkeypatch):
        monkeypatch.setenv("SSL", "true")
        monkeypatch.setattr("mcpgateway.utils.internal_http.settings.port", 4444)
        assert internal_loopback_verify() is False

    def test_verify_enabled_when_ssl_disabled(self, monkeypatch):
        monkeypatch.setenv("SSL", "false")
        monkeypatch.setattr("mcpgateway.utils.internal_http.settings.port", 4444)
        assert internal_loopback_verify() is True

    def test_verify_enabled_when_ssl_unset(self, monkeypatch):
        monkeypatch.delenv("SSL", raising=False)
        monkeypatch.setattr("mcpgateway.utils.internal_http.settings.port", 4444)
        assert internal_loopback_verify() is True


class TestPostInProcessTransport:
    """Tests for the shared in-process ASGI dispatch (_post_in_process)."""

    @pytest.mark.asyncio
    async def test_dispatch_uses_loopback_asgi_transport(self, monkeypatch):
        """The in-process dispatch builds an ASGITransport against the app with a
        loopback client and POSTs the given path/content/headers via AsyncClient."""
        captured = {}

        def _fake_transport(*, app, client):
            captured["transport_app"] = app
            captured["transport_client"] = client
            return MagicMock(name="transport")

        fake_response = MagicMock(name="response")
        fake_client = MagicMock(name="client")
        fake_client.post = AsyncMock(return_value=fake_response)
        fake_client.__aenter__ = AsyncMock(return_value=fake_client)
        fake_client.__aexit__ = AsyncMock(return_value=False)

        def _fake_async_client(*, transport, base_url):
            captured["client_base_url"] = base_url
            return fake_client

        # Stub the app so we don't import the full FastAPI app for this unit test.
        monkeypatch.setattr("mcpgateway.main.app", MagicMock(name="app"), raising=False)
        monkeypatch.setattr("mcpgateway.utils.internal_http.httpx.ASGITransport", _fake_transport)
        monkeypatch.setattr("mcpgateway.utils.internal_http.httpx.AsyncClient", _fake_async_client)

        result = await post_rpc_in_process(content=b'{"jsonrpc":"2.0"}', headers={"x-forwarded-internally": "true"}, timeout=5.0)

        assert result is fake_response
        # Loopback client address is required by the trust/loop guards.
        assert captured["transport_client"] == ("127.0.0.1", 0)
        # Generic JSON-RPC path goes to public /rpc.
        post_args, post_kwargs = fake_client.post.call_args
        assert post_args[0] == "/rpc"
        assert post_kwargs["content"] == b'{"jsonrpc":"2.0"}'
        assert post_kwargs["headers"]["x-forwarded-internally"] == "true"
        assert post_kwargs["timeout"] == 5.0


class TestPostInternalMcpRpcInProcess:
    """Tests for the trusted-internal streamable dispatch helper."""

    @pytest.mark.asyncio
    async def test_builds_trust_headers_and_targets_internal_endpoint(self):
        """The helper targets /_internal/mcp/rpc with the affinity marker, HMAC,
        encoded auth-context, session id, preserved Authorization, and passthrough."""
        with (
            patch("mcpgateway.utils.internal_http._post_in_process", new=AsyncMock(return_value="resp")) as mock_dispatch,
            patch("mcpgateway.auth_context._expected_internal_mcp_runtime_auth_header", return_value="hmac-value"),
            patch("mcpgateway.utils.passthrough_headers.safe_extract_and_filter_for_loopback", return_value={"x-tenant": "acme"}),
        ):
            result = await post_internal_mcp_rpc_in_process(
                content=b'{"jsonrpc":"2.0","method":"tools/list"}',
                timeout=7.0,
                session_id="sess-1234",
                auth_context="encoded-ctx",
                original_headers={"authorization": "Bearer abc", "x-tenant": "acme"},
            )

        assert result == "resp"
        path, kwargs = mock_dispatch.call_args.args, mock_dispatch.call_args.kwargs
        assert path[0] == "/_internal/mcp/rpc"
        headers = kwargs["headers"]
        assert headers["x-contextforge-mcp-runtime"] == "affinity"
        assert headers["x-contextforge-mcp-runtime-auth"] == "hmac-value"
        assert headers["x-contextforge-auth-context"] == "encoded-ctx"
        assert headers["x-mcp-session-id"] == "sess-1234"
        assert headers["content-type"] == "application/json"
        # Authorization preserved (CSRF bearer short-circuit) and passthrough merged.
        assert headers["authorization"] == "Bearer abc"
        assert headers["x-tenant"] == "acme"
        assert kwargs["content"] == b'{"jsonrpc":"2.0","method":"tools/list"}'
        assert kwargs["timeout"] == 7.0

    @pytest.mark.asyncio
    async def test_missing_auth_context_still_produces_trust_headers(self):
        """With no auth-context/headers, the trust headers are still emitted (empty
        auth-context falls back to the endpoint's existing visibility rules)."""
        with (
            patch("mcpgateway.utils.internal_http._post_in_process", new=AsyncMock(return_value="resp")) as mock_dispatch,
            patch("mcpgateway.auth_context._expected_internal_mcp_runtime_auth_header", return_value="hmac-value"),
        ):
            await post_internal_mcp_rpc_in_process(content=b"{}", timeout=1.0)

        headers = mock_dispatch.call_args.kwargs["headers"]
        assert headers["x-contextforge-mcp-runtime"] == "affinity"
        assert headers["x-contextforge-auth-context"] == ""
        assert headers["x-mcp-session-id"] == ""
        # No original headers → no Authorization key.
        assert "authorization" not in headers
