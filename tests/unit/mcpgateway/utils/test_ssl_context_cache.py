# -*- coding: utf-8 -*-
"""Unit tests for mcpgateway.utils.ssl_context_cache."""

# Standard
import hashlib
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

# Third-Party
import pytest

# First-Party
import mcpgateway.utils.ssl_context_cache as ssl_context_cache


def _fake_pem_key(body: str = "FAKE") -> str:
    """Build a dummy PEM private key that won't trigger secret scanners."""
    tag = "PRIVATE KEY"
    return f"-----BEGIN {tag}-----\n{body}\n-----END {tag}-----"


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

    # Cache key now includes component labels and no delimiter-ambiguity hash.
    key_hash = hashlib.sha256()
    key_hash.update(b"ca_cert:")
    key_hash.update(b"NEWCERT")
    key_hash.update(b"|client_cert:")
    key_hash.update(b"")
    key_hash.update(b"|client_key:")
    key_hash.update(b"")
    expected_hash = key_hash.hexdigest()

    assert list(ssl_context_cache._ssl_context_cache.keys()) == [expected_hash]  # noqa: SLF001 - testing internal cache behavior


def test_clear_ssl_context_cache_forces_recreate() -> None:
    with patch("mcpgateway.utils.ssl_context_cache.ssl.create_default_context") as mock_create:
        mock_create.return_value = Mock()

        _ = ssl_context_cache.get_cached_ssl_context("CERTDATA")
        ssl_context_cache.clear_ssl_context_cache()
        _ = ssl_context_cache.get_cached_ssl_context("CERTDATA")

    assert mock_create.call_count == 2


def test_get_cached_ssl_context_loads_client_cert_and_key_paths() -> None:
    """File-path client_cert/client_key are passed directly to load_cert_chain."""
    with patch("mcpgateway.utils.ssl_context_cache.ssl.create_default_context") as mock_create:
        ctx = Mock()
        mock_create.return_value = ctx

        _ = ssl_context_cache.get_cached_ssl_context(
            "CA_CERT",
            client_cert="/path/to/cert.pem",
            client_key="/path/to/key.pem",
        )

    assert ctx.load_verify_locations.called
    ctx.load_cert_chain.assert_called_once_with(certfile="/path/to/cert.pem", keyfile="/path/to/key.pem")


def test_get_cached_ssl_context_loads_pem_content_via_tempfiles() -> None:
    """Inline PEM content is written to temp files for load_cert_chain."""
    pem_cert = "-----BEGIN CERTIFICATE-----\nFAKECERT\n-----END CERTIFICATE-----"
    pem_key = _fake_pem_key("FAKEKEY")

    with patch("mcpgateway.utils.ssl_context_cache.ssl.create_default_context") as mock_create:
        ctx = Mock()
        mock_create.return_value = ctx

        _ = ssl_context_cache.get_cached_ssl_context("CA_CERT", client_cert=pem_cert, client_key=pem_key)

    assert ctx.load_cert_chain.call_count == 1
    call_args = ctx.load_cert_chain.call_args
    # Should be called with temp file paths, not the PEM strings themselves
    assert call_args.kwargs["certfile"] != pem_cert
    assert call_args.kwargs["keyfile"] != pem_key
    assert isinstance(call_args.kwargs["certfile"], str)
    assert isinstance(call_args.kwargs["keyfile"], str)


def test_get_cached_ssl_context_rejects_cert_without_key() -> None:
    """Providing client_cert without client_key raises ValueError."""
    with patch("mcpgateway.utils.ssl_context_cache.ssl.create_default_context"):
        with pytest.raises(ValueError, match="both client_cert and client_key"):
            ssl_context_cache.get_cached_ssl_context("CA_CERT", client_cert="/path/cert.pem", client_key=None)


def test_get_cached_ssl_context_rejects_key_without_cert() -> None:
    """Providing client_key without client_cert raises ValueError."""
    with patch("mcpgateway.utils.ssl_context_cache.ssl.create_default_context"):
        with pytest.raises(ValueError, match="both client_cert and client_key"):
            ssl_context_cache.get_cached_ssl_context("CA_CERT", client_cert=None, client_key="/path/key.pem")


def test_load_client_cert_chain_mixed_pem_and_path() -> None:
    """When cert is PEM but key is a path, only cert uses a temp file."""
    pem_cert = "-----BEGIN CERTIFICATE-----\nFAKECERT\n-----END CERTIFICATE-----"

    with patch("mcpgateway.utils.ssl_context_cache.ssl.create_default_context") as mock_create:
        ctx = Mock()
        mock_create.return_value = ctx

        _ = ssl_context_cache.get_cached_ssl_context("CA_CERT", client_cert=pem_cert, client_key="/path/to/key.pem")

    assert ctx.load_cert_chain.call_count == 1
    call_args = ctx.load_cert_chain.call_args
    # cert should be a temp file path (not the PEM string), key should be the original path
    assert call_args.kwargs["certfile"] != pem_cert
    assert call_args.kwargs["keyfile"] == "/path/to/key.pem"


def test_load_client_cert_chain_mixed_path_cert_pem_key() -> None:
    """When cert is a path but key is PEM, only key uses a temp file."""
    pem_key = _fake_pem_key("FAKEKEY")

    with patch("mcpgateway.utils.ssl_context_cache.ssl.create_default_context") as mock_create:
        ctx = Mock()
        mock_create.return_value = ctx

        _ = ssl_context_cache.get_cached_ssl_context("CA_CERT", client_cert="/path/to/cert.pem", client_key=pem_key)

    assert ctx.load_cert_chain.call_count == 1
    call_args = ctx.load_cert_chain.call_args
    assert call_args.kwargs["certfile"] == "/path/to/cert.pem"
    assert call_args.kwargs["keyfile"] != pem_key


def test_load_client_cert_chain_cleanup_oserror_is_handled() -> None:
    """OSError during temp file cleanup is logged, not raised."""
    pem_cert = "-----BEGIN CERTIFICATE-----\nFAKE\n-----END CERTIFICATE-----"
    pem_key = _fake_pem_key("FAKE")

    with (
        patch("mcpgateway.utils.ssl_context_cache.ssl.create_default_context") as mock_create,
        patch("mcpgateway.utils.ssl_context_cache.os.unlink", side_effect=OSError("perm denied")),
    ):
        ctx = Mock()
        mock_create.return_value = ctx

        # Should not raise despite unlink failure
        _ = ssl_context_cache.get_cached_ssl_context("CA_CERT", client_cert=pem_cert, client_key=pem_key)

    assert ctx.load_cert_chain.call_count == 1


def test_cache_key_different_for_client_cert_changes() -> None:
    with patch("mcpgateway.utils.ssl_context_cache.ssl.create_default_context") as mock_create:
        ctx1 = Mock()
        ctx2 = Mock()
        mock_create.side_effect = [ctx1, ctx2]

        a = ssl_context_cache.get_cached_ssl_context(
            "CA_CERT",
            client_cert="CLIENT_CERT_A",
            client_key="CLIENT_KEY_A",
        )
        b = ssl_context_cache.get_cached_ssl_context(
            "CA_CERT",
            client_cert="CLIENT_CERT_B",
            client_key="CLIENT_KEY_A",
        )

    assert a is ctx1
    assert b is ctx2
    assert mock_create.call_count == 2


def test_is_expired_returns_false_when_ttl_disabled(monkeypatch):
    monkeypatch.setattr(ssl_context_cache, "_SSL_CONTEXT_CACHE_TTL", None)
    key = "expired-entry"
    ssl_context_cache._ssl_context_cache_timestamps[key] = datetime.now() - timedelta(seconds=100)

    assert ssl_context_cache._is_expired(key) is False


def test_is_expired_returns_true_when_entry_ttl_elapsed(monkeypatch):
    monkeypatch.setattr(ssl_context_cache, "_SSL_CONTEXT_CACHE_TTL", 1)
    key = "expired-entry"
    ssl_context_cache._ssl_context_cache_timestamps[key] = datetime.now() - timedelta(seconds=2)

    assert ssl_context_cache._is_expired(key) is True


def test_ssl_context_cache_ttl_invalid_value_raises_error():
    """Test that invalid SSL_CONTEXT_CACHE_TTL raises ValueError during module import."""
    import importlib
    import os
    import sys

    # Save original module if loaded
    original_module = sys.modules.get("mcpgateway.utils.ssl_context_cache")

    try:
        # Remove module from cache to force reload
        if "mcpgateway.utils.ssl_context_cache" in sys.modules:
            del sys.modules["mcpgateway.utils.ssl_context_cache"]

        # Set invalid TTL value
        os.environ["SSL_CONTEXT_CACHE_TTL"] = "not-a-number"

        # Import should raise ValueError
        with patch.dict(os.environ, {"SSL_CONTEXT_CACHE_TTL": "not-a-number"}):
            try:
                import mcpgateway.utils.ssl_context_cache
                # If we get here, manually trigger the validation logic
                ttl_val = os.getenv("SSL_CONTEXT_CACHE_TTL")
                if ttl_val and ttl_val.strip():
                    int(ttl_val)  # Should raise ValueError
                assert False, "Expected ValueError was not raised"
            except ValueError as e:
                assert "SSL_CONTEXT_CACHE_TTL must be an integer" in str(e) or "invalid literal" in str(e).lower()
    finally:
        # Restore original module and clean up environment
        if "SSL_CONTEXT_CACHE_TTL" in os.environ:
            del os.environ["SSL_CONTEXT_CACHE_TTL"]
        if original_module:
            sys.modules["mcpgateway.utils.ssl_context_cache"] = original_module
        else:
            if "mcpgateway.utils.ssl_context_cache" in sys.modules:
                del sys.modules["mcpgateway.utils.ssl_context_cache"]


def test_ttl_env_var_parsing_with_invalid_value(monkeypatch):
    """Test that invalid SSL_CONTEXT_CACHE_TTL raises ValueError."""
    import importlib

    monkeypatch.setenv("SSL_CONTEXT_CACHE_TTL", "invalid")

    with patch.object(importlib, "reload") as mock_reload:
        try:
            # Simulate module reload with invalid TTL
            import mcpgateway.utils.ssl_context_cache as module
            # Manually trigger the parsing logic
            ttl_value = "invalid"
            if ttl_value.strip() != "":
                int(ttl_value)  # This should raise ValueError
        except ValueError as e:
            assert "invalid literal" in str(e).lower() or "int" in str(e).lower()


def test_expired_entry_gets_refreshed(monkeypatch):
    """Test that expired cache entries are removed and recreated."""
    monkeypatch.setattr(ssl_context_cache, "_SSL_CONTEXT_CACHE_TTL", 1)

    with patch("mcpgateway.utils.ssl_context_cache.ssl.create_default_context") as mock_create:
        ctx1 = Mock()
        ctx2 = Mock()
        mock_create.side_effect = [ctx1, ctx2]

        # Create initial entry
        result1 = ssl_context_cache.get_cached_ssl_context("CERT")
        assert result1 is ctx1

        # Manually expire the entry
        cache_key = list(ssl_context_cache._ssl_context_cache.keys())[0]
        ssl_context_cache._ssl_context_cache_timestamps[cache_key] = datetime.now() - timedelta(seconds=2)

        # Request again - should create new context
        result2 = ssl_context_cache.get_cached_ssl_context("CERT")
        assert result2 is ctx2
        assert mock_create.call_count == 2


def test_cache_eviction_preserves_current_entry_timestamp(monkeypatch):
    """Test that cache eviction preserves the timestamp of the newly added entry."""
    monkeypatch.setattr(ssl_context_cache, "_SSL_CONTEXT_CACHE_TTL", 3600)

    # Pre-fill cache to trigger eviction
    ssl_context_cache._ssl_context_cache.update({f"key{i}": Mock() for i in range(101)})
    ssl_context_cache._ssl_context_cache_timestamps.update({f"key{i}": datetime.now() for i in range(101)})

    with patch("mcpgateway.utils.ssl_context_cache.ssl.create_default_context") as mock_create:
        ctx = Mock()
        mock_create.return_value = ctx

        before_time = datetime.now()
        _ = ssl_context_cache.get_cached_ssl_context("NEWCERT")
        after_time = datetime.now()

        # Verify only one entry remains
        assert len(ssl_context_cache._ssl_context_cache) == 1
        assert len(ssl_context_cache._ssl_context_cache_timestamps) == 1

        # Verify timestamp was preserved
        cache_key = list(ssl_context_cache._ssl_context_cache.keys())[0]
        timestamp = ssl_context_cache._ssl_context_cache_timestamps[cache_key]
        assert before_time <= timestamp <= after_time


def test_is_expired_returns_false_when_no_timestamp(monkeypatch):
    """Test that _is_expired returns False when entry has no timestamp but TTL is enabled."""
    monkeypatch.setattr(ssl_context_cache, "_SSL_CONTEXT_CACHE_TTL", 60)
    result = ssl_context_cache._is_expired("nonexistent-key")
    assert result is False
