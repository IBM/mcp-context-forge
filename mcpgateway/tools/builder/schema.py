"""Location: ./mcpgateway/tools/builder/schema.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Pydantic schemas for MCP Stack configuration validation"""

# Standard
from typing import Any, Dict, List, Literal, Optional

# Third-Party
from pydantic import BaseModel, Field, field_validator


class DeploymentConfig(BaseModel):
    """Deployment configuration"""

    type: Literal["kubernetes", "compose"] = Field(..., description="Deployment type")
    project_name: Optional[str] = Field(None, description="Project name for compose")
    namespace: Optional[str] = Field(None, description="Namespace for Kubernetes")


class BuildableConfig(BaseModel):
    """Base class for components that can be built from source or use pre-built images.

    This base class provides common configuration for both gateway and plugins,
    supporting two build modes:
    1. Pre-built image: Specify only 'image' field
    2. Build from source: Specify 'repo' and optionally 'ref', 'context', 'containerfile', 'target'

    Attributes:
        image: Pre-built Docker image name (e.g., "mcpgateway/mcpgateway:latest")
        repo: Git repository URL to build from
        ref: Git branch/tag/commit to checkout (default: "main")
        context: Build context subdirectory within repo (default: ".")
        containerfile: Path to Containerfile/Dockerfile (default: "Containerfile")
        target: Target stage for multi-stage builds (optional)
        host_port: Host port mapping for direct access (optional)
        env_vars: Environment variables for container
        mtls_enabled: Enable mutual TLS authentication (default: True)
    """

    # Build configuration
    image: Optional[str] = Field(None, description="Pre-built Docker image")
    repo: Optional[str] = Field(None, description="Git repository URL")
    ref: Optional[str] = Field("main", description="Git branch/tag/commit")
    context: Optional[str] = Field(".", description="Build context subdirectory")
    containerfile: Optional[str] = Field("Containerfile", description="Containerfile path")
    target: Optional[str] = Field(None, description="Multi-stage build target")

    # Runtime configuration
    host_port: Optional[int] = Field(None, description="Host port mapping")
    env_vars: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Environment variables")
    mtls_enabled: Optional[bool] = Field(True, description="Enable mTLS")

    def model_post_init(self, __context: Any) -> None:
        """Validate that either image or repo is specified

        Raises:
            ValueError: If neither image nor repo is specified
        """
        if not self.image and not self.repo:
            component_type = self.__class__.__name__.replace("Config", "")
            raise ValueError(f"{component_type} must specify either 'image' or 'repo'")


class GatewayConfig(BuildableConfig):
    """Gateway configuration.

    Extends BuildableConfig to support either pre-built gateway images or
    building the gateway from source repository.

    Attributes:
        port: Gateway internal port (default: 4444)
    """

    port: Optional[int] = Field(4444, description="Gateway port")


class PluginConfig(BuildableConfig):
    """Plugin configuration.

    Extends BuildableConfig to support plugin-specific configuration while
    inheriting common build and runtime capabilities.

    Attributes:
        name: Unique plugin identifier
        port: Plugin internal port (default: 8000)
        expose_port: Whether to expose plugin port on host (default: False)
        plugin_overrides: Plugin-specific override configuration
    """

    name: str = Field(..., description="Plugin name")
    port: Optional[int] = Field(8000, description="Plugin port")
    expose_port: Optional[bool] = Field(False, description="Expose port on host")
    plugin_overrides: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Plugin overrides")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Validate plugin name is non-empty

        Args:
            v: Plugin name value to validate

        Returns:
            Validated plugin name

        Raises:
            ValueError: If plugin name is empty or whitespace only
        """
        if not v or not v.strip():
            raise ValueError("Plugin name cannot be empty")
        return v


class CertificatesConfig(BaseModel):
    """Certificate configuration"""

    validity_days: Optional[int] = Field(825, description="Certificate validity in days")
    auto_generate: Optional[bool] = Field(True, description="Auto-generate certificates")
    ca_path: Optional[str] = Field("./certs/mcp/ca", description="CA certificate path")
    gateway_path: Optional[str] = Field("./certs/mcp/gateway", description="Gateway cert path")
    plugins_path: Optional[str] = Field("./certs/mcp/plugins", description="Plugins cert path")


class PostgresConfig(BaseModel):
    """PostgreSQL database configuration"""

    enabled: Optional[bool] = Field(True, description="Enable PostgreSQL deployment")
    image: Optional[str] = Field("postgres:17", description="PostgreSQL image")
    database: Optional[str] = Field("mcp", description="Database name")
    user: Optional[str] = Field("postgres", description="Database user")
    password: Optional[str] = Field("mysecretpassword", description="Database password")
    storage_size: Optional[str] = Field("10Gi", description="Persistent volume size (Kubernetes only)")
    storage_class: Optional[str] = Field(None, description="Storage class name (Kubernetes only)")


class RedisConfig(BaseModel):
    """Redis cache configuration"""

    enabled: Optional[bool] = Field(True, description="Enable Redis deployment")
    image: Optional[str] = Field("redis:latest", description="Redis image")


class InfrastructureConfig(BaseModel):
    """Infrastructure services configuration"""

    postgres: Optional[PostgresConfig] = Field(default_factory=PostgresConfig)
    redis: Optional[RedisConfig] = Field(default_factory=RedisConfig)


class MCPStackConfig(BaseModel):
    """Complete MCP Stack configuration"""

    deployment: DeploymentConfig
    gateway: GatewayConfig
    plugins: List[PluginConfig] = Field(default_factory=list)
    certificates: Optional[CertificatesConfig] = Field(default_factory=CertificatesConfig)
    infrastructure: Optional[InfrastructureConfig] = Field(default_factory=InfrastructureConfig)

    @field_validator("plugins")
    @classmethod
    def validate_plugin_names_unique(cls, v: List[PluginConfig]) -> List[PluginConfig]:
        """Ensure plugin names are unique

        Args:
            v: List of plugin configurations to validate

        Returns:
            Validated list of plugin configurations

        Raises:
            ValueError: If duplicate plugin names are found
        """
        names = [p.name for p in v]
        if len(names) != len(set(names)):
            duplicates = [name for name in names if names.count(name) > 1]
            raise ValueError(f"Duplicate plugin names found: {duplicates}")
        return v
