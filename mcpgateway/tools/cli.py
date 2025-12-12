# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/tools/cli.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

cforge CLI ─ command line tools for building and deploying the
MCP Gateway and its plugins.

This module is exposed as a **console-script** via:

    [project.scripts]
    cforge = "mcpgateway.tools.cli:main"

so that a user can simply type `cforge ...` to use the CLI.

Features
─────────
* plugin:
    - bootstrap: Creates a new plugin project from template                                                           │
    - install: Installs plugins into a Python environment                                                           │
    - package: Builds an MCP server to serve plugins as tools
* gateway:
    - Validates deploy.yaml configuration
    - Builds plugin containers from git repos
    - Generates mTLS certificates
    - Deploys to Kubernetes or Docker Compose
    - Integrates with CI/CD vault secrets


Typical usage
─────────────
```console
$ cforge --help
```
"""

# Third-Party
import typer

# First-Party
import mcpgateway.plugins.tools.cli as plugins
import mcpgateway.tools.builder.cli as builder

app = typer.Typer(help="Command line tools for building, deploying, and interacting with the ContextForge MCP Gateway")

app.add_typer(plugins.app, name="plugin", help="Manage the plugin lifecycle")
app.add_typer(builder.app, name="gateway", help="Manage the building and deployment of the gateway")


def main() -> None:  # noqa: D401 - imperative mood is fine here
    """Entry point for the *cforge* console script."""
    app(obj={})


if __name__ == "__main__":
    main()
