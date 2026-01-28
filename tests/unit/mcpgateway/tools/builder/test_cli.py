# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/tools/builder/test_cli.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Unit tests for builder CLI commands.
"""

# Standard
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch

# Third-Party
import pytest
import typer
from typer.testing import CliRunner

# First-Party
from mcpgateway.tools.builder.cli import app, main


@pytest.fixture
def runner():
    """Create CLI test runner."""
    return CliRunner()


@pytest.fixture
def mock_deployer():
    """Create mock deployer instance."""
    deployer = MagicMock()
    deployer.validate = MagicMock()
    deployer.build = AsyncMock()
    deployer.generate_certificates = AsyncMock()
    deployer.deploy = AsyncMock()
    deployer.verify = AsyncMock()
    deployer.destroy = AsyncMock()
    deployer.generate_manifests = MagicMock(return_value=Path("/tmp/manifests"))
    return deployer


class TestCLICallback:
    """Test CLI callback initialization."""

    @patch("mcpgateway.tools.builder.cli.DeployFactory.create_deployer")
    def test_cli_callback_default(self, mock_factory, runner):
        """Test CLI callback with default options (Python mode by default)."""
        mock_deployer = MagicMock()
        mock_factory.return_value = (mock_deployer, "python")

        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0

    @patch("mcpgateway.tools.builder.cli.DeployFactory.create_deployer")
    def test_cli_callback_verbose(self, mock_factory, runner):
        """Test CLI callback with verbose flag (Python mode by default)."""
        mock_deployer = MagicMock()
        mock_factory.return_value = (mock_deployer, "python")

        result = runner.invoke(app, ["--verbose", "--help"])
        assert result.exit_code == 0

    @patch("mcpgateway.tools.builder.cli.DeployFactory.create_deployer")
    def test_cli_callback_with_dagger(self, mock_factory, runner, tmp_path):
        """Test CLI callback with --dagger flag (opt-in)."""
        mock_deployer = MagicMock()
        mock_deployer.validate = MagicMock()
        mock_factory.return_value = (mock_deployer, "dagger")

        config_file = tmp_path / "test-config.yaml"
        config_file.write_text("deployment:\n  type: compose\n")

        # Use validate command which invokes the callback
        result = runner.invoke(app, ["--dagger", "validate", str(config_file)])
        assert result.exit_code == 0
        # Verify dagger mode was requested
        mock_factory.assert_called_once_with("dagger", False)

    @patch("mcpgateway.tools.builder.cli.DeployFactory.create_deployer")
    def test_cli_callback_default_python(self, mock_factory, runner, tmp_path):
        """Test CLI callback defaults to Python mode."""
        mock_deployer = MagicMock()
        mock_deployer.validate = MagicMock()
        mock_factory.return_value = (mock_deployer, "python")

        config_file = tmp_path / "test-config.yaml"
        config_file.write_text("deployment:\n  type: compose\n")

        # Use validate command without --dagger flag to test default
        result = runner.invoke(app, ["validate", str(config_file)])
        assert result.exit_code == 0
        # Verify python mode was requested (default)
        mock_factory.assert_called_once_with("python", False)


class TestValidateCommand:
    """Test validate command."""

    @patch("mcpgateway.tools.builder.cli.DeployFactory.create_deployer")
    def test_validate_success(self, mock_factory, runner, tmp_path, mock_deployer):
        """Test successful configuration validation."""
        config_file = tmp_path / "mcp-stack.yaml"
        config_file.write_text("deployment:\n  type: compose\n")

        mock_factory.return_value = (mock_deployer, "python")
        mock_deployer.validate.return_value = None

        result = runner.invoke(app, ["validate", str(config_file)])
        assert result.exit_code == 0
        assert "Configuration valid" in result.stdout
        mock_deployer.validate.assert_called_once()

    @patch("mcpgateway.tools.builder.cli.DeployFactory.create_deployer")
    def test_validate_failure(self, mock_factory, runner, tmp_path, mock_deployer):
        """Test validation failure."""
        config_file = tmp_path / "invalid-config.yaml"
        config_file.write_text("invalid: yaml\n")

        mock_factory.return_value = (mock_deployer, "python")
        mock_deployer.validate.side_effect = ValueError("Invalid configuration")

        result = runner.invoke(app, ["validate", str(config_file)])
        assert result.exit_code == 1
        assert "Validation failed" in result.stdout


class TestBuildCommand:
    """Test build command."""

    @patch("mcpgateway.tools.builder.cli.DeployFactory.create_deployer")
    def test_build_success(self, mock_factory, runner, tmp_path, mock_deployer):
        """Test successful build."""
        config_file = tmp_path / "mcp-stack.yaml"
        config_file.write_text("gateway:\n  image: test:latest\n")

        mock_factory.return_value = (mock_deployer, "python")

        result = runner.invoke(app, ["build", str(config_file)])
        assert result.exit_code == 0
        assert "Build complete" in result.stdout
        mock_deployer.build.assert_called_once()

    @patch("mcpgateway.tools.builder.cli.DeployFactory.create_deployer")
    def test_build_plugins_only(self, mock_factory, runner, tmp_path, mock_deployer):
        """Test building only plugins."""
        config_file = tmp_path / "mcp-stack.yaml"
        config_file.write_text("plugins:\n  - name: TestPlugin\n")

        mock_factory.return_value = (mock_deployer, "python")

        result = runner.invoke(app, ["build", str(config_file), "--plugins-only"])
        assert result.exit_code == 0
        # Verify plugins_only flag was passed
        call_kwargs = mock_deployer.build.call_args[1]
        assert call_kwargs["plugins_only"] is True

    @patch("mcpgateway.tools.builder.cli.DeployFactory.create_deployer")
    def test_build_specific_plugins(self, mock_factory, runner, tmp_path, mock_deployer):
        """Test building specific plugins."""
        config_file = tmp_path / "mcp-stack.yaml"
        config_file.write_text("plugins:\n  - name: Plugin1\n  - name: Plugin2\n")

        mock_factory.return_value = (mock_deployer, "python")

        result = runner.invoke(
            app, ["build", str(config_file), "--plugin", "Plugin1", "--plugin", "Plugin2"]
        )
        assert result.exit_code == 0

    @patch("mcpgateway.tools.builder.cli.DeployFactory.create_deployer")
    def test_build_no_cache(self, mock_factory, runner, tmp_path, mock_deployer):
        """Test building with --no-cache flag."""
        config_file = tmp_path / "mcp-stack.yaml"
        config_file.write_text("gateway:\n  image: test:latest\n")

        mock_factory.return_value = (mock_deployer, "python")

        result = runner.invoke(app, ["build", str(config_file), "--no-cache"])
        assert result.exit_code == 0
        call_kwargs = mock_deployer.build.call_args[1]
        assert call_kwargs["no_cache"] is True

    @patch("mcpgateway.tools.builder.cli.DeployFactory.create_deployer")
    def test_build_failure(self, mock_factory, runner, tmp_path, mock_deployer):
        """Test build failure."""
        config_file = tmp_path / "mcp-stack.yaml"
        config_file.write_text("gateway:\n  image: test:latest\n")

        mock_factory.return_value = (mock_deployer, "python")
        mock_deployer.build.side_effect = RuntimeError("Build failed")

        result = runner.invoke(app, ["build", str(config_file)])
        assert result.exit_code == 1
        assert "Build failed" in result.stdout


class TestCertsCommand:
    """Test certs command."""

    @patch("mcpgateway.tools.builder.cli.DeployFactory.create_deployer")
    def test_certs_success(self, mock_factory, runner, tmp_path, mock_deployer):
        """Test successful certificate generation."""
        config_file = tmp_path / "mcp-stack.yaml"
        config_file.write_text("plugins:\n  - name: TestPlugin\n")

        mock_factory.return_value = (mock_deployer, "python")

        result = runner.invoke(app, ["certs", str(config_file)])
        assert result.exit_code == 0
        assert "Certificates generated" in result.stdout
        mock_deployer.generate_certificates.assert_called_once()

    @patch("mcpgateway.tools.builder.cli.DeployFactory.create_deployer")
    def test_certs_failure(self, mock_factory, runner, tmp_path, mock_deployer):
        """Test certificate generation failure."""
        config_file = tmp_path / "mcp-stack.yaml"
        config_file.write_text("plugins:\n  - name: TestPlugin\n")

        mock_factory.return_value = (mock_deployer, "python")
        mock_deployer.generate_certificates.side_effect = RuntimeError("Cert generation failed")

        result = runner.invoke(app, ["certs", str(config_file)])
        assert result.exit_code == 1
        assert "Certificate generation failed" in result.stdout


class TestDeployCommand:
    """Test deploy command."""

    @patch("mcpgateway.tools.builder.cli.DeployFactory.create_deployer")
    def test_deploy_success(self, mock_factory, runner, tmp_path, mock_deployer):
        """Test successful deployment."""
        config_file = tmp_path / "mcp-stack.yaml"
        config_file.write_text("deployment:\n  type: compose\n")

        mock_factory.return_value = (mock_deployer, "python")

        result = runner.invoke(app, ["deploy", str(config_file)])
        assert result.exit_code == 0
        assert "Deployment complete" in result.stdout
        mock_deployer.deploy.assert_called_once()

    @patch("mcpgateway.tools.builder.cli.DeployFactory.create_deployer")
    def test_deploy_dry_run(self, mock_factory, runner, tmp_path, mock_deployer):
        """Test dry-run deployment."""
        config_file = tmp_path / "mcp-stack.yaml"
        config_file.write_text("deployment:\n  type: compose\n")

        mock_factory.return_value = (mock_deployer, "python")

        result = runner.invoke(app, ["deploy", str(config_file), "--dry-run"])
        assert result.exit_code == 0
        assert "Dry-run complete" in result.stdout
        call_kwargs = mock_deployer.deploy.call_args[1]
        assert call_kwargs["dry_run"] is True

    @patch("mcpgateway.tools.builder.cli.DeployFactory.create_deployer")
    def test_deploy_skip_build(self, mock_factory, runner, tmp_path, mock_deployer):
        """Test deployment with --skip-build."""
        config_file = tmp_path / "mcp-stack.yaml"
        config_file.write_text("deployment:\n  type: compose\n")

        mock_factory.return_value = (mock_deployer, "python")

        result = runner.invoke(app, ["deploy", str(config_file), "--skip-build"])
        assert result.exit_code == 0
        call_kwargs = mock_deployer.deploy.call_args[1]
        assert call_kwargs["skip_build"] is True

    @patch("mcpgateway.tools.builder.cli.DeployFactory.create_deployer")
    def test_deploy_skip_certs(self, mock_factory, runner, tmp_path, mock_deployer):
        """Test deployment with --skip-certs."""
        config_file = tmp_path / "mcp-stack.yaml"
        config_file.write_text("deployment:\n  type: compose\n")

        mock_factory.return_value = (mock_deployer, "python")

        result = runner.invoke(app, ["deploy", str(config_file), "--skip-certs"])
        assert result.exit_code == 0
        call_kwargs = mock_deployer.deploy.call_args[1]
        assert call_kwargs["skip_certs"] is True

    @patch("mcpgateway.tools.builder.cli.DeployFactory.create_deployer")
    def test_deploy_custom_output_dir(self, mock_factory, runner, tmp_path, mock_deployer):
        """Test deployment with custom output directory."""
        config_file = tmp_path / "mcp-stack.yaml"
        config_file.write_text("deployment:\n  type: compose\n")
        output_dir = tmp_path / "custom-output"

        mock_factory.return_value = (mock_deployer, "python")

        result = runner.invoke(app, ["deploy", str(config_file), "--output-dir", str(output_dir)])
        assert result.exit_code == 0

    @patch("mcpgateway.tools.builder.cli.DeployFactory.create_deployer")
    def test_deploy_failure(self, mock_factory, runner, tmp_path, mock_deployer):
        """Test deployment failure."""
        config_file = tmp_path / "mcp-stack.yaml"
        config_file.write_text("deployment:\n  type: compose\n")

        mock_factory.return_value = (mock_deployer, "python")
        mock_deployer.deploy.side_effect = RuntimeError("Deployment failed")

        result = runner.invoke(app, ["deploy", str(config_file)])
        assert result.exit_code == 1
        assert "Deployment failed" in result.stdout


class TestVerifyCommand:
    """Test verify command."""

    @patch("mcpgateway.tools.builder.cli.DeployFactory.create_deployer")
    def test_verify_success(self, mock_factory, runner, tmp_path, mock_deployer):
        """Test successful deployment verification."""
        config_file = tmp_path / "mcp-stack.yaml"
        config_file.write_text("deployment:\n  type: compose\n")

        mock_factory.return_value = (mock_deployer, "python")

        result = runner.invoke(app, ["verify", str(config_file)])
        assert result.exit_code == 0
        assert "Deployment healthy" in result.stdout
        mock_deployer.verify.assert_called_once()

    @patch("mcpgateway.tools.builder.cli.DeployFactory.create_deployer")
    def test_verify_with_wait(self, mock_factory, runner, tmp_path, mock_deployer):
        """Test verification with default wait behavior (wait=True by default)."""
        config_file = tmp_path / "mcp-stack.yaml"
        config_file.write_text("deployment:\n  type: compose\n")

        mock_factory.return_value = (mock_deployer, "python")

        # Default wait is True, so just run verify without any flags
        result = runner.invoke(app, ["verify", str(config_file)])
        assert result.exit_code == 0
        call_kwargs = mock_deployer.verify.call_args[1]
        assert call_kwargs["wait"] is True

    @patch("mcpgateway.tools.builder.cli.DeployFactory.create_deployer")
    def test_verify_with_timeout(self, mock_factory, runner, tmp_path, mock_deployer):
        """Test verification with custom timeout."""
        config_file = tmp_path / "mcp-stack.yaml"
        config_file.write_text("deployment:\n  type: compose\n")

        mock_factory.return_value = (mock_deployer, "python")

        result = runner.invoke(app, ["verify", str(config_file), "--timeout", "600"])
        assert result.exit_code == 0
        call_kwargs = mock_deployer.verify.call_args[1]
        assert call_kwargs["timeout"] == 600

    @patch("mcpgateway.tools.builder.cli.DeployFactory.create_deployer")
    def test_verify_failure(self, mock_factory, runner, tmp_path, mock_deployer):
        """Test verification failure."""
        config_file = tmp_path / "mcp-stack.yaml"
        config_file.write_text("deployment:\n  type: compose\n")

        mock_factory.return_value = (mock_deployer, "python")
        mock_deployer.verify.side_effect = RuntimeError("Verification failed")

        result = runner.invoke(app, ["verify", str(config_file)])
        assert result.exit_code == 1
        assert "Verification failed" in result.stdout


class TestDestroyCommand:
    """Test destroy command."""

    @patch("mcpgateway.tools.builder.cli.DeployFactory.create_deployer")
    def test_destroy_with_force(self, mock_factory, runner, tmp_path, mock_deployer):
        """Test destroy with --force flag."""
        config_file = tmp_path / "mcp-stack.yaml"
        config_file.write_text("deployment:\n  type: compose\n")

        mock_factory.return_value = (mock_deployer, "python")

        result = runner.invoke(app, ["destroy", str(config_file), "--force"])
        assert result.exit_code == 0
        assert "Deployment destroyed" in result.stdout
        mock_deployer.destroy.assert_called_once()

    @patch("mcpgateway.tools.builder.cli.DeployFactory.create_deployer")
    def test_destroy_with_confirmation(self, mock_factory, runner, tmp_path, mock_deployer):
        """Test destroy with user confirmation."""
        config_file = tmp_path / "mcp-stack.yaml"
        config_file.write_text("deployment:\n  type: compose\n")

        mock_factory.return_value = (mock_deployer, "python")

        # Simulate user confirming "yes"
        result = runner.invoke(app, ["destroy", str(config_file)], input="y\n")
        assert result.exit_code == 0
        assert "Deployment destroyed" in result.stdout

    @patch("mcpgateway.tools.builder.cli.DeployFactory.create_deployer")
    def test_destroy_abort(self, mock_factory, runner, tmp_path, mock_deployer):
        """Test aborting destroy command."""
        config_file = tmp_path / "mcp-stack.yaml"
        config_file.write_text("deployment:\n  type: compose\n")

        mock_factory.return_value = (mock_deployer, "python")

        # Simulate user declining "no"
        result = runner.invoke(app, ["destroy", str(config_file)], input="n\n")
        assert "Aborted" in result.stdout
        mock_deployer.destroy.assert_not_called()

    @patch("mcpgateway.tools.builder.cli.DeployFactory.create_deployer")
    def test_destroy_failure(self, mock_factory, runner, tmp_path, mock_deployer):
        """Test destroy failure."""
        config_file = tmp_path / "mcp-stack.yaml"
        config_file.write_text("deployment:\n  type: compose\n")

        mock_factory.return_value = (mock_deployer, "python")
        mock_deployer.destroy.side_effect = RuntimeError("Destruction failed")

        result = runner.invoke(app, ["destroy", str(config_file), "--force"])
        assert result.exit_code == 1
        assert "Destruction failed" in result.stdout


class TestGenerateCommand:
    """Test generate command."""

    @patch("mcpgateway.tools.builder.cli.DeployFactory.create_deployer")
    def test_generate_success(self, mock_factory, runner, tmp_path, mock_deployer):
        """Test successful manifest generation."""
        config_file = tmp_path / "mcp-stack.yaml"
        config_file.write_text("deployment:\n  type: compose\n")

        mock_factory.return_value = (mock_deployer, "python")

        result = runner.invoke(app, ["generate", str(config_file)])
        assert result.exit_code == 0
        assert "Manifests generated" in result.stdout
        mock_deployer.generate_manifests.assert_called_once()

    @patch("mcpgateway.tools.builder.cli.DeployFactory.create_deployer")
    def test_generate_with_output_dir(self, mock_factory, runner, tmp_path, mock_deployer):
        """Test manifest generation with custom output directory."""
        config_file = tmp_path / "mcp-stack.yaml"
        config_file.write_text("deployment:\n  type: compose\n")
        output_dir = tmp_path / "custom-manifests"

        mock_factory.return_value = (mock_deployer, "python")

        result = runner.invoke(app, ["generate", str(config_file), "--output", str(output_dir)])
        assert result.exit_code == 0

    @patch("mcpgateway.tools.builder.cli.DeployFactory.create_deployer")
    def test_generate_failure(self, mock_factory, runner, tmp_path, mock_deployer):
        """Test manifest generation failure."""
        config_file = tmp_path / "mcp-stack.yaml"
        config_file.write_text("deployment:\n  type: compose\n")

        mock_factory.return_value = (mock_deployer, "python")
        mock_deployer.generate_manifests.side_effect = ValueError("Generation failed")

        result = runner.invoke(app, ["generate", str(config_file)])
        assert result.exit_code == 1
        assert "Manifest generation failed" in result.stdout


class TestVersionCommand:
    """Test version command."""

    def test_version(self, runner):
        """Test version command."""
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0
        assert "MCP Deploy" in result.stdout
        assert "Version" in result.stdout


class TestMainFunction:
    """Test main entry point."""

    @patch("mcpgateway.tools.builder.cli.app")
    def test_main_success(self, mock_app):
        """Test successful main execution."""
        mock_app.return_value = None
        main()
        mock_app.assert_called_once()

    @patch("mcpgateway.tools.builder.cli.app")
    def test_main_keyboard_interrupt(self, mock_app):
        """Test main with keyboard interrupt."""
        mock_app.side_effect = KeyboardInterrupt()
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 130

    @patch("mcpgateway.tools.builder.cli.app")
    def test_main_exception_no_debug(self, mock_app):
        """Test main with exception (no debug mode)."""
        mock_app.side_effect = RuntimeError("Test error")
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1

    @patch("mcpgateway.tools.builder.cli.app")
    @patch.dict(os.environ, {"MCP_DEBUG": "1"})
    def test_main_exception_debug_mode(self, mock_app):
        """Test main with exception (debug mode enabled)."""
        mock_app.side_effect = RuntimeError("Test error")
        with pytest.raises(RuntimeError, match="Test error"):
            main()
