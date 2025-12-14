# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/tools/builder/test_schema.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Unit tests for builder schema validation (Pydantic models).
"""

# Third-Party
import pytest
from pydantic import ValidationError

# First-Party
from mcpgateway.tools.builder.schema import (
    BuildableConfig,
    CertificatesConfig,
    DeploymentConfig,
    GatewayConfig,
    InfrastructureConfig,
    MCPStackConfig,
    PluginConfig,
    PostgresConfig,
    RedisConfig,
)


class TestDeploymentConfig:
    """Test DeploymentConfig validation."""

    def test_valid_kubernetes_deployment(self):
        """Test valid Kubernetes deployment configuration."""
        config = DeploymentConfig(type="kubernetes", namespace="test-ns")
        assert config.type == "kubernetes"
        assert config.namespace == "test-ns"
        assert config.project_name is None

    def test_valid_compose_deployment(self):
        """Test valid Docker Compose deployment configuration."""
        config = DeploymentConfig(type="compose", project_name="test-project")
        assert config.type == "compose"
        assert config.project_name == "test-project"
        assert config.namespace is None

    def test_invalid_deployment_type(self):
        """Test invalid deployment type."""
        with pytest.raises(ValidationError):
            DeploymentConfig(type="invalid")


class TestGatewayConfig:
    """Test GatewayConfig validation."""

    def test_gateway_with_image(self):
        """Test gateway config with pre-built image."""
        config = GatewayConfig(image="mcpgateway:latest", port=4444)
        assert config.image == "mcpgateway:latest"
        assert config.port == 4444
        assert config.repo is None

    def test_gateway_with_repo(self):
        """Test gateway config with repository build."""
        config = GatewayConfig(
            repo="https://github.com/org/repo.git",
            ref="main",
            context=".",
            port=4444
        )
        assert config.repo == "https://github.com/org/repo.git"
        assert config.ref == "main"
        assert config.image is None

    def test_gateway_without_image_or_repo(self):
        """Test that gateway requires either image or repo."""
        with pytest.raises(ValueError, match="must specify either 'image' or 'repo'"):
            GatewayConfig(port=4444)

    def test_gateway_defaults(self):
        """Test gateway default values."""
        config = GatewayConfig(image="test:latest")
        assert config.port == 4444
        assert config.mtls_enabled is True
        assert config.ref == "main"
        assert config.context == "."
        assert config.containerfile == "Containerfile"


class TestPluginConfig:
    """Test PluginConfig validation."""

    def test_plugin_with_image(self):
        """Test plugin config with pre-built image."""
        config = PluginConfig(name="TestPlugin", image="test:latest")
        assert config.name == "TestPlugin"
        assert config.image == "test:latest"
        assert config.repo is None

    def test_plugin_with_repo(self):
        """Test plugin config with repository build."""
        config = PluginConfig(
            name="TestPlugin",
            repo="https://github.com/org/plugin.git",
            ref="v1.0.0",
            context="plugins/test"
        )
        assert config.name == "TestPlugin"
        assert config.repo == "https://github.com/org/plugin.git"
        assert config.ref == "v1.0.0"
        assert config.context == "plugins/test"

    def test_plugin_without_name(self):
        """Test that plugin requires name."""
        with pytest.raises(ValidationError):
            PluginConfig(image="test:latest")

    def test_plugin_empty_name(self):
        """Test that plugin name cannot be empty."""
        with pytest.raises(ValidationError, match="Plugin name cannot be empty"):
            PluginConfig(name="", image="test:latest")

    def test_plugin_whitespace_name(self):
        """Test that plugin name cannot be whitespace only."""
        with pytest.raises(ValidationError, match="Plugin name cannot be empty"):
            PluginConfig(name="   ", image="test:latest")

    def test_plugin_defaults(self):
        """Test plugin default values."""
        config = PluginConfig(name="TestPlugin", image="test:latest")
        assert config.port == 8000
        assert config.expose_port is False
        assert config.mtls_enabled is True
        assert config.plugin_overrides == {}

    def test_plugin_overrides(self):
        """Test plugin with overrides."""
        config = PluginConfig(
            name="TestPlugin",
            image="test:latest",
            plugin_overrides={
                "priority": 10,
                "mode": "enforce",
                "tags": ["security", "filter"]
            }
        )
        assert config.plugin_overrides["priority"] == 10
        assert config.plugin_overrides["mode"] == "enforce"
        assert config.plugin_overrides["tags"] == ["security", "filter"]


class TestCertificatesConfig:
    """Test CertificatesConfig validation."""

    def test_certificates_defaults(self):
        """Test certificates default values."""
        config = CertificatesConfig()
        assert config.validity_days == 825
        assert config.auto_generate is True
        assert config.ca_path == "./certs/mcp/ca"
        assert config.gateway_path == "./certs/mcp/gateway"
        assert config.plugins_path == "./certs/mcp/plugins"

    def test_certificates_custom_values(self):
        """Test certificates with custom values."""
        config = CertificatesConfig(
            validity_days=365,
            auto_generate=False,
            ca_path="/custom/ca",
            gateway_path="/custom/gateway",
            plugins_path="/custom/plugins"
        )
        assert config.validity_days == 365
        assert config.auto_generate is False
        assert config.ca_path == "/custom/ca"


class TestInfrastructureConfig:
    """Test InfrastructureConfig validation."""

    def test_postgres_defaults(self):
        """Test PostgreSQL default configuration."""
        config = PostgresConfig()
        assert config.enabled is True
        assert config.image == "quay.io/sclorg/postgresql-15-c9s:latest"
        assert config.database == "mcp"
        assert config.user == "postgres"
        assert config.password == "mysecretpassword"
        assert config.storage_size == "10Gi"

    def test_postgres_custom(self):
        """Test PostgreSQL custom configuration."""
        config = PostgresConfig(
            enabled=True,
            image="postgres:16",
            database="customdb",
            user="customuser",
            password="custompass",
            storage_size="20Gi",
            storage_class="fast-ssd"
        )
        assert config.image == "postgres:16"
        assert config.database == "customdb"
        assert config.storage_class == "fast-ssd"

    def test_redis_defaults(self):
        """Test Redis default configuration."""
        config = RedisConfig()
        assert config.enabled is True
        assert config.image == "redis:latest"

    def test_infrastructure_defaults(self):
        """Test infrastructure with default values."""
        config = InfrastructureConfig()
        assert config.postgres.enabled is True
        assert config.redis.enabled is True


class TestMCPStackConfig:
    """Test complete MCPStackConfig validation."""

    def test_minimal_config(self):
        """Test minimal valid configuration."""
        config = MCPStackConfig(
            deployment=DeploymentConfig(type="compose", project_name="test"),
            gateway=GatewayConfig(image="mcpgateway:latest")
        )
        assert config.deployment.type == "compose"
        assert config.gateway.image == "mcpgateway:latest"
        assert config.plugins == []

    def test_full_config(self):
        """Test full configuration with all options."""
        config = MCPStackConfig(
            deployment=DeploymentConfig(type="kubernetes", namespace="prod"),
            gateway=GatewayConfig(
                image="mcpgateway:latest",
                port=4444,
                mtls_enabled=True
            ),
            plugins=[
                PluginConfig(name="Plugin1", image="plugin1:latest"),
                PluginConfig(name="Plugin2", image="plugin2:latest")
            ],
            certificates=CertificatesConfig(validity_days=365),
            infrastructure=InfrastructureConfig()
        )
        assert config.deployment.namespace == "prod"
        assert len(config.plugins) == 2
        assert config.certificates.validity_days == 365

    def test_duplicate_plugin_names(self):
        """Test that duplicate plugin names are rejected."""
        with pytest.raises(ValidationError, match="Duplicate plugin names found"):
            MCPStackConfig(
                deployment=DeploymentConfig(type="compose"),
                gateway=GatewayConfig(image="test:latest"),
                plugins=[
                    PluginConfig(name="DuplicatePlugin", image="plugin1:latest"),
                    PluginConfig(name="DuplicatePlugin", image="plugin2:latest")
                ]
            )

    def test_unique_plugin_names(self):
        """Test that unique plugin names are accepted."""
        config = MCPStackConfig(
            deployment=DeploymentConfig(type="compose"),
            gateway=GatewayConfig(image="test:latest"),
            plugins=[
                PluginConfig(name="Plugin1", image="plugin1:latest"),
                PluginConfig(name="Plugin2", image="plugin2:latest"),
                PluginConfig(name="Plugin3", image="plugin3:latest")
            ]
        )
        assert len(config.plugins) == 3
        assert [p.name for p in config.plugins] == ["Plugin1", "Plugin2", "Plugin3"]

    def test_config_with_repo_builds(self):
        """Test configuration with repository builds."""
        config = MCPStackConfig(
            deployment=DeploymentConfig(type="compose"),
            gateway=GatewayConfig(
                repo="https://github.com/org/gateway.git",
                ref="v2.0.0"
            ),
            plugins=[
                PluginConfig(
                    name="BuiltPlugin",
                    repo="https://github.com/org/plugin.git",
                    ref="main",
                    context="plugins/src"
                )
            ]
        )
        assert config.gateway.repo is not None
        assert config.gateway.ref == "v2.0.0"
        assert config.plugins[0].repo is not None
        assert config.plugins[0].context == "plugins/src"


class TestBuildableConfig:
    """Test BuildableConfig base class validation."""

    def test_mtls_defaults(self):
        """Test mTLS default settings."""
        config = GatewayConfig(image="test:latest")
        assert config.mtls_enabled is True

    def test_mtls_disabled(self):
        """Test mTLS can be disabled."""
        config = GatewayConfig(image="test:latest", mtls_enabled=False)
        assert config.mtls_enabled is False

    def test_env_vars(self):
        """Test environment variables."""
        config = GatewayConfig(
            image="test:latest",
            env_vars={"LOG_LEVEL": "DEBUG", "PORT": "4444"}
        )
        assert config.env_vars["LOG_LEVEL"] == "DEBUG"
        assert config.env_vars["PORT"] == "4444"

    def test_multi_stage_build(self):
        """Test multi-stage build target."""
        config = PluginConfig(
            name="TestPlugin",
            repo="https://github.com/org/plugin.git",
            containerfile="Dockerfile",
            target="production"
        )
        assert config.containerfile == "Dockerfile"
        assert config.target == "production"
