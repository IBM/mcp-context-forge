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

#@pytest.mark.asyncio
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

    res = await plugin.resource_pre_fetch(ResourcePreFetchPayload(uri="https://sub.example.com/login"))
    assert res.violation is None


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
    res = await plugin.resource_pre_fetch(ResourcePreFetchPayload(uri=url))
    assert not res.continue_processing


@pytest.mark.asyncio
async def test_http_blocked_but_https_allowed():
    """Non-HTTPS URLs should be blocked; HTTPS allowed."""
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

    res_http = await plugin.resource_pre_fetch(ResourcePreFetchPayload(uri="http://safe.com"))
    res_https = await plugin.resource_pre_fetch(ResourcePreFetchPayload(uri="https://safe.com"))

    assert not res_http.continue_processing
    assert res_https.continue_processing


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
            "entropy_threshold": 2.5,
            "block_non_secure_http": True,
        },
    )
    plugin = URLReputationPlugin(config)

    url = "https://ajsd9a8sd7a98sda7sd9.com"
    res = await plugin.resource_pre_fetch(ResourcePreFetchPayload(uri=url))
    assert not res.continue_processing


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
    res = await plugin.resource_pre_fetch(ResourcePreFetchPayload(uri=url))
    assert res.continue_processing


@pytest.mark.asyncio
async def test_blocked_pattern_url():
    """URLs matching blocked patterns are rejected even if domain is not blocked."""
    config = PluginConfig(
        name="urlrep",
        kind="plugins.url_reputation.url_reputation.URLReputationPlugin",
        hooks=[ResourceHookType.RESOURCE_PRE_FETCH],
        config={
            "whitelist_domains": [],
            "allowed_patterns": [],
            "blocked_domains": [],
            "blocked_patterns": [r".*admin.*", r".*login.*"],
            "use_heuristic_check": False,
            "entropy_threshold": 3.5,
            "block_non_secure_http": True,
        },
    )
    plugin = URLReputationPlugin(config)

    url = "https://example.com/admin/dashboard"
    res = await plugin.resource_pre_fetch(ResourcePreFetchPayload(uri=url))
    assert not res.continue_processing
    assert res.violation.reason == "Blocked pattern"


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
    res = await plugin.resource_pre_fetch(ResourcePreFetchPayload(uri=url))
    assert res.continue_processing


@pytest.mark.asyncio
async def test_mixed_case_domain_allowed():
    """Domains should be case-insensitive."""
    config = PluginConfig(
        name="urlrep",
        kind="plugins.url_reputation.url_reputation.URLReputationPlugin",
        hooks=[ResourceHookType.RESOURCE_PRE_FETCH],
        config={
            "whitelist_domains": ["Example.COM"],
            "allowed_patterns": [],
            "blocked_domains": [],
            "blocked_patterns": [],
            "use_heuristic_check": True,
            "entropy_threshold": 3.5,
            "block_non_secure_http": True,
        },
    )
    plugin = URLReputationPlugin(config)

    url = "https://example.com/path"
    res = await plugin.resource_pre_fetch(ResourcePreFetchPayload(uri=url))
    assert res.continue_processing


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
    res = await plugin.resource_pre_fetch(ResourcePreFetchPayload(uri=url))
    assert res.continue_processing
