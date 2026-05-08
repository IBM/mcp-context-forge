# -*- coding: utf-8 -*-
"""Location: ./tests/scripts/test_init_secrets.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Eleni Kechrioti

Unit tests for the secrets initialization script.
This module verifies token generation entropy, CLI argument handling,
file system interactions (creation/overwrite), and stdout output.
"""

# Standard
import argparse
from pathlib import Path
import stat
from unittest.mock import MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.scripts.init_secrets import generate_token, main


def test_token_entropy_and_length() -> None:
    """
    Verify that tokens have the correct length and sufficient entropy.

    Checks:
    - 32 bytes input results in 43 chars (URL-safe Base64).
    - 18 bytes input results in 24 chars.
    - Subsequent calls produce different values.
    """
    assert len(generate_token(32)) == 43
    assert len(generate_token(18)) == 24
    # Entropy check
    assert generate_token(32) != generate_token(32)


@patch("os.chmod")
@patch("argparse.ArgumentParser.parse_args")
def test_file_creation(mock_args: MagicMock, mock_chmod: MagicMock, tmp_path: Path) -> None:
    """Verify that the secrets file is created and permissions are set."""
    output_path = tmp_path / "test.env"
    mock_args.return_value = argparse.Namespace(output=str(output_path), force=False, stdout=False)

    main()

    assert output_path.exists()
    assert stat.S_IMODE(output_path.stat().st_mode) == 0o600
    assert "JWT_SECRET_KEY=" in output_path.read_text(encoding="utf-8")
    mock_chmod.assert_not_called()


@patch("os.close")
@patch("os.fchmod", side_effect=OSError("permission update failed"))
@patch("os.open", return_value=123)
@patch("argparse.ArgumentParser.parse_args")
def test_write_failure_closes_fd(mock_args: MagicMock, mock_open: MagicMock, mock_fchmod: MagicMock, mock_close: MagicMock) -> None:
    """Verify that a failed secure write closes the raw file descriptor."""
    mock_args.return_value = argparse.Namespace(output="test.env", force=False, stdout=False)

    with pytest.raises(SystemExit) as cm:
        main()

    assert cm.value.code == 1
    mock_open.assert_called_once()
    mock_fchmod.assert_called_once_with(123, 0o600)
    mock_close.assert_called_once_with(123)


@patch("argparse.ArgumentParser.parse_args")
def test_file_exists_error(mock_args: MagicMock, tmp_path: Path) -> None:
    """
    Verify that the command fails if the file already exists without --force.

    Expects a SystemExit with code 1.
    """
    output_path = tmp_path / ".env.secrets"
    output_path.write_text("existing=true\n", encoding="utf-8")
    mock_args.return_value = argparse.Namespace(output=str(output_path), force=False, stdout=False)

    with pytest.raises(SystemExit) as cm:
        main()
    assert cm.value.code == 1
    assert output_path.read_text(encoding="utf-8") == "existing=true\n"


@patch("argparse.ArgumentParser.parse_args")
def test_force_behavior(mock_args: MagicMock, tmp_path: Path) -> None:
    """
    Verify that --force allows overwriting an existing file.

    Ensures the file is opened for writing even if os.path.exists is True.
    """
    output_path = tmp_path / ".env.secrets"
    output_path.write_text("existing=true\n", encoding="utf-8")
    mock_args.return_value = argparse.Namespace(output=str(output_path), force=True, stdout=False)

    main()

    content = output_path.read_text(encoding="utf-8")
    assert "existing=true" not in content
    assert "AUTH_ENCRYPTION_SECRET=" in content
    assert stat.S_IMODE(output_path.stat().st_mode) == 0o600


@patch("builtins.print")
@patch("argparse.ArgumentParser.parse_args")
def test_stdout_behavior(mock_args: MagicMock, mock_print: MagicMock) -> None:
    """
    Verify that --stdout prints to console and bypasses file writing.

    Checks that the built-in open is never called when stdout is True.
    """
    mock_args.return_value = argparse.Namespace(output=".env.secrets", force=False, stdout=True)

    main()

    mock_print.assert_called_once()
    assert "JWT_SECRET_KEY=" in mock_print.call_args.args[0]
