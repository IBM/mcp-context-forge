# -*- coding: utf-8 -*-
"""Unit tests for mcpgateway.utils.ssl_context_cache."""

# Standard
import hashlib
from types import SimpleNamespace
from unittest.mock import Mock, patch

# First-Party
import mcpgateway.utils.ssl_context_cache as ssl_context_cache


def setup_function() -> None:
    # Ensure no cross-test pollution (module uses a global cache).
    ssl_context_cache.clear_ssl_context_cache()


def test_get_cached_ssl_context_caches_by_sha_for_str_and_bytes() -> None:
    with patch("mcpgateway.utils.ssl_context_cache.ssl.create_default_context") as mock_create:
        ctx = Mock()
        mock_create.return_value = ctx

        a = ssl_context_cache.get_cached_ssl_context("CERTDATA")
        b = ssl_context_cache.get_cached_ssl_context(b"CERTDATA")  # Same bytes => same cache key

    assert a is ctx
    assert b is ctx
    assert mock_create.call_count == 1
    ctx.load_verify_locations.assert_called_once()


def test_get_cached_ssl_context_handles_non_string_objects_via_str() -> None:
    class CertObj(SimpleNamespace):
        def __str__(self) -> str:  # pragma: no cover - method invoked by production code
            return "CERTDATA2"

    cert_obj = CertObj()

    with patch("mcpgateway.utils.ssl_context_cache.ssl.create_default_context") as mock_create:
        ctx = Mock()
        mock_create.return_value = ctx

        first = ssl_context_cache.get_cached_ssl_context(cert_obj)  # type: ignore[arg-type]
        second = ssl_context_cache.get_cached_ssl_context(cert_obj)  # type: ignore[arg-type]

    assert first is ctx
    assert second is ctx
    assert mock_create.call_count == 1


def test_get_cached_ssl_context_clears_cache_when_over_limit() -> None:
    # Pre-fill cache so len(cache) > 100 is true when inserting a new entry.
    ssl_context_cache._ssl_context_cache.update({f"key{i}": Mock() for i in range(101)})  # noqa: SLF001 - testing internal cache behavior

    with patch("mcpgateway.utils.ssl_context_cache.ssl.create_default_context") as mock_create:
        ctx = Mock()
        mock_create.return_value = ctx

        _ = ssl_context_cache.get_cached_ssl_context("NEWCERT")

    expected_hash = hashlib.sha256(b"NEWCERT").hexdigest()
    assert list(ssl_context_cache._ssl_context_cache.keys()) == [expected_hash]  # noqa: SLF001 - testing internal cache behavior


def test_clear_ssl_context_cache_forces_recreate() -> None:
    with patch("mcpgateway.utils.ssl_context_cache.ssl.create_default_context") as mock_create:
        mock_create.return_value = Mock()

        _ = ssl_context_cache.get_cached_ssl_context("CERTDATA")
        ssl_context_cache.clear_ssl_context_cache()
        _ = ssl_context_cache.get_cached_ssl_context("CERTDATA")

    assert mock_create.call_count == 2
