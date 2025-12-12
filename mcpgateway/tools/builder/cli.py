# -*- coding: utf-8 -*-
"""
Location: ./mcpgateway/tools/builder/cli.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

MCP Stack Deployment Tool - Hybrid Dagger/Python Implementation

This script can run in two modes:
1. Plain Python mode (default) - No external dependencies
2. Dagger mode (opt-in) - Requires dagger-io package, auto-downloads CLI

Usage:
    # Local execution (plain Python mode)
    cforge deploy deploy.yaml

    # Use Dagger mode for optimization (requires dagger-io, auto-downloads CLI)
    cforge --dagger deploy deploy.yaml

    # Inside container
    docker run -v $PWD:/workspace mcpgateway/mcp-builder:latest deploy deploy.yaml

Features:
    - Validates deploy.yaml configuration
    - Builds plugin containers from git repos
    - Generates mTLS certificates
    - Deploys to Kubernetes or Docker Compose
    - Integrates with CI/CD vault secrets

Examples:
    >>> # Test that IN_CONTAINER detection works
    >>> import os
    >>> isinstance(IN_CONTAINER, bool)
    True

    >>> # Test that BUILDER_DIR is a Path
    >>> from pathlib import Path
    >>> isinstance(BUILDER_DIR, Path)
    True

    >>> # Test IMPL_MODE is set
    >>> isinstance(IMPL_MODE, str)
    True
"""

# Standard
import asyncio
import os
from pathlib import Path
import sys
from typing import Optional

# Third-Party
from rich.console import Console
from rich.panel import Panel
import typer
from typing_extensions import Annotated

# First-Party
from mcpgateway.tools.builder.factory import DeployFactory

app = typer.Typer(
    help="Command line tools for deploying the gateway and plugins via a config file.",
)

console = Console()

deployer = None

IN_CONTAINER = os.path.exists("/.dockerenv") or os.environ.get("CONTAINER") == "true"
BUILDER_DIR = Path(__file__).parent / "builder"
IMPL_MODE = "plain"


@app.callback()
def cli(
    ctx: typer.Context,
    dagger: Annotated[bool, typer.Option("--dagger", help="Use Dagger mode (requires dagger-io package)")] = False,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Verbose output")] = False,
):
    """MCP Stack deployment tool

    Deploys MCP Gateway + external plugins from a single YAML configuration.

    By default, uses plain Python mode. Use --dagger to enable Dagger optimization.

    Args:
        ctx: Typer context object
        dagger: Enable Dagger mode (requires dagger-io package and auto-downloads CLI)
        verbose: Enable verbose output
    """
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose
    ctx.obj["dagger"] = dagger

    if ctx.invoked_subcommand != "version":
        # Show execution mode - default to Python, opt-in to Dagger
        mode = "dagger" if dagger else "python"
        ctx.obj["deployer"], ctx.obj["mode"] = DeployFactory.create_deployer(mode, verbose)
        mode_color = "green" if ctx.obj["mode"] == "dagger" else "yellow"
        env_text = "container" if IN_CONTAINER else "local"

        if verbose:
            console.print(Panel(f"[bold]Mode:[/bold] [{mode_color}]{ctx.obj['mode']}[/{mode_color}]\n" f"[bold]Environment:[/bold] {env_text}\n", title="MCP Deploy", border_style=mode_color))


@app.command()
def validate(ctx: typer.Context, config_file: Annotated[Path, typer.Argument(help="The deployment configuration file.")]):
    """Validate mcp-stack.yaml configuration

    Args:
        ctx: Typer context object
        config_file: Path to the deployment configuration file
    """
    impl = ctx.obj["deployer"]

    try:
        impl.validate(config_file)
        console.print("[green]✓ Configuration valid[/green]")
    except Exception as e:
        console.print(f"[red]✗ Validation failed: {e}[/red]")
        sys.exit(1)


@app.command()
def build(
    ctx: typer.Context,
    config_file: Annotated[Path, typer.Argument(help="The deployment configuration file")],
    plugins_only: Annotated[bool, typer.Option("--plugins-only", help="Only build plugin containers")] = False,
    plugin: Annotated[Optional[list[str]], typer.Option("--plugin", "-p", help="Build specific plugin(s)")] = None,
    no_cache: Annotated[bool, typer.Option("--no-cache", help="Disable build cache")] = False,
    copy_env_templates: Annotated[bool, typer.Option("--copy-env-templates", help="Copy .env.template files from plugin repos")] = True,
):
    """Build containers

    Args:
        ctx: Typer context object
        config_file: Path to the deployment configuration file
        plugins_only: Only build plugin containers, skip gateway
        plugin: List of specific plugin names to build
        no_cache: Disable build cache
        copy_env_templates: Copy .env.template files from plugin repos
    """
    impl = ctx.obj["deployer"]

    try:
        asyncio.run(impl.build(config_file, plugins_only=plugins_only, specific_plugins=list(plugin) if plugin else None, no_cache=no_cache, copy_env_templates=copy_env_templates))
        console.print("[green]✓ Build complete[/green]")

        if copy_env_templates:
            console.print("[yellow]⚠ IMPORTANT: Review .env files in deploy/env/ before deploying![/yellow]")
            console.print("[yellow]   Update any required configuration values.[/yellow]")
    except Exception as e:
        console.print(f"[red]✗ Build failed: {e}[/red]")
        sys.exit(1)


@app.command()
def certs(ctx: typer.Context, config_file: Annotated[Path, typer.Argument(help="The deployment configuration file")]):
    """Generate mTLS certificates

    Args:
        ctx: Typer context object
        config_file: Path to the deployment configuration file
    """
    impl = ctx.obj["deployer"]

    try:
        asyncio.run(impl.generate_certificates(config_file))
        console.print("[green]✓ Certificates generated[/green]")
    except Exception as e:
        console.print(f"[red]✗ Certificate generation failed: {e}[/red]")
        sys.exit(1)


@app.command()
def deploy(
    ctx: typer.Context,
    config_file: Annotated[Path, typer.Argument(help="The deployment configuration file")],
    output_dir: Annotated[Optional[Path], typer.Option("--output-dir", "-o", help="The deployment configuration file")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Generate manifests without deploying")] = False,
    skip_build: Annotated[bool, typer.Option("--skip-build", help="Skip building containers")] = False,
    skip_certs: Annotated[bool, typer.Option("--skip-certs", help="Skip certificate generation")] = False,
):
    """Deploy MCP stack

    Args:
        ctx: Typer context object
        config_file: Path to the deployment configuration file
        output_dir: Custom output directory for manifests
        dry_run: Generate manifests without deploying
        skip_build: Skip building containers
        skip_certs: Skip certificate generation
    """
    impl = ctx.obj["deployer"]

    try:
        asyncio.run(impl.deploy(config_file, dry_run=dry_run, skip_build=skip_build, skip_certs=skip_certs, output_dir=output_dir))
        if dry_run:
            console.print("[yellow]✓ Dry-run complete (no changes made)[/yellow]")
        else:
            console.print("[green]✓ Deployment complete[/green]")
    except Exception as e:
        console.print(f"[red]✗ Deployment failed: {e}[/red]")
        sys.exit(1)


@app.command()
def verify(
    ctx: typer.Context,
    config_file: Annotated[Path, typer.Argument(help="The deployment configuration file")],
    wait: Annotated[bool, typer.Option("--wait", help="Wait for deployment to be ready")] = True,
    timeout: Annotated[int, typer.Option("--timeout", help="Wait timeout in seconds")] = 300,
):
    """Verify deployment health

    Args:
        ctx: Typer context object
        config_file: Path to the deployment configuration file
        wait: Wait for deployment to be ready
        timeout: Wait timeout in seconds
    """
    impl = ctx.obj["deployer"]

    try:
        asyncio.run(impl.verify(config_file, wait=wait, timeout=timeout))
        console.print("[green]✓ Deployment healthy[/green]")
    except Exception as e:
        console.print(f"[red]✗ Verification failed: {e}[/red]")
        sys.exit(1)


@app.command()
def destroy(
    ctx: typer.Context,
    config_file: Annotated[Path, typer.Argument(help="The deployment configuration file")],
    force: Annotated[bool, typer.Option("--force", help="Force destruction without confirmation")] = False,
):
    """Destroy deployed MCP stack

    Args:
        ctx: Typer context object
        config_file: Path to the deployment configuration file
        force: Force destruction without confirmation
    """
    impl = ctx.obj["deployer"]

    if not force:
        if not typer.confirm("Are you sure you want to destroy the deployment?"):
            console.print("[yellow]Aborted[/yellow]")
            return

    try:
        asyncio.run(impl.destroy(config_file))
        console.print("[green]✓ Deployment destroyed[/green]")
    except Exception as e:
        console.print(f"[red]✗ Destruction failed: {e}[/red]")
        sys.exit(1)


@app.command()
def version():
    """Show version information

    Examples:
        >>> # Test that version function exists
        >>> callable(version)
        True

        >>> # Test that it accesses module constants
        >>> IMPL_MODE in ['plain', 'dagger']
        True
    """
    console.print(
        Panel(f"[bold]MCP Deploy[/bold]\n" f"Version: 1.0.0\n" f"Mode: {IMPL_MODE}\n" f"Environment: {'container' if IN_CONTAINER else 'local'}\n", title="Version Info", border_style="blue")
    )


@app.command()
def generate(
    ctx: typer.Context,
    config_file: Annotated[Path, typer.Argument(help="The deployment configuration file")],
    output: Annotated[Optional[Path], typer.Option("--output", "-o", help="Output directory for manifests")] = None,
):
    """Generate deployment manifests (k8s or compose)

    Args:
        ctx: Typer context object
        config_file: Path to the deployment configuration file
        output: Output directory for manifests
    """
    impl = ctx.obj["deployer"]

    try:
        manifests_dir = impl.generate_manifests(config_file, output_dir=output)
        console.print(f"[green]✓ Manifests generated: {manifests_dir}[/green]")
    except Exception as e:
        console.print(f"[red]✗ Manifest generation failed: {e}[/red]")
        sys.exit(1)


def main():
    """Main entry point

    Raises:
        Exception: Any unhandled exception from subcommands (re-raised in debug mode)

    Examples:
        >>> # Test that main function exists and is callable
        >>> callable(main)
        True

        >>> # Test that app is a Typer instance
        >>> import typer
        >>> isinstance(app, typer.Typer)
        True

        >>> # Test that console is available
        >>> from rich.console import Console
        >>> isinstance(console, Console)
        True
    """
    try:
        app(obj={})
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user[/yellow]")
        sys.exit(130)
    except Exception as e:
        console.print(f"[red]Fatal error: {e}[/red]")
        if os.environ.get("MCP_DEBUG"):
            raise
        sys.exit(1)


if __name__ == "__main__":
    main()
