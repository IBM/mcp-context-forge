# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/tools/builder/test_python_deploy.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Unit tests for plain Python MCP Stack deployment.
"""

# Standard
from pathlib import Path
import subprocess
from unittest.mock import MagicMock, Mock, patch, call

# Third-Party
import pytest

# First-Party
from mcpgateway.tools.builder.python_deploy import MCPStackPython


class TestMCPStackPython:
    """Test MCPStackPython deployment class."""

    @patch("mcpgateway.tools.builder.python_deploy.shutil.which")
    def test_init_with_docker(self, mock_which):
        """Test initialization with Docker runtime."""
        mock_which.return_value = "/usr/bin/docker"
        stack = MCPStackPython()
        assert stack.container_runtime == "docker"

    @patch("mcpgateway.tools.builder.python_deploy.shutil.which")
    def test_init_with_podman(self, mock_which):
        """Test initialization with Podman runtime."""

        def which_side_effect(cmd):
            if cmd == "docker":
                return None
            elif cmd == "podman":
                return "/usr/bin/podman"
            return None

        mock_which.side_effect = which_side_effect
        stack = MCPStackPython()
        assert stack.container_runtime == "podman"

    @patch("mcpgateway.tools.builder.python_deploy.shutil.which")
    def test_init_no_runtime(self, mock_which):
        """Test initialization when no container runtime available."""
        mock_which.return_value = None
        with pytest.raises(RuntimeError, match="No container runtime found"):
            MCPStackPython()

    @patch("mcpgateway.tools.builder.python_deploy.shutil.which")
    @patch("mcpgateway.tools.builder.python_deploy.load_config")
    @patch.object(MCPStackPython, "_build_component")
    @pytest.mark.asyncio
    async def test_build_gateway(self, mock_build, mock_load, mock_which):
        """Test building gateway container."""
        mock_which.return_value = "/usr/bin/docker"
        mock_load.return_value = {
            "gateway": {"repo": "https://github.com/test/gateway.git", "ref": "main"},
            "plugins": [],
        }

        stack = MCPStackPython()
        await stack.build("test-config.yaml")

        mock_build.assert_called_once()
        assert mock_build.call_args[0][1] == "gateway"

    @patch("mcpgateway.tools.builder.python_deploy.shutil.which")
    @patch("mcpgateway.tools.builder.python_deploy.load_config")
    @pytest.mark.asyncio
    async def test_build_plugins_only(self, mock_load, mock_which):
        """Test building only plugins."""
        mock_which.return_value = "/usr/bin/docker"
        mock_load.return_value = {
            "gateway": {"repo": "https://github.com/test/gateway.git"},
            "plugins": [
                {"name": "Plugin1", "repo": "https://github.com/test/plugin1.git"}
            ],
        }

        stack = MCPStackPython()
        with patch.object(stack, "_build_component") as mock_build:
            await stack.build("test-config.yaml", plugins_only=True)

            # Gateway should not be built
            calls = [call_args[0][1] for call_args in mock_build.call_args_list]
            assert "gateway" not in calls
            assert "Plugin1" in calls

    @patch("mcpgateway.tools.builder.python_deploy.shutil.which")
    @patch("mcpgateway.tools.builder.python_deploy.load_config")
    @patch.object(MCPStackPython, "_build_component")
    @pytest.mark.asyncio
    async def test_build_specific_plugins(self, mock_build, mock_load, mock_which):
        """Test building specific plugins only."""
        mock_which.return_value = "/usr/bin/docker"
        mock_load.return_value = {
            "gateway": {"image": "mcpgateway:latest"},
            "plugins": [
                {"name": "Plugin1", "repo": "https://github.com/test/plugin1.git"},
                {"name": "Plugin2", "repo": "https://github.com/test/plugin2.git"},
                {"name": "Plugin3", "repo": "https://github.com/test/plugin3.git"},
            ],
        }

        stack = MCPStackPython()
        await stack.build("test-config.yaml", specific_plugins=["Plugin1", "Plugin3"])

        # Should only build Plugin1 and Plugin3
        calls = [call_args[0][1] for call_args in mock_build.call_args_list]
        assert "Plugin1" in calls
        assert "Plugin3" in calls
        assert "Plugin2" not in calls

    @patch("mcpgateway.tools.builder.python_deploy.shutil.which")
    @patch("mcpgateway.tools.builder.python_deploy.load_config")
    @pytest.mark.asyncio
    async def test_build_no_plugins(self, mock_load, mock_which):
        """Test building when no plugins are defined."""
        mock_which.return_value = "/usr/bin/docker"
        mock_load.return_value = {
            "gateway": {"image": "mcpgateway:latest"},
            "plugins": [],
        }

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
        mock_load.return_value = {
            "plugins": [
                {"name": "Plugin1"},
                {"name": "Plugin2"},
            ]
        }

        stack = MCPStackPython()
        await stack.generate_certificates("test-config.yaml")

        # Should call make commands for CA, gateway, and each plugin
        assert mock_run.call_count == 4  # CA + gateway + 2 plugins

    @patch("mcpgateway.tools.builder.python_deploy.load_config")
    @pytest.mark.asyncio
    async def test_generate_certificates_make_not_found(self, mock_load):
        """Test certificate generation when make is not available."""
        mock_load.return_value = {"plugins": []}

        # Patch shutil.which to return docker for __init__, then None for make check
        with patch("mcpgateway.tools.builder.python_deploy.shutil.which") as mock_which:
            # First call returns docker (for __init__), subsequent calls return None (for make check)
            mock_which.side_effect = ["/usr/bin/docker", None]

            stack = MCPStackPython(verbose=True)

            with pytest.raises(RuntimeError, match="'make' command not found"):
                await stack.generate_certificates("test-config.yaml")

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
        mock_load.return_value = {
            "deployment": {"type": "compose", "project_name": "test"},
            "gateway": {"image": "mcpgateway:latest", "mtls_enabled": True},
            "plugins": [],
        }
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
        mock_load.return_value = {
            "deployment": {"type": "compose"},
            "gateway": {"image": "mcpgateway:latest"},
            "plugins": [],
        }
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
        mock_load.return_value = {
            "deployment": {"type": "compose"},
            "gateway": {"image": "mcpgateway:latest", "mtls_enabled": False},
            "plugins": [],
        }
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
        mock_load.return_value = {
            "deployment": {"type": "kubernetes", "namespace": "test-ns"}
        }

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
        mock_load.return_value = {"deployment": {"type": "compose"}}

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
        mock_load.return_value = {"deployment": {"type": "kubernetes"}}

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
        mock_load.return_value = {"deployment": {"type": "compose"}}

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
        mock_load.return_value = {
            "deployment": {"type": "kubernetes", "namespace": "test-ns"},
            "gateway": {"image": "mcpgateway:latest"},
            "plugins": [],
        }

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
        mock_load.return_value = {
            "deployment": {"type": "compose"},
            "gateway": {"image": "mcpgateway:latest"},
            "plugins": [],
        }

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
        mock_load.return_value = {
            "deployment": {"type": "invalid"},
            "gateway": {"image": "mcpgateway:latest"},
        }
        mock_get_deploy.return_value = tmp_path / "deploy"

        stack = MCPStackPython()
        with pytest.raises(ValueError, match="Unsupported deployment type"):
            stack.generate_manifests("test-config.yaml")


class TestBuildComponent:
    """Test _build_component method."""

    @patch("mcpgateway.tools.builder.python_deploy.shutil.which")
    @patch.object(MCPStackPython, "_run_command")
    def test_build_component_clone_new(self, mock_run, mock_which, tmp_path):
        """Test building component with new git clone."""
        mock_which.return_value = "/usr/bin/docker"
        component = {
            "repo": "https://github.com/test/component.git",
            "ref": "main",
            "context": ".",
            "image": "test-component:latest",
        }

        # Create Containerfile in expected location
        build_dir = tmp_path / "build" / "test-component"
        build_dir.mkdir(parents=True)
        (build_dir / "Containerfile").write_text("FROM alpine\n")

        stack = MCPStackPython()

        with patch("mcpgateway.tools.builder.python_deploy.Path") as mock_path_class:
            mock_path_class.return_value = tmp_path / "build" / "test-component"
            # Mock the path checks
            with patch.object(Path, "exists", return_value=True):
                with patch.object(Path, "__truediv__", return_value=build_dir / "Containerfile"):
                    stack._build_component(component, "test-component")

        # Verify git clone was called
        clone_calls = [c for c in mock_run.call_args_list if "git" in str(c) and "clone" in str(c)]
        assert len(clone_calls) > 0

    @patch("mcpgateway.tools.builder.python_deploy.shutil.which")
    def test_build_component_no_repo(self, mock_which):
        """Test building component without repo field."""
        mock_which.return_value = "/usr/bin/docker"
        component = {"image": "test:latest"}

        stack = MCPStackPython()
        with pytest.raises(ValueError, match="has no 'repo' field"):
            stack._build_component(component, "test-component")

    @patch("mcpgateway.tools.builder.python_deploy.shutil.which")
    @patch.object(MCPStackPython, "_run_command")
    def test_build_component_with_target(self, mock_run, mock_which, tmp_path):
        """Test building component with multi-stage target."""
        mock_which.return_value = "/usr/bin/docker"
        component = {
            "repo": "https://github.com/test/component.git",
            "ref": "main",
            "image": "test:latest",
            "target": "production",
        }

        build_dir = tmp_path / "build" / "test"
        build_dir.mkdir(parents=True)
        (build_dir / "Containerfile").write_text("FROM alpine\n")

        stack = MCPStackPython()

        with patch("mcpgateway.tools.builder.python_deploy.Path") as mock_path_class:
            mock_path_class.return_value = build_dir
            with patch.object(Path, "exists", return_value=True):
                with patch.object(Path, "__truediv__", return_value=build_dir / "Containerfile"):
                    stack._build_component(component, "test")

        # Verify --target was included in build command
        build_calls = [c for c in mock_run.call_args_list if "docker" in str(c) and "build" in str(c)]
        assert len(build_calls) > 0


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
