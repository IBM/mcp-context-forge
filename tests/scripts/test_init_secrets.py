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
from unittest.mock import MagicMock, patch, mock_open

# Third-Party
import pytest

# Local
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


@patch("os.path.exists", return_value=False)
@patch("argparse.ArgumentParser.parse_args")
def test_file_creation(mock_args: MagicMock, mock_exists: MagicMock) -> None:
    """
    Verify that the secrets file is created when it does not exist.
    
    Ensures that 'open' is called with the correct path and 'w' mode
    only within the script's namespace.
    """
    mock_args.return_value = patch(
        "argparse.Namespace", output="test.env", force=False, stdout=False
    ).start()
    
    m = mock_open()
    # Patch only the open inside our script's namespace to avoid side effects
    with patch("mcpgateway.scripts.init_secrets.open", m, create=True):
        main()
        m.assert_called_once_with("test.env", "w", encoding="utf-8")


@patch("os.path.exists", return_value=True)
@patch("argparse.ArgumentParser.parse_args")
def test_file_exists_error(mock_args: MagicMock, mock_exists: MagicMock) -> None:
    """
    Verify that the command fails if the file already exists without --force.
    
    Expects a SystemExit with code 1.
    """
    mock_args.return_value = patch(
        "argparse.Namespace", output=".env.secrets", force=False, stdout=False
    ).start()
    
    with pytest.raises(SystemExit) as cm:
        main()
    assert cm.value.code == 1


@patch("os.path.exists", return_value=True)
@patch("argparse.ArgumentParser.parse_args")
def test_force_behavior(mock_args: MagicMock, mock_exists: MagicMock) -> None:
    """
    Verify that --force allows overwriting an existing file.
    
    Ensures the file is opened for writing even if os.path.exists is True.
    """
    mock_args.return_value = patch(
        "argparse.Namespace", output=".env.secrets", force=True, stdout=False
    ).start()
    
    m = mock_open()
    with patch("mcpgateway.scripts.init_secrets.open", m, create=True):
        main()
        m.assert_called_once_with(".env.secrets", "w", encoding="utf-8")


@patch("builtins.print")
@patch("os.path.exists", return_value=False)
@patch("argparse.ArgumentParser.parse_args")
def test_stdout_behavior(
    mock_args: MagicMock, mock_exists: MagicMock, mock_print: MagicMock
) -> None:
    """
    Verify that --stdout prints to console and bypasses file writing.
    
    Checks that the built-in open is never called when stdout is True.
    """
    mock_args.return_value = patch(
        "argparse.Namespace", output=".env.secrets", force=False, stdout=True
    ).start()
    
    with patch("mcpgateway.scripts.init_secrets.open", mock_open()) as mocked_file:
        main()
        mocked_file.assert_not_called()
        # Verify that output was directed to print
        assert mock_print.called