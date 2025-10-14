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
from pathlib import Path
import shutil
import subprocess
from typing import Any, Dict, List, Optional

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
    load_config,
    verify_compose,
    verify_kubernetes,
)
from mcpgateway.tools.builder.common import copy_env_template as copy_template
from mcpgateway.tools.builder.pipeline import CICDModule

console = Console()


class MCPStackPython(CICDModule):
    """Plain Python implementation of MCP Stack deployment."""

    def __init__(self, verbose: bool = False):
        """Initialize MCPStackPython instance.

        Args:
            verbose: Enable verbose output
        """
        super().__init__(verbose)

        # Detect container runtime (docker or podman)
        self.container_runtime = self._detect_container_runtime()

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
            gateway = config.get("gateway", {})
            if gateway.get("repo"):
                with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=self.console) as progress:
                    task = progress.add_task("Building gateway...", total=None)
                    try:
                        self._build_component(gateway, "gateway", no_cache=no_cache)
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
        plugins = config.get("plugins", [])

        if specific_plugins:
            plugins = [p for p in plugins if p["name"] in specific_plugins]

        if not plugins:
            self.console.print("[yellow]No plugins to build[/yellow]")
            return

        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=self.console) as progress:

            for plugin in plugins:
                plugin_name = plugin["name"]

                # Skip if pre-built image specified
                if "image" in plugin and "repo" not in plugin:
                    task = progress.add_task(f"Skipping {plugin_name} (using pre-built image)", total=1)
                    progress.update(task, completed=1)
                    continue

                task = progress.add_task(f"Building {plugin_name}...", total=None)

                try:
                    self._build_component(plugin, plugin_name, no_cache=no_cache, copy_env_templates=copy_env_templates)
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

        Args:
            config_file: Path to mcp-stack.yaml

        Raises:
            RuntimeError: If make command not found
        """
        config = load_config(config_file)

        if self.verbose:
            self.console.print("[blue]Generating mTLS certificates...[/blue]")

        # Check if make is available
        if not shutil.which("make"):
            raise RuntimeError("'make' command not found. Cannot generate certificates.")

        # Generate CA
        self._run_command(["make", "certs-mcp-ca", "MCP_CERT_DAYS=825"])

        # Generate gateway cert
        self._run_command(["make", "certs-mcp-gateway", "MCP_CERT_DAYS=825"])

        # Generate plugin certificates
        plugins = config.get("plugins", [])
        for plugin in plugins:
            plugin_name = plugin["name"]
            self._run_command(["make", "certs-mcp-plugin", f"PLUGIN_NAME={plugin_name}", "MCP_CERT_DAYS=825"])

        if self.verbose:
            self.console.print("[green]✓ Certificates generated[/green]")

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
        gateway_mtls = config.get("gateway", {}).get("mtls_enabled", True)
        plugin_mtls = any(p.get("mtls_enabled", True) for p in config.get("plugins", []))
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
        deployment_type = config["deployment"]["type"]

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
        deployment_type = config["deployment"]["type"]

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
        deployment_type = config["deployment"]["type"]

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
        """
        config = load_config(config_file)
        deployment_type = config["deployment"]["type"]

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

    def _detect_container_runtime(self) -> str:
        """Detect available container runtime (docker or podman).

        Returns:
            Name of available runtime "docker" or "podman"

        Raises:
            RuntimeError: If no container runtime found
        """
        if shutil.which("docker"):
            return "docker"
        elif shutil.which("podman"):
            return "podman"
        else:
            raise RuntimeError("No container runtime found. Install docker or podman.")

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

        result = subprocess.run(cmd, cwd=cwd, capture_output=capture_output, text=True, check=True)

        return result

    def _build_component(self, component: Dict[str, Any], component_name: str, no_cache: bool = False, copy_env_templates: bool = False) -> None:
        """Build a component (gateway or plugin) container using docker/podman.

        Args:
            component: Component configuration dict
            component_name: Name of the component (gateway or plugin name)
            no_cache: Disable cache
            copy_env_templates: Copy .env.template from repo if it exists

        Raises:
            ValueError: If component has no repo field
            FileNotFoundError: If build context or containerfile not found
        """
        repo = component.get("repo")

        if not repo:
            raise ValueError(f"Component '{component_name}' has no 'repo' field")

        # Clone repository
        git_ref = component.get("ref", "main")
        clone_dir = Path(f"./build/{component_name}")
        clone_dir.mkdir(parents=True, exist_ok=True)

        # Clone or update repo
        if (clone_dir / ".git").exists():
            if self.verbose:
                self.console.print(f"[dim]Updating {component_name} repository...[/dim]")
            self._run_command(["git", "fetch", "origin", git_ref], cwd=clone_dir)
            self._run_command(["git", "checkout", "-B", git_ref, f"origin/{git_ref}"], cwd=clone_dir)
        else:
            if self.verbose:
                self.console.print(f"[dim]Cloning {component_name} repository...[/dim]")
            self._run_command(["git", "clone", "--branch", git_ref, "--depth", "1", repo, str(clone_dir)])

        # Determine build context (subdirectory within repo)
        build_context = component.get("context", ".")
        build_dir = clone_dir / build_context

        if not build_dir.exists():
            raise FileNotFoundError(f"Build context not found: {build_dir}")

        # Detect Containerfile/Dockerfile
        containerfile = component.get("containerfile", "Containerfile")
        containerfile_path = build_dir / containerfile

        if not containerfile_path.exists():
            containerfile = "Dockerfile"
            containerfile_path = build_dir / containerfile
            if not containerfile_path.exists():
                raise FileNotFoundError(f"No Containerfile or Dockerfile found in {build_dir}")

        # Build container - determine image tag
        if "image" in component:
            # Use explicitly specified image name
            image_tag = component["image"]
        else:
            # Generate default image name based on component type
            image_tag = f"mcpgateway-{component_name.lower()}:latest"

        build_cmd = [self.container_runtime, "build", "-f", containerfile, "-t", image_tag]

        if no_cache:
            build_cmd.append("--no-cache")

        # Add target stage if specified (for multi-stage builds)
        if "target" in component:
            build_cmd.extend(["--target", component["target"]])

        build_cmd.append(".")

        self._run_command(build_cmd, cwd=build_dir)

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

    def _verify_kubernetes(self, config: Dict[str, Any], wait: bool = False, timeout: int = 300) -> None:
        """Verify Kubernetes deployment health.

        Uses shared verify_kubernetes() from common.py to avoid code duplication.

        Args:
            config: Parsed configuration dict
            wait: Wait for pods to be ready
            timeout: Wait timeout in seconds
        """
        namespace = config["deployment"].get("namespace", "mcp-gateway")
        output = verify_kubernetes(namespace, wait=wait, timeout=timeout, verbose=self.verbose)
        self.console.print(output)

    def _verify_compose(self, config: Dict[str, Any], wait: bool = False, timeout: int = 300) -> None:
        """Verify Docker Compose deployment health.

        Uses shared verify_compose() from common.py to avoid code duplication.

        Args:
            config: Parsed configuration dict
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

    def _destroy_kubernetes(self, config: Dict[str, Any]) -> None:
        """Destroy Kubernetes deployment.

        Uses shared destroy_kubernetes() from common.py to avoid code duplication.

        Args:
            config: Parsed configuration dict
        """
        _ = config  # Reserved for future use (namespace, labels, etc.)
        # Use the same manifests directory as generate_manifests
        deploy_dir = get_deploy_dir()
        manifests_dir = getattr(self, "_last_output_dir", deploy_dir / "manifests" / "kubernetes")
        destroy_kubernetes(manifests_dir, verbose=self.verbose)

    def _destroy_compose(self, config: Dict[str, Any]) -> None:
        """Destroy Docker Compose deployment.

        Uses shared destroy_compose() from common.py to avoid code duplication.

        Args:
            config: Parsed configuration dict
        """
        _ = config  # Reserved for future use (project name, networks, etc.)
        # Use the same manifests directory as generate_manifests
        deploy_dir = get_deploy_dir()
        output_dir = getattr(self, "_last_output_dir", deploy_dir / "manifests" / "compose")
        compose_file = output_dir / "docker-compose.yaml"
        destroy_compose(compose_file, verbose=self.verbose)
