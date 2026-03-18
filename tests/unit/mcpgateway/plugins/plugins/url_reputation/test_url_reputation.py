# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/plugins/url_reputation/test_url_reputation.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for URLReputationPlugin.
"""

import pytest
from unittest.mock import patch

from mcpgateway.plugins.framework import (
    GlobalContext,
    PluginConfig,
    PluginContext,
    ResourceHookType,
    ResourcePreFetchPayload,
)

from plugins.url_reputation.url_reputation import URLReputationPlugin, URLReputationConfig

try:
    from url_reputation_rust import URLReputationPlugin as _rust_plugin
    _RUST_AVAILABLE = True
except ImportError as e:
    _RUST_AVAILABLE = False
except Exception as e:
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
