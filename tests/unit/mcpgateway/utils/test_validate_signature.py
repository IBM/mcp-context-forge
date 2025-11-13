# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/utils/test_validate_signature.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit Tests for ./mcpgateway/utils/validate_signature.py
"""

import pytest
import logging
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization

from mcpgateway.utils.validate_signature import sign_data, validate_signature, resign_data

@pytest.fixture
def ed25519_keys():
    private_key = ed25519.Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return private_pem, public_pem, private_key, public_key

def test_sign_data_valid_key(ed25519_keys):
    private_pem, _, private_key, _ = ed25519_keys
    data = b"hello world"
    signature_hex = sign_data(data, private_pem)
    assert isinstance(signature_hex, str)
    assert len(signature_hex) > 0
    # Verify signature correctness
    signature_bytes = bytes.fromhex(signature_hex)
    public_key = private_key.public_key()
    public_key.verify(signature_bytes, data)

def test_sign_data_invalid_key_type(ed25519_keys):
    _, public_pem, _, _ = ed25519_keys
    data = b"invalid"
    with pytest.raises((TypeError, ValueError)):
        sign_data(data, public_pem)

def test_sign_data_invalid_pem_logs_error(caplog):
    caplog.set_level(logging.ERROR)
    with pytest.raises(Exception):
        sign_data(b"data", "not-a-valid-pem")
    assert "Error signing data" in caplog.text

def test_validate_signature_valid(ed25519_keys):
    private_pem, public_pem, private_key, _ = ed25519_keys
    data = b"message"
    signature = private_key.sign(data)
    assert validate_signature(data, signature, public_pem) is True

def test_validate_signature_invalid_signature(ed25519_keys):
    private_pem, public_pem, private_key, _ = ed25519_keys
    data = b"message"
    bad_signature = b"wrong"
    assert validate_signature(data, bad_signature, public_pem) is False

def test_validate_signature_invalid_hex(ed25519_keys, caplog):
    _, public_pem, _, _ = ed25519_keys
    caplog.set_level(logging.ERROR)
    result = validate_signature(b"data", "nothex", public_pem)
    assert result is False
    assert "Invalid hex signature format" in caplog.text

def test_validate_signature_data_as_string(ed25519_keys):
    private_pem, public_pem, private_key, _ = ed25519_keys
    data = "string data"
    signature = private_key.sign(data.encode())
    assert validate_signature(data, signature, public_pem) is True

def test_validate_signature_non_ed25519_key(ed25519_keys, caplog):
    caplog.set_level(logging.ERROR)
    # Use private key PEM as public key PEM to simulate wrong type
    private_pem, _, _, _ = ed25519_keys
    data = b"data"
    signature = b"fake"
    result = validate_signature(data, signature, private_pem)
    assert result is False
    assert "Signature validation failed" in caplog.text

def test_resign_data_no_old_signature(ed25519_keys):
    private_pem, public_pem, private_key, _ = ed25519_keys
    data = b"new data"
    new_signature = resign_data(data, public_pem, b"", private_pem)
    assert isinstance(new_signature, str)
    assert len(new_signature) > 0

def test_resign_data_invalid_old_signature(ed25519_keys, caplog):
    caplog.set_level(logging.WARNING)
    private_pem, public_pem, _, _ = ed25519_keys
    data = b"data"
    result = resign_data(data, public_pem, b"invalidsig", private_pem)
    assert result is None
    assert "Old signature invalid" in caplog.text

def test_resign_data_valid_old_signature(ed25519_keys):
    old_private_pem, old_public_pem, old_private_key, _ = ed25519_keys
    new_private_key = ed25519.Ed25519PrivateKey.generate()
    new_private_pem = new_private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    data = b"data"
    old_signature = old_private_key.sign(data)
    new_signature = resign_data(data, old_public_pem, old_signature, new_private_pem)
    assert isinstance(new_signature, str)
    assert len(new_signature) > 0
