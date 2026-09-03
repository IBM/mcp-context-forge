# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/token_backends/test_base.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for base token backend utilities.
"""

# Third-Party
import pytest

# First-Party
from mcpgateway.services.token_backends.base import normalize_resource_url


class TestNormalizeResourceUrl:
    """Test suite for normalize_resource_url utility function."""

    def test_normalize_with_query_preserved(self):
        """Test URL normalization preserving query parameters."""
        url = "https://api.example.com/path?foo=bar&baz=qux"
        result = normalize_resource_url(url, preserve_query=True)
        assert result == "https://api.example.com/path?foo=bar&baz=qux"

    def test_normalize_without_query_stripped(self):
        """Test URL normalization stripping query parameters."""
        url = "https://api.example.com/path?foo=bar&baz=qux"
        result = normalize_resource_url(url, preserve_query=False)
        assert result == "https://api.example.com/path"

    def test_normalize_with_fragment(self):
        """Test URL normalization removes fragments."""
        url = "https://api.example.com/path#section"
        result = normalize_resource_url(url, preserve_query=False)
        assert result == "https://api.example.com/path"

    def test_normalize_trailing_slash(self):
        """Test URL normalization with trailing slashes."""
        url = "https://api.example.com/path/"
        result = normalize_resource_url(url, preserve_query=False)
        # Trailing slash is preserved per implementation
        assert result == "https://api.example.com/path/"

    def test_normalize_empty_url(self):
        """Test normalize_resource_url with empty string returns None."""
        result = normalize_resource_url("", preserve_query=False)
        assert result is None

    def test_normalize_none_url(self):
        """Test normalize_resource_url with None."""
        result = normalize_resource_url(None, preserve_query=False)
        assert result is None

    def test_normalize_invalid_url(self):
        """Test normalize_resource_url with invalid URL."""
        result = normalize_resource_url("not a valid url", preserve_query=False)
        # Should return original string if parsing fails
        assert result == "not a valid url"


# ---------------------------------------------------------------------------
# Round-7 coverage: store_oauth_credentials default (line 261) and
# get_user_auth_headers default (line 290)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_store_oauth_credentials_default_returns_false():
    """Default store_oauth_credentials returns False (not supported by base)."""
    from mcpgateway.services.token_backends.base import AbstractTokenBackend

    class _Concrete(AbstractTokenBackend):
        """Minimal concrete backend for testing base defaults."""

        async def store_tokens(self, *a, **kw):
            """Stub."""

        async def get_user_token(self, *a, **kw):
            """Stub."""

        async def get_token_info(self, *a, **kw):
            """Stub."""

        async def revoke_user_tokens(self, *a, **kw):
            """Stub."""

        async def cleanup_expired_tokens(self, *a, **kw):
            """Stub."""

        async def get_user_learned_audience(self, *a, **kw):
            """Stub."""

    backend = _Concrete()
    result = await backend.store_oauth_credentials("team-1", "https://mcp.example.com", {})
    assert result is False


@pytest.mark.asyncio
async def test_get_user_auth_headers_default_returns_none():
    """Default get_user_auth_headers returns None (not supported by base)."""
    from mcpgateway.services.token_backends.base import AbstractTokenBackend

    class _Concrete(AbstractTokenBackend):
        """Minimal concrete backend for testing base defaults."""

        async def store_tokens(self, *a, **kw):
            """Stub."""

        async def get_user_token(self, *a, **kw):
            """Stub."""

        async def get_token_info(self, *a, **kw):
            """Stub."""

        async def revoke_user_tokens(self, *a, **kw):
            """Stub."""

        async def cleanup_expired_tokens(self, *a, **kw):
            """Stub."""

        async def get_user_learned_audience(self, *a, **kw):
            """Stub."""

    backend = _Concrete()
    result = await backend.get_user_auth_headers("gw-1", "team-1", "alice@example.com")
    assert result is None
