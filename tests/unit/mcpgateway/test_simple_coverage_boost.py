# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_simple_coverage_boost.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Simple tests to boost coverage to 75%.
"""

# Standard
import sys
from unittest.mock import MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.cli_export_import import AuthenticationError, CLIError


def test_exception_classes():
    """Test exception class inheritance."""
    # Test AuthenticationError
    auth_error = AuthenticationError("Auth failed")
    assert str(auth_error) == "Auth failed"
    assert isinstance(auth_error, Exception)

    # Test CLIError
    cli_error = CLIError("CLI failed")
    assert str(cli_error) == "CLI failed"
    assert isinstance(cli_error, Exception)


@pytest.mark.asyncio
async def test_export_command_basic_structure():
    """Test export command basic structure without execution."""
    # Standard
    import argparse

    # First-Party
    from mcpgateway.cli_export_import import export_command

    # Create minimal args structure
    args = argparse.Namespace(
        types=None,
        exclude_types=None,
        tags=None,
        include_inactive=False,
        include_dependencies=True,
        output=None,
        verbose=False
    )

    # Mock everything to prevent actual execution
    with patch('mcpgateway.cli_export_import.make_authenticated_request') as mock_request:
        mock_request.side_effect = Exception("Mocked to prevent execution")

        with pytest.raises(SystemExit):  # Function calls sys.exit(1) on error
            await export_command(args)


@pytest.mark.asyncio
async def test_import_command_basic_structure():
    """Test import command basic structure without execution."""
    # Standard
    import argparse
    import json
    import tempfile

    # First-Party
    from mcpgateway.cli_export_import import import_command

    # Create test file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump({"version": "2025-03-26", "entities": {}}, f)
        temp_file = f.name

    # Create minimal args structure
    args = argparse.Namespace(
        input_file=temp_file,
        conflict_strategy='update',
        dry_run=False,
        rekey_secret=None,
        include=None,
        verbose=False
    )

    # Mock everything to prevent actual execution
    with patch('mcpgateway.cli_export_import.make_authenticated_request') as mock_request:
        mock_request.side_effect = Exception("Mocked to prevent execution")

        with pytest.raises(SystemExit):  # Function calls sys.exit(1) on error
            await import_command(args)


def test_cli_export_import_constants():
    """Test CLI module constants and basic imports."""
    # First-Party
    from mcpgateway.cli_export_import import logger

    # Test logger exists
    assert logger is not None
    assert hasattr(logger, 'info')
    assert hasattr(logger, 'error')


@pytest.mark.asyncio
async def test_make_authenticated_request_structure():
    """Test make_authenticated_request basic structure."""
    # First-Party
    from mcpgateway.cli_export_import import make_authenticated_request

    # Mock auth token to return None (no auth configured)
    with patch('mcpgateway.cli_export_import.get_auth_token', return_value=None):
        with pytest.raises(AuthenticationError):
            await make_authenticated_request("GET", "/test")


def test_import_command_file_not_found():
    """Test import command with non-existent file."""
    # Standard
    import argparse

    # First-Party
    from mcpgateway.cli_export_import import import_command

    # Args with non-existent file
    args = argparse.Namespace(
        input_file="/nonexistent/file.json",
        conflict_strategy='update',
        dry_run=False,
        rekey_secret=None,
        include=None,
        verbose=False
    )

    # Should exit with error
    # Standard
    import asyncio
    with pytest.raises(SystemExit) as exc_info:
        asyncio.run(import_command(args))

    assert exc_info.value.code == 1


def test_cli_module_imports():
    """Test CLI module can be imported and has expected attributes."""
    # First-Party
    import mcpgateway.cli_export_import as cli_module

    # Test required functions exist
    assert hasattr(cli_module, 'create_parser')
    assert hasattr(cli_module, 'get_auth_token')
    assert hasattr(cli_module, 'export_command')
    assert hasattr(cli_module, 'import_command')
    assert hasattr(cli_module, 'main_with_subcommands')

    # Test required classes exist
    assert hasattr(cli_module, 'AuthenticationError')
    assert hasattr(cli_module, 'CLIError')
