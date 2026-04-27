# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/tools/builder/test_python_deploy.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Unit tests for plain Python MCP Stack deployment.
"""

# Standard
from pathlib import Path
import re
import subprocess
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch, call

# Third-Party
import pytest
from pydantic import ValidationError

# First-Party
from mcpgateway.tools.builder.python_deploy import MCPStackPython
from mcpgateway.tools.builder.schema import BuildableConfig, MCPStackConfig


class TestMCPStackPython:
    """Test MCPStackPython deployment class."""

    @patch("mcpgateway.tools.builder.python_deploy.shutil.which")
    @patch("mcpgateway.tools.builder.python_deploy.load_config")
    @pytest.mark.asyncio
    async def test_build_no_plugins(self, mock_load, mock_which):
        """Test building when no plugins are defined."""
        mock_which.return_value = "/usr/bin/docker"
        mock_load.return_value =  MCPStackConfig.model_validate({
            "deployment": {"type": "compose"},
            "gateway": {"image": "mcpgateway:latest"},
            "plugins": [],
        })

        stack = MCPStackPython()
        # Should not raise error
        await stack.build("test-config.yaml", plugins_only=True)

    @patch("mcpgateway.tools.builder.python_deploy.shutil.which")
    @patch("mcpgateway.tools.builder.python_deploy.load_config")
    @patch("mcpgateway.tools.builder.python_deploy.shutil.which", return_value="/usr/bin/make")
    @patch.object(MCPStackPython, "_run_command")
    @pytest.mark.asyncio
    async def test_generate_certificates(self, mock_run, mock_make, mock_load, mock_which_runtime):
        """Test certificate generation."""
        mock_which_runtime.return_value = "/usr/bin/docker"
        mock_load.return_value =  MCPStackConfig.model_validate({
            "gateway": {"image": "mcpgateway:latest"},
            "deployment": {"type": "compose"},
            "plugins": [
                {"name": "Plugin1", "repo": "https://github.com/test/plugin1.git"},
                {"name": "Plugin2", "repo": "https://github.com/test/plugin2.git"},
            ]
        })

        stack = MCPStackPython()
        await stack.generate_certificates("test-config.yaml")

        # Should call make commands for CA, gateway, and each plugin
        assert mock_run.call_count == 4  # CA + gateway + 2 plugins
        mock_run.assert_has_calls(
            [
                call(["make", "certs-mcp-ca", "MCP_CERT_DAYS=825"]),
                call(["make", "certs-mcp-gateway", "MCP_CERT_DAYS=825"]),
                call(["make", "certs-mcp-plugin", "PLUGIN_NAME=Plugin1", "MCP_CERT_DAYS=825"]),
                call(["make", "certs-mcp-plugin", "PLUGIN_NAME=Plugin2", "MCP_CERT_DAYS=825"]),
            ]
        )

    def test_escape_make_value_doubles_dollar(self):
        """Make variable values should escape '$' to '$$'."""
        assert MCPStackPython._escape_make_value("Plugin$Name") == "Plugin$$Name"

    @patch("mcpgateway.tools.builder.python_deploy.shutil.which")
    @patch("mcpgateway.tools.builder.python_deploy.load_config")
    @patch("mcpgateway.tools.builder.python_deploy.shutil.which", return_value="/usr/bin/make")
    @patch.object(MCPStackPython, "_run_command")
    @pytest.mark.asyncio
    async def test_generate_certificates_escapes_plugin_name(self, mock_run, mock_make, mock_load, mock_which_runtime):
        """Certificate generation should escape '$' in make variable values."""
        mock_which_runtime.return_value = "/usr/bin/docker"
        mock_load.return_value = SimpleNamespace(
            certificates=SimpleNamespace(use_cert_manager=False, validity_days=365),
            plugins=[SimpleNamespace(name="Plugin$One")],
        )

        stack = MCPStackPython()
        await stack.generate_certificates("test-config.yaml")

        mock_run.assert_has_calls(
            [
                call(["make", "certs-mcp-ca", "MCP_CERT_DAYS=365"]),
                call(["make", "certs-mcp-gateway", "MCP_CERT_DAYS=365"]),
                call(["make", "certs-mcp-plugin", "PLUGIN_NAME=Plugin$$One", "MCP_CERT_DAYS=365"]),
            ]
        )

    def test_build_component_existing_repo_uses_fetch_separator(self, tmp_path, monkeypatch):
        """Existing clone must fetch refs with '--' separator to avoid option parsing."""
        monkeypatch.chdir(tmp_path)
        clone_dir = tmp_path / "build" / "gateway"
        (clone_dir / ".git").mkdir(parents=True)
        (clone_dir / "Containerfile").write_text("FROM scratch\n")

        config = MCPStackConfig.model_validate(
            {
                "deployment": {"type": "compose"},
                "gateway": {"repo": "https://github.com/test/gateway.git", "ref": "main"},
                "plugins": [],
            }
        )

        stack = MCPStackPython()
        with patch.object(stack, "_detect_container_engine", return_value="docker"):
            with patch.object(stack, "_run_command") as mock_run:
                with patch("mcpgateway.tools.builder.python_deploy.handle_registry_operations", return_value="mcpgateway-gateway:latest"):
                    stack._build_component(config.gateway, config, "gateway")

        assert mock_run.call_args_list[0] == call(["git", "fetch", "origin", "--", "main"], cwd=Path("build/gateway"))

    def test_build_component_new_repo_uses_clone_separator(self, tmp_path, monkeypatch):
        """Fresh clone must pass repository after '--' separator."""
        monkeypatch.chdir(tmp_path)
        clone_dir = tmp_path / "build" / "PluginOne"
        clone_dir.mkdir(parents=True)
        (clone_dir / "Containerfile").write_text("FROM scratch\n")

        config = MCPStackConfig.model_validate(
            {
                "deployment": {"type": "compose"},
                "gateway": {"image": "mcpgateway:latest"},
                "plugins": [{"name": "PluginOne", "repo": "https://github.com/test/plugin1.git", "ref": "release/v1"}],
            }
        )

        stack = MCPStackPython()
        with patch.object(stack, "_detect_container_engine", return_value="docker"):
            with patch.object(stack, "_run_command") as mock_run:
                with patch("mcpgateway.tools.builder.python_deploy.handle_registry_operations", return_value="mcpgateway-pluginone:latest"):
                    stack._build_component(config.plugins[0], config, "PluginOne")

        assert mock_run.call_args_list[0] == call(
            ["git", "clone", "--branch", "release/v1", "--depth", "1", "--", "https://github.com/test/plugin1.git", str(Path("build/PluginOne"))]
        )

    @patch("mcpgateway.tools.builder.python_deploy.shutil.which")
    @patch("mcpgateway.tools.builder.python_deploy.load_config")
    @patch.object(MCPStackPython, "build")
    @patch.object(MCPStackPython, "generate_certificates")
    @patch.object(MCPStackPython, "generate_manifests")
    @patch.object(MCPStackPython, "_deploy_compose")
    @pytest.mark.asyncio
    async def test_deploy_compose(
        self, mock_deploy, mock_gen_manifests, mock_certs, mock_build, mock_load, mock_which
    ):
        """Test full compose deployment."""
        mock_which.return_value = "/usr/bin/docker"
        mock_load.return_value =  MCPStackConfig.model_validate({
            "deployment": {"type": "compose", "project_name": "test"},
            "gateway": {"image": "mcpgateway:latest", "mtls_enabled": True},
            "plugins": [],
        })
        mock_gen_manifests.return_value = Path("/tmp/manifests")

        stack = MCPStackPython()
        await stack.deploy("test-config.yaml")

        mock_build.assert_called_once()
        mock_certs.assert_called_once()
        mock_gen_manifests.assert_called_once()
        mock_deploy.assert_called_once()

    @patch("mcpgateway.tools.builder.python_deploy.shutil.which")
    @patch("mcpgateway.tools.builder.python_deploy.load_config")
    @patch.object(MCPStackPython, "build")
    @patch.object(MCPStackPython, "generate_manifests")
    @pytest.mark.asyncio
    async def test_deploy_dry_run(self, mock_gen_manifests, mock_build, mock_load, mock_which):
        """Test dry-run deployment."""
        mock_which.return_value = "/usr/bin/docker"
        mock_load.return_value =  MCPStackConfig.model_validate({
            "deployment": {"type": "compose"},
            "gateway": {"image": "mcpgateway:latest"},
            "plugins": [],
        })
        mock_gen_manifests.return_value = Path("/tmp/manifests")

        stack = MCPStackPython()
        await stack.deploy("test-config.yaml", dry_run=True, skip_build=True, skip_certs=True)

        mock_gen_manifests.assert_called_once()
        # Should not call actual deployment

    @patch("mcpgateway.tools.builder.python_deploy.shutil.which")
    @patch("mcpgateway.tools.builder.python_deploy.load_config")
    @patch.object(MCPStackPython, "generate_manifests")
    @pytest.mark.asyncio
    async def test_deploy_skip_certs_mtls_disabled(self, mock_gen_manifests, mock_load, mock_which):
        """Test deployment with mTLS disabled."""
        mock_which.return_value = "/usr/bin/docker"
        mock_load.return_value =  MCPStackConfig.model_validate({
            "deployment": {"type": "compose"},
            "gateway": {"image": "mcpgateway:latest", "mtls_enabled": False},
            "plugins": [],
        })
        mock_gen_manifests.return_value = Path("/tmp/manifests")

        stack = MCPStackPython()
        with patch.object(stack, "generate_certificates") as mock_certs:
            await stack.deploy("test-config.yaml", dry_run=True, skip_build=True)

            # Certificates should not be generated
            mock_certs.assert_not_called()

    @patch("mcpgateway.tools.builder.python_deploy.shutil.which")
    @patch("mcpgateway.tools.builder.python_deploy.load_config")
    @patch.object(MCPStackPython, "_verify_kubernetes")
    @pytest.mark.asyncio
    async def test_verify_kubernetes(self, mock_verify, mock_load, mock_which):
        """Test Kubernetes deployment verification."""
        mock_which.return_value = "/usr/bin/docker"
        mock_load.return_value =  MCPStackConfig.model_validate({
            "gateway": {"image": "mcpgateway:latest", "mtls_enabled": False},
            "deployment": {"type": "kubernetes", "namespace": "test-ns"}
        })

        stack = MCPStackPython()
        await stack.verify("test-config.yaml")

        mock_verify.assert_called_once()

    @patch("mcpgateway.tools.builder.python_deploy.shutil.which")
    @patch("mcpgateway.tools.builder.python_deploy.load_config")
    @patch.object(MCPStackPython, "_verify_compose")
    @pytest.mark.asyncio
    async def test_verify_compose(self, mock_verify, mock_load, mock_which):
        """Test Docker Compose deployment verification."""
        mock_which.return_value = "/usr/bin/docker"
        mock_load.return_value =  MCPStackConfig.model_validate({"deployment": {"type": "compose"},
            "gateway": {"image": "mcpgateway:latest", "mtls_enabled": False},
        })

        stack = MCPStackPython()
        await stack.verify("test-config.yaml")

        mock_verify.assert_called_once()

    @patch("mcpgateway.tools.builder.python_deploy.shutil.which")
    @patch("mcpgateway.tools.builder.python_deploy.load_config")
    @patch.object(MCPStackPython, "_destroy_kubernetes")
    @pytest.mark.asyncio
    async def test_destroy_kubernetes(self, mock_destroy, mock_load, mock_which):
        """Test Kubernetes deployment destruction."""
        mock_which.return_value = "/usr/bin/docker"
        mock_load.return_value =  MCPStackConfig.model_validate({"deployment": {"type": "kubernetes"},
            "gateway": {"image": "mcpgateway:latest", "mtls_enabled": False},
        })

        stack = MCPStackPython()
        await stack.destroy("test-config.yaml")

        mock_destroy.assert_called_once()

    @patch("mcpgateway.tools.builder.python_deploy.shutil.which")
    @patch("mcpgateway.tools.builder.python_deploy.load_config")
    @patch.object(MCPStackPython, "_destroy_compose")
    @pytest.mark.asyncio
    async def test_destroy_compose(self, mock_destroy, mock_load, mock_which):
        """Test Docker Compose deployment destruction."""
        mock_which.return_value = "/usr/bin/docker"
        mock_load.return_value =  MCPStackConfig.model_validate({"deployment": {"type": "compose"},
            "gateway": {"image": "mcpgateway:latest", "mtls_enabled": False},
        })

        stack = MCPStackPython()
        await stack.destroy("test-config.yaml")

        mock_destroy.assert_called_once()

    @patch("mcpgateway.tools.builder.python_deploy.shutil.which")
    @patch("mcpgateway.tools.builder.python_deploy.load_config")
    @patch("mcpgateway.tools.builder.python_deploy.generate_plugin_config")
    @patch("mcpgateway.tools.builder.python_deploy.generate_kubernetes_manifests")
    def test_generate_manifests_kubernetes(
        self, mock_k8s_gen, mock_plugin_gen, mock_load, mock_which, tmp_path
    ):
        """Test generating Kubernetes manifests."""
        mock_which.return_value = "/usr/bin/docker"
        mock_load.return_value =  MCPStackConfig.model_validate({
            "deployment": {"type": "kubernetes", "namespace": "test-ns"},
            "gateway": {"image": "mcpgateway:latest"},
            "plugins": [],
        })

        stack = MCPStackPython()
        result = stack.generate_manifests("test-config.yaml", output_dir=str(tmp_path))

        mock_plugin_gen.assert_called_once()
        mock_k8s_gen.assert_called_once()
        assert result == tmp_path

    @patch("mcpgateway.tools.builder.python_deploy.shutil.which")
    @patch("mcpgateway.tools.builder.python_deploy.load_config")
    @patch("mcpgateway.tools.builder.python_deploy.generate_plugin_config")
    @patch("mcpgateway.tools.builder.python_deploy.generate_compose_manifests")
    def test_generate_manifests_compose(
        self, mock_compose_gen, mock_plugin_gen, mock_load, mock_which, tmp_path
    ):
        """Test generating Docker Compose manifests."""
        mock_which.return_value = "/usr/bin/docker"
        mock_load.return_value = MCPStackConfig.model_validate({
            "deployment": {"type": "compose"},
            "gateway": {"image": "mcpgateway:latest"},
            "plugins": [],
        })

        stack = MCPStackPython()
        result = stack.generate_manifests("test-config.yaml", output_dir=str(tmp_path))

        mock_plugin_gen.assert_called_once()
        mock_compose_gen.assert_called_once()
        assert result == tmp_path

    @patch("mcpgateway.tools.builder.python_deploy.shutil.which")
    @patch("mcpgateway.tools.builder.python_deploy.load_config")
    @patch("mcpgateway.tools.builder.python_deploy.get_deploy_dir")
    def test_generate_manifests_invalid_type(self, mock_get_deploy, mock_load, mock_which, tmp_path):
        """Test generating manifests with invalid deployment type."""
        mock_which.return_value = "/usr/bin/docker"
        with pytest.raises(ValidationError, match=r"Input should be 'kubernetes' or 'compose'"):
            mock_load.return_value =  MCPStackConfig.model_validate({
                "deployment": {"type": "invalid"},
                "gateway": {"image": "mcpgateway:latest"},
            })

class TestRunCommand:
    """Test _run_command method."""

    @patch("mcpgateway.tools.builder.python_deploy.shutil.which")
    @patch("mcpgateway.tools.builder.python_deploy.subprocess.run")
    def test_run_command_success(self, mock_run, mock_which):
        """Test successful command execution."""
        mock_which.return_value = "/usr/bin/docker"
        mock_run.return_value = Mock(returncode=0, stdout="Success", stderr="")

        stack = MCPStackPython()
        result = stack._run_command(["echo", "test"])

        assert result.returncode == 0
        mock_run.assert_called_once()

    @patch("mcpgateway.tools.builder.python_deploy.shutil.which")
    @patch("mcpgateway.tools.builder.python_deploy.subprocess.run")
    def test_run_command_failure(self, mock_run, mock_which):
        """Test command execution failure."""
        mock_which.return_value = "/usr/bin/docker"
        mock_run.side_effect = subprocess.CalledProcessError(1, "cmd")

        stack = MCPStackPython()
        with pytest.raises(subprocess.CalledProcessError):
            stack._run_command(["false"])

    @patch("mcpgateway.tools.builder.python_deploy.shutil.which")
    @patch("mcpgateway.tools.builder.python_deploy.subprocess.run")
    def test_run_command_with_cwd(self, mock_run, mock_which, tmp_path):
        """Test command execution with working directory."""
        mock_which.return_value = "/usr/bin/docker"
        mock_run.return_value = Mock(returncode=0)

        stack = MCPStackPython()
        stack._run_command(["ls"], cwd=tmp_path)

        assert mock_run.call_args[1]["cwd"] == tmp_path
