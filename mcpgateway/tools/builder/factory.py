# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/tools/builder/factory.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Factory for creating MCP Stack deployment implementations.

This module provides a factory pattern for creating the appropriate deployment
implementation (Dagger or Plain Python) based on availability and user preference.

The factory handles graceful fallback from Dagger to Python if dependencies are
unavailable, ensuring the deployment system works in various environments.

Example:
    >>> deployer, mode = DeployFactory.create_deployer("dagger", verbose=False)
    ⚠ Dagger not installed. Using plain python.
    >>> # Validate configuration (output varies by config)
    >>> # deployer.validate("mcp-stack.yaml")
"""

# Standard
from enum import Enum

# Third-Party
from rich.console import Console

# First-Party
from mcpgateway.tools.builder.pipeline import CICDModule


class CICDTypes(str, Enum):
    """Deployment implementation types.

    Attributes:
        DAGGER: Dagger-based implementation (optimal performance)
        PYTHON: Plain Python implementation (fallback, no dependencies)

    Examples:
        >>> # Test enum values
        >>> CICDTypes.DAGGER.value
        'dagger'
        >>> CICDTypes.PYTHON.value
        'python'

        >>> # Test enum comparison
        >>> CICDTypes.DAGGER == "dagger"
        True
        >>> CICDTypes.PYTHON == "python"
        True

        >>> # Test enum membership
        >>> "dagger" in [t.value for t in CICDTypes]
        True
        >>> "python" in [t.value for t in CICDTypes]
        True

        >>> # Test enum iteration
        >>> types = list(CICDTypes)
        >>> len(types)
        2
        >>> CICDTypes.DAGGER in types
        True
    """

    DAGGER = "dagger"
    PYTHON = "python"


console = Console()


class DeployFactory:
    """Factory for creating MCP Stack deployment implementations.

    This factory implements the Strategy pattern, allowing dynamic selection
    between Dagger and Python implementations based on availability.
    """

    @staticmethod
    def create_deployer(deployer: str, verbose: bool = False) -> tuple[CICDModule, CICDTypes]:
        """Create a deployment implementation instance.

        Attempts to load the requested deployer type with automatic fallback
        to Python implementation if dependencies are missing.

        Args:
            deployer: Deployment type to create ("dagger" or "python")
            verbose: Enable verbose logging during creation

        Returns:
            tuple: (deployer_instance, actual_type)
                - deployer_instance: Instance of MCPStackDagger or MCPStackPython
                - actual_type: CICDTypes enum indicating which implementation was loaded

        Raises:
            RuntimeError: If no implementation can be loaded (critical failure)

        Example:
            >>> # Try to load Dagger, fall back to Python if unavailable
            >>> deployer, mode = DeployFactory.create_deployer("dagger", verbose=False)
            ⚠ Dagger not installed. Using plain python.
            >>> if mode == CICDTypes.DAGGER:
            ...     print("Using optimized Dagger implementation")
            ... else:
            ...     print("Using fallback Python implementation")
            Using fallback Python implementation
        """
        # Attempt to load Dagger implementation first if requested
        if deployer == "dagger":
            try:
                # First-Party
                from mcpgateway.tools.builder.dagger_deploy import DAGGER_AVAILABLE, MCPStackDagger

                # Check if dagger is actually available (not just the module)
                if not DAGGER_AVAILABLE:
                    raise ImportError("Dagger SDK not installed")

                if verbose:
                    console.print("[green]✓ Dagger module loaded[/green]")

                return (MCPStackDagger(verbose), CICDTypes.DAGGER)

            except ImportError:
                # Dagger dependencies not available, fall back to Python
                console.print("[yellow]⚠ Dagger not installed. Using plain python.[/yellow]")

        # Load plain Python implementation (fallback or explicitly requested)
        try:
            # First-Party
            from mcpgateway.tools.builder.python_deploy import MCPStackPython

            if verbose and deployer != "dagger":
                console.print("[blue]Using plain Python implementation[/blue]")

            return (MCPStackPython(verbose), CICDTypes.PYTHON)

        except ImportError as e:
            # Critical failure - neither implementation can be loaded
            console.print("[red]✗ ERROR: Cannot import deployment modules[/red]")
            console.print(f"[red]  Details: {e}[/red]")
            console.print("[yellow]  Make sure you're running from the project root[/yellow]")
            console.print("[yellow]  and PYTHONPATH is set correctly[/yellow]")

        # This should never be reached if PYTHONPATH is set correctly
        raise RuntimeError(f"Unable to load deployer of type '{deployer}'. ")
