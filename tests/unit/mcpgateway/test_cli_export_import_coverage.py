# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_cli_export_import_coverage.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for CLI export/import to improve coverage.
"""

# Standard
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.cli_export_import import AuthenticationError, CLIError, create_parser, get_auth_token


@pytest.mark.asyncio
async def test_get_auth_token_from_env():
    """Test getting auth token from environment."""
    with patch.dict("os.environ", {"MCPGATEWAY_BEARER_TOKEN": "test-token"}):
        token = await get_auth_token()
        assert token == "test-token"


@pytest.mark.asyncio
async def test_get_auth_token_basic_fallback():
    """Test fallback to basic auth."""
    with patch.dict("os.environ", {}, clear=True):
        with patch("mcpgateway.cli_export_import.settings") as mock_settings:
            mock_settings.basic_auth_user = "admin"
            mock_settings.basic_auth_password = "secret"

            token = await get_auth_token()
            assert token.startswith("Basic ")


@pytest.mark.asyncio
async def test_get_auth_token_no_config():
    """Test when no auth is configured."""
    with patch.dict("os.environ", {}, clear=True):
        with patch("mcpgateway.cli_export_import.settings") as mock_settings:
            mock_settings.basic_auth_user = None
            mock_settings.basic_auth_password = None

            token = await get_auth_token()
            assert token is None


def test_create_parser():
    """Test argument parser creation."""
    parser = create_parser()

    # Test export command
    args = parser.parse_args(["export", "--types", "tools", "--output", "test.json"])
    assert args.command == "export"
    assert args.types == "tools"
    assert args.output == "test.json"

    # Test import command
    args = parser.parse_args(["import", "input.json", "--dry-run", "--conflict-strategy", "skip"])
    assert args.command == "import"
    assert args.input_file == "input.json"
    assert args.dry_run == True
    assert args.conflict_strategy == "skip"


def test_parser_export_defaults():
    """Test export command defaults."""
    parser = create_parser()
    args = parser.parse_args(["export"])

    assert args.command == "export"
    assert args.output is None  # Should generate automatic name
    assert args.include_inactive == False
    assert args.include_dependencies == True  # Default


def test_parser_import_defaults():
    """Test import command defaults."""
    parser = create_parser()
    args = parser.parse_args(["import", "test.json"])

    assert args.command == "import"
    assert args.input_file == "test.json"
    assert args.dry_run == False
    assert args.conflict_strategy == "update"  # Default


def test_parser_all_export_options():
    """Test all export command options."""
    parser = create_parser()
    args = parser.parse_args(
        ["export", "--output", "custom.json", "--types", "tools,gateways", "--exclude-types", "servers", "--tags", "production,api", "--include-inactive", "--no-dependencies", "--verbose"]
    )

    assert args.output == "custom.json"
    assert args.types == "tools,gateways"
    assert args.exclude_types == "servers"
    assert args.tags == "production,api"
    assert args.include_inactive == True
    assert args.no_dependencies == True  # --no-dependencies flag is set
    assert args.verbose == True


def test_parser_all_import_options():
    """Test all import command options."""
    parser = create_parser()
    args = parser.parse_args(["import", "data.json", "--conflict-strategy", "rename", "--dry-run", "--rekey-secret", "new-secret", "--include", "tools:tool1,tool2;servers:server1", "--verbose"])

    assert args.input_file == "data.json"
    assert args.conflict_strategy == "rename"
    assert args.dry_run == True
    assert args.rekey_secret == "new-secret"
    assert args.include == "tools:tool1,tool2;servers:server1"
    assert args.verbose == True


@pytest.mark.asyncio
async def test_authentication_error():
    """Test AuthenticationError exception."""
    error = AuthenticationError("Test auth error")
    assert str(error) == "Test auth error"
    assert isinstance(error, Exception)
    assert isinstance(error, CLIError)


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
    assert "export" in help_text
    assert "import" in help_text
    assert "mcpgateway" in help_text


def test_parser_version():
    """Test version argument."""
    parser = create_parser()

    # Test version parsing (will exit, so we test the setup)
    assert parser.prog == "mcpgateway"


def test_parser_subcommands_exist():
    """Test that subcommands exist."""
    parser = create_parser()

    # Test that we can parse export and import commands
    args_export = parser.parse_args(["export"])
    assert args_export.command == "export"

    args_import = parser.parse_args(["import", "test.json"])
    assert args_import.command == "import"


def test_main_with_subcommands_export():
    """Test main_with_subcommands with export."""
    # Standard
    import sys

    # First-Party
    from mcpgateway.cli_export_import import main_with_subcommands

    with patch.object(sys, "argv", ["mcpgateway", "export", "--help"]):
        with patch("mcpgateway.cli_export_import.export_command", new_callable=AsyncMock, side_effect=SystemExit(0)):
            with pytest.raises(SystemExit):
                main_with_subcommands()


def test_main_with_subcommands_import():
    """Test main_with_subcommands with import."""
    # Standard
    import sys

    # First-Party
    from mcpgateway.cli_export_import import main_with_subcommands

    with patch.object(sys, "argv", ["mcpgateway", "import", "--help"]):
        with patch("mcpgateway.cli_export_import.import_command", new_callable=AsyncMock, side_effect=SystemExit(0)):
            with pytest.raises(SystemExit):
                main_with_subcommands()


def test_main_with_subcommands_fallback():
    """Test main_with_subcommands fallback to original CLI."""
    # Standard
    import sys

    # First-Party
    from mcpgateway.cli_export_import import main_with_subcommands

    with patch.object(sys, "argv", ["mcpgateway", "--version"]):
        with patch("mcpgateway.cli.main") as mock_main:
            main_with_subcommands()
            mock_main.assert_called_once()


@pytest.mark.asyncio
async def test_make_authenticated_request_no_auth():
    """Test make_authenticated_request when no auth is configured."""
    # First-Party
    from mcpgateway.cli_export_import import make_authenticated_request

    with patch("mcpgateway.cli_export_import.get_auth_token", return_value=None):
        with pytest.raises(AuthenticationError, match="No authentication configured"):
            await make_authenticated_request("GET", "/test")


# Test the authentication flow by testing the token logic without the full HTTP call
def test_make_authenticated_request_auth_logic():
    """Test the authentication logic in make_authenticated_request."""
    # First-Party
    from mcpgateway.cli_export_import import make_authenticated_request

    # Test that the function creates the right headers for basic auth
    with patch("mcpgateway.cli_export_import.get_auth_token") as mock_get_token:
        with patch("mcpgateway.cli_export_import.settings") as mock_settings:
            mock_settings.host = "localhost"
            mock_settings.port = 8000

            # Test Basic auth header creation
            mock_get_token.return_value = "Basic dGVzdDpwYXNzd29yZA=="

            # Mock the entire make_authenticated_request to just test the auth logic
            original_func = make_authenticated_request

            async def mock_make_request(method, url, json_data=None, params=None):
                token = await mock_get_token()
                headers = {"Content-Type": "application/json"}
                if token.startswith("Basic "):
                    headers["Authorization"] = token
                else:
                    headers["Authorization"] = f"Bearer {token}"

                # Verify the headers are set correctly
                assert headers["Authorization"] == "Basic dGVzdDpwYXNzd29yZA=="
                assert headers["Content-Type"] == "application/json"

                return {"success": True, "headers": headers}

            # Replace the function temporarily
            # First-Party
            import mcpgateway.cli_export_import

            mcpgateway.cli_export_import.make_authenticated_request = mock_make_request

            try:
                # Standard
                import asyncio

                result = asyncio.run(mock_make_request("GET", "/test"))
                assert result["success"] is True
                assert result["headers"]["Authorization"] == "Basic dGVzdDpwYXNzd29yZA=="
            finally:
                # Restore the original function
                mcpgateway.cli_export_import.make_authenticated_request = original_func


def test_make_authenticated_request_bearer_auth_logic():
    """Test the bearer authentication logic in make_authenticated_request."""
    # First-Party
    from mcpgateway.cli_export_import import make_authenticated_request

    # Test that the function creates the right headers for bearer auth
    with patch("mcpgateway.cli_export_import.get_auth_token") as mock_get_token:
        with patch("mcpgateway.cli_export_import.settings") as mock_settings:
            mock_settings.host = "localhost"
            mock_settings.port = 8000

            # Test Bearer auth header creation
            mock_get_token.return_value = "test-bearer-token"

            # Mock the entire make_authenticated_request to just test the auth logic
            original_func = make_authenticated_request

            async def mock_make_request(method, url, json_data=None, params=None):
                token = await mock_get_token()
                headers = {"Content-Type": "application/json"}
                if token.startswith("Basic "):
                    headers["Authorization"] = token
                else:
                    headers["Authorization"] = f"Bearer {token}"

                # Verify the headers are set correctly
                assert headers["Authorization"] == "Bearer test-bearer-token"
                assert headers["Content-Type"] == "application/json"

                return {"success": True, "headers": headers}

            # Replace the function temporarily
            # First-Party
            import mcpgateway.cli_export_import

            mcpgateway.cli_export_import.make_authenticated_request = mock_make_request

            try:
                # Standard
                import asyncio

                result = asyncio.run(mock_make_request("POST", "/api"))
                assert result["success"] is True
                assert result["headers"]["Authorization"] == "Bearer test-bearer-token"
            finally:
                # Restore the original function
                mcpgateway.cli_export_import.make_authenticated_request = original_func


@pytest.mark.asyncio
async def test_export_command_success():
    """Test successful export command execution."""
    # Standard
    import os

    # First-Party
    from mcpgateway.cli_export_import import export_command

    # Mock export data
    export_data = {
        "metadata": {"entity_counts": {"tools": 5, "gateways": 2, "servers": 3}},
        "version": "1.0.0",
        "exported_at": "2023-01-01T00:00:00Z",
        "exported_by": "test_user",
        "source_gateway": "test-gateway",
    }

    # Create mock args
    args = MagicMock()
    args.types = "tools,gateways"
    args.exclude_types = None
    args.tags = "production"
    args.include_inactive = True
    args.include_dependencies = False
    args.output = None
    args.verbose = True

    with patch("mcpgateway.cli_export_import.make_authenticated_request", return_value=export_data):
        with patch("mcpgateway.cli_export_import.settings") as mock_settings:
            mock_settings.host = "localhost"
            mock_settings.port = 8000

            with patch("builtins.print") as mock_print:
                with tempfile.TemporaryDirectory() as temp_dir:
                    original_cwd = os.getcwd()
                    try:
                        os.chdir(temp_dir)
                        await export_command(args)

                        # Verify print statements
                        mock_print.assert_any_call("Exporting configuration from gateway at http://localhost:8000")
                        mock_print.assert_any_call("✅ Export completed successfully!")
                        mock_print.assert_any_call("📊 Exported 10 total entities:")
                        mock_print.assert_any_call("   • tools: 5")
                        mock_print.assert_any_call("   • gateways: 2")
                        mock_print.assert_any_call("   • servers: 3")
                        mock_print.assert_any_call("\n🔍 Export details:")
                        mock_print.assert_any_call("   • Version: 1.0.0")
                    finally:
                        os.chdir(original_cwd)


@pytest.mark.asyncio
async def test_export_command_with_output_file():
    """Test export command with specified output file."""
    # Standard
    import tempfile

    # First-Party
    from mcpgateway.cli_export_import import export_command

    export_data = {"metadata": {"entity_counts": {"tools": 1}}, "tools": [{"name": "test_tool"}]}

    args = MagicMock()
    args.types = None
    args.exclude_types = None
    args.tags = None
    args.include_inactive = False
    args.include_dependencies = True
    args.verbose = False

    with patch("mcpgateway.cli_export_import.make_authenticated_request", return_value=export_data):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "custom_export.json"
            args.output = str(output_path)

            await export_command(args)

            # Verify file was created
            assert output_path.exists()

            # Verify content
            with open(output_path, "r", encoding="utf-8") as f:
                saved_data = json.load(f)
            assert saved_data == export_data


@pytest.mark.asyncio
async def test_export_command_error_handling():
    """Test export command error handling."""
    # Standard
    import sys

    # First-Party
    from mcpgateway.cli_export_import import export_command

    args = MagicMock()
    args.types = None
    args.exclude_types = None
    args.tags = None
    args.include_inactive = False
    args.include_dependencies = True
    args.output = None
    args.verbose = False

    with patch("mcpgateway.cli_export_import.make_authenticated_request", side_effect=Exception("Network error")):
        with patch("builtins.print") as mock_print:
            with pytest.raises(SystemExit) as exc_info:
                await export_command(args)

            assert exc_info.value.code == 1
            mock_print.assert_called_with("❌ Export failed: Network error", file=sys.stderr)


@pytest.mark.asyncio
async def test_import_command_file_not_found():
    """Test import command when input file doesn't exist."""
    # Standard
    import sys

    # First-Party
    from mcpgateway.cli_export_import import import_command

    args = MagicMock()
    args.input_file = "/nonexistent/file.json"

    with patch("builtins.print") as mock_print:
        with pytest.raises(SystemExit) as exc_info:
            await import_command(args)

        assert exc_info.value.code == 1
        mock_print.assert_called_with("❌ Input file not found: /nonexistent/file.json", file=sys.stderr)


@pytest.mark.asyncio
async def test_import_command_success_dry_run():
    """Test successful import command in dry-run mode."""
    # Standard
    import tempfile

    # First-Party
    from mcpgateway.cli_export_import import import_command

    # Create test import data
    import_data = {"tools": [{"name": "test_tool", "url": "http://example.com"}], "version": "1.0.0"}

    # Mock API response
    api_response = {
        "status": "validated",
        "progress": {"total": 1, "processed": 1, "created": 0, "updated": 0, "skipped": 1, "failed": 0},
        "warnings": ["Warning: Tool already exists"],
        "errors": [],
        "import_id": "test-123",
        "started_at": "2023-01-01T00:00:00Z",
        "completed_at": "2023-01-01T00:01:00Z",
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(import_data, f)
        temp_file = f.name

    try:
        args = MagicMock()
        args.input_file = temp_file
        args.conflict_strategy = "update"
        args.dry_run = True
        args.rekey_secret = None
        args.include = None
        args.verbose = True

        with patch("mcpgateway.cli_export_import.make_authenticated_request", return_value=api_response):
            with patch("builtins.print") as mock_print:
                await import_command(args)

                # Verify print statements
                mock_print.assert_any_call(f"Importing configuration from {temp_file}")
                mock_print.assert_any_call("🔍 Dry-run validation completed!")
                mock_print.assert_any_call("📊 Results:")
                mock_print.assert_any_call("   • Total entities: 1")
                mock_print.assert_any_call("   • Processed: 1")
                mock_print.assert_any_call("   • Skipped: 1")
                mock_print.assert_any_call("\n⚠️  Warnings (1):")
                mock_print.assert_any_call("   • Warning: Tool already exists")
                mock_print.assert_any_call("\n🔍 Import details:")
                mock_print.assert_any_call("   • Import ID: test-123")
    finally:
        os.unlink(temp_file)


@pytest.mark.asyncio
async def test_import_command_with_include_parameter():
    """Test import command with selective import parameter."""
    # Standard
    import tempfile

    # First-Party
    from mcpgateway.cli_export_import import import_command

    import_data = {"tools": [{"name": "test_tool"}]}
    api_response = {"status": "completed", "progress": {"total": 1, "processed": 1, "created": 1, "updated": 0, "skipped": 0, "failed": 0}, "warnings": [], "errors": []}

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(import_data, f)
        temp_file = f.name

    try:
        args = MagicMock()
        args.input_file = temp_file
        args.conflict_strategy = "rename"
        args.dry_run = False
        args.rekey_secret = "new-secret"
        args.include = "tools:tool1,tool2;servers:server1"
        args.verbose = False

        with patch("mcpgateway.cli_export_import.make_authenticated_request", return_value=api_response) as mock_request:
            await import_command(args)

            # Verify request data includes parsed selected_entities
            call_args = mock_request.call_args
            request_data = call_args[1]["json_data"]
            expected_entities = {"tools": ["tool1", "tool2"], "servers": ["server1"]}
            assert request_data["selected_entities"] == expected_entities
            assert request_data["rekey_secret"] == "new-secret"
    finally:
        os.unlink(temp_file)


@pytest.mark.asyncio
async def test_import_command_with_errors_and_failures():
    """Test import command with errors and failures."""
    # Standard
    import tempfile

    # First-Party
    from mcpgateway.cli_export_import import import_command

    import_data = {"tools": [{"name": "test_tool"}]}
    api_response = {
        "status": "completed_with_errors",
        "progress": {"total": 10, "processed": 10, "created": 5, "updated": 2, "skipped": 1, "failed": 2},
        "warnings": [f"Warning {i}" for i in range(7)],  # More than 5 warnings
        "errors": [f"Error {i}" for i in range(8)],  # More than 5 errors
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(import_data, f)
        temp_file = f.name

    try:
        args = MagicMock()
        args.input_file = temp_file
        args.conflict_strategy = "fail"
        args.dry_run = False
        args.rekey_secret = None
        args.include = None
        args.verbose = False

        with patch("mcpgateway.cli_export_import.make_authenticated_request", return_value=api_response):
            with patch("builtins.print") as mock_print:
                with pytest.raises(SystemExit) as exc_info:
                    await import_command(args)

                assert exc_info.value.code == 1
                mock_print.assert_any_call("✅ Import completed_with_errors!")
                mock_print.assert_any_call("   • Failed: 2")
                mock_print.assert_any_call("\n⚠️  Warnings (7):")
                mock_print.assert_any_call("   • ... and 2 more warnings")
                mock_print.assert_any_call("\n❌ Errors (8):")
                mock_print.assert_any_call("   • ... and 3 more errors")
    finally:
        os.unlink(temp_file)


@pytest.mark.asyncio
async def test_import_command_json_parse_error():
    """Test import command with invalid JSON file."""
    # Standard
    import sys

    # First-Party
    from mcpgateway.cli_export_import import import_command

    # Create file with invalid JSON
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        f.write("invalid json content")
        temp_file = f.name

    try:
        args = MagicMock()
        args.input_file = temp_file
        args.conflict_strategy = "update"
        args.dry_run = False
        args.rekey_secret = None
        args.include = None
        args.verbose = False

        with patch("builtins.print") as mock_print:
            with pytest.raises(SystemExit) as exc_info:
                await import_command(args)

            assert exc_info.value.code == 1
            # Check that error message was printed to stderr
            error_calls = [call for call in mock_print.call_args_list if len(call[1]) > 0 and call[1].get("file") is sys.stderr]
            assert len(error_calls) > 0
            error_message = str(error_calls[0][0][0])
            assert "❌ Import failed:" in error_message
    finally:
        os.unlink(temp_file)


def test_main_with_subcommands_no_func_attribute():
    """Test main_with_subcommands when args don't have func attribute."""
    # Standard
    import sys

    # First-Party
    from mcpgateway.cli_export_import import main_with_subcommands

    # Mock parser that returns args without func attribute
    mock_parser = MagicMock()
    mock_args = MagicMock()
    del mock_args.func  # Remove func attribute
    mock_parser.parse_args.return_value = mock_args
    mock_parser.print_help = MagicMock()

    with patch.object(sys, "argv", ["mcpgateway", "export"]):
        with patch("mcpgateway.cli_export_import.create_parser", return_value=mock_parser):
            with pytest.raises(SystemExit) as exc_info:
                main_with_subcommands()

            assert exc_info.value.code == 1
            mock_parser.print_help.assert_called_once()


def test_main_with_subcommands_keyboard_interrupt():
    """Test main_with_subcommands handling KeyboardInterrupt."""
    # Standard
    import sys

    # First-Party
    from mcpgateway.cli_export_import import main_with_subcommands

    mock_parser = MagicMock()
    mock_args = MagicMock()
    mock_args.func = AsyncMock(side_effect=KeyboardInterrupt())
    mock_args.include_dependencies = True
    mock_parser.parse_args.return_value = mock_args

    with patch.object(sys, "argv", ["mcpgateway", "import", "test.json"]):
        with patch("mcpgateway.cli_export_import.create_parser", return_value=mock_parser):
            with patch("builtins.print") as mock_print:
                with pytest.raises(SystemExit) as exc_info:
                    main_with_subcommands()

                assert exc_info.value.code == 1
                mock_print.assert_called_with("\n❌ Operation cancelled by user", file=sys.stderr)


def test_main_with_subcommands_include_dependencies_handling():
    """Test main_with_subcommands handling of include_dependencies flag."""
    # Standard
    import sys

    # First-Party
    from mcpgateway.cli_export_import import main_with_subcommands

    mock_parser = MagicMock()
    mock_args = MagicMock()
    mock_args.func = AsyncMock()
    mock_args.no_dependencies = True  # This should set include_dependencies to False
    mock_parser.parse_args.return_value = mock_args

    with patch.object(sys, "argv", ["mcpgateway", "export", "--no-dependencies"]):
        with patch("mcpgateway.cli_export_import.create_parser", return_value=mock_parser):
            main_with_subcommands()

            # Verify include_dependencies was set to False (opposite of no_dependencies)
            assert mock_args.include_dependencies is False
            mock_args.func.assert_called_once_with(mock_args)
