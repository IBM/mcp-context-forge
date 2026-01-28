# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/tools/builder/dagger_deploy.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Dagger-based MCP Stack Deployment Module

This module provides optimized build and deployment using Dagger.

Features:
- Automatic caching and parallelization
- Content-addressable storage
- Efficient multi-stage builds
- Built-in layer caching
"""

# Standard
import asyncio
from pathlib import Path
import subprocess  # nosec B404
from typing import List, Optional

try:
    # Third-Party
    import dagger
    from dagger import dag

    DAGGER_AVAILABLE = True
except ImportError:
    DAGGER_AVAILABLE = False
    dagger = None  # type: ignore
    dag = None  # type: ignore

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


class MCPStackDagger(CICDModule):
    """Dagger-based implementation of MCP Stack deployment."""

    def __init__(self, verbose: bool = False):
        """Initialize MCPStackDagger instance.

        Args:
            verbose: Enable verbose output

        Raises:
            ImportError: If dagger is not installed
        """
        if not DAGGER_AVAILABLE:
            raise ImportError("Dagger is not installed. Install with: pip install dagger-io\n" "Alternatively, use the plain Python deployer with --deployer=python")
        super().__init__(verbose)

    async def build(self, config_file: str, plugins_only: bool = False, specific_plugins: Optional[List[str]] = None, no_cache: bool = False, copy_env_templates: bool = False) -> None:
        """Build gateway and plugin containers using Dagger.

        Args:
            config_file: Path to mcp-stack.yaml
            plugins_only: Only build plugins, skip gateway
            specific_plugins: List of specific plugin names to build
            no_cache: Disable Dagger cache
            copy_env_templates: Copy .env.template files from cloned repos

        Raises:
            Exception: If build fails for any component
        """
        config = load_config(config_file)

        async with dagger.connection(dagger.Config(workdir=str(Path.cwd()))):
            # Build gateway (unless plugins_only=True)
            if not plugins_only:
                gateway = config.gateway
                if gateway.repo:
                    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=self.console) as progress:
                        task = progress.add_task("Building gateway...", total=None)
                        try:
                            await self._build_component_with_dagger(gateway, "gateway", no_cache=no_cache)
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
                        await self._build_component_with_dagger(plugin, plugin_name, no_cache=no_cache, copy_env_templates=copy_env_templates)
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
        1. Local generation (use_cert_manager=false): Uses Dagger to generate certificates locally
        2. cert-manager (use_cert_manager=true): Skips local generation, cert-manager will create certificates

        Args:
            config_file: Path to mcp-stack.yaml

        Raises:
            dagger.ExecError: If certificate generation command fails (when using local generation)
            dagger.QueryError: If Dagger query fails (when using local generation)
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

        # Use Dagger container to run certificate generation
        async with dagger.connection(dagger.Config(workdir=str(Path.cwd()))):
            # Mount current directory
            source = dag.host().directory(".")
            try:
                # Use Alpine with openssl
                container = (
                    dag.container()
                    .from_("alpine:latest")
                    .with_exec(["apk", "add", "--no-cache", "openssl", "python3", "py3-pip", "make", "bash"])
                    .with_mounted_directory("/workspace", source)
                    .with_workdir("/workspace")
                    # .with_exec(["python3", "-m", "venv", ".venv"])
                    # .with_exec(["sh", "-c", "source .venv/bin/activate && pip install pyyaml"])
                    # .with_exec(["pip", "install", "pyyaml"])
                )

                # Generate CA
                container = container.with_exec(["sh", "-c", f"make certs-mcp-ca MCP_CERT_DAYS={validity_days}"])

                # Generate gateway cert
                container = container.with_exec(["sh", "-c", f"make certs-mcp-gateway MCP_CERT_DAYS={validity_days}"])

                # Generate plugin certificates
                plugins = config.plugins
                for plugin in plugins:
                    plugin_name = plugin.name
                    container = container.with_exec(["sh", "-c", f"make certs-mcp-plugin PLUGIN_NAME={plugin_name} MCP_CERT_DAYS={validity_days}"])

                # Export certificates back to host
                output = container.directory("/workspace/certs")
                await output.export("./certs")
            except dagger.ExecError as e:
                self.console.print(f"Dagger Exec Error: {e.message}")
                self.console.print(f"Exit Code: {e.exit_code}")
                self.console.print(f"Stderr: {e.stderr}")
                raise
            except dagger.QueryError as e:
                self.console.print(f"Dagger Query Error: {e.errors}")
                self.console.print(f"Debug Query: {e.debug_query()}")
                raise
            except Exception as e:
                self.console.print(f"An unexpected error occurred: {e}")
                raise

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
            dagger.ExecError: If deployment command fails
            dagger.QueryError: If Dagger query fails
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

        async with dagger.connection(dagger.Config(workdir=str(Path.cwd()))):
            try:
                if deployment_type == "kubernetes":
                    await self._deploy_kubernetes(manifests_dir)
                elif deployment_type == "compose":
                    await self._deploy_compose(manifests_dir)
                else:
                    raise ValueError(f"Unsupported deployment type: {deployment_type}")
            except dagger.ExecError as e:
                self.console.print(f"Dagger Exec Error: {e.message}")
                self.console.print(f"Exit Code: {e.exit_code}")
                self.console.print(f"Stderr: {e.stderr}")
                raise
            except dagger.QueryError as e:
                self.console.print(f"Dagger Query Error: {e.errors}")
                self.console.print(f"Debug Query: {e.debug_query()}")
                raise
            except Exception as e:
                # Extract detailed error from Dagger exception
                error_msg = str(e)
                self.console.print("\n[red bold]Deployment failed:[/red bold]")
                self.console.print(f"[red]{error_msg}[/red]")

                # Check if it's a compose-specific error and try to provide more context
                if "compose" in error_msg.lower() and self.verbose:
                    self.console.print("\n[yellow]Hint:[/yellow] Check the generated docker-compose.yaml:")
                    self.console.print(f"[dim]  {manifests_dir}/docker-compose.yaml[/dim]")
                    self.console.print("[yellow]Try running manually:[/yellow]")
                    self.console.print(f"[dim]  cd {manifests_dir} && docker compose up[/dim]")

                raise

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

        async with dagger.connection(dagger.Config(workdir=str(Path.cwd()))):
            if deployment_type == "kubernetes":
                await self._verify_kubernetes(config, wait=wait, timeout=timeout)
            elif deployment_type == "compose":
                await self._verify_compose(config, wait=wait, timeout=timeout)

    async def destroy(self, config_file: str) -> None:
        """Destroy deployed MCP stack.

        Args:
            config_file: Path to mcp-stack.yaml
        """
        config = load_config(config_file)
        deployment_type = config.deployment.type

        if self.verbose:
            self.console.print("[blue]Destroying deployment...[/blue]")

        async with dagger.connection(dagger.Config(workdir=str(Path.cwd()))):
            if deployment_type == "kubernetes":
                await self._destroy_kubernetes(config)
            elif deployment_type == "compose":
                await self._destroy_compose(config)

    def generate_manifests(self, config_file: str, output_dir: Optional[str] = None) -> Path:
        """Generate deployment manifests.

        Args:
            config_file: Path to mcp-stack.yaml
            output_dir: Output directory for manifests

        Returns:
            Path to generated manifests directory

        Raises:
            ValueError: If unsupported deployment type specified
        """
        config = load_config(config_file)
        deployment_type = config.deployment.type

        if output_dir is None:
            deploy_dir = get_deploy_dir()
            # Separate subdirectories for kubernetes and compose
            manifests_path = deploy_dir / "manifests" / deployment_type
        else:
            manifests_path = Path(output_dir)

        manifests_path.mkdir(parents=True, exist_ok=True)

        # Store output dir for later use
        self._last_output_dir = manifests_path

        # Generate plugin config.yaml for gateway (shared function)
        generate_plugin_config(config, manifests_path, verbose=self.verbose)

        if deployment_type == "kubernetes":
            generate_kubernetes_manifests(config, manifests_path, verbose=self.verbose)
        elif deployment_type == "compose":
            generate_compose_manifests(config, manifests_path, verbose=self.verbose)
        else:
            raise ValueError(f"Unsupported deployment type: {deployment_type}")

        return manifests_path

    # Private helper methods

    async def _build_component_with_dagger(self, component: BuildableConfig, component_name: str, no_cache: bool = False, copy_env_templates: bool = False) -> None:
        """Build a component (gateway or plugin) container using Dagger.

        Args:
            component: Component configuration (GatewayConfig or PluginConfig)
            component_name: Name of the component (gateway or plugin name)
            no_cache: Disable cache
            copy_env_templates: Copy .env.template from repo if it exists

        Raises:
            ValueError: If component has no repo field
            Exception: If build or export fails
        """
        repo = component.repo

        if not repo:
            raise ValueError(f"Component '{component_name}' has no 'repo' field")

        # Clone repository to local directory for env template access
        git_ref = component.ref or "main"
        clone_dir = Path(f"./build/{component_name}")

        # For Dagger, we still need local clone if copying env templates
        if copy_env_templates:
            clone_dir.mkdir(parents=True, exist_ok=True)

            if (clone_dir / ".git").exists():
                await asyncio.to_thread(subprocess.run, ["git", "fetch", "origin", git_ref], cwd=clone_dir, check=True, capture_output=True)  # nosec B603, B607
                # Checkout what we just fetched (FETCH_HEAD)
                await asyncio.to_thread(subprocess.run, ["git", "checkout", "FETCH_HEAD"], cwd=clone_dir, check=True, capture_output=True)  # nosec B603, B607
            else:
                await asyncio.to_thread(subprocess.run, ["git", "clone", "--branch", git_ref, "--depth", "1", repo, str(clone_dir)], check=True, capture_output=True)  # nosec B603, B607

            # Determine build context
            build_context = component.context or "."
            build_dir = clone_dir / build_context

            # Copy env template using shared function
            copy_template(component_name, build_dir, verbose=self.verbose)

        # Use Dagger for the actual build
        source = dag.git(repo).branch(git_ref).tree()

        # If component has context subdirectory, navigate to it
        build_context = component.context or "."
        if build_context != ".":
            source = source.directory(build_context)

        # Detect Containerfile/Dockerfile
        containerfile = component.containerfile or "Containerfile"

        # Build container - determine image tag
        if component.image:
            # Use explicitly specified image name
            image_tag = component.image
        else:
            # Generate default image name based on component type
            image_tag = f"mcpgateway-{component_name.lower()}:latest"

        # Build with optional target stage for multi-stage builds
        build_kwargs = {"dockerfile": containerfile}
        if component.target:
            build_kwargs["target"] = component.target

        # Use docker_build on the directory
        container = source.docker_build(**build_kwargs)

        # Export image to Docker daemon (always export, Dagger handles caching)
        # Workaround for dagger-io 0.19.0 bug: export_image returns None instead of Void
        # The export actually works, but beartype complains about the return type
        try:
            await container.export_image(image_tag)
        except Exception as e:
            # Ignore beartype validation error - the export actually succeeds
            if "BeartypeCallHintReturnViolation" not in str(type(e)):
                raise

        # Handle registry operations (tag and push if enabled)
        # Note: Dagger exports to local docker/podman, so we need to detect which runtime to use
        # Standard
        import shutil

        container_runtime = "docker" if shutil.which("docker") else "podman"
        image_tag = handle_registry_operations(component, component_name, image_tag, container_runtime, verbose=self.verbose)

        if self.verbose:
            self.console.print(f"[green]✓ Built {component_name} -> {image_tag}[/green]")

    async def _deploy_kubernetes(self, manifests_dir: Path) -> None:
        """Deploy to Kubernetes using kubectl.

        Uses shared deploy_kubernetes() from common.py to avoid code duplication.

        Args:
            manifests_dir: Path to directory containing Kubernetes manifests
        """
        deploy_kubernetes(manifests_dir, verbose=self.verbose)

    async def _deploy_compose(self, manifests_dir: Path) -> None:
        """Deploy using Docker Compose.

        Uses shared deploy_compose() from common.py to avoid code duplication.

        Args:
            manifests_dir: Path to directory containing compose manifest
        """
        compose_file = manifests_dir / "docker-compose.yaml"
        deploy_compose(compose_file, verbose=self.verbose)

    async def _verify_kubernetes(self, config: MCPStackConfig, wait: bool = False, timeout: int = 300) -> None:
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

    async def _verify_compose(self, config: MCPStackConfig, wait: bool = False, timeout: int = 300) -> None:
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

    async def _destroy_kubernetes(self, config: MCPStackConfig) -> None:
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

    async def _destroy_compose(self, config: MCPStackConfig) -> None:
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
