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


class TestGetTokenInfoBulkDefault:
    """Tests for AbstractTokenBackend's default (loop-based) get_token_info_bulk."""

    @staticmethod
    def _make_backend(get_token_info):
        from mcpgateway.services.token_backends.base import AbstractTokenBackend

        class _Concrete(AbstractTokenBackend):
            """Minimal concrete backend for testing the default bulk loop."""

            async def store_tokens(self, *a, **kw):
                """Stub."""

            async def get_user_token(self, *a, **kw):
                """Stub."""

            async def get_token_info(self, *a, **kw):
                """Stub - overridden per-instance below."""

            async def revoke_user_tokens(self, *a, **kw):
                """Stub."""

            async def cleanup_expired_tokens(self, *a, **kw):
                """Stub."""

            async def get_user_learned_audience(self, *a, **kw):
                """Stub."""

        backend = _Concrete()
        backend.get_token_info = get_token_info
        return backend

    @pytest.mark.asyncio
    async def test_default_bulk_loops_over_get_token_info(self):
        """Without a backend override, get_token_info_bulk loops over get_token_info() per id."""
        # Standard
        from unittest.mock import AsyncMock

        get_token_info = AsyncMock(side_effect=[{"status": "valid"}, None])
        backend = self._make_backend(get_token_info)

        result = await backend.get_token_info_bulk(["gw-1", "gw-2"], "team-1", "alice@example.com")

        assert result == {"gw-1": {"status": "valid"}, "gw-2": None}
        assert get_token_info.await_count == 2
        get_token_info.assert_any_await("gw-1", "team-1", "alice@example.com")
        get_token_info.assert_any_await("gw-2", "team-1", "alice@example.com")

    @pytest.mark.asyncio
    async def test_default_bulk_isolates_one_id_failure_from_the_rest(self):
        """One id's get_token_info() failure is captured as that id's value, not propagated -
        the rest of the batch still gets a real answer instead of the whole call failing."""
        # Standard
        from unittest.mock import AsyncMock

        boom = RuntimeError("backend unavailable")
        get_token_info = AsyncMock(side_effect=[{"status": "valid"}, boom])
        backend = self._make_backend(get_token_info)

        result = await backend.get_token_info_bulk(["gw-ok", "gw-fails"], "team-1", "alice@example.com")

        assert result["gw-ok"] == {"status": "valid"}
        assert result["gw-fails"] is boom
