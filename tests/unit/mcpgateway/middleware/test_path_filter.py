# -*- coding: utf-8 -*-
"""Unit tests for path_filter module.

Copyright 2025
SPDX-License-Identifier: Apache-2.0

Tests centralized path filtering for middleware chain optimization.
"""

import pytest

from mcpgateway.config import settings
from mcpgateway.middleware.path_filter import (
    OBSERVABILITY_SKIP_EXACT,
    clear_all_caches,
    should_skip_auth_context,
    should_skip_db_query_logging,
    should_skip_observability,
    should_skip_request_logging,
)


class TestObservabilitySkip:
    """Test observability middleware skip logic."""

    @pytest.mark.parametrize(
        "path,expected",
        [
            # Exact health/metrics matches
            ("/health", True),
            ("/healthz", True),  # translate.py compatibility
            ("/ready", True),
            ("/metrics", True),
            # Static prefix (with trailing slash)
            ("/static/css/app.css", True),
            ("/static/js/bundle.js", True),
            ("/static/", True),
            # /static without trailing slash is skipped via allowlist
            ("/static", True),
            # Exact vs prefix behavior - allowlist skips non-MCP endpoints
            ("/health/security", True),
            ("/healthz/check", True),
            ("/tools", True),
            ("/admin", True),
            ("/api/v1/tools", True),
            ("/", True),
            ("/docs", True),
            ("/openapi.json", True),
            # MCP/A2A allowlist paths should NOT skip
            ("/rpc", False),
            ("/rpc/", False),
            ("/sse", False),
            ("/message", False),
            ("/mcp", False),
            ("/mcp/", False),
            ("/servers/123/mcp", False),
            ("/servers/123/mcp/", False),
            ("/servers/123/sse", False),
            ("/servers/123/message", False),
            ("/a2a", False),
            ("/a2a/agents", False),
        ],
    )
    def test_should_skip_observability(self, path: str, expected: bool):
        """Test observability skip includes health/static/excludes and allowlist behavior."""
        assert should_skip_observability(path) == expected


class TestAuthContextSkip:
    """Test auth context middleware skip logic."""

    @pytest.mark.parametrize(
        "path,expected",
        [
            # Health/static only (no allowlist here)
            ("/health", True),
            ("/healthz", True),
            ("/ready", True),
            ("/metrics", True),
            ("/static/js/app.js", True),
            ("/static/", True),
            # Exact vs prefix
            ("/health/security", False),
            ("/static", False),
            # Auth paths are NOT skipped by auth context
            # (TokenScopingMiddleware handles those separately)
            ("/auth/email/login", False),
            ("/auth/email/register", False),
            ("/.well-known/openid-configuration", False),
            # Normal paths not skipped
            ("/tools", False),
            ("/admin", False),
        ],
    )
    def test_should_skip_auth_context(self, path: str, expected: bool):
        """Test auth context skip matches health/static semantics."""
        assert should_skip_auth_context(path) == expected


class TestLoggingSkip:
    """Test request logging middleware skip logic."""

    @pytest.mark.parametrize(
        "path,expected",
        [
            # Prefix match behavior - these all match
            ("/health", True),
            ("/healthz", True),
            ("/health/security", True),  # Prefix match includes subpaths
            ("/healthz/check", True),
            ("/static", True),
            ("/static/css/app.css", True),
            ("/static/", True),
            ("/favicon.ico", True),
            ("/favicon.ico.backup", True),  # Prefix includes extensions
            # Should NOT skip - different endpoints
            ("/ready", False),  # Not in request logging skip list
            ("/metrics", False),  # Not in request logging skip list
            ("/tools", False),
            ("/admin", False),
            ("/api/v1/tools", False),
            ("/", False),
        ],
    )
    def test_should_skip_request_logging(self, path: str, expected: bool):
        """Test request logging skip preserves prefix semantics."""
        assert should_skip_request_logging(path) == expected


class TestDbQueryLoggingSkip:
    """Test DB query logging middleware skip logic."""

    @pytest.mark.parametrize(
        "path,expected",
        [
            # Exact health/readiness + /static prefix (no trailing slash needed)
            ("/health", True),
            ("/healthz", True),  # translate.py compatibility
            ("/ready", True),
            # /health/security is NOT skipped (exact match only for health)
            ("/health/security", False),
            # /static prefix works with or without trailing slash
            ("/static", True),
            ("/static/", True),
            ("/static/css/app.css", True),
            # Metrics is NOT skipped for DB logging (may need DB for metrics)
            ("/metrics", False),
            # Normal paths not skipped
            ("/tools", False),
            ("/admin", False),
            ("/api/v1/tools", False),
        ],
    )
    def test_should_skip_db_query_logging(self, path: str, expected: bool):
        """Test DB query logging skip uses exact health + /static prefix."""
        assert should_skip_db_query_logging(path) == expected


class TestCacheEffectiveness:
    """Test LRU cache behavior."""

    def setup_method(self):
        """Clear caches before each test."""
        clear_all_caches()

    def test_cache_hit_after_first_call(self):
        """Verify cache hit on repeated calls."""
        # First call - cache miss
        should_skip_observability("/health")
        info = should_skip_observability.cache_info()
        assert info.misses == 1
        assert info.hits == 0

        # Second call - cache hit
        should_skip_observability("/health")
        info = should_skip_observability.cache_info()
        assert info.hits == 1

    def test_different_paths_cached_separately(self):
        """Verify different paths are cached independently."""
        should_skip_observability("/health")
        should_skip_observability("/tools")
        should_skip_observability("/health")  # Should hit cache

        info = should_skip_observability.cache_info()
        assert info.misses == 2  # /health and /tools
        assert info.hits == 1  # Second /health call

    def test_cache_clear_works(self):
        """Verify clear_all_caches resets all caches."""
        # Populate caches
        should_skip_observability("/health")
        should_skip_auth_context("/health")
        should_skip_request_logging("/health")
        should_skip_db_query_logging("/health")

        # Clear all
        clear_all_caches()

        # All caches should be empty
        assert should_skip_observability.cache_info().misses == 0
        assert should_skip_auth_context.cache_info().misses == 0
        assert should_skip_request_logging.cache_info().misses == 0
        assert should_skip_db_query_logging.cache_info().misses == 0

    def test_auth_context_cache_independent(self):
        """Verify auth_context cache is independent from observability."""
        clear_all_caches()

        # Call auth_context first
        should_skip_auth_context("/health")

        obs_info = should_skip_observability.cache_info()
        auth_info = should_skip_auth_context.cache_info()

        assert obs_info.misses == 0
        assert auth_info.misses == 1


class TestPathImmutability:
    """Test that path sets cannot be modified at runtime."""

    def test_observability_skip_exact_immutable(self):
        """Ensure OBSERVABILITY_SKIP_EXACT cannot be modified."""
        with pytest.raises(AttributeError):
            OBSERVABILITY_SKIP_EXACT.add("/new-path")  # type: ignore

    def test_observability_skip_exact_is_frozenset(self):
        """Ensure OBSERVABILITY_SKIP_EXACT is a frozenset."""
        assert isinstance(OBSERVABILITY_SKIP_EXACT, frozenset)


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    @pytest.mark.parametrize(
        "path",
        [
            "",  # Empty path
            "/",  # Root path
            "/HEALTH",  # Case sensitive (should not skip)
            "/Health",  # Mixed case (should not skip)
            "/health ",  # Trailing space (should not skip)
            " /health",  # Leading space (should not skip)
        ],
    )
    def test_case_sensitivity_and_whitespace(self, path: str):
        """Test that non-allowlisted variants are skipped."""
        assert should_skip_observability(path) is True

    def test_unicode_paths(self):
        """Test handling of unicode paths."""
        assert should_skip_observability("/health\u200b") is True  # zero-width space
        assert should_skip_observability("/healthé") is True  # accented character

    def test_very_long_paths(self):
        """Test handling of very long paths."""
        long_path = "/static/" + "a" * 10000
        assert should_skip_observability(long_path) is True  # Still matches /static/ prefix

    def test_path_with_query_string_component(self):
        """Test that paths are matched as-is (query strings should be stripped before calling)."""
        # Note: In practice, request.url.path doesn't include query strings
        # but if it did, these would not match
        assert should_skip_observability("/health?check=true") is True
        assert should_skip_request_logging("/health?check=true") is True  # Prefix match


class TestObservabilityIncludeExclude:
    """Test observability include/exclude pattern behavior."""

    def test_custom_include_overrides_default(self, monkeypatch: pytest.MonkeyPatch):
        """Custom include list should allow only matching paths."""
        monkeypatch.setattr(settings, "observability_include_paths", [r"^/admin$"], raising=False)
        monkeypatch.setattr(settings, "observability_exclude_paths", [], raising=False)
        clear_all_caches()

        assert should_skip_observability("/admin") is False
        assert should_skip_observability("/rpc") is True

        clear_all_caches()

    def test_empty_include_allows_all(self, monkeypatch: pytest.MonkeyPatch):
        """Empty include list allows all paths except explicit skips/excludes."""
        monkeypatch.setattr(settings, "observability_include_paths", [], raising=False)
        monkeypatch.setattr(settings, "observability_exclude_paths", [], raising=False)
        clear_all_caches()

        assert should_skip_observability("/tools") is False
        assert should_skip_observability("/health") is True

        clear_all_caches()

    def test_exclude_overrides_include(self, monkeypatch: pytest.MonkeyPatch):
        """Exclude patterns should override includes."""
        monkeypatch.setattr(settings, "observability_include_paths", [r"^/rpc$"], raising=False)
        monkeypatch.setattr(settings, "observability_exclude_paths", [r"^/rpc$"], raising=False)
        clear_all_caches()

        assert should_skip_observability("/rpc") is True

        clear_all_caches()
