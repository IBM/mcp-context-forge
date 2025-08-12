# -*- coding: utf-8 -*-
"""mcpplugins CLI ─ command line tools for authoring and packaging plugins

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Fred Araujo

This module is exposed as a **console-script** via:

    [project.scripts]
    mcpplugins = "mcpgateway.plugins.tools.cli:main"

so that a user can simply type `mcpplugins ...` to use the CLI.

Features
─────────
* bootstrap: Creates a new plugin project from template                                                           │
* install: Installs plugins into a Python environment                                                           │
* package: Builds an MCP server to serve plugins as tools

Typical usage
─────────────
```console
$ mcpplugins --help
```
"""

# Standard
from pathlib import Path
from typing import Optional

# Third-Party
from copier import Worker
import typer
from typing_extensions import Annotated

# First-Party
from mcpgateway.config import settings

# ---------------------------------------------------------------------------
# Configuration defaults
# ---------------------------------------------------------------------------
DEFAULT_TEMPLATE_URL = "https://github.com/IBM/mcp-context-forge-plugins-template.git"
DEFAULT_PROJECT_DIR = Path("./.")
DEFAULT_INSTALL_MANIFEST = Path("plugins/install.yaml")
DEFAULT_IMAGE_TAG = "contextforge-plugin:latest"  # TBD: add plugin name and version
DEFAULT_IMAGE_BUILDER = "docker"
DEFAULT_CONTAINERFILE_PATH = Path("docker/Dockerfile")
DEFAULT_VCS_REF = "main"

# ---------------------------------------------------------------------------
# CLI (overridable via environment variables)
# ---------------------------------------------------------------------------

markup_mode = settings.plugins_cli_markup_mode or typer.core.DEFAULT_MARKUP_MODE
app = typer.Typer(
    help="Command line tools for authoring and packaging plugins.",
    add_completion=settings.plugins_cli_completion,
    rich_markup_mode=None if markup_mode == "disabled" else markup_mode,
)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
@app.command(help="Creates a new plugin project from template.")
def bootstrap(
    destination: Annotated[Path, typer.Option("--destination", "-d", help="The directory in which to bootstrap the plugin project.")] = DEFAULT_PROJECT_DIR,
    template_url: Annotated[str, typer.Option("--template_url", "-u", help="The URL to the plugins copier template.")] = DEFAULT_TEMPLATE_URL,
    vcs_ref: Annotated[str, typer.Option("--vcs_ref", "-r", help="The version control system tag/branch/commit to use for the template.")] = DEFAULT_VCS_REF,
    answers_file: Optional[Annotated[typer.FileText, typer.Option("--answers_file", "-a", help="The answers file to be used for bootstrapping.")]] = None,
    defaults: Annotated[str, typer.Option("--vcs_ref", "-r", help="Bootstrap with defaults.")] = False,
):
    print("Boostrapping a plugin project from template.")
    with Worker(
        src_path=template_url,
        dst_path=destination,
        answers_file=answers_file,
        defaults=defaults,
        vcs_ref=vcs_ref,
    ) as worker:
        worker.run_copy()


@app.command(help="Installs plugins into a Python environment.")
def install(
    install_manifest: Annotated[typer.FileText, typer.Option("--install_manifest", "-i", help="The install manifest describing which plugins to install.")] = DEFAULT_INSTALL_MANIFEST,
):
    print("Installing plugins")


@app.command(help="Builds an MCP server to serve plugins as tools")
def package(
    install_manifest: Annotated[typer.FileText, typer.Option("--install_manifest", "-i", help="The install manifest describing which plugins to install.")] = DEFAULT_INSTALL_MANIFEST,
    image_tag: Annotated[str, typer.Option("--image_tag", "-t", help="The container image tag to generated container.")] = DEFAULT_IMAGE_TAG,
    containerfile: Annotated[Path, typer.Option("--containerfile", "-c", help="The Dockerfile used to build the container.")] = DEFAULT_CONTAINERFILE_PATH,
    builder: Annotated[str, typer.Option("--builder", "-b", help="The container builder, compatible with docker build.")] = DEFAULT_IMAGE_BUILDER,
):
    print("Deleting user: Hiro Hamada")


def main() -> None:  # noqa: D401 - imperative mood is fine here
    app()


if __name__ == "__main__":
    app()
