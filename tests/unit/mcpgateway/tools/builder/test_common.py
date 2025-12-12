# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/tools/builder/test_common.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Unit tests for builder common utilities.
"""

# Standard
import os
from pathlib import Path
import shutil
import subprocess
from unittest.mock import MagicMock, Mock, patch
from mcpgateway.tools.builder.schema import MCPStackConfig

# Third-Party
import pytest
import yaml

# First-Party
from mcpgateway.tools.builder.common import (
    copy_env_template,
    deploy_compose,
    deploy_kubernetes,
    destroy_compose,
    destroy_kubernetes,
    generate_compose_manifests,
    generate_kubernetes_manifests,
    generate_plugin_config,
    get_deploy_dir,
    get_docker_compose_command,
    load_config,
    run_compose,
    verify_compose,
    verify_kubernetes,
)


class TestGetDeployDir:
    """Test get_deploy_dir function."""

    def test_default_deploy_dir(self):
        """Test default deploy directory."""
        with patch.dict(os.environ, {}, clear=True):
            result = get_deploy_dir()
            assert result == Path("./deploy")

    def test_custom_deploy_dir(self):
        """Test custom deploy directory from environment variable."""
        with patch.dict(os.environ, {"MCP_DEPLOY_DIR": "/custom/deploy"}):
            result = get_deploy_dir()
            assert result == Path("/custom/deploy")


class TestLoadConfig:
    """Test load_config function."""

    def test_load_valid_config(self, tmp_path):
        """Test loading valid YAML configuration."""
        config_file = tmp_path / "mcp-stack.yaml"
        config_data = {
            "deployment": {"type": "compose", "project_name": "test"},
            "gateway": {"image": "mcpgateway:latest"},
            "plugins": [],
        }
        config_file.write_text(yaml.dump(config_data))

        result = load_config(str(config_file))
        assert result.deployment.type == "compose"
        assert result.gateway.image == "mcpgateway:latest"

    def test_load_nonexistent_config(self):
        """Test loading non-existent configuration file."""
        with pytest.raises(FileNotFoundError, match="Configuration file not found"):
            load_config("/nonexistent/config.yaml")


class TestGeneratePluginConfig:
    """Test generate_plugin_config function."""

    @patch("mcpgateway.tools.builder.common.Environment")
    def test_generate_plugin_config_compose(self, mock_env_class, tmp_path):
        """Test generating plugin config for Docker Compose deployment."""
        # Setup mock template
        mock_template = MagicMock()
        mock_template.render.return_value = "plugins:\n  - name: TestPlugin\n"
        mock_env = MagicMock()
        mock_env.get_template.return_value = mock_template
        mock_env_class.return_value = mock_env

        # Create fake template directory
        template_dir = tmp_path / "templates"
        template_dir.mkdir()

        config =  MCPStackConfig.model_validate({
            "gateway": {"image": "mcpgateway:latest"},
            "deployment": {"type": "compose"},
            "plugins": [
                {"name": "TestPlugin", "port": 8000, "mtls_enabled": True, "repo": "https://github.com/test/plugin.git"}
            ],
        })

        with patch("mcpgateway.tools.builder.common.Path") as mock_path:
            mock_path.return_value.__truediv__.return_value = template_dir
            output_dir = tmp_path / "output"
            output_dir.mkdir()

            result = generate_plugin_config(config, output_dir)

            # Verify template was called
            mock_env.get_template.assert_called_once_with("plugins-config.yaml.j2")
            assert result == output_dir / "plugins-config.yaml"

    @patch("mcpgateway.tools.builder.common.Environment")
    def test_generate_plugin_config_kubernetes(self, mock_env_class, tmp_path):
        """Test generating plugin config for Kubernetes deployment."""
        # Setup mock template
        mock_template = MagicMock()
        mock_template.render.return_value = "plugins:\n  - name: TestPlugin\n"
        mock_env = MagicMock()
        mock_env.get_template.return_value = mock_template
        mock_env_class.return_value = mock_env

        # Create fake template directory
        template_dir = tmp_path / "templates"
        template_dir.mkdir()

        config =  MCPStackConfig.model_validate({
            "gateway": {"image": "mcpgateway:latest"},
            "deployment": {"type": "kubernetes", "namespace": "test-ns"},
            "plugins": [
                {"name": "TestPlugin", "port": 8000, "mtls_enabled": False, "repo": "https://github.com/test/plugin1.git"}
            ],
        })

        with patch("mcpgateway.tools.builder.common.Path") as mock_path:
            mock_path.return_value.__truediv__.return_value = template_dir
            output_dir = tmp_path / "output"
            output_dir.mkdir()

            result = generate_plugin_config(config, output_dir)

            # Verify template was called
            assert mock_env.get_template.called
            assert result == output_dir / "plugins-config.yaml"

    @patch("mcpgateway.tools.builder.common.Environment")
    def test_generate_plugin_config_with_overrides(self, mock_env_class, tmp_path):
        """Test generating plugin config with plugin_overrides."""
        # Setup mock template
        mock_template = MagicMock()
        mock_template.render.return_value = "plugins:\n  - name: TestPlugin\n"
        mock_env = MagicMock()
        mock_env.get_template.return_value = mock_template
        mock_env_class.return_value = mock_env

        # Create fake template directory
        template_dir = tmp_path / "templates"
        template_dir.mkdir()

        config =  MCPStackConfig.model_validate({
            "deployment": {"type": "compose"},
            "gateway": {"image": "mcpgateway:latest"},
            "plugins": [
                {
                    "name": "TestPlugin",
                    "port": 8000,
                    "plugin_overrides": {
                        "priority": 10,
                        "mode": "enforce",
                        "tags": ["security"],
                    },
                    "repo": "https://github.com/test/plugin1.git"
                }
            ],
        })

        with patch("mcpgateway.tools.builder.common.Path") as mock_path:
            mock_path.return_value.__truediv__.return_value = template_dir
            output_dir = tmp_path / "output"
            output_dir.mkdir()

            result = generate_plugin_config(config, output_dir)
            assert result == output_dir / "plugins-config.yaml"


class TestCopyEnvTemplate:
    """Test copy_env_template function."""

    def test_copy_env_template_success(self, tmp_path):
        """Test successful copying of .env.template."""
        # Create plugin build dir with .env.template
        plugin_dir = tmp_path / "plugin"
        plugin_dir.mkdir()
        template_file = plugin_dir / ".env.template"
        template_file.write_text("TEST_VAR=value\n")

        # Setup deploy dir
        deploy_dir = tmp_path / "deploy"

        with patch("mcpgateway.tools.builder.common.get_deploy_dir", return_value=deploy_dir):
            copy_env_template("TestPlugin", plugin_dir)

            target_file = deploy_dir / "env" / ".env.TestPlugin"
            assert target_file.exists()
            assert target_file.read_text() == "TEST_VAR=value\n"

    def test_copy_env_template_no_template(self, tmp_path):
        """Test when .env.template doesn't exist."""
        plugin_dir = tmp_path / "plugin"
        plugin_dir.mkdir()

        deploy_dir = tmp_path / "deploy"

        with patch("mcpgateway.tools.builder.common.get_deploy_dir", return_value=deploy_dir):
            # Should not raise error, just skip
            copy_env_template("TestPlugin", plugin_dir, verbose=True)

    def test_copy_env_template_target_exists(self, tmp_path):
        """Test when target file already exists."""
        # Create plugin build dir with .env.template
        plugin_dir = tmp_path / "plugin"
        plugin_dir.mkdir()
        template_file = plugin_dir / ".env.template"
        template_file.write_text("NEW_VAR=newvalue\n")

        # Setup deploy dir with existing target
        deploy_dir = tmp_path / "deploy"
        deploy_dir.mkdir()
        env_dir = deploy_dir / "env"
        env_dir.mkdir()
        target_file = env_dir / ".env.TestPlugin"
        target_file.write_text("OLD_VAR=oldvalue\n")

        with patch("mcpgateway.tools.builder.common.get_deploy_dir", return_value=deploy_dir):
            copy_env_template("TestPlugin", plugin_dir)

            # Should not overwrite
            assert target_file.read_text() == "OLD_VAR=oldvalue\n"


class TestGetDockerComposeCommand:
    """Test get_docker_compose_command function."""

    @patch("mcpgateway.tools.builder.common.shutil.which")
    @patch("mcpgateway.tools.builder.common.subprocess.run")
    def test_docker_compose_plugin(self, mock_run, mock_which):
        """Test detecting docker compose plugin."""
        mock_which.return_value = "/usr/bin/docker"
        mock_run.return_value = Mock(returncode=0)

        result = get_docker_compose_command()
        assert result == ["docker", "compose"]

    @patch("mcpgateway.tools.builder.common.shutil.which")
    @patch("mcpgateway.tools.builder.common.subprocess.run")
    def test_docker_compose_standalone(self, mock_run, mock_which):
        """Test detecting standalone docker-compose."""

        def which_side_effect(cmd):
            if cmd == "docker":
                return "/usr/bin/docker"
            elif cmd == "docker-compose":
                return "/usr/bin/docker-compose"
            return None

        mock_which.side_effect = which_side_effect
        mock_run.side_effect = subprocess.CalledProcessError(1, "cmd")

        result = get_docker_compose_command()
        assert result == ["docker-compose"]

    @patch("mcpgateway.tools.builder.common.shutil.which")
    def test_docker_compose_not_found(self, mock_which):
        """Test when docker compose is not available."""
        mock_which.return_value = None

        with pytest.raises(RuntimeError, match="Docker Compose not found"):
            get_docker_compose_command()


class TestRunCompose:
    """Test run_compose function."""

    @patch("mcpgateway.tools.builder.common.get_docker_compose_command")
    @patch("mcpgateway.tools.builder.common.subprocess.run")
    def test_run_compose_success(self, mock_run, mock_get_cmd, tmp_path):
        """Test successful compose command execution."""
        compose_file = tmp_path / "docker-compose.yaml"
        compose_file.write_text("services:\n  test: {}\n")

        mock_get_cmd.return_value = ["docker", "compose"]
        mock_run.return_value = Mock(returncode=0, stdout="Success", stderr="")

        result = run_compose(compose_file, ["ps"])
        assert result.returncode == 0
        mock_run.assert_called_once()

    @patch("mcpgateway.tools.builder.common.get_docker_compose_command")
    def test_run_compose_file_not_found(self, mock_get_cmd, tmp_path):
        """Test run_compose with non-existent file."""
        compose_file = tmp_path / "nonexistent.yaml"
        mock_get_cmd.return_value = ["docker", "compose"]

        with pytest.raises(FileNotFoundError, match="Compose file not found"):
            run_compose(compose_file, ["ps"])

    @patch("mcpgateway.tools.builder.common.get_docker_compose_command")
    @patch("mcpgateway.tools.builder.common.subprocess.run")
    def test_run_compose_command_failure(self, mock_run, mock_get_cmd, tmp_path):
        """Test run_compose command failure."""
        compose_file = tmp_path / "docker-compose.yaml"
        compose_file.write_text("services:\n  test: {}\n")

        mock_get_cmd.return_value = ["docker", "compose"]
        mock_run.side_effect = subprocess.CalledProcessError(
            1, "cmd", output="", stderr="Error"
        )

        with pytest.raises(RuntimeError, match="Docker Compose failed"):
            run_compose(compose_file, ["up", "-d"])


class TestDeployCompose:
    """Test deploy_compose function."""

    @patch("mcpgateway.tools.builder.common.run_compose")
    def test_deploy_compose_success(self, mock_run, tmp_path):
        """Test successful Docker Compose deployment."""
        compose_file = tmp_path / "docker-compose.yaml"
        mock_run.return_value = Mock(stdout="Deployed", stderr="")

        deploy_compose(compose_file)
        mock_run.assert_called_once_with(compose_file, ["up", "-d"], verbose=False)


class TestVerifyCompose:
    """Test verify_compose function."""

    @patch("mcpgateway.tools.builder.common.run_compose")
    def test_verify_compose(self, mock_run, tmp_path):
        """Test verifying Docker Compose deployment."""
        compose_file = tmp_path / "docker-compose.yaml"
        mock_run.return_value = Mock(stdout="test-service running", stderr="")

        result = verify_compose(compose_file)
        assert "test-service running" in result
        mock_run.assert_called_once_with(compose_file, ["ps"], verbose=False, check=False)


class TestDestroyCompose:
    """Test destroy_compose function."""

    @patch("mcpgateway.tools.builder.common.run_compose")
    def test_destroy_compose_success(self, mock_run, tmp_path):
        """Test successful Docker Compose destruction."""
        compose_file = tmp_path / "docker-compose.yaml"
        compose_file.write_text("services:\n  test: {}\n")
        mock_run.return_value = Mock(stdout="Removed", stderr="")

        destroy_compose(compose_file)
        mock_run.assert_called_once_with(compose_file, ["down", "-v"], verbose=False)

    def test_destroy_compose_file_not_found(self, tmp_path):
        """Test destroying with non-existent compose file."""
        compose_file = tmp_path / "nonexistent.yaml"

        # Should not raise error, just print warning
        destroy_compose(compose_file)


class TestDeployKubernetes:
    """Test deploy_kubernetes function."""

    @patch("mcpgateway.tools.builder.common.shutil.which")
    @patch("mcpgateway.tools.builder.common.subprocess.run")
    def test_deploy_kubernetes_success(self, mock_run, mock_which, tmp_path):
        """Test successful Kubernetes deployment."""
        mock_which.return_value = "/usr/bin/kubectl"
        mock_run.return_value = Mock(returncode=0, stdout="created", stderr="")

        manifests_dir = tmp_path / "manifests"
        manifests_dir.mkdir()
        (manifests_dir / "gateway-deployment.yaml").write_text("apiVersion: v1\n")
        (manifests_dir / "plugins-config.yaml").write_text("plugins: []\n")

        deploy_kubernetes(manifests_dir)
        assert mock_run.called

    @patch("mcpgateway.tools.builder.common.shutil.which")
    def test_deploy_kubernetes_kubectl_not_found(self, mock_which, tmp_path):
        """Test deployment when kubectl is not available."""
        mock_which.return_value = None
        manifests_dir = tmp_path / "manifests"

        with pytest.raises(RuntimeError, match="kubectl not found"):
            deploy_kubernetes(manifests_dir)

    @patch("mcpgateway.tools.builder.common.shutil.which")
    @patch("mcpgateway.tools.builder.common.subprocess.run")
    def test_deploy_kubernetes_with_certs(self, mock_run, mock_which, tmp_path):
        """Test Kubernetes deployment with certificate secrets."""
        mock_which.return_value = "/usr/bin/kubectl"
        mock_run.return_value = Mock(returncode=0, stdout="created", stderr="")

        manifests_dir = tmp_path / "manifests"
        manifests_dir.mkdir()
        (manifests_dir / "gateway-deployment.yaml").write_text("apiVersion: v1\n")
        (manifests_dir / "cert-secrets.yaml").write_text("apiVersion: v1\n")

        deploy_kubernetes(manifests_dir)
        assert mock_run.called


class TestVerifyKubernetes:
    """Test verify_kubernetes function."""

    @patch("mcpgateway.tools.builder.common.shutil.which")
    @patch("mcpgateway.tools.builder.common.subprocess.run")
    def test_verify_kubernetes_success(self, mock_run, mock_which):
        """Test successful Kubernetes verification."""
        mock_which.return_value = "/usr/bin/kubectl"
        mock_run.return_value = Mock(
            returncode=0, stdout="pod-1 Running\npod-2 Running", stderr=""
        )

        result = verify_kubernetes("test-ns")
        assert "Running" in result
        mock_run.assert_called_once()

    @patch("mcpgateway.tools.builder.common.shutil.which")
    def test_verify_kubernetes_kubectl_not_found(self, mock_which):
        """Test verification when kubectl is not available."""
        mock_which.return_value = None

        with pytest.raises(RuntimeError, match="kubectl not found"):
            verify_kubernetes("test-ns")

    @patch("mcpgateway.tools.builder.common.shutil.which")
    @patch("mcpgateway.tools.builder.common.subprocess.run")
    def test_verify_kubernetes_with_wait(self, mock_run, mock_which):
        """Test Kubernetes verification with wait."""
        mock_which.return_value = "/usr/bin/kubectl"
        mock_run.return_value = Mock(returncode=0, stdout="Ready", stderr="")

        result = verify_kubernetes("test-ns", wait=True, timeout=60)
        assert mock_run.call_count >= 1


class TestDestroyKubernetes:
    """Test destroy_kubernetes function."""

    @patch("mcpgateway.tools.builder.common.shutil.which")
    @patch("mcpgateway.tools.builder.common.subprocess.run")
    def test_destroy_kubernetes_success(self, mock_run, mock_which, tmp_path):
        """Test successful Kubernetes destruction."""
        mock_which.return_value = "/usr/bin/kubectl"
        mock_run.return_value = Mock(returncode=0, stdout="deleted", stderr="")

        manifests_dir = tmp_path / "manifests"
        manifests_dir.mkdir()
        (manifests_dir / "gateway-deployment.yaml").write_text("apiVersion: v1\n")
        (manifests_dir / "plugins-config.yaml").write_text("plugins: []\n")

        destroy_kubernetes(manifests_dir)
        assert mock_run.called

    @patch("mcpgateway.tools.builder.common.shutil.which")
    def test_destroy_kubernetes_kubectl_not_found(self, mock_which, tmp_path):
        """Test destruction when kubectl is not available."""
        mock_which.return_value = None
        manifests_dir = tmp_path / "manifests"

        with pytest.raises(RuntimeError, match="kubectl not found"):
            destroy_kubernetes(manifests_dir)

    def test_destroy_kubernetes_dir_not_found(self, tmp_path):
        """Test destroying with non-existent manifests directory."""
        manifests_dir = tmp_path / "nonexistent"

        with patch("mcpgateway.tools.builder.common.shutil.which", return_value="/usr/bin/kubectl"):
            # Should not raise error, just print warning
            destroy_kubernetes(manifests_dir)


class TestGenerateKubernetesManifests:
    """Test generate_kubernetes_manifests function with real template rendering."""

    def test_generate_manifests_gateway_only(self, tmp_path):
        """Test generating Kubernetes manifests for gateway only."""
        output_dir = tmp_path / "manifests"
        output_dir.mkdir()

        config = MCPStackConfig.model_validate({
            "deployment": {"type": "kubernetes", "namespace": "test-ns"},
            "gateway": {
                "image": "mcpgateway:latest",
                "port": 4444,
                "mtls_enabled": False,
            },
            "plugins": [],
        })

        generate_kubernetes_manifests(config, output_dir)

        # Verify gateway deployment was created
        gateway_file = output_dir / "gateway-deployment.yaml"
        assert gateway_file.exists()

        # Parse and validate YAML
        with open(gateway_file) as f:
            docs = list(yaml.safe_load_all(f))

        # Should have Deployment and Service
        assert len(docs) >= 2

        # Validate Deployment
        deployment = next((d for d in docs if d.get("kind") == "Deployment"), None)
        assert deployment is not None
        assert deployment["metadata"]["name"] == "mcpgateway"
        assert deployment["metadata"]["namespace"] == "test-ns"
        assert deployment["spec"]["template"]["spec"]["containers"][0]["image"] == "mcpgateway:latest"

        # Validate Service
        service = next((d for d in docs if d.get("kind") == "Service"), None)
        assert service is not None
        assert service["metadata"]["name"] == "mcpgateway"
        assert service["spec"]["ports"][0]["port"] == 4444

    def test_generate_manifests_with_plugins(self, tmp_path):
        """Test generating Kubernetes manifests with plugins."""
        output_dir = tmp_path / "manifests"
        output_dir.mkdir()

        config =  MCPStackConfig.model_validate({
            "deployment": {"type": "kubernetes", "namespace": "mcp-test"},
            "gateway": {
                "image": "mcpgateway:latest",
                "port": 4444,
                "mtls_enabled": False,
            },
            "plugins": [
                {
                    "name": "TestPlugin",
                    "image": "test-plugin:v1",
                    "port": 8000,
                    "mtls_enabled": False,
                },
                {
                    "name": "AnotherPlugin",
                    "image": "another-plugin:v2",
                    "port": 8001,
                    "mtls_enabled": False,
                },
            ],
        })

        generate_kubernetes_manifests(config, output_dir)

        # Verify plugin deployments were created
        plugin1_file = output_dir / "plugin-testplugin-deployment.yaml"
        plugin2_file = output_dir / "plugin-anotherplugin-deployment.yaml"

        assert plugin1_file.exists()
        assert plugin2_file.exists()

        # Parse and validate first plugin
        with open(plugin1_file) as f:
            docs = list(yaml.safe_load_all(f))

        deployment = next((d for d in docs if d.get("kind") == "Deployment"), None)
        assert deployment is not None
        assert deployment["metadata"]["name"] == "mcp-plugin-testplugin"
        assert deployment["metadata"]["namespace"] == "mcp-test"
        assert deployment["spec"]["template"]["spec"]["containers"][0]["image"] == "test-plugin:v1"

    def test_generate_manifests_with_mtls(self, tmp_path):
        """Test generating Kubernetes manifests with mTLS enabled."""
        # Change to tmp_path to ensure we have a valid working directory
        original_dir = None
        try:
            original_dir = os.getcwd()
        except (FileNotFoundError, OSError):
            pass  # Current directory doesn't exist

        os.chdir(tmp_path)

        try:
            output_dir = tmp_path / "manifests"
            output_dir.mkdir()

            # Create fake certificate files in the actual location where the code looks
            certs_dir = Path("certs/mcp")
            ca_dir = certs_dir / "ca"
            gateway_dir = certs_dir / "gateway"
            plugin_dir = certs_dir / "plugins" / "SecurePlugin"

            ca_dir.mkdir(parents=True, exist_ok=True)
            gateway_dir.mkdir(parents=True, exist_ok=True)
            plugin_dir.mkdir(parents=True, exist_ok=True)

            (ca_dir / "ca.crt").write_bytes(b"fake-ca-cert")
            (gateway_dir / "client.crt").write_bytes(b"fake-gateway-cert")
            (gateway_dir / "client.key").write_bytes(b"fake-gateway-key")
            (plugin_dir / "server.crt").write_bytes(b"fake-plugin-cert")
            (plugin_dir / "server.key").write_bytes(b"fake-plugin-key")

            config =  MCPStackConfig.model_validate({
                "deployment": {"type": "kubernetes", "namespace": "secure-ns"},
                "gateway": {
                    "image": "mcpgateway:latest",
                    "port": 4444,
                    "mtls_enabled": True,
                },
                "plugins": [
                    {
                        "name": "SecurePlugin",
                        "image": "secure-plugin:v1",
                        "port": 8000,
                        "mtls_enabled": True,
                    }
                ],
            })

            generate_kubernetes_manifests(config, output_dir)
        finally:
            # Clean up created certificate files
            if Path("certs").exists():
                shutil.rmtree("certs")

            # Restore original directory if it exists
            if original_dir and Path(original_dir).exists():
                os.chdir(original_dir)

        # Verify certificate secrets were created
        cert_secrets_file = output_dir / "cert-secrets.yaml"
        assert cert_secrets_file.exists()

        # Parse and validate secrets
        with open(cert_secrets_file) as f:
            docs = list(yaml.safe_load_all(f))

        # Should have secrets for CA, gateway, and plugin
        secrets = [d for d in docs if d.get("kind") == "Secret"]
        assert len(secrets) >= 2  # At least gateway and plugin secrets

    def test_generate_manifests_with_infrastructure(self, tmp_path):
        """Test generating Kubernetes manifests with PostgreSQL and Redis."""
        output_dir = tmp_path / "manifests"
        output_dir.mkdir()

        config =  MCPStackConfig.model_validate({
            "deployment": {"type": "kubernetes", "namespace": "infra-ns"},
            "gateway": {
                "image": "mcpgateway:latest",
                "port": 4444,
                "mtls_enabled": False,
            },
            "plugins": [],
            "infrastructure": {
                "postgres": {
                    "enabled": True,
                    "image": "postgres:17",
                    "database": "testdb",
                    "user": "testuser",
                    "password": "testpass",
                },
                "redis": {
                    "enabled": True,
                    "image": "redis:alpine",
                },
            },
        })

        generate_kubernetes_manifests(config, output_dir)

        # Verify infrastructure manifests were created
        postgres_file = output_dir / "postgres-deployment.yaml"
        redis_file = output_dir / "redis-deployment.yaml"

        assert postgres_file.exists()
        assert redis_file.exists()

        # Parse and validate PostgreSQL
        with open(postgres_file) as f:
            docs = list(yaml.safe_load_all(f))

        postgres_deployment = next((d for d in docs if d.get("kind") == "Deployment"), None)
        assert postgres_deployment is not None
        assert postgres_deployment["metadata"]["name"] == "postgres"
        assert postgres_deployment["spec"]["template"]["spec"]["containers"][0]["image"] == "postgres:17"

        # Parse and validate Redis
        with open(redis_file) as f:
            docs = list(yaml.safe_load_all(f))

        redis_deployment = next((d for d in docs if d.get("kind") == "Deployment"), None)
        assert redis_deployment is not None
        assert redis_deployment["metadata"]["name"] == "redis"

        # Verify gateway has database environment variables in Secret
        gateway_file = output_dir / "gateway-deployment.yaml"
        with open(gateway_file) as f:
            docs = list(yaml.safe_load_all(f))

        # Find the Secret containing environment variables
        secret = next((d for d in docs if d.get("kind") == "Secret" and d["metadata"]["name"] == "mcpgateway-env"), None)
        assert secret is not None
        assert "stringData" in secret

        string_data = secret["stringData"]

        # Check DATABASE_URL is set
        assert "DATABASE_URL" in string_data
        assert "postgresql://" in string_data["DATABASE_URL"]
        assert "testuser:testpass" in string_data["DATABASE_URL"]

        # Check REDIS_URL is set
        assert "REDIS_URL" in string_data
        assert "redis://redis:6379" in string_data["REDIS_URL"]

        # Verify deployment references the Secret via envFrom
        gateway_deployment = next((d for d in docs if d.get("kind") == "Deployment"), None)
        assert gateway_deployment is not None
        env_from = gateway_deployment["spec"]["template"]["spec"]["containers"][0]["envFrom"]
        assert any(ref.get("secretRef", {}).get("name") == "mcpgateway-env" for ref in env_from)


class TestGenerateComposeManifests:
    """Test generate_compose_manifests function with real template rendering."""

    def test_generate_compose_gateway_only(self, tmp_path):
        """Test generating Docker Compose manifest for gateway only."""
        output_dir = tmp_path / "manifests"
        output_dir.mkdir()

        config =  MCPStackConfig.model_validate({
            "deployment": {"type": "compose", "project_name": "test-mcp"},
            "gateway": {
                "image": "mcpgateway:latest",
                "port": 4444,
                "host_port": 4444,
                "mtls_enabled": False,
            },
            "plugins": [],
        })

        with patch("mcpgateway.tools.builder.common.Path.cwd", return_value=tmp_path):
            generate_compose_manifests(config, output_dir)

        # Verify compose file was created
        compose_file = output_dir / "docker-compose.yaml"
        assert compose_file.exists()

        # Parse and validate
        with open(compose_file) as f:
            compose_data = yaml.safe_load(f)

        assert "services" in compose_data
        assert "mcpgateway" in compose_data["services"]

        gateway = compose_data["services"]["mcpgateway"]
        assert gateway["image"] == "mcpgateway:latest"
        assert gateway["ports"] == ["4444:4444"]

    def test_generate_compose_with_plugins(self, tmp_path):
        """Test generating Docker Compose manifest with plugins."""
        output_dir = tmp_path / "manifests"
        output_dir.mkdir()

        config =  MCPStackConfig.model_validate({
            "deployment": {"type": "compose", "project_name": "mcp-stack"},
            "gateway": {
                "image": "mcpgateway:latest",
                "port": 4444,
                "host_port": 4444,
                "mtls_enabled": False,
            },
            "plugins": [
                {
                    "name": "Plugin1",
                    "image": "plugin1:v1",
                    "port": 8000,
                    "expose_port": True,
                    "host_port": 8000,
                    "mtls_enabled": False,
                },
                {
                    "name": "Plugin2",
                    "image": "plugin2:v1",
                    "port": 8001,
                    "expose_port": False,
                    "mtls_enabled": False,
                },
            ],
        })

        with patch("mcpgateway.tools.builder.common.Path.cwd", return_value=tmp_path):
            generate_compose_manifests(config, output_dir)

        # Parse and validate
        compose_file = output_dir / "docker-compose.yaml"
        with open(compose_file) as f:
            compose_data = yaml.safe_load(f)

        # Verify plugins are in services
        assert "plugin1" in compose_data["services"]
        assert "plugin2" in compose_data["services"]

        plugin1 = compose_data["services"]["plugin1"]
        assert plugin1["image"] == "plugin1:v1"
        assert "8000:8000" in plugin1["ports"]  # Exposed

        plugin2 = compose_data["services"]["plugin2"]
        assert plugin2["image"] == "plugin2:v1"
        # Plugin2 should not have host port mapping since expose_port is False

    def test_generate_compose_with_mtls(self, tmp_path):
        """Test generating Docker Compose manifest with mTLS certificates."""
        output_dir = tmp_path / "manifests"
        output_dir.mkdir()

        # Create fake certificate structure
        certs_dir = tmp_path / "certs" / "mcp"
        ca_dir = certs_dir / "ca"
        gateway_dir = certs_dir / "gateway"
        plugin_dir = certs_dir / "plugins" / "SecurePlugin"

        ca_dir.mkdir(parents=True)
        gateway_dir.mkdir(parents=True)
        plugin_dir.mkdir(parents=True)

        (ca_dir / "ca.crt").write_text("fake-ca")
        (gateway_dir / "client.crt").write_text("fake-cert")
        (gateway_dir / "client.key").write_text("fake-key")
        (plugin_dir / "server.crt").write_text("fake-plugin-cert")
        (plugin_dir / "server.key").write_text("fake-plugin-key")

        config =  MCPStackConfig.model_validate({
            "deployment": {"type": "compose"},
            "gateway": {
                "image": "mcpgateway:latest",
                "port": 4444,
                "host_port": 4444,
                "mtls_enabled": True,
            },
            "plugins": [
                {
                    "name": "SecurePlugin",
                    "image": "secure:v1",
                    "port": 8000,
                    "mtls_enabled": True,
                }
            ],
        })

        with patch("mcpgateway.tools.builder.common.Path.cwd", return_value=tmp_path):
            generate_compose_manifests(config, output_dir)

        # Parse and validate
        compose_file = output_dir / "docker-compose.yaml"
        with open(compose_file) as f:
            compose_data = yaml.safe_load(f)

        # Verify gateway has certificate volumes
        gateway = compose_data["services"]["mcpgateway"]
        assert "volumes" in gateway
        # Should have volume mounts for certificates
        volumes = gateway["volumes"]
        assert any("certs" in str(v) or "ca.crt" in str(v) for v in volumes)

        # Verify plugin has certificate volumes
        plugin = compose_data["services"]["secureplugin"]
        assert "volumes" in plugin

    def test_generate_compose_with_env_files(self, tmp_path):
        """Test generating Docker Compose manifest with environment files."""
        output_dir = tmp_path / "manifests"
        output_dir.mkdir()

        # Create env files
        deploy_dir = tmp_path / "deploy"
        env_dir = deploy_dir / "env"
        env_dir.mkdir(parents=True)
        (env_dir / ".env.gateway").write_text("GATEWAY_VAR=value1\n")
        (env_dir / ".env.TestPlugin").write_text("PLUGIN_VAR=value2\n")

        config =  MCPStackConfig.model_validate({
            "deployment": {"type": "compose"},
            "gateway": {
                "image": "mcpgateway:latest",
                "port": 4444,
                "mtls_enabled": False,
            },
            "plugins": [
                {
                    "name": "TestPlugin",
                    "image": "test:v1",
                    "port": 8000,
                    "mtls_enabled": False,
                }
            ],
        })

        with patch("mcpgateway.tools.builder.common.get_deploy_dir", return_value=deploy_dir):
            with patch("mcpgateway.tools.builder.common.Path.cwd", return_value=tmp_path):
                generate_compose_manifests(config, output_dir)

        # Parse and validate
        compose_file = output_dir / "docker-compose.yaml"
        with open(compose_file) as f:
            compose_data = yaml.safe_load(f)

        # Verify env_file is set
        gateway = compose_data["services"]["mcpgateway"]
        assert "env_file" in gateway

        plugin = compose_data["services"]["testplugin"]
        assert "env_file" in plugin

    def test_generate_compose_with_infrastructure(self, tmp_path):
        """Test generating Docker Compose manifest with PostgreSQL and Redis.

        Note: Currently the template uses hardcoded infrastructure images/config.
        Infrastructure customization is not yet implemented for Docker Compose.
        """
        output_dir = tmp_path / "manifests"
        output_dir.mkdir()

        config =  MCPStackConfig.model_validate({
            "deployment": {"type": "compose"},
            "gateway": {
                "image": "mcpgateway:latest",
                "port": 4444,
                "mtls_enabled": False,
            },
            "plugins": [],
            "infrastructure": {
                "postgres": {
                    "enabled": True,
                    "image": "postgres:17",
                    "database": "mcpdb",
                    "user": "mcpuser",
                    "password": "secret123",
                },
                "redis": {
                    "enabled": True,
                    "image": "redis:7-alpine",
                },
            },
        })

        with patch("mcpgateway.tools.builder.common.Path.cwd", return_value=tmp_path):
            generate_compose_manifests(config, output_dir)

        # Parse and validate
        compose_file = output_dir / "docker-compose.yaml"
        with open(compose_file) as f:
            compose_data = yaml.safe_load(f)

        # Verify PostgreSQL service exists
        # Note: Template uses hardcoded "postgres:17" and "mcp" database
        assert "postgres" in compose_data["services"]
        postgres = compose_data["services"]["postgres"]
        assert postgres["image"] == "postgres:17"  # Hardcoded in template
        assert "environment" in postgres

        # Verify database name is "mcp" (hardcoded default, not "mcpdb" from config)
        env = postgres["environment"]
        if isinstance(env, list):
            assert any("POSTGRES_DB=mcp" in str(e) for e in env)
        else:
            assert env["POSTGRES_DB"] == "mcp"

        # Verify Redis service exists
        # Note: Template uses hardcoded "redis:latest"
        assert "redis" in compose_data["services"]
        redis = compose_data["services"]["redis"]
        assert redis["image"] == "redis:latest"  # Hardcoded in template

        # Verify gateway has database environment variables
        gateway = compose_data["services"]["mcpgateway"]
        assert "environment" in gateway
        env = gateway["environment"]

        # Should have DATABASE_URL with default values
        if isinstance(env, list):
            db_url = next((e for e in env if "DATABASE_URL" in str(e)), None)
        else:
            db_url = env.get("DATABASE_URL")
        assert db_url is not None
        assert "postgresql://" in str(db_url)
