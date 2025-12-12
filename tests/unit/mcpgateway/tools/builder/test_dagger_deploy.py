# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/tools/builder/test_dagger_deploy.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Unit tests for Dagger-based MCP Stack deployment.

These tests are skipped if Dagger is not installed.
"""

# Standard
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch

# Third-Party
import pytest

# Check if dagger is available
try:
    import dagger

    DAGGER_AVAILABLE = True
except ImportError:
    DAGGER_AVAILABLE = False

# Skip all tests in this module if Dagger is not available
pytestmark = pytest.mark.skipif(not DAGGER_AVAILABLE, reason="Dagger not installed")

# Conditional import to avoid errors when Dagger is not installed
if DAGGER_AVAILABLE:
    # First-Party
    from mcpgateway.tools.builder.dagger_deploy import MCPStackDagger
else:
    # Create a dummy class to avoid NameError in decorators
    MCPStackDagger = type("MCPStackDagger", (), {})


@pytest.fixture
def mock_dagger_connection(tmp_path):
    """Fixture to mock Dagger connection and dag."""
    with patch("mcpgateway.tools.builder.dagger_deploy.dagger.connection") as mock_conn:
        with patch("mcpgateway.tools.builder.dagger_deploy.dag") as mock_dag:
            with patch("mcpgateway.tools.builder.dagger_deploy.Path.cwd") as mock_cwd:
                # Mock Path.cwd() to return a valid temporary directory
                mock_cwd.return_value = tmp_path

                # Mock the async context manager
                mock_conn_ctx = AsyncMock()
                mock_conn.return_value = mock_conn_ctx
                mock_conn_ctx.__aenter__.return_value = None
                mock_conn_ctx.__aexit__.return_value = None

                # Setup dag mocks (use regular Mock for synchronous Dagger API)
                mock_git = Mock()
                mock_tree = Mock()
                mock_container = Mock()
                mock_container.export_image = AsyncMock()  # Only export_image is async
                mock_host = Mock()
                mock_dir = Mock()
                mock_dir.export = AsyncMock()  # export is async

                # Set up the method chain for git operations
                mock_dag.git.return_value = mock_git
                mock_git.branch.return_value = mock_git
                mock_git.tree.return_value = mock_tree
                mock_tree.docker_build.return_value = mock_container

                # Set up container operations
                mock_dag.container.return_value = mock_container
                mock_container.from_.return_value = mock_container
                mock_container.with_exec.return_value = mock_container
                mock_container.with_mounted_directory.return_value = mock_container
                mock_container.with_workdir.return_value = mock_container
                mock_container.directory.return_value = mock_dir

                # Set up host operations
                mock_dag.host.return_value = mock_host
                mock_host.directory.return_value = mock_dir

                yield {"connection": mock_conn, "dag": mock_dag, "container": mock_container}


class TestMCPStackDaggerInit:
    """Test MCPStackDagger initialization."""

    def test_init_default(self):
        """Test default initialization."""
        stack = MCPStackDagger()
        assert stack.verbose is False

    def test_init_verbose(self):
        """Test initialization with verbose flag."""
        stack = MCPStackDagger(verbose=True)
        assert stack.verbose is True


class TestMCPStackDaggerBuild:
    """Test MCPStackDagger build method."""

    @patch("mcpgateway.tools.builder.dagger_deploy.get_deploy_dir")
    @patch("mcpgateway.tools.builder.dagger_deploy.load_config")
    @pytest.mark.asyncio
    async def test_build_gateway_only(self, mock_load, mock_get_deploy, mock_dagger_connection, tmp_path):
        """Test building gateway container with Dagger."""
        mock_load.return_value = {
            "gateway": {"repo": "https://github.com/test/gateway.git", "ref": "main"},
            "plugins": [],
        }
        mock_get_deploy.return_value = tmp_path / "deploy"

        stack = MCPStackDagger()
        await stack.build("test-config.yaml")

        mock_load.assert_called_once_with("test-config.yaml")

    @patch("mcpgateway.tools.builder.dagger_deploy.get_deploy_dir")
    @patch("mcpgateway.tools.builder.dagger_deploy.load_config")
    @pytest.mark.asyncio
    async def test_build_plugins_only(self, mock_load, mock_get_deploy, mock_dagger_connection, tmp_path):
        """Test building only plugins."""
        mock_load.return_value = {
            "gateway": {"repo": "https://github.com/test/gateway.git"},
            "plugins": [
                {"name": "Plugin1", "repo": "https://github.com/test/plugin1.git"}
            ],
        }
        mock_get_deploy.return_value = tmp_path / "deploy"

        stack = MCPStackDagger()
        await stack.build("test-config.yaml", plugins_only=True)

        mock_load.assert_called_once()

    @patch("mcpgateway.tools.builder.dagger_deploy.get_deploy_dir")
    @patch("mcpgateway.tools.builder.dagger_deploy.load_config")
    @pytest.mark.asyncio
    async def test_build_specific_plugins(self, mock_load, mock_get_deploy, mock_dagger_connection, tmp_path):
        """Test building specific plugins only."""
        mock_load.return_value = {
            "gateway": {"image": "mcpgateway:latest"},
            "plugins": [
                {"name": "Plugin1", "repo": "https://github.com/test/plugin1.git"},
                {"name": "Plugin2", "repo": "https://github.com/test/plugin2.git"},
            ],
        }
        mock_get_deploy.return_value = tmp_path / "deploy"

        stack = MCPStackDagger()
        await stack.build("test-config.yaml", specific_plugins=["Plugin1"])

        mock_load.assert_called_once()

    @patch("mcpgateway.tools.builder.dagger_deploy.get_deploy_dir")
    @patch("mcpgateway.tools.builder.dagger_deploy.load_config")
    @pytest.mark.asyncio
    async def test_build_no_plugins(self, mock_load, mock_get_deploy, mock_dagger_connection, tmp_path):
        """Test building when no plugins are defined."""
        mock_load.return_value = {
            "gateway": {"image": "mcpgateway:latest"},
            "plugins": [],
        }
        mock_get_deploy.return_value = tmp_path / "deploy"

        stack = MCPStackDagger()
        # Should not raise error
        await stack.build("test-config.yaml", plugins_only=True)


class TestMCPStackDaggerGenerateCertificates:
    """Test MCPStackDagger generate_certificates method."""

    @patch("mcpgateway.tools.builder.dagger_deploy.get_deploy_dir")
    @patch("mcpgateway.tools.builder.dagger_deploy.load_config")
    @pytest.mark.asyncio
    async def test_generate_certificates(self, mock_load, mock_get_deploy, mock_dagger_connection, tmp_path):
        """Test certificate generation with Dagger."""
        mock_load.return_value = {
            "plugins": [
                {"name": "Plugin1"},
                {"name": "Plugin2"},
            ]
        }
        mock_get_deploy.return_value = tmp_path / "deploy"

        stack = MCPStackDagger()
        await stack.generate_certificates("test-config.yaml")

        mock_load.assert_called_once()


class TestMCPStackDaggerDeploy:
    """Test MCPStackDagger deploy method."""

    @patch("mcpgateway.tools.builder.dagger_deploy.get_deploy_dir")
    @patch("mcpgateway.tools.builder.dagger_deploy.load_config")
    @patch.object(MCPStackDagger, "build")
    @patch.object(MCPStackDagger, "generate_certificates")
    @patch.object(MCPStackDagger, "generate_manifests")
    @patch.object(MCPStackDagger, "_deploy_compose")
    @pytest.mark.asyncio
    async def test_deploy_compose_full(
        self, mock_deploy, mock_gen_manifests, mock_certs, mock_build, mock_load, mock_get_deploy, mock_dagger_connection, tmp_path
    ):
        """Test full Docker Compose deployment with Dagger."""
        mock_load.return_value = {
            "deployment": {"type": "compose", "project_name": "test"},
            "gateway": {"repo": "https://github.com/test/gateway.git", "mtls_enabled": True},
            "plugins": [],
        }
        mock_gen_manifests.return_value = Path("/tmp/manifests")
        mock_get_deploy.return_value = tmp_path / "deploy"

        stack = MCPStackDagger()
        await stack.deploy("test-config.yaml")

        mock_build.assert_called_once()
        mock_certs.assert_called_once()
        mock_gen_manifests.assert_called_once()
        mock_deploy.assert_called_once()

    @patch("mcpgateway.tools.builder.dagger_deploy.load_config")
    @patch.object(MCPStackDagger, "generate_manifests")
    @pytest.mark.asyncio
    async def test_deploy_dry_run(self, mock_gen_manifests, mock_load, mock_dagger_connection, tmp_path):
        """Test dry-run deployment with Dagger."""
        mock_load.return_value = {
            "deployment": {"type": "compose"},
            "gateway": {"image": "mcpgateway:latest"},
            "plugins": [],
        }
        mock_gen_manifests.return_value = Path("/tmp/manifests")

        stack = MCPStackDagger()
        await stack.deploy("test-config.yaml", dry_run=True, skip_build=True, skip_certs=True)

        mock_gen_manifests.assert_called_once()

    @patch("mcpgateway.tools.builder.dagger_deploy.get_deploy_dir")
    @patch("mcpgateway.tools.builder.dagger_deploy.load_config")
    @patch.object(MCPStackDagger, "generate_manifests")
    @patch.object(MCPStackDagger, "_deploy_kubernetes")
    @pytest.mark.asyncio
    async def test_deploy_kubernetes(self, mock_deploy, mock_gen_manifests, mock_load, mock_get_deploy, mock_dagger_connection, tmp_path):
        """Test Kubernetes deployment with Dagger."""
        mock_load.return_value = {
            "deployment": {"type": "kubernetes", "namespace": "test-ns"},
            "gateway": {"image": "mcpgateway:latest", "mtls_enabled": False},
            "plugins": [],
        }
        mock_gen_manifests.return_value = Path("/tmp/manifests")
        mock_get_deploy.return_value = tmp_path / "deploy"

        stack = MCPStackDagger()
        await stack.deploy("test-config.yaml", skip_build=True, skip_certs=True)

        mock_deploy.assert_called_once()


class TestMCPStackDaggerVerify:
    """Test MCPStackDagger verify method."""

    @patch("mcpgateway.tools.builder.dagger_deploy.get_deploy_dir")
    @patch("mcpgateway.tools.builder.dagger_deploy.load_config")
    @patch.object(MCPStackDagger, "_verify_kubernetes")
    @pytest.mark.asyncio
    async def test_verify_kubernetes(self, mock_verify_kubernetes, mock_load, mock_get_deploy, mock_dagger_connection, tmp_path):
        """Test Kubernetes deployment verification with Dagger."""
        mock_load.return_value = {
            "deployment": {"type": "kubernetes", "namespace": "test-ns"}
        }
        mock_get_deploy.return_value = tmp_path / "deploy"

        stack = MCPStackDagger()
        await stack.verify("test-config.yaml")

        mock_verify_kubernetes.assert_called_once()

    @patch("mcpgateway.tools.builder.dagger_deploy.get_deploy_dir")
    @patch("mcpgateway.tools.builder.dagger_deploy.load_config")
    @patch.object(MCPStackDagger, "_verify_compose")
    @pytest.mark.asyncio
    async def test_verify_compose(self, mock_verify_compose, mock_load, mock_get_deploy, mock_dagger_connection, tmp_path):
        """Test Docker Compose deployment verification with Dagger."""
        mock_load.return_value = {"deployment": {"type": "compose"}}
        mock_get_deploy.return_value = tmp_path / "deploy"

        stack = MCPStackDagger()
        await stack.verify("test-config.yaml")

        mock_verify_compose.assert_called_once()


class TestMCPStackDaggerDestroy:
    """Test MCPStackDagger destroy method."""

    @patch("mcpgateway.tools.builder.dagger_deploy.get_deploy_dir")
    @patch("mcpgateway.tools.builder.dagger_deploy.load_config")
    @patch.object(MCPStackDagger, "_destroy_kubernetes")
    @pytest.mark.asyncio
    async def test_destroy_kubernetes(self, mock_destroy_kubernetes, mock_load, mock_get_deploy, mock_dagger_connection, tmp_path):
        """Test Kubernetes deployment destruction with Dagger."""
        mock_load.return_value = {"deployment": {"type": "kubernetes"}}
        mock_get_deploy.return_value = tmp_path / "deploy"

        stack = MCPStackDagger()
        await stack.destroy("test-config.yaml")

        mock_destroy_kubernetes.assert_called_once()

    @patch("mcpgateway.tools.builder.dagger_deploy.get_deploy_dir")
    @patch("mcpgateway.tools.builder.dagger_deploy.load_config")
    @patch.object(MCPStackDagger, "_destroy_compose")
    @pytest.mark.asyncio
    async def test_destroy_compose(self, mock_destroy_compose, mock_load, mock_get_deploy, mock_dagger_connection, tmp_path):
        """Test Docker Compose deployment destruction with Dagger."""
        mock_load.return_value = {"deployment": {"type": "compose"}}
        mock_get_deploy.return_value = tmp_path / "deploy"

        stack = MCPStackDagger()
        await stack.destroy("test-config.yaml")

        mock_destroy_compose.assert_called_once()


class TestMCPStackDaggerGenerateManifests:
    """Test MCPStackDagger generate_manifests method."""

    @patch("mcpgateway.tools.builder.dagger_deploy.load_config")
    @patch("mcpgateway.tools.builder.dagger_deploy.generate_plugin_config")
    @patch("mcpgateway.tools.builder.dagger_deploy.generate_kubernetes_manifests")
    def test_generate_manifests_kubernetes(
        self, mock_k8s_gen, mock_plugin_gen, mock_load, tmp_path
    ):
        """Test generating Kubernetes manifests with Dagger."""
        mock_load.return_value = {
            "deployment": {"type": "kubernetes", "namespace": "test-ns"},
            "gateway": {"image": "mcpgateway:latest"},
            "plugins": [],
        }

        stack = MCPStackDagger()
        result = stack.generate_manifests("test-config.yaml", output_dir=str(tmp_path))

        mock_plugin_gen.assert_called_once()
        mock_k8s_gen.assert_called_once()
        assert result == tmp_path

    @patch("mcpgateway.tools.builder.dagger_deploy.load_config")
    @patch("mcpgateway.tools.builder.dagger_deploy.generate_plugin_config")
    @patch("mcpgateway.tools.builder.dagger_deploy.generate_compose_manifests")
    def test_generate_manifests_compose(
        self, mock_compose_gen, mock_plugin_gen, mock_load, tmp_path
    ):
        """Test generating Docker Compose manifests with Dagger."""
        mock_load.return_value = {
            "deployment": {"type": "compose"},
            "gateway": {"image": "mcpgateway:latest"},
            "plugins": [],
        }

        stack = MCPStackDagger()
        result = stack.generate_manifests("test-config.yaml", output_dir=str(tmp_path))

        mock_plugin_gen.assert_called_once()
        mock_compose_gen.assert_called_once()
        assert result == tmp_path

    @patch("mcpgateway.tools.builder.dagger_deploy.get_deploy_dir")
    @patch("mcpgateway.tools.builder.dagger_deploy.load_config")
    def test_generate_manifests_invalid_type(self, mock_load, mock_get_deploy, tmp_path):
        """Test generating manifests with invalid deployment type."""
        mock_load.return_value = {
            "deployment": {"type": "invalid"},
            "gateway": {"image": "mcpgateway:latest"},
        }
        mock_get_deploy.return_value = tmp_path / "deploy"

        stack = MCPStackDagger()
        with pytest.raises(ValueError, match="Unsupported deployment type"):
            stack.generate_manifests("test-config.yaml")


class TestMCPStackDaggerBuildComponent:
    """Test MCPStackDagger _build_component_with_dagger method."""

    @pytest.mark.asyncio
    async def test_build_component_basic(self, mock_dagger_connection, tmp_path):
        """Test basic component build with Dagger."""
        component = {
            "repo": "https://github.com/test/component.git",
            "ref": "main",
            "context": ".",
            "containerfile": "Containerfile",
            "image": "test-component:latest",
        }

        stack = MCPStackDagger()
        await stack._build_component_with_dagger(component, "test-component")

        # Verify Dagger operations were called (using mocks from fixture)
        mock_dag = mock_dagger_connection["dag"]
        mock_dag.git.assert_called_once()

        # Get the mock git object
        mock_git = mock_dag.git.return_value
        mock_git.branch.assert_called_with("main")

        # Get the mock tree object
        mock_tree = mock_git.tree.return_value
        mock_tree.docker_build.assert_called_once()

    @pytest.mark.asyncio
    async def test_build_component_with_target(self, mock_dagger_connection, tmp_path):
        """Test component build with multi-stage target."""
        component = {
            "repo": "https://github.com/test/component.git",
            "ref": "main",
            "context": ".",
            "image": "test:latest",
            "target": "production",
        }

        stack = MCPStackDagger()
        await stack._build_component_with_dagger(component, "test")

        # Verify docker_build was called with target parameter
        mock_dag = mock_dagger_connection["dag"]
        mock_git = mock_dag.git.return_value
        mock_tree = mock_git.tree.return_value
        call_args = mock_tree.docker_build.call_args
        assert "target" in call_args[1] or call_args[0]

    @pytest.mark.asyncio
    async def test_build_component_with_env_vars(self, mock_dagger_connection, tmp_path):
        """Test component build with environment variables."""
        component = {
            "repo": "https://github.com/test/component.git",
            "ref": "main",
            "image": "test:latest",
            "env_vars": {"BUILD_ENV": "production", "VERSION": "1.0"},
        }

        stack = MCPStackDagger()
        await stack._build_component_with_dagger(component, "test")

        # Verify docker_build was called
        mock_dag = mock_dagger_connection["dag"]
        mock_git = mock_dag.git.return_value
        mock_tree = mock_git.tree.return_value
        mock_tree.docker_build.assert_called_once()
