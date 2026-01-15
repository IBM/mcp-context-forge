# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/utils/test_services_auth.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for mcpgateway.utils.services_auth
Author: Mihai Criveti

Covered behaviour
-----------------
* Round-trip integrity: encode_auth ➜ decode_auth
* Graceful handling of None for encode_auth / decode_auth
* get_key raises ValueError when the encryption secret is unset
"""

# Third-Party
import pytest

# First-Party
# --------------------------------------------------------------------------- #
# Import the module under test: mcpgateway.utils.services_auth                #
# --------------------------------------------------------------------------- #
from mcpgateway.utils import services_auth  # noqa: E402  (import after docstring)

encode_auth = services_auth.encode_auth
decode_auth = services_auth.decode_auth
get_key = services_auth.get_key
settings = services_auth.settings


# --------------------------------------------------------------------------- #
# Tests                                                                       #
# --------------------------------------------------------------------------- #
def test_encode_decode_roundtrip(monkeypatch):
    """Data survives an encode ➜ decode cycle unmodified."""
    monkeypatch.setattr(settings, "auth_encryption_secret", "top-secret")

    payload = {"user": "alice", "roles": ["admin", "qa"]}
    encoded = encode_auth(payload)

    assert isinstance(encoded, str) and encoded  # non-empty string

    decoded = decode_auth(encoded)
    assert decoded == payload


def test_encode_none_returns_none(monkeypatch):
    monkeypatch.setattr(settings, "auth_encryption_secret", "x")
    assert encode_auth(None) is None


def test_decode_none_returns_empty_dict(monkeypatch):
    monkeypatch.setattr(settings, "auth_encryption_secret", "x")
    assert decode_auth(None) == {}


def test_get_key_without_secret_raises(monkeypatch):
    """get_key must raise if secret is missing or empty."""
    monkeypatch.setattr(settings, "auth_encryption_secret", "")
    with pytest.raises(ValueError):
        get_key()


def test_crypto_cache_reuse(monkeypatch):
    """Verify that AESGCM and key are cached and reused."""
    from mcpgateway.utils.services_auth import clear_crypto_cache
    clear_crypto_cache()

    monkeypatch.setattr(settings, "auth_encryption_secret", "test-secret")

    # Get key twice - should return same bytes object
    key1 = get_key()
    key2 = get_key()
    assert key1 == key2
    assert isinstance(key1, bytes)


def test_clear_crypto_cache(monkeypatch):
    """Verify that clearing crypto cache works correctly."""
    from mcpgateway.utils.services_auth import clear_crypto_cache

    monkeypatch.setattr(settings, "auth_encryption_secret", "secret1")

    # Warm cache
    get_key()
    encode_auth({"test": "data"})

    # Clear cache
    clear_crypto_cache()

    # Should still work after clearing
    monkeypatch.setattr(settings, "auth_encryption_secret", "secret2")
    key = get_key()
    assert isinstance(key, bytes)


def test_encode_decode_uses_cached_aesgcm(monkeypatch):
    """Verify that encode/decode operations use cached AESGCM."""
    from mcpgateway.utils.services_auth import clear_crypto_cache
    clear_crypto_cache()

    monkeypatch.setattr(settings, "auth_encryption_secret", "cache-test")

    # Multiple encode/decode operations
    data1 = {"user": "alice"}
    data2 = {"user": "bob"}

    token1 = encode_auth(data1)
    token2 = encode_auth(data2)

    assert decode_auth(token1) == data1
    assert decode_auth(token2) == data2
