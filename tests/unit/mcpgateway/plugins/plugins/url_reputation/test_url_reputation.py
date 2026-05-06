# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/plugins/url_reputation/test_url_reputation.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for URLReputationPlugin.
"""

# Third-Party
import pytest

# First-Party
from mcpgateway.plugins.framework import PluginConfig, ResourceHookType, ResourcePreFetchPayload
from cpex_url_reputation.url_reputation import URLReputationConfig, URLReputationPlugin


def _plugin(config: dict) -> URLReputationPlugin:
    return URLReputationPlugin(
        PluginConfig(
            name="urlrep",
            kind="cpex_url_reputation.url_reputation.URLReputationPlugin",
            hooks=[ResourceHookType.RESOURCE_PRE_FETCH],
            config=config,
        )
    )


@pytest.mark.asyncio
async def test_whitelisted_subdomain():
    """Subdomains of a whitelisted domain should be allowed."""
    plugin = _plugin(
        {
            "whitelist_domains": ["example.com"],
            "allowed_patterns": [],
            "blocked_domains": [],
            "blocked_patterns": [],
            "use_heuristic_check": True,
            "entropy_threshold": 3.5,
            "block_non_secure_http": True,
        }
    )

    res = await plugin.resource_pre_fetch(ResourcePreFetchPayload(uri="https://sub.example.com/login"), None)
    assert res.violation is None


@pytest.mark.asyncio
async def test_phishing_like_domain_blocked():
    """Domains mimicking popular sites but not whitelisted are blocked."""
    plugin = _plugin(
        {
            "whitelist_domains": ["paypal.com"],
            "allowed_patterns": [],
            "blocked_domains": [],
            "blocked_patterns": [],
            "use_heuristic_check": True,
            "entropy_threshold": 3.5,
            "block_non_secure_http": True,
        }
    )

    url = "https://pаypal.com/login"  # Cyrillic 'а'
    res = await plugin.resource_pre_fetch(ResourcePreFetchPayload(uri=url), None)
    assert not res.continue_processing


@pytest.mark.asyncio
async def test_http_blocked_but_https_allowed():
    """Non-HTTPS URLs should be blocked while HTTPS passes."""
    plugin = _plugin(
        {
            "whitelist_domains": [],
            "allowed_patterns": [],
            "blocked_domains": [],
            "blocked_patterns": [],
            "use_heuristic_check": False,
            "entropy_threshold": 3.5,
            "block_non_secure_http": True,
        }
    )

    res_http = await plugin.resource_pre_fetch(ResourcePreFetchPayload(uri="http://safe.com"), None)
    res_https = await plugin.resource_pre_fetch(ResourcePreFetchPayload(uri="https://safe.com"), None)

    assert not res_http.continue_processing
    assert res_https.continue_processing


@pytest.mark.asyncio
async def test_allowed_pattern_url():
    """URLs matching allowed patterns bypass checks."""
    plugin = _plugin(
        {
            "whitelist_domains": [],
            "allowed_patterns": [r"^https://trusted\.example/.*$"],
            "blocked_domains": ["malicious.com"],
            "blocked_patterns": [r".*login.*"],
            "use_heuristic_check": True,
            "entropy_threshold": 3.5,
            "block_non_secure_http": True,
        }
    )

    res = await plugin.resource_pre_fetch(ResourcePreFetchPayload(uri="https://trusted.example/path"), None)
    assert res.continue_processing


@pytest.mark.asyncio
async def test_blocked_pattern_url():
    """URLs matching blocked patterns are rejected."""
    plugin = _plugin(
        {
            "whitelist_domains": [],
            "allowed_patterns": [],
            "blocked_domains": [],
            "blocked_patterns": ["admin", "login"],
            "use_heuristic_check": False,
            "entropy_threshold": 3.5,
            "block_non_secure_http": False,
        }
    )

    res = await plugin.resource_pre_fetch(ResourcePreFetchPayload(uri="https://example.com/admin/dashboard"), None)
    assert not res.continue_processing
    assert res.violation.reason == "Blocked pattern"


@pytest.mark.asyncio
async def test_config_normalize_domains_empty():
    """URLReputationConfig normalizes empty domain sets correctly."""
    cfg = URLReputationConfig(whitelist_domains=set(), blocked_domains=set())
    assert cfg.whitelist_domains == set()
    assert cfg.blocked_domains == set()


@pytest.mark.asyncio
async def test_config_normalize_domains_none():
    """URLReputationConfig normalizes None domain sets to empty sets."""
    cfg = URLReputationConfig(whitelist_domains=None, blocked_domains=None)
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
async def test_blocked_domain():
    """URLs on blocked domains are rejected."""
    plugin = _plugin(
        {
            "whitelist_domains": [],
            "allowed_patterns": [],
            "blocked_domains": ["bad.com"],
            "blocked_patterns": [],
            "use_heuristic_check": False,
            "entropy_threshold": 3.5,
            "block_non_secure_http": False,
        }
    )

    res = await plugin.resource_pre_fetch(ResourcePreFetchPayload(uri="https://bad.com/path"), None)
    assert not res.continue_processing
    assert res.violation.reason == "Blocked domain"


@pytest.mark.asyncio
async def test_subdomain_of_blocked_domain():
    """Subdomains of blocked domains are also rejected."""
    plugin = _plugin(
        {
            "whitelist_domains": [],
            "allowed_patterns": [],
            "blocked_domains": ["bad.com"],
            "blocked_patterns": [],
            "use_heuristic_check": False,
            "entropy_threshold": 3.5,
            "block_non_secure_http": False,
        }
    )

    res = await plugin.resource_pre_fetch(ResourcePreFetchPayload(uri="https://api.bad.com/v1"), None)
    assert not res.continue_processing
    assert res.violation.reason == "Blocked domain"


@pytest.mark.asyncio
async def test_case_insensitive_whitelist():
    """Whitelist matching should be case-insensitive after normalization."""
    plugin = _plugin(
        {
            "whitelist_domains": ["Example.COM"],
            "allowed_patterns": [],
            "blocked_domains": [],
            "blocked_patterns": [],
            "use_heuristic_check": False,
            "entropy_threshold": 3.5,
            "block_non_secure_http": True,
        }
    )

    res = await plugin.resource_pre_fetch(ResourcePreFetchPayload(uri="https://example.com/path"), None)
    assert res.continue_processing
