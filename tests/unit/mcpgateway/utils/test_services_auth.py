# -*- coding: utf-8 -*-
"""Unit tests for mcpgateway.utils.services_auth

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Author: Mihai Criveti

Covered behaviour
-----------------
* Round-trip integrity: encode_auth ➜ decode_auth
* Graceful handling of None for encode_auth / decode_auth
* get_key raises ValueError when the encryption secret is unset
"""
import pytest

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
