#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./tests/unit/plugins/test_container_scanner/test_cache_manager.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Agnetha

Unit tests for CacheManager.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from plugins.container_scanner.cache.cache_manager import CacheManager
from plugins.container_scanner.types import Vulnerability


def make_vuln(**kwargs) -> Vulnerability:
    defaults = dict(
        scanner="trivy",
        cve_id="CVE-2023-0001",
        severity="HIGH",
        package_name="libfoo",
        installed_version="1.0.0",
        fixed_version="1.0.1",
    )
    defaults.update(kwargs)
    return Vulnerability(**defaults)


class TestCacheManagerLookup:
    def test_miss_when_disabled(self):
        cache = CacheManager(enabled=False)
        cache.store("sha256:abc", [make_vuln()])
        assert cache.lookup("sha256:abc") is None

    def test_miss_on_none_digest(self):
        cache = CacheManager()
        assert cache.lookup(None) is None

    def test_miss_on_empty_string_digest(self):
        cache = CacheManager()
        assert cache.lookup("") is None

    def test_miss_when_not_stored(self):
        cache = CacheManager()
        assert cache.lookup("sha256:unknown") is None

    def test_hit_returns_stored_vulns(self):
        cache = CacheManager()
        vulns = [make_vuln()]
        cache.store("sha256:abc", vulns)
        result = cache.lookup("sha256:abc")
        assert result == vulns

    def test_miss_when_expired(self):
        cache = CacheManager(ttl_hours=1)
        vulns = [make_vuln()]
        cache.store("sha256:abc", vulns)
        # Backdate the cached_at timestamp to simulate expiry
        two_hours_ago = datetime.now(timezone.utc) - timedelta(hours=2)
        cache._cache["sha256:abc"] = (vulns, two_hours_ago)
        assert cache.lookup("sha256:abc") is None
        # Expired entry should be lazily evicted
        assert "sha256:abc" not in cache._cache

    def test_hit_within_ttl(self):
        cache = CacheManager(ttl_hours=24)
        vulns = [make_vuln()]
        cache.store("sha256:abc", vulns)
        assert cache.lookup("sha256:abc") is not None


class TestCacheManagerStore:
    def test_store_is_noop_when_disabled(self):
        cache = CacheManager(enabled=False)
        cache.store("sha256:abc", [make_vuln()])
        assert len(cache._cache) == 0

    def test_store_is_noop_on_none_digest(self):
        cache = CacheManager()
        cache.store(None, [make_vuln()])
        assert len(cache._cache) == 0

    def test_store_overwrites_previous_entry(self):
        cache = CacheManager()
        v1 = [make_vuln(cve_id="CVE-2023-0001")]
        v2 = [make_vuln(cve_id="CVE-2023-0002")]
        cache.store("sha256:abc", v1)
        cache.store("sha256:abc", v2)
        assert cache.lookup("sha256:abc") == v2


class TestCacheManagerInvalidateAndClear:
    def test_invalidate_removes_entry(self):
        cache = CacheManager()
        cache.store("sha256:abc", [make_vuln()])
        cache.invalidate("sha256:abc")
        assert cache.lookup("sha256:abc") is None

    def test_invalidate_nonexistent_is_safe(self):
        cache = CacheManager()
        cache.invalidate("sha256:nonexistent")  # should not raise

    def test_clear_empties_cache(self):
        cache = CacheManager()
        cache.store("sha256:abc", [make_vuln()])
        cache.store("sha256:def", [make_vuln(cve_id="CVE-2023-0002")])
        cache.clear()
        assert cache.lookup("sha256:abc") is None
        assert cache.lookup("sha256:def") is None

    def test_clear_resets_stats(self):
        cache = CacheManager()
        cache.store("sha256:abc", [make_vuln()])
        cache.lookup("sha256:abc")  # hit
        cache.lookup("sha256:miss")  # miss
        cache.clear()
        stats = cache.get_stats()
        assert stats["hits"] == 0.0
        assert stats["misses"] == 0.0


class TestCacheManagerStats:
    def test_initial_stats_are_zero(self):
        cache = CacheManager()
        stats = cache.get_stats()
        assert stats["hits"] == 0.0
        assert stats["misses"] == 0.0
        assert stats["size"] == 0.0
        assert stats["hit_rate_percent"] == 0.0

    def test_hit_rate_calculation(self):
        cache = CacheManager()
        cache.store("sha256:abc", [make_vuln()])
        cache.lookup("sha256:abc")  # hit
        cache.lookup("sha256:abc")  # hit
        cache.lookup("sha256:miss")  # miss
        stats = cache.get_stats()
        assert stats["hits"] == 2.0
        assert stats["misses"] == 1.0
        assert stats["hit_rate_percent"] == pytest.approx(66.67, abs=0.01)

    def test_size_reflects_stored_entries(self):
        cache = CacheManager()
        cache.store("sha256:a", [make_vuln()])
        cache.store("sha256:b", [make_vuln(cve_id="CVE-2023-0002")])
        assert cache.get_stats()["size"] == 2.0
