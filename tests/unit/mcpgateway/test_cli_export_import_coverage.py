# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_cli_export_import_coverage.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for CLI export/import to improve coverage.
"""

# Standard
import argparse
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock
import json

# Third-Party
import pytest

# First-Party
from mcpgateway.cli_export_import import (
    create_parser, get_auth_token, AuthenticationError, CLIError
)


@pytest.mark.asyncio
async def test_get_auth_token_from_env():
    """Test getting auth token from environment."""
    with patch.dict('os.environ', {'MCPGATEWAY_BEARER_TOKEN': 'test-token'}):
        token = await get_auth_token()
        assert token == 'test-token'


@pytest.mark.asyncio
async def test_get_auth_token_basic_fallback():
    """Test fallback to basic auth."""
    with patch.dict('os.environ', {}, clear=True):
        with patch('mcpgateway.cli_export_import.settings') as mock_settings:
            mock_settings.basic_auth_user = 'admin'
            mock_settings.basic_auth_password = 'secret'

            token = await get_auth_token()
            assert token.startswith('Basic ')


@pytest.mark.asyncio
async def test_get_auth_token_no_config():
    """Test when no auth is configured."""
    with patch.dict('os.environ', {}, clear=True):
        with patch('mcpgateway.cli_export_import.settings') as mock_settings:
            mock_settings.basic_auth_user = None
            mock_settings.basic_auth_password = None

            token = await get_auth_token()
            assert token is None


def test_create_parser():
    """Test argument parser creation."""
    parser = create_parser()

    # Test export command
    args = parser.parse_args(['export', '--types', 'tools', '--output', 'test.json'])
    assert args.command == 'export'
    assert args.types == 'tools'
    assert args.output == 'test.json'

    # Test import command
    args = parser.parse_args(['import', 'input.json', '--dry-run', '--conflict-strategy', 'skip'])
    assert args.command == 'import'
    assert args.input_file == 'input.json'
    assert args.dry_run == True
    assert args.conflict_strategy == 'skip'


def test_parser_export_defaults():
    """Test export command defaults."""
    parser = create_parser()
    args = parser.parse_args(['export'])

    assert args.command == 'export'
    assert args.output is None  # Should generate automatic name
    assert args.include_inactive == False
    assert args.include_dependencies == True  # Default


def test_parser_import_defaults():
    """Test import command defaults."""
    parser = create_parser()
    args = parser.parse_args(['import', 'test.json'])

    assert args.command == 'import'
    assert args.input_file == 'test.json'
    assert args.dry_run == False
    assert args.conflict_strategy == 'update'  # Default


def test_parser_all_export_options():
    """Test all export command options."""
    parser = create_parser()
    args = parser.parse_args([
        'export',
        '--output', 'custom.json',
        '--types', 'tools,gateways',
        '--exclude-types', 'servers',
        '--tags', 'production,api',
        '--include-inactive',
        '--no-dependencies',
        '--verbose'
    ])

    assert args.output == 'custom.json'
    assert args.types == 'tools,gateways'
    assert args.exclude_types == 'servers'
    assert args.tags == 'production,api'
    assert args.include_inactive == True
    assert args.no_dependencies == True  # --no-dependencies flag is set
    assert args.verbose == True


def test_parser_all_import_options():
    """Test all import command options."""
    parser = create_parser()
    args = parser.parse_args([
        'import',
        'data.json',
        '--conflict-strategy', 'rename',
        '--dry-run',
        '--rekey-secret', 'new-secret',
        '--include', 'tools:tool1,tool2;servers:server1',
        '--verbose'
    ])

    assert args.input_file == 'data.json'
    assert args.conflict_strategy == 'rename'
    assert args.dry_run == True
    assert args.rekey_secret == 'new-secret'
    assert args.include == 'tools:tool1,tool2;servers:server1'
    assert args.verbose == True


@pytest.mark.asyncio
async def test_authentication_error():
    """Test AuthenticationError exception."""
    error = AuthenticationError("Test auth error")
    assert str(error) == "Test auth error"
    assert isinstance(error, Exception)


@pytest.mark.asyncio
async def test_cli_error():
    """Test CLIError exception."""
    error = CLIError("Test CLI error")
    assert str(error) == "Test CLI error"
    assert isinstance(error, Exception)


def test_parser_help():
    """Test parser help generation."""
    parser = create_parser()

    # Should not raise exception
    help_text = parser.format_help()
    assert 'export' in help_text
    assert 'import' in help_text
    assert 'mcpgateway' in help_text


def test_parser_version():
    """Test version argument."""
    parser = create_parser()

    # Test version parsing (will exit, so we test the setup)
    assert parser.prog == 'mcpgateway'


def test_parser_subcommands_exist():
    """Test that subcommands exist."""
    parser = create_parser()

    # Test that we can parse export and import commands
    args_export = parser.parse_args(['export'])
    assert args_export.command == 'export'

    args_import = parser.parse_args(['import', 'test.json'])
    assert args_import.command == 'import'


def test_main_with_subcommands_export():
    """Test main_with_subcommands with export."""
    from mcpgateway.cli_export_import import main_with_subcommands
    import sys

    with patch.object(sys, 'argv', ['mcpgateway', 'export', '--help']):
        with patch('mcpgateway.cli_export_import.asyncio.run') as mock_run:
            mock_run.side_effect = SystemExit(0)  # Simulate help exit
            with pytest.raises(SystemExit):
                main_with_subcommands()


def test_main_with_subcommands_import():
    """Test main_with_subcommands with import."""
    from mcpgateway.cli_export_import import main_with_subcommands
    import sys

    with patch.object(sys, 'argv', ['mcpgateway', 'import', '--help']):
        with patch('mcpgateway.cli_export_import.asyncio.run') as mock_run:
            mock_run.side_effect = SystemExit(0)  # Simulate help exit
            with pytest.raises(SystemExit):
                main_with_subcommands()


def test_main_with_subcommands_fallback():
    """Test main_with_subcommands fallback to original CLI."""
    from mcpgateway.cli_export_import import main_with_subcommands
    import sys

    with patch.object(sys, 'argv', ['mcpgateway', '--version']):
        with patch('mcpgateway.cli.main') as mock_main:
            main_with_subcommands()
            mock_main.assert_called_once()
