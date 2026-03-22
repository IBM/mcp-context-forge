# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/plugins/url_reputation/test_url_reputation.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for URLReputationPlugin.
"""

import pytest
from unittest.mock import MagicMock, patch

from mcpgateway.plugins.framework import (
    PluginConfig,
    ResourceHookType,
    ResourcePreFetchPayload,
)

from plugins.url_reputation.url_reputation import URLReputationPlugin, URLReputationConfig

try:
    import url_reputation_rust  # noqa: F401
    _RUST_AVAILABLE = True
except ImportError:
    _RUST_AVAILABLE = False
except Exception:
    _RUST_AVAILABLE = False


@pytest.mark.skipif(not _RUST_AVAILABLE, reason="Rust url_reputation plugin not available")
@pytest.mark.asyncio
async def test_whitelisted_subdomain():
    """Subdomains of a whitelisted domain should be allowed."""
    config = PluginConfig(
        name="urlrep",
        kind="plugins.url_reputation.url_reputation.URLReputationPlugin",
        hooks=[ResourceHookType.RESOURCE_PRE_FETCH],
        config={
            "whitelist_domains": ["example.com"],
            "allowed_patterns": [],
            "blocked_domains": [],
            "blocked_patterns": [],
            "use_heuristic_check": True,
            "entropy_threshold": 3.5,
            "block_non_secure_http": True,
        },
    )
    plugin = URLReputationPlugin(config)

    res = await plugin.resource_pre_fetch(ResourcePreFetchPayload(uri="https://sub.example.com/login"), None)
    assert res.violation is None


@pytest.mark.skipif(not _RUST_AVAILABLE, reason="Rust url_reputation plugin not available")
@pytest.mark.asyncio
async def test_phishing_like_domain_blocked():
    """Domains mimicking popular sites but not whitelisted are blocked."""
    config = PluginConfig(
        name="urlrep",
        kind="plugins.url_reputation.url_reputation.URLReputationPlugin",
        hooks=[ResourceHookType.RESOURCE_PRE_FETCH],
        config={
            "whitelist_domains": ["paypal.com"],
            "allowed_patterns": [],
            "blocked_domains": [],
            "blocked_patterns": [],
            "use_heuristic_check": True,
            "entropy_threshold": 3.5,
            "block_non_secure_http": True,
        },
    )
    plugin = URLReputationPlugin(config)

    url = "https://pаypal.com/login"  # Cyrillic 'а'
    res = await plugin.resource_pre_fetch(ResourcePreFetchPayload(uri=url), None)
    assert not res.continue_processing



@pytest.mark.skipif(not _RUST_AVAILABLE, reason="Rust url_reputation plugin not available")
@pytest.mark.asyncio
async def test_high_entropy_domain_blocked():
    """Random-looking high-entropy domains should be blocked."""
    config = PluginConfig(
        name="urlrep",
        kind="plugins.url_reputation.url_reputation.URLReputationPlugin",
        hooks=[ResourceHookType.RESOURCE_PRE_FETCH],
        config={
            "whitelist_domains": [],
            "allowed_patterns": [],
            "blocked_domains": [],
            "blocked_patterns": [],
            "use_heuristic_check": True,
            "entropy_threshold": 3.5,
            "block_non_secure_http": True,
        },
    )
    plugin = URLReputationPlugin(config)

    url = "https://h7f893jkld90-234.com"
    res = await plugin.resource_pre_fetch(ResourcePreFetchPayload(uri=url), None)
    assert not res.continue_processing


@pytest.mark.skipif(not _RUST_AVAILABLE, reason="Rust url_reputation plugin not available")
@pytest.mark.asyncio
async def test_unicode_homograph_blocked():
    """URLs with unicode homograph attacks should be blocked."""
    config = PluginConfig(
        name="urlrep",
        kind="plugins.url_reputation.url_reputation.URLReputationPlugin",
        hooks=[ResourceHookType.RESOURCE_PRE_FETCH],
        config={
            "whitelist_domains": ["paypal.com"],
            "allowed_patterns": [],
            "blocked_domains": [],
            "blocked_patterns": [],
            "use_heuristic_check": True,
            "entropy_threshold": 3.5,
            "block_non_secure_http": True,
        },
    )
    plugin = URLReputationPlugin(config)

    url = "https://pаypal.com/login"  # Cyrillic 'а'
    res = await plugin.resource_pre_fetch(ResourcePreFetchPayload(uri=url), None)
    assert not res.continue_processing


@pytest.mark.asyncio
async def test_http_blocked_but_https_allowed_python():
    """Non-HTTPS URLs should be blocked; HTTPS allowed (Python fallback compatible)."""
    config = PluginConfig(
        name="urlrep",
        kind="plugins.url_reputation.url_reputation.URLReputationPlugin",
        hooks=[ResourceHookType.RESOURCE_PRE_FETCH],
        config={
            "whitelist_domains": [],
            "allowed_patterns": [],
            "blocked_domains": [],
            "blocked_patterns": [],
            "use_heuristic_check": False,
            "entropy_threshold": 3.5,
            "block_non_secure_http": True,
        },
    )
    plugin = URLReputationPlugin(config)

    res_http = await plugin.resource_pre_fetch(ResourcePreFetchPayload(uri="http://safe.com"), None)
    res_https = await plugin.resource_pre_fetch(ResourcePreFetchPayload(uri="https://safe.com"), None)

    assert not res_http.continue_processing
    assert res_https.continue_processing


@pytest.mark.skipif(not _RUST_AVAILABLE, reason="Rust url_reputation plugin not available")
@pytest.mark.asyncio
async def test_high_entropy_domain_blocked_heuristic():
    """Random-looking high-entropy domains should be blocked (requires Rust heuristics)."""
    config = PluginConfig(
        name="urlrep",
        kind="plugins.url_reputation.url_reputation.URLReputationPlugin",
        hooks=[ResourceHookType.RESOURCE_PRE_FETCH],
        config={
            "whitelist_domains": [],
            "allowed_patterns": [],
            "blocked_domains": [],
            "blocked_patterns": [],
            "use_heuristic_check": True,
            "entropy_threshold": 2.5,
            "block_non_secure_http": True,
        },
    )
    plugin = URLReputationPlugin(config)

    url = "https://ajsd9a8sd7a98sda7sd9.com"
    res = await plugin.resource_pre_fetch(ResourcePreFetchPayload(uri=url), None)
    assert not res.continue_processing


@pytest.mark.skipif(not _RUST_AVAILABLE, reason="Rust url_reputation plugin not available")
@pytest.mark.asyncio
async def test_allowed_pattern_url():
    """URLs matching allowed patterns bypass checks."""
    config = PluginConfig(
        name="urlrep",
        kind="plugins.url_reputation.url_reputation.URLReputationPlugin",
        hooks=[ResourceHookType.RESOURCE_PRE_FETCH],
        config={
            "whitelist_domains": [],
            "allowed_patterns": [r"^https://trusted\.example/.*$"],
            "blocked_domains": ["malicious.com"],
            "blocked_patterns": [r".*login.*"],
            "use_heuristic_check": True,
            "entropy_threshold": 3.5,
            "block_non_secure_http": True,
        },
    )
    plugin = URLReputationPlugin(config)

    url = "https://trusted.example/path"
    res = await plugin.resource_pre_fetch(ResourcePreFetchPayload(uri=url), None)
    assert res.continue_processing


@pytest.mark.asyncio
async def test_blocked_pattern_url():
    """URLs matching blocked patterns are rejected (Python fallback compatible - simple substring match)."""
    config = PluginConfig(
        name="urlrep",
        kind="plugins.url_reputation.url_reputation.URLReputationPlugin",
        hooks=[ResourceHookType.RESOURCE_PRE_FETCH],
        config={
            "whitelist_domains": [],
            "allowed_patterns": [],
            "blocked_domains": [],
            "blocked_patterns": ["admin", "login"],  # Simple patterns for Python compatibility
            "use_heuristic_check": False,
            "entropy_threshold": 3.5,
            "block_non_secure_http": False,
        },
    )
    plugin = URLReputationPlugin(config)

    url = "https://example.com/admin/dashboard"
    res = await plugin.resource_pre_fetch(ResourcePreFetchPayload(uri=url), None)
    assert not res.continue_processing
    assert res.violation.reason == "Blocked pattern"


@pytest.mark.skipif(not _RUST_AVAILABLE, reason="Rust url_reputation plugin not available")
@pytest.mark.asyncio
async def test_internationalized_domain():
    """Test that Punycode domains are correctly handled."""
    config = PluginConfig(
        name="urlrep",
        kind="plugins.url_reputation.url_reputation.URLReputationPlugin",
        hooks=[ResourceHookType.RESOURCE_PRE_FETCH],
        config={
            "whitelist_domains": [],
            "allowed_patterns": [],
            "blocked_domains": [],
            "blocked_patterns": [],
            "use_heuristic_check": True,
            "entropy_threshold": 3.5,
            "block_non_secure_http": True,
        },
    )
    plugin = URLReputationPlugin(config)

    url = "https://xn--fsq.com"  # punycode representation
    res = await plugin.resource_pre_fetch(ResourcePreFetchPayload(uri=url), None)
    assert res.continue_processing


@pytest.mark.skipif(not _RUST_AVAILABLE, reason="Rust url_reputation plugin not available")
@pytest.mark.asyncio
async def test_mixed_case_domain_allowed():
    """Whitelist with mixed-case entry should bypass blocked_domains for that domain."""
    config = PluginConfig(
        name="urlrep",
        kind="plugins.url_reputation.url_reputation.URLReputationPlugin",
        hooks=[ResourceHookType.RESOURCE_PRE_FETCH],
        config={
            "whitelist_domains": ["Example.COM"],
            "allowed_patterns": [],
            "blocked_domains": ["example.com"],
            "blocked_patterns": [],
            "use_heuristic_check": False,
            "entropy_threshold": 3.5,
            "block_non_secure_http": False,
        },
    )
    plugin = URLReputationPlugin(config)

    res = await plugin.resource_pre_fetch(ResourcePreFetchPayload(uri="https://example.com/path"), None)
    assert res.continue_processing


@pytest.mark.skipif(not _RUST_AVAILABLE, reason="Rust url_reputation plugin not available")
@pytest.mark.asyncio
async def test_url_with_port_allowed():
    """URLs with valid ports should be allowed if everything else is OK."""
    config = PluginConfig(
        name="urlrep",
        kind="plugins.url_reputation.url_reputation.URLReputationPlugin",
        hooks=[ResourceHookType.RESOURCE_PRE_FETCH],
        config={
            "whitelist_domains": [],
            "allowed_patterns": [],
            "blocked_domains": [],
            "blocked_patterns": [],
            "use_heuristic_check": True,
            "entropy_threshold": 3.5,
            "block_non_secure_http": True,
        },
    )
    plugin = URLReputationPlugin(config)

    url = "https://example.com:8080/path"
    res = await plugin.resource_pre_fetch(ResourcePreFetchPayload(uri=url), None)
    assert res.continue_processing


# ---------------------------------------------------------------------------
# Python fallback path tests (force _RUST_AVAILABLE=False via mock)
# ---------------------------------------------------------------------------

_PLUGIN_MODULE = "plugins.url_reputation.url_reputation"


@pytest.mark.asyncio
async def test_python_whitelist_bypasses_blocked_domain():
    """Python path: whitelisted domain bypasses blocked_domains check."""
    config = PluginConfig(
        name="urlrep",
        kind="plugins.url_reputation.url_reputation.URLReputationPlugin",
        hooks=[ResourceHookType.RESOURCE_PRE_FETCH],
        config={
            "whitelist_domains": ["example.com"],
            "allowed_patterns": [],
            "blocked_domains": ["example.com"],
            "blocked_patterns": [],
            "use_heuristic_check": False,
            "entropy_threshold": 3.5,
            "block_non_secure_http": False,
        },
    )
    with patch(f"{_PLUGIN_MODULE}._RUST_AVAILABLE", False):
        plugin = URLReputationPlugin(config)
        res = await plugin.resource_pre_fetch(ResourcePreFetchPayload(uri="https://example.com/path"), None)
    assert res.continue_processing


@pytest.mark.asyncio
async def test_python_whitelisted_subdomain():
    """Python path: subdomains of a whitelisted domain should be allowed."""
    config = PluginConfig(
        name="urlrep",
        kind="plugins.url_reputation.url_reputation.URLReputationPlugin",
        hooks=[ResourceHookType.RESOURCE_PRE_FETCH],
        config={
            "whitelist_domains": ["example.com"],
            "allowed_patterns": [],
            "blocked_domains": [],
            "blocked_patterns": [],
            "use_heuristic_check": False,
            "entropy_threshold": 3.5,
            "block_non_secure_http": True,
        },
    )
    with patch(f"{_PLUGIN_MODULE}._RUST_AVAILABLE", False):
        plugin = URLReputationPlugin(config)
        res = await plugin.resource_pre_fetch(ResourcePreFetchPayload(uri="https://sub.example.com/path"), None)
    assert res.continue_processing
    assert res.violation is None


@pytest.mark.asyncio
async def test_python_http_allowed_when_not_enforced():
    """Python path: HTTP URLs are allowed when block_non_secure_http is False."""
    config = PluginConfig(
        name="urlrep",
        kind="plugins.url_reputation.url_reputation.URLReputationPlugin",
        hooks=[ResourceHookType.RESOURCE_PRE_FETCH],
        config={
            "whitelist_domains": [],
            "allowed_patterns": [],
            "blocked_domains": [],
            "blocked_patterns": [],
            "use_heuristic_check": False,
            "entropy_threshold": 3.5,
            "block_non_secure_http": False,
        },
    )
    with patch(f"{_PLUGIN_MODULE}._RUST_AVAILABLE", False):
        plugin = URLReputationPlugin(config)
        res = await plugin.resource_pre_fetch(ResourcePreFetchPayload(uri="http://safe.com/page"), None)
    assert res.continue_processing


@pytest.mark.asyncio
async def test_python_clean_url_passes_all_checks():
    """Python path: a clean HTTPS URL with no matches passes all checks."""
    config = PluginConfig(
        name="urlrep",
        kind="plugins.url_reputation.url_reputation.URLReputationPlugin",
        hooks=[ResourceHookType.RESOURCE_PRE_FETCH],
        config={
            "whitelist_domains": [],
            "allowed_patterns": [],
            "blocked_domains": ["evil.com"],
            "blocked_patterns": ["malware"],
            "use_heuristic_check": False,
            "entropy_threshold": 3.5,
            "block_non_secure_http": True,
        },
    )
    with patch(f"{_PLUGIN_MODULE}._RUST_AVAILABLE", False):
        plugin = URLReputationPlugin(config)
        res = await plugin.resource_pre_fetch(ResourcePreFetchPayload(uri="https://safe.example.com/path"), None)
    assert res.continue_processing
    assert res.violation is None


@pytest.mark.asyncio
async def test_python_blocked_pattern_substring():
    """Python path: blocked_patterns uses substring matching (not regex)."""
    config = PluginConfig(
        name="urlrep",
        kind="plugins.url_reputation.url_reputation.URLReputationPlugin",
        hooks=[ResourceHookType.RESOURCE_PRE_FETCH],
        config={
            "whitelist_domains": [],
            "allowed_patterns": [],
            "blocked_domains": [],
            "blocked_patterns": ["phishing"],
            "use_heuristic_check": False,
            "entropy_threshold": 3.5,
            "block_non_secure_http": False,
        },
    )
    with patch(f"{_PLUGIN_MODULE}._RUST_AVAILABLE", False):
        plugin = URLReputationPlugin(config)
        res = await plugin.resource_pre_fetch(ResourcePreFetchPayload(uri="https://example.com/phishing-page"), None)
    assert not res.continue_processing
    assert res.violation.reason == "Blocked pattern"


@pytest.mark.asyncio
async def test_python_allowed_patterns_not_honored():
    """Python path: allowed_patterns are not implemented in Python fallback."""
    config = PluginConfig(
        name="urlrep",
        kind="plugins.url_reputation.url_reputation.URLReputationPlugin",
        hooks=[ResourceHookType.RESOURCE_PRE_FETCH],
        config={
            "whitelist_domains": [],
            "allowed_patterns": ["trusted"],
            "blocked_domains": [],
            "blocked_patterns": ["trusted"],
            "use_heuristic_check": False,
            "entropy_threshold": 3.5,
            "block_non_secure_http": False,
        },
    )
    with patch(f"{_PLUGIN_MODULE}._RUST_AVAILABLE", False):
        plugin = URLReputationPlugin(config)
        # In Python fallback, allowed_patterns are not checked, so blocked_patterns will block
        res = await plugin.resource_pre_fetch(ResourcePreFetchPayload(uri="https://trusted.example.com/path"), None)
    assert not res.continue_processing


@pytest.mark.asyncio
async def test_rust_error_fallback_blocks_url():
    """When Rust plugin raises an exception, URL should be blocked for security."""
    config = PluginConfig(
        name="urlrep",
        kind="plugins.url_reputation.url_reputation.URLReputationPlugin",
        hooks=[ResourceHookType.RESOURCE_PRE_FETCH],
        config={
            "whitelist_domains": [],
            "allowed_patterns": [],
            "blocked_domains": [],
            "blocked_patterns": [],
            "use_heuristic_check": False,
            "entropy_threshold": 3.5,
            "block_non_secure_http": False,
        },
    )
    mock_rust = MagicMock()
    mock_rust.validate_url_py.side_effect = RuntimeError("Rust engine crashed")
    with patch(f"{_PLUGIN_MODULE}._RUST_AVAILABLE", True), \
         patch(f"{_PLUGIN_MODULE}.URLReputationPluginRust", return_value=mock_rust, create=True):
        plugin = URLReputationPlugin(config)
        res = await plugin.resource_pre_fetch(ResourcePreFetchPayload(uri="https://example.com"), None)
    assert not res.continue_processing
    assert res.violation.reason == "Rust validation failure"
    assert res.violation.code == "URL_REPUTATION_BLOCK"


@pytest.mark.asyncio
async def test_config_normalize_domains_empty():
    """URLReputationConfig normalizes empty domain sets correctly."""
    cfg = URLReputationConfig(
        whitelist_domains=set(),
        blocked_domains=set(),
    )
    assert cfg.whitelist_domains == set()
    assert cfg.blocked_domains == set()


@pytest.mark.asyncio
async def test_config_normalize_domains_none():
    """URLReputationConfig normalizes None domain sets to empty sets."""
    cfg = URLReputationConfig(
        whitelist_domains=None,
        blocked_domains=None,
    )
    assert cfg.whitelist_domains == set()
    assert cfg.blocked_domains == set()


@pytest.mark.asyncio
async def test_config_normalize_domains_mixed_case():
    """URLReputationConfig normalizes domain sets to lowercase."""
    cfg = URLReputationConfig(
        whitelist_domains={"EXAMPLE.COM", "Test.ORG"},
        blocked_domains={"BAD.com"},
    )
    assert cfg.whitelist_domains == {"example.com", "test.org"}
    assert cfg.blocked_domains == {"bad.com"}


@pytest.mark.asyncio
async def test_python_blocked_domain():
    """Python path: URLs on blocked domains are rejected."""
    config = PluginConfig(
        name="urlrep",
        kind="plugins.url_reputation.url_reputation.URLReputationPlugin",
        hooks=[ResourceHookType.RESOURCE_PRE_FETCH],
        config={
            "whitelist_domains": [],
            "allowed_patterns": [],
            "blocked_domains": ["bad.com"],
            "blocked_patterns": [],
            "use_heuristic_check": False,
            "entropy_threshold": 3.5,
            "block_non_secure_http": False,
        },
    )
    with patch(f"{_PLUGIN_MODULE}._RUST_AVAILABLE", False):
        plugin = URLReputationPlugin(config)
        res = await plugin.resource_pre_fetch(ResourcePreFetchPayload(uri="https://bad.com/path"), None)
    assert not res.continue_processing
    assert res.violation.reason == "Blocked domain"


@pytest.mark.asyncio
async def test_python_subdomain_of_blocked_domain():
    """Python path: subdomains of blocked domains are also rejected."""
    config = PluginConfig(
        name="urlrep",
        kind="plugins.url_reputation.url_reputation.URLReputationPlugin",
        hooks=[ResourceHookType.RESOURCE_PRE_FETCH],
        config={
            "whitelist_domains": [],
            "allowed_patterns": [],
            "blocked_domains": ["bad.com"],
            "blocked_patterns": [],
            "use_heuristic_check": False,
            "entropy_threshold": 3.5,
            "block_non_secure_http": False,
        },
    )
    with patch(f"{_PLUGIN_MODULE}._RUST_AVAILABLE", False):
        plugin = URLReputationPlugin(config)
        res = await plugin.resource_pre_fetch(ResourcePreFetchPayload(uri="https://api.bad.com/v1"), None)
    assert not res.continue_processing
    assert res.violation.reason == "Blocked domain"


@pytest.mark.asyncio
async def test_python_case_insensitive_whitelist():
    """Python path: whitelist matching is case-insensitive after normalization."""
    config = PluginConfig(
        name="urlrep",
        kind="plugins.url_reputation.url_reputation.URLReputationPlugin",
        hooks=[ResourceHookType.RESOURCE_PRE_FETCH],
        config={
            "whitelist_domains": ["Example.COM"],
            "allowed_patterns": [],
            "blocked_domains": [],
            "blocked_patterns": [],
            "use_heuristic_check": False,
            "entropy_threshold": 3.5,
            "block_non_secure_http": True,
        },
    )
    with patch(f"{_PLUGIN_MODULE}._RUST_AVAILABLE", False):
        plugin = URLReputationPlugin(config)
        res = await plugin.resource_pre_fetch(ResourcePreFetchPayload(uri="https://example.com/path"), None)
    assert res.continue_processing
