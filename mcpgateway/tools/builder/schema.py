# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/tools/builder/schema.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Pydantic schemas for MCP Stack configuration validation"""

# Standard
from typing import Any, Dict, List, Literal, Optional

# Third-Party
from pydantic import BaseModel, ConfigDict, Field, field_validator


class OpenShiftConfig(BaseModel):
    """OpenShift-specific configuration.

    Routes are OpenShift's native way of exposing services externally (predates Kubernetes Ingress).
    They provide built-in TLS termination and are integrated with OpenShift's router/HAProxy infrastructure.

    Attributes:
        create_routes: Create OpenShift Route resources for external access (default: False)
        domain: OpenShift apps domain for route hostnames (default: auto-detected from cluster)
        tls_termination: TLS termination mode - edge, passthrough, or reencrypt (default: edge)

    Examples:
        >>> # Test with default values
        >>> config = OpenShiftConfig()
        >>> config.create_routes
        False
        >>> config.tls_termination
        'edge'

        >>> # Test with custom values
        >>> config = OpenShiftConfig(
        ...     create_routes=True,
        ...     domain="apps.example.com",
        ...     tls_termination="passthrough"
        ... )
        >>> config.create_routes
        True
        >>> config.domain
        'apps.example.com'
        >>> config.tls_termination
        'passthrough'

        >>> # Test valid TLS termination modes
        >>> for mode in ["edge", "passthrough", "reencrypt"]:
        ...     cfg = OpenShiftConfig(tls_termination=mode)
        ...     cfg.tls_termination == mode
        True
        True
        True
    """

    create_routes: bool = Field(False, description="Create OpenShift Route resources")
    domain: Optional[str] = Field(None, description="OpenShift apps domain (e.g., apps-crc.testing)")
    tls_termination: Literal["edge", "passthrough", "reencrypt"] = Field("edge", description="TLS termination mode")


class DeploymentConfig(BaseModel):
    """Deployment configuration

    Examples:
        >>> # Test compose deployment
        >>> config = DeploymentConfig(type="compose", project_name="test-project")
        >>> config.type
        'compose'
        >>> config.project_name
        'test-project'

        >>> # Test kubernetes deployment
        >>> config = DeploymentConfig(type="kubernetes", namespace="mcp-test")
        >>> config.type
        'kubernetes'
        >>> config.namespace
        'mcp-test'

        >>> # Test container engine options
        >>> config = DeploymentConfig(type="compose", container_engine="podman")
        >>> config.container_engine
        'podman'

        >>> # Test with OpenShift config
        >>> config = DeploymentConfig(
        ...     type="kubernetes",
        ...     namespace="test",
        ...     openshift=OpenShiftConfig(create_routes=True)
        ... )
        >>> config.openshift.create_routes
        True
    """

    type: Literal["kubernetes", "compose"] = Field(..., description="Deployment type")
    container_engine: Optional[str] = Field(default=None, description="Container engine: 'podman', 'docker', or full path (e.g., '/opt/podman/bin/podman')")
    project_name: Optional[str] = Field(None, description="Project name for compose")
    namespace: Optional[str] = Field(None, description="Namespace for Kubernetes")
    openshift: Optional[OpenShiftConfig] = Field(None, description="OpenShift-specific configuration")


class RegistryConfig(BaseModel):
    """Container registry configuration.

    Optional configuration for pushing built images to a container registry.
    When enabled, images will be tagged with the full registry path and optionally pushed.

    Authentication:
        Users must authenticate to the registry before running the build:
        - Docker Hub: `docker login`
        - Quay.io: `podman login quay.io`
        - OpenShift internal: `podman login $(oc registry info) -u $(oc whoami) -p $(oc whoami -t)`
        - Private registry: `podman login your-registry.com -u username`

    Attributes:
        enabled: Enable registry integration (default: False)
        url: Registry URL (e.g., "docker.io", "quay.io", "default-route-openshift-image-registry.apps-crc.testing")
        namespace: Registry namespace/organization/project (e.g., "myorg", "mcp-gateway-test")
        push: Push image after build (default: True)
        image_pull_policy: Kubernetes imagePullPolicy (default: "IfNotPresent")

    Examples:
        >>> # Test with defaults (registry disabled)
        >>> config = RegistryConfig()
        >>> config.enabled
        False
        >>> config.push
        True
        >>> config.image_pull_policy
        'IfNotPresent'

        >>> # Test Docker Hub configuration
        >>> config = RegistryConfig(
        ...     enabled=True,
        ...     url="docker.io",
        ...     namespace="myusername"
        ... )
        >>> config.enabled
        True
        >>> config.url
        'docker.io'
        >>> config.namespace
        'myusername'

        >>> # Test with custom pull policy
        >>> config = RegistryConfig(
        ...     enabled=True,
        ...     url="quay.io",
        ...     namespace="myorg",
        ...     image_pull_policy="Always"
        ... )
        >>> config.image_pull_policy
        'Always'

        >>> # Test tag-only mode (no push)
        >>> config = RegistryConfig(
        ...     enabled=True,
        ...     url="registry.local",
        ...     namespace="test",
        ...     push=False
        ... )
        >>> config.push
        False
    """

    enabled: bool = Field(False, description="Enable registry push")
    url: Optional[str] = Field(None, description="Registry URL (e.g., docker.io, quay.io, or internal registry)")
    namespace: Optional[str] = Field(None, description="Registry namespace/organization/project")
    push: bool = Field(True, description="Push image after build")
    image_pull_policy: Optional[str] = Field("IfNotPresent", description="Kubernetes imagePullPolicy (IfNotPresent, Always, Never)")


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
        env_file: Path to environment file (.env)
        mtls_enabled: Enable mutual TLS authentication (default: True)
    """

    # Allow attribute assignment after model creation (needed for auto-detection of env_file)
    model_config = ConfigDict(validate_assignment=True)

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
    env_file: Optional[str] = Field(None, description="Path to environment file (.env)")
    mtls_enabled: Optional[bool] = Field(True, description="Enable mTLS")

    # Registry configuration
    registry: Optional[RegistryConfig] = Field(None, description="Container registry configuration")

    def model_post_init(self, _: Any) -> None:
        """Validate that either image or repo is specified

        Raises:
            ValueError: If neither image nor repo is specified

        Examples:
            >>> # Test that error is raised when neither image nor repo specified
            >>> try:
            ...     # BuildableConfig can't be instantiated directly, use GatewayConfig
            ...     from mcpgateway.tools.builder.schema import GatewayConfig
            ...     GatewayConfig()
            ... except ValueError as e:
            ...     "must specify either 'image' or 'repo'" in str(e)
            True

            >>> # Test valid config with image
            >>> from mcpgateway.tools.builder.schema import GatewayConfig
            >>> config = GatewayConfig(image="mcpgateway:latest")
            >>> config.image
            'mcpgateway:latest'

            >>> # Test valid config with repo
            >>> from mcpgateway.tools.builder.schema import GatewayConfig
            >>> config = GatewayConfig(repo="https://github.com/example/repo")
            >>> config.repo
            'https://github.com/example/repo'
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

    Examples:
        >>> # Test with pre-built image
        >>> config = GatewayConfig(image="mcpgateway:latest")
        >>> config.image
        'mcpgateway:latest'
        >>> config.port
        4444

        >>> # Test with custom port
        >>> config = GatewayConfig(image="mcpgateway:latest", port=8080)
        >>> config.port
        8080

        >>> # Test with source repository
        >>> config = GatewayConfig(
        ...     repo="https://github.com/example/gateway",
        ...     ref="v1.0.0"
        ... )
        >>> config.repo
        'https://github.com/example/gateway'
        >>> config.ref
        'v1.0.0'

        >>> # Test with environment variables
        >>> config = GatewayConfig(
        ...     image="mcpgateway:latest",
        ...     env_vars={"LOG_LEVEL": "DEBUG", "PORT": "4444"}
        ... )
        >>> config.env_vars['LOG_LEVEL']
        'DEBUG'

        >>> # Test with mTLS enabled
        >>> config = GatewayConfig(image="mcpgateway:latest", mtls_enabled=True)
        >>> config.mtls_enabled
        True
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

        Examples:
            >>> # Test valid plugin names
            >>> PluginConfig.validate_name("my-plugin")
            'my-plugin'
            >>> PluginConfig.validate_name("plugin_123")
            'plugin_123'
            >>> PluginConfig.validate_name("TestPlugin")
            'TestPlugin'

            >>> # Test empty name raises error
            >>> try:
            ...     PluginConfig.validate_name("")
            ... except ValueError as e:
            ...     "cannot be empty" in str(e)
            True

            >>> # Test whitespace-only name raises error
            >>> try:
            ...     PluginConfig.validate_name("   ")
            ... except ValueError as e:
            ...     "cannot be empty" in str(e)
            True
        """
        if not v or not v.strip():
            raise ValueError("Plugin name cannot be empty")
        return v


class CertificatesConfig(BaseModel):
    """Certificate configuration.

    Supports two modes:
    1. Local certificate generation (use_cert_manager=false, default):
       - Certificates generated locally using OpenSSL (via Makefile)
       - Deployed to Kubernetes as secrets via kubectl
       - Manual rotation required before expiry

    2. cert-manager integration (use_cert_manager=true, Kubernetes only):
       - Certificates managed by cert-manager controller
       - Automatic renewal before expiry (default: at 2/3 of lifetime)
       - Native Kubernetes Certificate resources
       - Requires cert-manager to be installed in cluster

    Attributes:
        validity_days: Certificate validity period in days (default: 825 ≈ 2.25 years)
        auto_generate: Auto-generate certificates locally (default: True)
        use_cert_manager: Use cert-manager for certificate management (default: False, Kubernetes only)
        cert_manager_issuer: Name of cert-manager Issuer/ClusterIssuer (default: "mcp-ca-issuer")
        cert_manager_kind: Type of issuer - Issuer or ClusterIssuer (default: "Issuer")
        ca_path: Path to CA certificates for local generation (default: "./certs/mcp/ca")
        gateway_path: Path to gateway certificates for local generation (default: "./certs/mcp/gateway")
        plugins_path: Path to plugin certificates for local generation (default: "./certs/mcp/plugins")
    """

    validity_days: Optional[int] = Field(825, description="Certificate validity in days")
    auto_generate: Optional[bool] = Field(True, description="Auto-generate certificates locally")

    # cert-manager integration (Kubernetes only)
    use_cert_manager: Optional[bool] = Field(False, description="Use cert-manager for certificate management (Kubernetes only)")
    cert_manager_issuer: Optional[str] = Field("mcp-ca-issuer", description="cert-manager Issuer/ClusterIssuer name")
    cert_manager_kind: Optional[Literal["Issuer", "ClusterIssuer"]] = Field("Issuer", description="cert-manager issuer kind")

    ca_path: Optional[str] = Field("./certs/mcp/ca", description="CA certificate path")
    gateway_path: Optional[str] = Field("./certs/mcp/gateway", description="Gateway cert path")
    plugins_path: Optional[str] = Field("./certs/mcp/plugins", description="Plugins cert path")


class PostgresConfig(BaseModel):
    """PostgreSQL database configuration"""

    enabled: Optional[bool] = Field(True, description="Enable PostgreSQL deployment")
    image: Optional[str] = Field("quay.io/sclorg/postgresql-15-c9s:latest", description="PostgreSQL image (default is OpenShift-compatible)")
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

        Examples:
            >>> from mcpgateway.tools.builder.schema import PluginConfig
            >>> # Test with unique names (valid)
            >>> plugins = [
            ...     PluginConfig(name="plugin1", image="img1:latest"),
            ...     PluginConfig(name="plugin2", image="img2:latest")
            ... ]
            >>> result = MCPStackConfig.validate_plugin_names_unique(plugins)
            >>> len(result) == 2
            True

            >>> # Test with duplicate names (invalid)
            >>> try:
            ...     duplicates = [
            ...         PluginConfig(name="duplicate", image="img1:latest"),
            ...         PluginConfig(name="duplicate", image="img2:latest")
            ...     ]
            ...     MCPStackConfig.validate_plugin_names_unique(duplicates)
            ... except ValueError as e:
            ...     "Duplicate plugin names found" in str(e)
            True

            >>> # Test with empty list (valid)
            >>> empty = MCPStackConfig.validate_plugin_names_unique([])
            >>> len(empty) == 0
            True
        """
        names = [p.name for p in v]
        if len(names) != len(set(names)):
            duplicates = [name for name in names if names.count(name) > 1]
            raise ValueError(f"Duplicate plugin names found: {duplicates}")
        return v
