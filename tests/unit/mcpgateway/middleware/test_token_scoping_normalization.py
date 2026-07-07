# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/middleware/test_token_scoping_normalization.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Test token scoping path normalization behavior.

This test suite validates that token scope patterns work consistently
across both versioned (/v1/*) and legacy (unversioned) routes.
"""

import pytest

from mcpgateway.middleware.token_scoping import TokenScopingMiddleware, _normalize_llm_api_prefix, _strip_v1_prefix


@pytest.mark.parametrize(
    "input_path,expected",
    [
        # Basic /v1 prefix stripping
        ("/v1/tools", "/tools"),
        ("/tools", "/tools"),
        ("/v1/admin/users", "/admin/users"),
        ("/admin/users", "/admin/users"),

        # Edge cases
        ("/v1", "/"),
        ("/v1/", "/"),

        # Paths that should NOT be modified (no /v1 prefix)
        ("/health", "/health"),
        ("/oauth/token", "/oauth/token"),
        ("/.well-known/security.txt", "/.well-known/security.txt"),

        # Paths with /v1 in middle (should NOT be stripped)
        ("/api/v1/tools", "/api/v1/tools"),
        ("/tools/v1/test", "/tools/v1/test"),

        # Complex paths
        ("/v1/servers/abc/tools", "/servers/abc/tools"),
        ("/v1/teams/123/members", "/teams/123/members"),
    ],
)
def test_normalize_path_for_matching(input_path, expected):
    """Verify path normalization strips /v1 prefix correctly.

    Args:
        input_path: Input path to normalize.
        expected: Expected normalized path.
    """
    middleware = TokenScopingMiddleware()
    result = middleware._normalize_path_for_matching(input_path)
    assert result == expected, f"Expected {expected}, got {result}"


def test_scope_pattern_matches_both_versions():
    """Verify scope patterns work for both /v1/* and legacy paths.

    This test demonstrates that a single pattern (without /v1 prefix)
    matches both versioned and unversioned routes.
    """
    middleware = TokenScopingMiddleware()

    # Pattern without /v1 prefix
    pattern_prefix = "/tools"

    # Both versions should normalize to the same path
    legacy_normalized = middleware._normalize_path_for_matching("/tools")
    v1_normalized = middleware._normalize_path_for_matching("/v1/tools")

    assert legacy_normalized == v1_normalized == "/tools"
    assert legacy_normalized.startswith(pattern_prefix)
    assert v1_normalized.startswith(pattern_prefix)


def test_v1_prefix_in_pattern_is_redundant():
    """Verify that including /v1 in pattern is redundant but harmless.

    If a user writes a pattern like "^/v1/tools", it will be normalized
    to "^/tools" internally, so it still works but is misleading.
    """
    middleware = TokenScopingMiddleware()

    # A pattern with /v1 prefix would be normalized
    pattern_with_v1 = "/v1/tools"
    normalized_pattern = middleware._normalize_path_for_matching(pattern_with_v1)

    # The pattern is normalized to /tools
    assert normalized_pattern == "/tools"

    # So it matches both versions
    assert middleware._normalize_path_for_matching("/tools") == normalized_pattern
    assert middleware._normalize_path_for_matching("/v1/tools") == normalized_pattern


@pytest.mark.parametrize(
    "path",
    [
        "/v1/tools",
        "/v1/servers",
        "/v1/prompts",
        "/v1/resources",
        "/v1/gateways",
    ],
)
def test_core_v1_routes_normalize_correctly(path):
    """Verify core /v1 routes normalize to unversioned paths.

    Args:
        path: Versioned path to test.
    """
    middleware = TokenScopingMiddleware()
    result = middleware._normalize_path_for_matching(path)

    # Should strip /v1 prefix
    assert not result.startswith("/v1")
    assert result.startswith("/")

    # Should match the unversioned equivalent
    unversioned = path.replace("/v1", "", 1)
    assert result == unversioned


def test_empty_path_normalization():
    """Verify empty or root paths are handled correctly."""
    middleware = TokenScopingMiddleware()

    assert middleware._normalize_path_for_matching("") == "/"
    assert middleware._normalize_path_for_matching("/") == "/"
    assert middleware._normalize_path_for_matching("/v1") == "/"
    assert middleware._normalize_path_for_matching("/v1/") == "/"


def test_path_without_leading_slash():
    """Verify paths without leading slash are normalized correctly."""
    middleware = TokenScopingMiddleware()

    # Paths should always start with /
    result = middleware._normalize_path_for_matching("tools")
    assert result.startswith("/")
    assert result == "/tools"


# ---------------------------------------------------------------------------
# _normalize_llm_api_prefix unit tests
# ---------------------------------------------------------------------------


def test_normalize_llm_api_prefix_single_slash_returns_empty():
    """Input '/' normalizes to '/' then returns '' (line 247)."""
    assert _normalize_llm_api_prefix("/") == ""


def test_normalize_llm_api_prefix_v1_subpath_strips_version():
    """Input '/v1/llm' starts with '/v1/' so version prefix is stripped (line 252)."""
    assert _normalize_llm_api_prefix("/v1/llm") == "/llm"
    assert _normalize_llm_api_prefix("/v1/api/chat") == "/api/chat"


# ---------------------------------------------------------------------------
# _strip_v1_prefix unit tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "input_path,expected",
    [
        ("/v1/tools", "/tools"),
        ("/v1/admin/users", "/admin/users"),
        ("/v1/", "/"),
        ("/v1", "/"),
        ("/tools", "/tools"),
        ("/admin", "/admin"),
        ("/", "/"),
        ("/v2/tools", "/v2/tools"),
        ("/v1tools", "/v1tools"),
    ],
)
def test_strip_v1_prefix_parametrized(input_path, expected):
    """_strip_v1_prefix must strip exactly the /v1 segment and nothing else."""
    assert _strip_v1_prefix(input_path) == expected


def test_strip_v1_prefix_idempotent():
    """/tools is already unversioned — second call must return the same value."""
    assert _strip_v1_prefix(_strip_v1_prefix("/v1/tools")) == "/tools"
