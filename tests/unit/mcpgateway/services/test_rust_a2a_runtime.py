# -*- coding: utf-8 -*-
"""Tests for mcpgateway.services.rust_a2a_runtime."""

# Standard
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import httpx
import pytest

# First-Party
from mcpgateway.services.a2a_protocol import PreparedA2AInvocation
from mcpgateway.services.rust_a2a_runtime import (
    _build_runtime_invoke_url,
    get_rust_a2a_runtime_client,
    RustA2ARuntimeClient,
    RustA2ARuntimeError,
)


@pytest.fixture
def sample_prepared():
    """A minimal PreparedA2AInvocation for testing."""
    return PreparedA2AInvocation(
        endpoint_url="https://agent.test/",
        sanitized_endpoint_url="https://agent.test/",
        headers={"Content-Type": "application/json"},
        request_data={"jsonrpc": "2.0", "method": "SendMessage", "params": {}, "id": 1},
        protocol_version_header="1.0",
        uses_jsonrpc=True,
    )


# ── _build_runtime_invoke_url ────────────────────────────────────────────────


class TestBuildRuntimeInvokeUrl:
    def test_default_url(self):
        with patch("mcpgateway.services.rust_a2a_runtime.settings") as mock_settings:
            mock_settings.experimental_rust_a2a_runtime_url = "http://127.0.0.1:8788"
            url = _build_runtime_invoke_url()
            assert url == "http://127.0.0.1:8788/invoke"

    def test_url_with_base_path(self):
        with patch("mcpgateway.services.rust_a2a_runtime.settings") as mock_settings:
            mock_settings.experimental_rust_a2a_runtime_url = "http://127.0.0.1:8788/a2a"
            url = _build_runtime_invoke_url()
            assert url == "http://127.0.0.1:8788/a2a/invoke"

    def test_url_with_trailing_slash(self):
        with patch("mcpgateway.services.rust_a2a_runtime.settings") as mock_settings:
            mock_settings.experimental_rust_a2a_runtime_url = "http://127.0.0.1:8788/"
            url = _build_runtime_invoke_url()
            assert url == "http://127.0.0.1:8788/invoke"


# ── get_rust_a2a_runtime_client ──────────────────────────────────────────────


class TestGetRustA2ARuntimeClient:
    def test_returns_singleton(self):
        with patch("mcpgateway.services.rust_a2a_runtime._rust_a2a_runtime_client", None):
            client1 = get_rust_a2a_runtime_client()
            assert isinstance(client1, RustA2ARuntimeClient)

    def test_returns_same_instance(self):
        with patch("mcpgateway.services.rust_a2a_runtime._rust_a2a_runtime_client", None):
            client1 = get_rust_a2a_runtime_client()
            with patch("mcpgateway.services.rust_a2a_runtime._rust_a2a_runtime_client", client1):
                client2 = get_rust_a2a_runtime_client()
            assert client1 is client2


# ── RustA2ARuntimeClient ─────────────────────────────────────────────────────


class TestRustA2ARuntimeClient:
    @pytest.mark.asyncio
    async def test_invoke_success(self, sample_prepared):
        """Successful invoke returns parsed JSON dict."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status_code": 200, "json": {"ok": True}, "text": ""}
        mock_response.text = '{"status_code": 200}'

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        client = RustA2ARuntimeClient()
        with patch.object(client, "_get_runtime_client", return_value=mock_client):
            result = await client.invoke(sample_prepared, timeout_seconds=10.0)

        assert result == {"status_code": 200, "json": {"ok": True}, "text": ""}
        call_kwargs = mock_client.post.call_args
        assert call_kwargs.kwargs["json"]["endpoint_url"] == "https://agent.test/"
        assert call_kwargs.kwargs["json"]["timeout_seconds"] == 10.0
        assert call_kwargs.kwargs["follow_redirects"] is False

    @pytest.mark.asyncio
    async def test_invoke_uses_default_timeout(self, sample_prepared):
        """When no timeout_seconds given, uses settings default."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": True}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        client = RustA2ARuntimeClient()
        with (
            patch.object(client, "_get_runtime_client", return_value=mock_client),
            patch("mcpgateway.services.rust_a2a_runtime.settings") as mock_settings,
        ):
            mock_settings.experimental_rust_a2a_runtime_timeout_seconds = 25
            mock_settings.experimental_rust_a2a_runtime_url = "http://127.0.0.1:8788"
            await client.invoke(sample_prepared)

        call_kwargs = mock_client.post.call_args
        assert call_kwargs.kwargs["json"]["timeout_seconds"] == 25.0

    @pytest.mark.asyncio
    async def test_invoke_http_error_raises(self, sample_prepared):
        """Non-200 response raises RustA2ARuntimeError."""
        mock_response = MagicMock()
        mock_response.status_code = 502
        mock_response.text = "Bad Gateway"

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        client = RustA2ARuntimeClient()
        with patch.object(client, "_get_runtime_client", return_value=mock_client):
            with pytest.raises(RustA2ARuntimeError, match="HTTP 502") as exc_info:
                await client.invoke(sample_prepared)
            assert exc_info.value.is_timeout is False

    @pytest.mark.asyncio
    async def test_invoke_504_sets_is_timeout_true(self, sample_prepared):
        """Regression: upstream 504 must set is_timeout so callers route it correctly."""
        mock_response = MagicMock()
        mock_response.status_code = 504
        mock_response.text = "Gateway Timeout"

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        client = RustA2ARuntimeClient()
        with patch.object(client, "_get_runtime_client", return_value=mock_client):
            with pytest.raises(RustA2ARuntimeError, match="HTTP 504") as exc_info:
                await client.invoke(sample_prepared)
            assert exc_info.value.is_timeout is True

    @pytest.mark.asyncio
    async def test_invoke_connect_error_wraps_as_runtime_error(self, sample_prepared):
        """Rust sidecar unreachable (process down, socket missing) surfaces as RustA2ARuntimeError.

        Without the wrap, the caller's ``except RustA2ARuntimeError`` branch
        is bypassed and an uncaught httpx exception propagates as an opaque
        500 — making a missing sidecar indistinguishable from a Python-side
        bug.  ``is_timeout=False`` so the caller does not retry as if it
        were a transient slow response.
        """
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.ConnectError("Connection refused")

        client = RustA2ARuntimeClient()
        with patch.object(client, "_get_runtime_client", return_value=mock_client):
            with pytest.raises(RustA2ARuntimeError, match="unreachable") as exc_info:
                await client.invoke(sample_prepared)
            assert exc_info.value.is_timeout is False

    @pytest.mark.asyncio
    async def test_invoke_connect_timeout_flags_is_timeout(self, sample_prepared):
        """A ConnectTimeout is timeout-shaped and must set ``is_timeout=True``."""
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.ConnectTimeout("Connect phase timed out")

        client = RustA2ARuntimeClient()
        with patch.object(client, "_get_runtime_client", return_value=mock_client):
            with pytest.raises(RustA2ARuntimeError, match="unreachable") as exc_info:
                await client.invoke(sample_prepared)
            assert exc_info.value.is_timeout is True

    @pytest.mark.asyncio
    async def test_invoke_read_timeout_wraps_with_is_timeout(self, sample_prepared):
        """ReadTimeout (slow sidecar response) surfaces as ``is_timeout=True``.

        Callers rely on ``is_timeout`` to decide retry vs. fail-fast; an
        uncaught ``httpx.ReadTimeout`` would bypass that signal.
        """
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.ReadTimeout("Read timed out")

        client = RustA2ARuntimeClient()
        with patch.object(client, "_get_runtime_client", return_value=mock_client):
            with pytest.raises(RustA2ARuntimeError, match="timed out") as exc_info:
                await client.invoke(sample_prepared)
            assert exc_info.value.is_timeout is True

    @pytest.mark.asyncio
    async def test_invoke_pool_timeout_wraps_with_is_timeout(self, sample_prepared):
        """PoolTimeout (exhausted connection pool) also surfaces as is_timeout."""
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.PoolTimeout("no connections available")

        client = RustA2ARuntimeClient()
        with patch.object(client, "_get_runtime_client", return_value=mock_client):
            with pytest.raises(RustA2ARuntimeError, match="timed out") as exc_info:
                await client.invoke(sample_prepared)
            assert exc_info.value.is_timeout is True

    @pytest.mark.asyncio
    async def test_invoke_remote_protocol_error_wraps_as_transport_error(self, sample_prepared):
        """Other httpx transport errors (ReadError, RemoteProtocolError, ...) also wrap.

        Without this catch-all, sidecar crashes mid-response would propagate
        as uncaught httpx exceptions — bypassing the caller's
        ``except RustA2ARuntimeError`` branch entirely.
        """
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.RemoteProtocolError("peer closed connection")

        client = RustA2ARuntimeClient()
        with patch.object(client, "_get_runtime_client", return_value=mock_client):
            with pytest.raises(RustA2ARuntimeError, match="transport error") as exc_info:
                await client.invoke(sample_prepared)
            assert exc_info.value.is_timeout is False

    @pytest.mark.asyncio
    async def test_invoke_invalid_json_raises(self, sample_prepared):
        """Invalid JSON response raises RustA2ARuntimeError."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("invalid json")

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        client = RustA2ARuntimeClient()
        with patch.object(client, "_get_runtime_client", return_value=mock_client):
            with pytest.raises(RustA2ARuntimeError, match="invalid JSON"):
                await client.invoke(sample_prepared)

    @pytest.mark.asyncio
    async def test_invoke_non_dict_payload_raises(self, sample_prepared):
        """Non-dict JSON payload raises RustA2ARuntimeError."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [1, 2, 3]

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        client = RustA2ARuntimeClient()
        with patch.object(client, "_get_runtime_client", return_value=mock_client):
            with pytest.raises(RustA2ARuntimeError, match="non-object"):
                await client.invoke(sample_prepared)

    @pytest.mark.asyncio
    async def test_get_runtime_client_returns_shared_http_client_when_no_uds(self):
        """Without UDS configured, returns the shared HTTP client."""
        mock_shared_client = AsyncMock()
        client = RustA2ARuntimeClient()
        with (
            patch("mcpgateway.services.rust_a2a_runtime.settings") as mock_settings,
            patch("mcpgateway.services.rust_a2a_runtime.get_http_client", return_value=mock_shared_client),
        ):
            mock_settings.experimental_rust_a2a_runtime_uds = None
            result = await client._get_runtime_client()
            assert result is mock_shared_client

    @pytest.mark.asyncio
    async def test_get_runtime_client_creates_uds_client(self):
        """With UDS configured, lazily creates a UDS transport client."""
        client = RustA2ARuntimeClient()
        assert client._uds_client is None

        with (
            patch("mcpgateway.services.rust_a2a_runtime.settings") as mock_settings,
            patch("mcpgateway.services.rust_a2a_runtime.get_http_limits") as mock_limits,
        ):
            mock_settings.experimental_rust_a2a_runtime_uds = "/tmp/test.sock"
            mock_settings.experimental_rust_a2a_runtime_timeout_seconds = 30
            mock_limits.return_value = httpx.Limits()
            uds_client = await client._get_runtime_client()
            assert uds_client is not None
            assert client._uds_client is uds_client

            # Second call returns the same instance
            uds_client2 = await client._get_runtime_client()
            assert uds_client2 is uds_client

        await uds_client.aclose()

    @pytest.mark.asyncio
    async def test_invoke_sends_encrypted_auth_fields(self):
        """Encrypted auth blobs are forwarded in the JSON payload to the Rust sidecar."""
        prepared = PreparedA2AInvocation(
            endpoint_url="https://agent.test/?api_key=decrypted",
            sanitized_endpoint_url="https://agent.test/?api_key=REDACTED",
            headers={"Content-Type": "application/json"},
            request_data={"jsonrpc": "2.0", "method": "SendMessage", "params": {}, "id": 1},
            protocol_version_header="1.0",
            uses_jsonrpc=True,
            base_endpoint_url="https://agent.test/",
            auth_value_encrypted="enc-bearer-blob",
            auth_query_params_encrypted={"api_key": "enc-qp-blob"},  # pragma: allowlist secret
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": True}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        client = RustA2ARuntimeClient()
        with patch.object(client, "_get_runtime_client", return_value=mock_client):
            await client.invoke(prepared, timeout_seconds=5.0)

        call_kwargs = mock_client.post.call_args
        payload = call_kwargs.kwargs["json"]
        assert payload["auth_headers_encrypted"] == "enc-bearer-blob"
        assert payload["auth_query_params_encrypted"] == {"api_key": "enc-qp-blob"}  # pragma: allowlist secret

    @pytest.mark.asyncio
    async def test_invoke_uses_base_endpoint_url_when_available(self):
        """When base_endpoint_url is set, it is used as the endpoint_url in the payload."""
        prepared = PreparedA2AInvocation(
            endpoint_url="https://agent.test/?api_key=decrypted",
            sanitized_endpoint_url="https://agent.test/?api_key=REDACTED",
            headers={"Content-Type": "application/json"},
            request_data={"jsonrpc": "2.0", "method": "SendMessage", "params": {}, "id": 1},
            protocol_version_header="1.0",
            uses_jsonrpc=True,
            base_endpoint_url="https://agent.test/",
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": True}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        client = RustA2ARuntimeClient()
        with patch.object(client, "_get_runtime_client", return_value=mock_client):
            await client.invoke(prepared, timeout_seconds=5.0)

        call_kwargs = mock_client.post.call_args
        payload = call_kwargs.kwargs["json"]
        # base_endpoint_url should be used instead of the query-param-enriched endpoint_url
        assert payload["endpoint_url"] == "https://agent.test/"

    @pytest.mark.asyncio
    async def test_invoke_omits_encrypted_fields_when_not_set(self, sample_prepared):
        """When encrypted auth fields are None, they are absent from the payload."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": True}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        client = RustA2ARuntimeClient()
        with patch.object(client, "_get_runtime_client", return_value=mock_client):
            await client.invoke(sample_prepared, timeout_seconds=5.0)

        call_kwargs = mock_client.post.call_args
        payload = call_kwargs.kwargs["json"]
        assert "auth_headers_encrypted" not in payload
        assert "auth_query_params_encrypted" not in payload

    @pytest.mark.asyncio
    async def test_proxy_timeout_is_at_least_request_timeout_plus_five(self, sample_prepared):
        """The proxy timeout should be max(settings, request_timeout + 5)."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": True}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        client = RustA2ARuntimeClient()
        with (
            patch.object(client, "_get_runtime_client", return_value=mock_client),
            patch("mcpgateway.services.rust_a2a_runtime.settings") as mock_settings,
        ):
            mock_settings.experimental_rust_a2a_runtime_timeout_seconds = 10
            mock_settings.experimental_rust_a2a_runtime_url = "http://127.0.0.1:8788"
            await client.invoke(sample_prepared, timeout_seconds=60.0)

        call_kwargs = mock_client.post.call_args
        timeout_obj = call_kwargs.kwargs["timeout"]
        # proxy_timeout = max(10, 60 + 5) = 65
        assert timeout_obj.read == 65.0
