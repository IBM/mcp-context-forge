# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/utils/test_oidc_discovery.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Unit tests for shared OIDC discovery and JWKS caching module.
"""

# Standard
from time import monotonic
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.utils.oidc_discovery import (
    _build_metadata_urls,
    _jwks_client_cache,
    _oidc_metadata_cache,
    clear_caches,
    discover_oidc_metadata,
    get_jwks_client,
)


class TestBuildMetadataUrls:
    """Tests for _build_metadata_urls helper function."""

    def test_issuer_with_path(self):
        """Issuer with path component generates both RFC 8414 and OIDC URLs."""
        issuer = "https://auth.example.com/realms/test"
        urls = _build_metadata_urls(issuer)

        assert len(urls) == 2
        # RFC 8414: well-known inserted between host and path
        assert urls[0] == "https://auth.example.com/.well-known/oauth-authorization-server/realms/test"
        # OIDC Discovery: well-known appended to path
        assert urls[1] == "https://auth.example.com/realms/test/.well-known/openid-configuration"

    def test_issuer_without_path(self):
        """Issuer without path component generates both URLs (may be duplicates)."""
        issuer = "https://auth.example.com"
        urls = _build_metadata_urls(issuer)

        # Both URLs should be present (de-duplicated if identical)
        assert len(urls) >= 1
        assert "https://auth.example.com/.well-known/oauth-authorization-server" in urls
        assert "https://auth.example.com/.well-known/openid-configuration" in urls

    def test_trailing_slash_normalization(self):
        """Trailing slashes are stripped before URL construction."""
        issuer_with_slash = "https://auth.example.com/realms/test/"
        issuer_without_slash = "https://auth.example.com/realms/test"

        urls_with = _build_metadata_urls(issuer_with_slash)
        urls_without = _build_metadata_urls(issuer_without_slash)

        assert urls_with == urls_without


class TestDiscoverOidcMetadata:
    """Tests for discover_oidc_metadata function."""

    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        """Clear caches before and after each test."""
        clear_caches()
        yield
        clear_caches()

    @pytest.mark.asyncio
    async def test_successful_discovery_caches_result(self):
        """Successful discovery caches metadata for subsequent calls."""
        issuer = "https://auth.example.com"
        metadata = {"issuer": issuer, "jwks_uri": "https://auth.example.com/jwks"}

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = metadata
        mock_http = AsyncMock()
        mock_http.get.return_value = mock_resp

        with patch("mcpgateway.services.http_client_service.get_http_client", AsyncMock(return_value=mock_http)):
            result1 = await discover_oidc_metadata(issuer)
            result2 = await discover_oidc_metadata(issuer)

        assert result1 == metadata
        assert result2 == metadata
        # Should only make one HTTP request (second call uses cache)
        assert mock_http.get.call_count == 1

    @pytest.mark.asyncio
    async def test_http_500_error_negative_cache_transient(self):
        """5xx errors are negatively cached with transient TTL."""
        issuer = "https://auth.example.com"

        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_http = AsyncMock()
        mock_http.get.return_value = mock_resp

        with patch("mcpgateway.services.http_client_service.get_http_client", AsyncMock(return_value=mock_http)):
            result1 = await discover_oidc_metadata(issuer)
            result2 = await discover_oidc_metadata(issuer)

        assert result1 is None
        assert result2 is None
        # Should probe both RFC 8414 and OIDC endpoints on first call, then use cache
        assert mock_http.get.call_count == 2  # First call tries both endpoints

    @pytest.mark.asyncio
    async def test_http_404_error_negative_cache_permanent(self):
        """404 errors are negatively cached with permanent TTL."""
        issuer = "https://auth.example.com"

        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_http = AsyncMock()
        mock_http.get.return_value = mock_resp

        with patch("mcpgateway.services.http_client_service.get_http_client", AsyncMock(return_value=mock_http)):
            result = await discover_oidc_metadata(issuer)

        assert result is None
        # Should probe both endpoints
        assert mock_http.get.call_count == 2

    @pytest.mark.asyncio
    async def test_malformed_json_returns_none(self):
        """Malformed JSON response returns None."""
        issuer = "https://auth.example.com"

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.side_effect = ValueError("Invalid JSON")
        mock_http = AsyncMock()
        mock_http.get.return_value = mock_resp

        with patch("mcpgateway.services.http_client_service.get_http_client", AsyncMock(return_value=mock_http)):
            result = await discover_oidc_metadata(issuer)

        assert result is None

    @pytest.mark.asyncio
    async def test_issuer_mismatch_rejected(self):
        """Metadata with mismatched issuer claim is rejected."""
        issuer = "https://auth.example.com"
        metadata = {"issuer": "https://evil.example.com", "jwks_uri": "https://evil.example.com/jwks"}

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = metadata
        mock_http = AsyncMock()
        mock_http.get.return_value = mock_resp

        with patch("mcpgateway.services.http_client_service.get_http_client", AsyncMock(return_value=mock_http)):
            result = await discover_oidc_metadata(issuer)

        assert result is None

    @pytest.mark.asyncio
    async def test_trailing_slash_issuer_normalization(self):
        """Issuer trailing slashes are normalized for cache key and validation."""
        issuer_with_slash = "https://auth.example.com/"
        issuer_without_slash = "https://auth.example.com"
        metadata = {"issuer": issuer_without_slash, "jwks_uri": "https://auth.example.com/jwks"}

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = metadata
        mock_http = AsyncMock()
        mock_http.get.return_value = mock_resp

        with patch("mcpgateway.services.http_client_service.get_http_client", AsyncMock(return_value=mock_http)):
            result = await discover_oidc_metadata(issuer_with_slash)

        assert result == metadata

    @pytest.mark.asyncio
    async def test_network_error_transient_cache(self):
        """Network errors are negatively cached with transient TTL."""
        issuer = "https://auth.example.com"

        mock_http = AsyncMock()
        mock_http.get.side_effect = ConnectionError("Network unreachable")

        with patch("mcpgateway.services.http_client_service.get_http_client", AsyncMock(return_value=mock_http)):
            result = await discover_oidc_metadata(issuer)

        assert result is None

    @pytest.mark.asyncio
    async def test_rfc8414_success_stops_probing(self):
        """Successful RFC 8414 response stops probing OIDC endpoint."""
        issuer = "https://auth.example.com"
        metadata = {"issuer": issuer, "jwks_uri": "https://auth.example.com/jwks"}

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = metadata
        mock_http = AsyncMock()
        mock_http.get.return_value = mock_resp

        with patch("mcpgateway.services.http_client_service.get_http_client", AsyncMock(return_value=mock_http)):
            result = await discover_oidc_metadata(issuer)

        assert result == metadata
        # Should only call the first URL (RFC 8414)
        assert mock_http.get.call_count == 1

    @pytest.mark.asyncio
    async def test_custom_ttl_parameters(self):
        """Custom TTL parameters are respected."""
        issuer = "https://auth.example.com"
        metadata = {"issuer": issuer, "jwks_uri": "https://auth.example.com/jwks"}

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = metadata
        mock_http = AsyncMock()
        mock_http.get.return_value = mock_resp

        with patch("mcpgateway.services.http_client_service.get_http_client", AsyncMock(return_value=mock_http)):
            result = await discover_oidc_metadata(issuer, success_ttl=1, negative_ttl_permanent=1, negative_ttl_transient=1)

        assert result == metadata
        # Verify cache entry exists
        normalized = issuer.rstrip("/")
        assert normalized in _oidc_metadata_cache


class TestGetJwksClient:
    """Tests for get_jwks_client function."""

    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        """Clear caches before and after each test."""
        clear_caches()
        yield
        clear_caches()

    def test_creates_new_client_on_first_call(self):
        """First call creates a new PyJWKClient instance."""
        jwks_uri = "https://auth.example.com/jwks"

        with patch("mcpgateway.utils.oidc_discovery.jwt.PyJWKClient") as mock_client_class:
            mock_instance = MagicMock()
            mock_client_class.return_value = mock_instance

            client = get_jwks_client(jwks_uri)

            assert client == mock_instance
            mock_client_class.assert_called_once_with(jwks_uri)

    def test_reuses_cached_client_on_subsequent_calls(self):
        """Subsequent calls reuse the cached PyJWKClient instance."""
        jwks_uri = "https://auth.example.com/jwks"

        with patch("mcpgateway.utils.oidc_discovery.jwt.PyJWKClient") as mock_client_class:
            mock_instance = MagicMock()
            mock_client_class.return_value = mock_instance

            client1 = get_jwks_client(jwks_uri)
            client2 = get_jwks_client(jwks_uri)

            assert client1 == client2
            assert client1 == mock_instance
            # Should only create client once
            mock_client_class.assert_called_once_with(jwks_uri)

    def test_different_uris_create_different_clients(self):
        """Different JWKS URIs create separate cached clients."""
        jwks_uri1 = "https://auth1.example.com/jwks"
        jwks_uri2 = "https://auth2.example.com/jwks"

        with patch("mcpgateway.utils.oidc_discovery.jwt.PyJWKClient") as mock_client_class:
            mock_instance1 = MagicMock()
            mock_instance2 = MagicMock()
            mock_client_class.side_effect = [mock_instance1, mock_instance2]

            client1 = get_jwks_client(jwks_uri1)
            client2 = get_jwks_client(jwks_uri2)

            assert client1 != client2
            assert mock_client_class.call_count == 2


class TestClearCaches:
    """Tests for clear_caches function."""

    def test_clears_both_caches(self):
        """clear_caches removes all entries from both caches."""
        # Populate caches
        _oidc_metadata_cache["test"] = (monotonic(), {"issuer": "test"}, 300)
        _jwks_client_cache["test"] = MagicMock()

        assert len(_oidc_metadata_cache) == 1
        assert len(_jwks_client_cache) == 1

        clear_caches()

        assert len(_oidc_metadata_cache) == 0
        assert len(_jwks_client_cache) == 0

# Made with Bob
