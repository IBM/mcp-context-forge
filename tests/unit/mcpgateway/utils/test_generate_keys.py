# -*- coding: utf-8 -*-
"""Tests for generate_keys utilities."""

# Standard
from pathlib import Path

# Third-Party
import pytest

# First-Party
from mcpgateway.utils import generate_keys


def test_generate_ed25519_private_key_and_derive_public():
    """Generate a private key and derive a public key from it."""
    private_pem = generate_keys.generate_ed25519_private_key()
    assert "BEGIN PRIVATE KEY" in private_pem

    public_pem = generate_keys.derive_public_key_from_private(private_pem)
    assert "BEGIN PUBLIC KEY" in public_pem


def test_generate_ed25519_keypair_writes_files(tmp_path: Path):
    """Keypair generator should write PEM files to disk."""
    private_path = tmp_path / "private.pem"
    public_path = tmp_path / "public.pem"

    generate_keys.generate_ed25519_keypair(private_path, public_path)

    assert private_path.exists()
    assert public_path.exists()
    assert "BEGIN PRIVATE KEY" in private_path.read_text()
    assert "BEGIN PUBLIC KEY" in public_path.read_text()


def test_derive_public_key_invalid_pem_logs_error(caplog: pytest.LogCaptureFixture):
    """Invalid PEM should raise a RuntimeError and log an error."""
    with pytest.raises(RuntimeError):
        generate_keys.derive_public_key_from_private("not-a-pem")

    assert any("Error deriving public key" in record.message for record in caplog.records)
