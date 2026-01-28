# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/tools/builder/python_deploy.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Plain Python MCP Stack Deployment Module

This module provides deployment functionality using only standard Python
and system commands (docker/podman, kubectl, docker-compose).

This is the fallback implementation when Dagger is not available.
"""

# Standard
import asyncio
from pathlib import Path
import shutil
import subprocess  # nosec B404
from typing import List, Optional

# Third-Party
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

# First-Party
from mcpgateway.tools.builder.common import (
    deploy_compose,
    deploy_kubernetes,
    destroy_compose,
    destroy_kubernetes,
    generate_compose_manifests,
    generate_kubernetes_manifests,
    generate_plugin_config,
    get_deploy_dir,
    handle_registry_operations,
    load_config,
    verify_compose,
    verify_kubernetes,
)
from mcpgateway.tools.builder.common import copy_env_template as copy_template
from mcpgateway.tools.builder.pipeline import CICDModule
from mcpgateway.tools.builder.schema import BuildableConfig, MCPStackConfig

console = Console()


class MCPStackPython(CICDModule):
    """Plain Python implementation of MCP Stack deployment.

    This implementation uses standard Python and system commands (docker/podman,
    kubectl, docker-compose) without requiring additional dependencies like Dagger.

    Examples:
        >>> # Test class instantiation
        >>> deployer = MCPStackPython(verbose=False)
        >>> deployer.verbose
        False

        >>> # Test with verbose mode
        >>> deployer_verbose = MCPStackPython(verbose=True)
        >>> deployer_verbose.verbose
        True

        >>> # Test that console is available
        >>> hasattr(deployer, 'console')
        True

        >>> # Test that it's a CICDModule subclass
        >>> from mcpgateway.tools.builder.pipeline import CICDModule
        >>> isinstance(deployer, CICDModule)
        True
    """

    async def build(self, config_file: str, plugins_only: bool = False, specific_plugins: Optional[List[str]] = None, no_cache: bool = False, copy_env_templates: bool = False) -> None:
        """Build gateway and plugin containers using docker/podman.

        Args:
            config_file: Path to mcp-stack.yaml
            plugins_only: Only build plugins, skip gateway
            specific_plugins: List of specific plugin names to build
            no_cache: Disable build cache
            copy_env_templates: Copy .env.template files from cloned repos

        Raises:
            Exception: If build fails for any component
        """
        config = load_config(config_file)

        # Build gateway (unless plugins_only=True)
        if not plugins_only:
            gateway = config.gateway
            if gateway.repo:
                with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=self.console) as progress:
                    task = progress.add_task("Building gateway...", total=None)
                    try:
                        await asyncio.to_thread(self._build_component, gateway, config, "gateway", no_cache=no_cache)
                        progress.update(task, completed=1, description="[green]✓ Built gateway[/green]")
                    except Exception as e:
                        progress.update(task, completed=1, description="[red]✗ Failed gateway[/red]")
                        # Print full error after progress bar closes
                        self.console.print("\n[red bold]Gateway build failed:[/red bold]")
                        self.console.print(f"[red]{type(e).__name__}: {str(e)}[/red]")
                        if self.verbose:
                            # Standard
                            import traceback

                            self.console.print(f"[dim]{traceback.format_exc()}[/dim]")
                        raise
            elif self.verbose:
                self.console.print("[dim]Skipping gateway build (using pre-built image)[/dim]")

        # Build plugins
        plugins = config.plugins

        if specific_plugins:
            plugins = [p for p in plugins if p.name in specific_plugins]

        if not plugins:
            self.console.print("[yellow]No plugins to build[/yellow]")
            return

        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=self.console) as progress:

            for plugin in plugins:
                plugin_name = plugin.name

                # Skip if pre-built image specified
                if plugin.image and not plugin.repo:
                    task = progress.add_task(f"Skipping {plugin_name} (using pre-built image)", total=1)
                    progress.update(task, completed=1)
                    continue

                task = progress.add_task(f"Building {plugin_name}...", total=None)

                try:
                    await asyncio.to_thread(self._build_component, plugin, config, plugin_name, no_cache=no_cache, copy_env_templates=copy_env_templates)
                    progress.update(task, completed=1, description=f"[green]✓ Built {plugin_name}[/green]")
                except Exception as e:
                    progress.update(task, completed=1, description=f"[red]✗ Failed {plugin_name}[/red]")
                    # Print full error after progress bar closes
                    self.console.print(f"\n[red bold]Plugin '{plugin_name}' build failed:[/red bold]")
                    self.console.print(f"[red]{type(e).__name__}: {str(e)}[/red]")
                    if self.verbose:
                        # Standard
                        import traceback

                        self.console.print(f"[dim]{traceback.format_exc()}[/dim]")
                    raise

    async def generate_certificates(self, config_file: str) -> None:
        """Generate mTLS certificates for plugins.

        Supports two modes:
        1. Local generation (use_cert_manager=false): Uses Makefile to generate certificates locally
        2. cert-manager (use_cert_manager=true): Skips local generation, cert-manager will create certificates

        Args:
            config_file: Path to mcp-stack.yaml

        Raises:
            RuntimeError: If make command not found (when using local generation)
        """
        config = load_config(config_file)

        # Check if using cert-manager
        cert_config = config.certificates
        use_cert_manager = cert_config.use_cert_manager if cert_config else False
        validity_days = cert_config.validity_days if cert_config else 825

        if use_cert_manager:
            # Skip local generation - cert-manager will handle certificate creation
            if self.verbose:
                self.console.print("[blue]Using cert-manager for certificate management[/blue]")
                self.console.print("[dim]Skipping local certificate generation (cert-manager will create certificates)[/dim]")
            return

        # Local certificate generation (backward compatibility)
        if self.verbose:
            self.console.print("[blue]Generating mTLS certificates locally...[/blue]")

        # Check if make is available
        if not shutil.which("make"):
            raise RuntimeError("'make' command not found. Cannot generate certificates.")

        # Generate CA
        await asyncio.to_thread(self._run_command, ["make", "certs-mcp-ca", f"MCP_CERT_DAYS={validity_days}"])

        # Generate gateway cert
        await asyncio.to_thread(self._run_command, ["make", "certs-mcp-gateway", f"MCP_CERT_DAYS={validity_days}"])

        # Generate plugin certificates
        plugins = config.plugins
        for plugin in plugins:
            plugin_name = plugin.name
            await asyncio.to_thread(self._run_command, ["make", "certs-mcp-plugin", f"PLUGIN_NAME={plugin_name}", f"MCP_CERT_DAYS={validity_days}"])

        if self.verbose:
            self.console.print("[green]✓ Certificates generated locally[/green]")

    async def deploy(self, config_file: str, dry_run: bool = False, skip_build: bool = False, skip_certs: bool = False, output_dir: Optional[str] = None) -> None:
        """Deploy MCP stack.

        Args:
            config_file: Path to mcp-stack.yaml
            dry_run: Generate manifests without deploying
            skip_build: Skip building containers
            skip_certs: Skip certificate generation
            output_dir: Output directory for manifests (default: ./deploy)

        Raises:
            ValueError: If unsupported deployment type specified
        """
        config = load_config(config_file)

        # Build containers
        if not skip_build:
            await self.build(config_file)

        # Generate certificates (only if mTLS is enabled)
        gateway_mtls = config.gateway.mtls_enabled if config.gateway.mtls_enabled is not None else True
        plugin_mtls = any((p.mtls_enabled if p.mtls_enabled is not None else True) for p in config.plugins)
        mtls_needed = gateway_mtls or plugin_mtls

        if not skip_certs and mtls_needed:
            await self.generate_certificates(config_file)
        elif not skip_certs and not mtls_needed:
            if self.verbose:
                self.console.print("[dim]Skipping certificate generation (mTLS disabled)[/dim]")

        # Generate manifests
        manifests_dir = self.generate_manifests(config_file, output_dir=output_dir)

        if dry_run:
            self.console.print(f"[yellow]Dry-run: Manifests generated in {manifests_dir}[/yellow]")
            return

        # Apply deployment
        deployment_type = config.deployment.type

        if deployment_type == "kubernetes":
            self._deploy_kubernetes(manifests_dir)
        elif deployment_type == "compose":
            self._deploy_compose(manifests_dir)
        else:
            raise ValueError(f"Unsupported deployment type: {deployment_type}")

    async def verify(self, config_file: str, wait: bool = False, timeout: int = 300) -> None:
        """Verify deployment health.

        Args:
            config_file: Path to mcp-stack.yaml
            wait: Wait for deployment to be ready
            timeout: Wait timeout in seconds
        """
        config = load_config(config_file)
        deployment_type = config.deployment.type

        if self.verbose:
            self.console.print("[blue]Verifying deployment...[/blue]")

        if deployment_type == "kubernetes":
            self._verify_kubernetes(config, wait=wait, timeout=timeout)
        elif deployment_type == "compose":
            self._verify_compose(config, wait=wait, timeout=timeout)

    async def destroy(self, config_file: str) -> None:
        """Destroy deployed MCP stack.

        Args:
            config_file: Path to mcp-stack.yaml
        """
        config = load_config(config_file)
        deployment_type = config.deployment.type

        if self.verbose:
            self.console.print("[blue]Destroying deployment...[/blue]")

        if deployment_type == "kubernetes":
            self._destroy_kubernetes(config)
        elif deployment_type == "compose":
            self._destroy_compose(config)

    def generate_manifests(self, config_file: str, output_dir: Optional[str] = None) -> Path:
        """Generate deployment manifests.

        Args:
            config_file: Path to mcp-stack.yaml
            output_dir: Output directory for manifests

        Returns:
            Path to generated manifests directory

        Raises:
            ValueError: If unsupported deployment type specified

        Examples:
            >>> import tempfile
            >>> import yaml
            >>> from pathlib import Path
            >>> deployer = MCPStackPython(verbose=False)

            >>> # Test method signature and return type
            >>> import inspect
            >>> sig = inspect.signature(deployer.generate_manifests)
            >>> 'config_file' in sig.parameters
            True
            >>> 'output_dir' in sig.parameters
            True
            >>> sig.return_annotation == Path
            True

            >>> # Test that method exists and is callable
            >>> callable(deployer.generate_manifests)
            True
        """
        config = load_config(config_file)
        deployment_type = config.deployment.type

        if output_dir is None:
            deploy_dir = get_deploy_dir()
            # Separate subdirectories for kubernetes and compose
            output_dir = deploy_dir / "manifests" / deployment_type
        else:
            output_dir = Path(output_dir)

        output_dir.mkdir(parents=True, exist_ok=True)

        # Store output dir for later use
        self._last_output_dir = output_dir

        # Generate plugin config.yaml for gateway (shared function)
        generate_plugin_config(config, output_dir, verbose=self.verbose)

        if deployment_type == "kubernetes":
            generate_kubernetes_manifests(config, output_dir, verbose=self.verbose)
        elif deployment_type == "compose":
            generate_compose_manifests(config, output_dir, verbose=self.verbose)
        else:
            raise ValueError(f"Unsupported deployment type: {deployment_type}")

        return output_dir

    # Private helper methods

    def _detect_container_engine(self, config: MCPStackConfig) -> str:
        """Detect available container engine (docker or podman).

        Supports both engine names ("docker", "podman") and full paths ("/opt/podman/bin/podman").

        Args:
            config: MCP Stack configuration containing deployment settings

        Returns:
            Name or full path to available engine

        Raises:
            RuntimeError: If no container engine found

        Examples:
            >>> from mcpgateway.tools.builder.schema import MCPStackConfig, DeploymentConfig, GatewayConfig
            >>> deployer = MCPStackPython(verbose=False)

            >>> # Test with docker specified
            >>> config = MCPStackConfig(
            ...     deployment=DeploymentConfig(type="compose", container_engine="docker"),
            ...     gateway=GatewayConfig(image="test:latest"),
            ...     plugins=[]
            ... )
            >>> result = deployer._detect_container_engine(config)
            >>> result in ["docker", "podman"]  # Returns available engine
            True

            >>> # Test that method returns a string
            >>> import shutil
            >>> if shutil.which("docker") or shutil.which("podman"):
            ...     config = MCPStackConfig(
            ...         deployment=DeploymentConfig(type="compose"),
            ...         gateway=GatewayConfig(image="test:latest"),
            ...         plugins=[]
            ...     )
            ...     engine = deployer._detect_container_engine(config)
            ...     isinstance(engine, str)
            ... else:
            ...     True  # Skip test if no container engine available
            True
        """
        if config.deployment.container_engine:
            engine = config.deployment.container_engine

            # Check if it's a full path
            if "/" in engine:
                if Path(engine).exists() and Path(engine).is_file():
                    return engine
                else:
                    raise RuntimeError(f"Specified container engine path does not exist: {engine}")

            # Otherwise treat as command name and check PATH
            if shutil.which(engine):
                return engine
            else:
                raise RuntimeError(f"Unable to find specified container engine: {engine}")

        # Auto-detect
        if shutil.which("docker"):
            return "docker"
        elif shutil.which("podman"):
            return "podman"
        else:
            raise RuntimeError("No container engine found. Install docker or podman.")

    def _run_command(self, cmd: List[str], cwd: Optional[Path] = None, capture_output: bool = False) -> subprocess.CompletedProcess:
        """Run a shell command.

        Args:
            cmd: Command and arguments
            cwd: Working directory
            capture_output: Capture stdout/stderr

        Returns:
            CompletedProcess instance

        Raises:
            subprocess.CalledProcessError: If command fails
        """
        if self.verbose:
            self.console.print(f"[dim]Running: {' '.join(cmd)}[/dim]")

        result = subprocess.run(cmd, cwd=cwd, capture_output=capture_output, text=True, check=True)  # nosec B603, B607

        return result

    def _build_component(self, component: BuildableConfig, config: MCPStackConfig, component_name: str, no_cache: bool = False, copy_env_templates: bool = False) -> None:
        """Build a component (gateway or plugin) container using docker/podman.

        Args:
            component: Component configuration (GatewayConfig or PluginConfig)
            config: Overall stack configuration
            component_name: Name of the component (gateway or plugin name)
            no_cache: Disable cache
            copy_env_templates: Copy .env.template from repo if it exists

        Raises:
            ValueError: If component has no repo field
            FileNotFoundError: If build context or containerfile not found
        """
        repo = component.repo

        container_engine = self._detect_container_engine(config)

        if not repo:
            raise ValueError(f"Component '{component_name}' has no 'repo' field")

        # Clone repository
        git_ref = component.ref or "main"
        clone_dir = Path(f"./build/{component_name}")
        clone_dir.mkdir(parents=True, exist_ok=True)

        # Clone or update repo
        if (clone_dir / ".git").exists():
            if self.verbose:
                self.console.print(f"[dim]Updating {component_name} repository...[/dim]")
            self._run_command(["git", "fetch", "origin", git_ref], cwd=clone_dir)
            # Checkout what we just fetched (FETCH_HEAD)
            self._run_command(["git", "checkout", "FETCH_HEAD"], cwd=clone_dir)
        else:
            if self.verbose:
                self.console.print(f"[dim]Cloning {component_name} repository...[/dim]")
            self._run_command(["git", "clone", "--branch", git_ref, "--depth", "1", repo, str(clone_dir)])

        # Determine build context (subdirectory within repo)
        build_context = component.context or "."
        build_dir = clone_dir / build_context

        if not build_dir.exists():
            raise FileNotFoundError(f"Build context not found: {build_dir}")

        # Detect Containerfile/Dockerfile
        containerfile = component.containerfile or "Containerfile"
        containerfile_path = build_dir / containerfile

        if not containerfile_path.exists():
            containerfile = "Dockerfile"
            containerfile_path = build_dir / containerfile
            if not containerfile_path.exists():
                raise FileNotFoundError(f"No Containerfile or Dockerfile found in {build_dir}")

        # Build container - determine image tag
        if component.image:
            # Use explicitly specified image name
            image_tag = component.image
        else:
            # Generate default image name based on component type
            image_tag = f"mcpgateway-{component_name.lower()}:latest"

        build_cmd = [container_engine, "build", "-f", containerfile, "-t", image_tag]

        if no_cache:
            build_cmd.append("--no-cache")

        # Add target stage if specified (for multi-stage builds)
        if component.target:
            build_cmd.extend(["--target", component.target])

        # For Docker, add --load to ensure image is loaded into daemon
        # (needed for buildx/docker-container driver)
        if container_engine == "docker":
            build_cmd.append("--load")

        build_cmd.append(".")

        self._run_command(build_cmd, cwd=build_dir)

        # Handle registry operations (tag and push if enabled)
        image_tag = handle_registry_operations(component, component_name, image_tag, container_engine, verbose=self.verbose)

        # Copy .env.template if requested and exists
        if copy_env_templates:
            copy_template(component_name, build_dir, verbose=self.verbose)

        if self.verbose:
            self.console.print(f"[green]✓ Built {component_name} -> {image_tag}[/green]")

    def _deploy_kubernetes(self, manifests_dir: Path) -> None:
        """Deploy to Kubernetes using kubectl.

        Uses shared deploy_kubernetes() from common.py to avoid code duplication.

        Args:
            manifests_dir: Path to directory containing Kubernetes manifests
        """
        deploy_kubernetes(manifests_dir, verbose=self.verbose)

    def _deploy_compose(self, manifests_dir: Path) -> None:
        """Deploy using Docker Compose.

        Uses shared deploy_compose() from common.py to avoid code duplication.

        Args:
            manifests_dir: Path to directory containing compose manifest
        """
        compose_file = manifests_dir / "docker-compose.yaml"
        deploy_compose(compose_file, verbose=self.verbose)

    def _verify_kubernetes(self, config: MCPStackConfig, wait: bool = False, timeout: int = 300) -> None:
        """Verify Kubernetes deployment health.

        Uses shared verify_kubernetes() from common.py to avoid code duplication.

        Args:
            config: Parsed configuration Pydantic model
            wait: Wait for pods to be ready
            timeout: Wait timeout in seconds
        """
        namespace = config.deployment.namespace or "mcp-gateway"
        output = verify_kubernetes(namespace, wait=wait, timeout=timeout, verbose=self.verbose)
        self.console.print(output)

    def _verify_compose(self, config: MCPStackConfig, wait: bool = False, timeout: int = 300) -> None:
        """Verify Docker Compose deployment health.

        Uses shared verify_compose() from common.py to avoid code duplication.

        Args:
            config: Parsed configuration Pydantic model
            wait: Wait for containers to be ready
            timeout: Wait timeout in seconds
        """
        _ = config, wait, timeout  # Reserved for future use
        # Use the same manifests directory as generate_manifests
        deploy_dir = get_deploy_dir()
        output_dir = getattr(self, "_last_output_dir", deploy_dir / "manifests" / "compose")
        compose_file = output_dir / "docker-compose.yaml"
        output = verify_compose(compose_file, verbose=self.verbose)
        self.console.print(output)

    def _destroy_kubernetes(self, config: MCPStackConfig) -> None:
        """Destroy Kubernetes deployment.

        Uses shared destroy_kubernetes() from common.py to avoid code duplication.

        Args:
            config: Parsed configuration Pydantic model
        """
        _ = config  # Reserved for future use (namespace, labels, etc.)
        # Use the same manifests directory as generate_manifests
        deploy_dir = get_deploy_dir()
        manifests_dir = getattr(self, "_last_output_dir", deploy_dir / "manifests" / "kubernetes")
        destroy_kubernetes(manifests_dir, verbose=self.verbose)

    def _destroy_compose(self, config: MCPStackConfig) -> None:
        """Destroy Docker Compose deployment.

        Uses shared destroy_compose() from common.py to avoid code duplication.

        Args:
            config: Parsed configuration Pydantic model
        """
        _ = config  # Reserved for future use (project name, networks, etc.)
        # Use the same manifests directory as generate_manifests
        deploy_dir = get_deploy_dir()
        output_dir = getattr(self, "_last_output_dir", deploy_dir / "manifests" / "compose")
        compose_file = output_dir / "docker-compose.yaml"
        destroy_compose(compose_file, verbose=self.verbose)
