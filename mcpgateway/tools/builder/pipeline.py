# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/tools/builder/pipeline.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Abstract base class for MCP Stack deployment implementations.

This module defines the CICDModule interface that all deployment implementations
must implement. It provides a common API for building, deploying, and managing
MCP Gateway stacks with external plugin servers.

The base class implements shared functionality (validation) while requiring
subclasses to implement deployment-specific logic (build, deploy, etc.).

Design Pattern:
    Strategy Pattern - Different implementations (Dagger vs Python) can be
    swapped transparently via the DeployFactory.

Example:
    >>> from mcpgateway.tools.builder.factory import DeployFactory
    >>> deployer, mode = DeployFactory.create_deployer("dagger", verbose=False)
    ⚠ Dagger not installed. Using plain python.
    >>> # Validate configuration (output varies by config)
    >>> # deployer.validate("mcp-stack.yaml")
    >>> # Async methods must be called with await (see method examples below)
"""

# Standard
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

# Third-Party
from pydantic import ValidationError
from rich.console import Console
import yaml

# First-Party
from mcpgateway.tools.builder.schema import MCPStackConfig

# Shared console instance for consistent output formatting
console = Console()


class CICDModule(ABC):
    """Abstract base class for MCP Stack deployment implementations.

    This class defines the interface that all deployment implementations must
    implement. It provides common initialization and validation logic while
    deferring implementation-specific details to subclasses.

    Attributes:
        verbose (bool): Enable verbose output during operations
        console (Console): Rich console for formatted output

    Implementations:
        - MCPStackDagger: High-performance implementation using Dagger SDK
        - MCPStackPython: Fallback implementation using plain Python + Docker/Podman

    Examples:
        >>> # Test that CICDModule is abstract
        >>> from abc import ABC
        >>> issubclass(CICDModule, ABC)
        True

        >>> # Test initialization with defaults
        >>> class TestDeployer(CICDModule):
        ...     async def build(self, config_file: str, **kwargs) -> None:
        ...         pass
        ...     async def generate_certificates(self, config_file: str) -> None:
        ...         pass
        ...     async def deploy(self, config_file: str, **kwargs) -> None:
        ...         pass
        ...     async def verify(self, config_file: str, **kwargs) -> None:
        ...         pass
        ...     async def destroy(self, config_file: str) -> None:
        ...         pass
        ...     def generate_manifests(self, config_file: str, **kwargs) -> Path:
        ...         return Path(".")
        >>> deployer = TestDeployer()
        >>> deployer.verbose
        False

        >>> # Test initialization with verbose=True
        >>> verbose_deployer = TestDeployer(verbose=True)
        >>> verbose_deployer.verbose
        True

        >>> # Test that console is available
        >>> hasattr(deployer, 'console')
        True
    """

    def __init__(self, verbose: bool = False):
        """Initialize the deployment module.

        Args:
            verbose: Enable verbose output during all operations

        Examples:
            >>> # Cannot instantiate abstract class directly
            >>> try:
            ...     CICDModule()
            ... except TypeError as e:
            ...     "abstract" in str(e).lower()
            True
        """
        self.verbose = verbose
        self.console = console

    def validate(self, config_file: str) -> None:
        """Validate mcp-stack.yaml configuration using Pydantic schemas.

        This method provides comprehensive validation of the MCP stack configuration
        using Pydantic models defined in schema.py. It validates:
        - Required sections (deployment, gateway, plugins)
        - Deployment type (kubernetes or compose)
        - Gateway image specification
        - Plugin configurations (name, repo/image, etc.)
        - Custom business rules (unique names, valid combinations)

        Args:
            config_file: Path to mcp-stack.yaml configuration file

        Raises:
            ValueError: If configuration is invalid, with formatted error details
            ValidationError: If Pydantic schema validation fails
            FileNotFoundError: If config_file does not exist

        Examples:
            >>> import tempfile
            >>> import yaml
            >>> from pathlib import Path
            >>> # Create a test deployer
            >>> class TestDeployer(CICDModule):
            ...     async def build(self, config_file: str, **kwargs) -> None:
            ...         pass
            ...     async def generate_certificates(self, config_file: str) -> None:
            ...         pass
            ...     async def deploy(self, config_file: str, **kwargs) -> None:
            ...         pass
            ...     async def verify(self, config_file: str, **kwargs) -> None:
            ...         pass
            ...     async def destroy(self, config_file: str) -> None:
            ...         pass
            ...     def generate_manifests(self, config_file: str, **kwargs) -> Path:
            ...         return Path(".")
            >>> deployer = TestDeployer(verbose=False)

            >>> # Test with valid minimal config
            >>> with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            ...     config = {
            ...         'deployment': {'type': 'compose'},
            ...         'gateway': {'image': 'test:latest'},
            ...         'plugins': []
            ...     }
            ...     yaml.dump(config, f)
            ...     config_path = f.name
            >>> deployer.validate(config_path)
            >>> import os
            >>> os.unlink(config_path)

            >>> # Test with missing file
            >>> try:
            ...     deployer.validate("/nonexistent/config.yaml")
            ... except FileNotFoundError as e:
            ...     "config.yaml" in str(e)
            True

            >>> # Test with invalid config (missing required fields)
            >>> with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            ...     bad_config = {'deployment': {'type': 'compose'}}
            ...     yaml.dump(bad_config, f)
            ...     bad_path = f.name
            >>> try:
            ...     deployer.validate(bad_path)
            ... except ValueError as e:
            ...     "validation failed" in str(e).lower()
            True
            >>> os.unlink(bad_path)
        """
        if self.verbose:
            self.console.print(f"[blue]Validating {config_file}...[/blue]")

        # Load YAML configuration
        with open(config_file, "r") as f:
            config_dict = yaml.safe_load(f)

        # Validate using Pydantic schema
        try:
            # Local

            MCPStackConfig(**config_dict)
        except ValidationError as e:
            # Format validation errors for better readability
            error_msg = "Configuration validation failed:\n"
            for error in e.errors():
                # Join the error location path (e.g., plugins -> 0 -> name)
                loc = " -> ".join(str(x) for x in error["loc"])
                error_msg += f"  • {loc}: {error['msg']}\n"
            raise ValueError(error_msg) from e

        if self.verbose:
            self.console.print("[green]✓ Configuration valid[/green]")

    @abstractmethod
    async def build(self, config_file: str, plugins_only: bool = False, specific_plugins: Optional[list[str]] = None, no_cache: bool = False, copy_env_templates: bool = False) -> None:
        """Build container images for plugins and/or gateway.

        Subclasses must implement this to build Docker/Podman images from
        Git repositories or use pre-built images.

        Args:
            config_file: Path to mcp-stack.yaml
            plugins_only: Only build plugins, skip gateway
            specific_plugins: List of specific plugin names to build (optional)
            no_cache: Disable build cache for fresh builds
            copy_env_templates: Copy .env.template files from cloned repos

        Raises:
            RuntimeError: If build fails
            ValueError: If plugin configuration is invalid

        Example:
            # await deployer.build("mcp-stack.yaml", plugins_only=True)
            # ✓ Built OPAPluginFilter
            # ✓ Built LLMGuardPlugin
        """

    @abstractmethod
    async def generate_certificates(self, config_file: str) -> None:
        """Generate mTLS certificates for gateway and plugins.

        Creates a certificate authority (CA) and issues certificates for:
        - Gateway (client certificates for connecting to plugins)
        - Each plugin (server certificates for accepting connections)

        Certificates are stored in the paths defined in the config's
        certificates section (default: ./certs/mcp/).

        Args:
            config_file: Path to mcp-stack.yaml

        Raises:
            RuntimeError: If certificate generation fails
            FileNotFoundError: If required tools (openssl) are not available

        Example:
            # await deployer.generate_certificates("mcp-stack.yaml")
            # ✓ Certificates generated
        """

    @abstractmethod
    async def deploy(self, config_file: str, dry_run: bool = False, skip_build: bool = False, skip_certs: bool = False) -> None:
        """Deploy the MCP stack to Kubernetes or Docker Compose.

        This is the main deployment method that orchestrates:
        1. Building containers (unless skip_build=True)
        2. Generating mTLS certificates (unless skip_certs=True or mTLS disabled)
        3. Generating manifests (Kubernetes YAML or docker-compose.yaml)
        4. Applying the deployment (unless dry_run=True)

        Args:
            config_file: Path to mcp-stack.yaml
            dry_run: Generate manifests without actually deploying
            skip_build: Skip building containers (use existing images)
            skip_certs: Skip certificate generation (use existing certs)

        Raises:
            RuntimeError: If deployment fails at any stage
            ValueError: If configuration is invalid

        Example:
            # Full deployment
            # await deployer.deploy("mcp-stack.yaml")
            # ✓ Build complete
            # ✓ Certificates generated
            # ✓ Deployment complete

            # Dry run (generate manifests only)
            # await deployer.deploy("mcp-stack.yaml", dry_run=True)
            # ✓ Dry-run complete (no changes made)
        """

    @abstractmethod
    async def verify(self, config_file: str, wait: bool = False, timeout: int = 300) -> None:
        """Verify deployment health and readiness.

        Checks that all deployed services are healthy and ready:
        - Kubernetes: Checks pod status, optionally waits for Ready
        - Docker Compose: Checks container status

        Args:
            config_file: Path to mcp-stack.yaml
            wait: Wait for deployment to become ready
            timeout: Maximum time to wait in seconds (default: 300)

        Raises:
            RuntimeError: If verification fails or timeout is reached
            TimeoutError: If wait=True and deployment doesn't become ready

        Example:
            # Quick health check
            # await deployer.verify("mcp-stack.yaml")
            # NAME                    READY   STATUS    RESTARTS   AGE
            # mcpgateway-xxx          1/1     Running   0          2m
            # mcp-plugin-opa-xxx      1/1     Running   0          2m

            # Wait for ready state
            # await deployer.verify("mcp-stack.yaml", wait=True, timeout=600)
            # ✓ Deployment healthy
        """

    @abstractmethod
    async def destroy(self, config_file: str) -> None:
        """Destroy the deployed MCP stack.

        Removes all deployed resources:
        - Kubernetes: Deletes all resources in the namespace
        - Docker Compose: Stops and removes containers, networks, volumes

        WARNING: This is destructive and cannot be undone!

        Args:
            config_file: Path to mcp-stack.yaml

        Raises:
            RuntimeError: If destruction fails

        Example:
            # await deployer.destroy("mcp-stack.yaml")
            # ✓ Deployment destroyed
        """

    @abstractmethod
    def generate_manifests(self, config_file: str, output_dir: Optional[str] = None) -> Path:
        """Generate deployment manifests (Kubernetes YAML or docker-compose.yaml).

        Creates deployment manifests based on configuration:
        - Kubernetes: Generates Deployment, Service, ConfigMap, Secret YAML files
        - Docker Compose: Generates docker-compose.yaml with all services

        Also generates:
        - plugins-config.yaml: Plugin manager configuration for gateway
        - Environment files: .env files for each service

        Args:
            config_file: Path to mcp-stack.yaml
            output_dir: Output directory for manifests (default: ./deploy/manifests)

        Returns:
            Path: Directory containing generated manifests

        Raises:
            ValueError: If configuration is invalid
            OSError: If output directory cannot be created

        Example:
            # manifests_path = deployer.generate_manifests("mcp-stack.yaml")
            # print(f"Manifests generated in: {manifests_path}")
            # Manifests generated in: /path/to/deploy/manifests

            # Custom output directory
            # deployer.generate_manifests("mcp-stack.yaml", output_dir="./my-manifests")
            # ✓ Manifests generated: ./my-manifests
        """
