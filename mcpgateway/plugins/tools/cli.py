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
import os
from pathlib import Path
import subprocess
from typing import Optional

# Third-Party
from copier import Worker
import typer
from typing_extensions import Annotated
import yaml

# First-Party
from mcpgateway.config import settings
from mcpgateway.plugins.tools.models import InstallManifest

# ---------------------------------------------------------------------------
# Configuration defaults
# ---------------------------------------------------------------------------
DEFAULT_TEMPLATE_BASE_URL = "https://github.com/IBM/mcp-context-forge.git"
DEFAULT_TEMPLATE_TYPE = "external"
DEFAULT_TEMPLATE_URL = f"{DEFAULT_TEMPLATE_BASE_URL}::plugin_templates/{DEFAULT_TEMPLATE_TYPE}"
DEFAULT_PROJECT_DIR = Path("./.")
DEFAULT_INSTALL_MANIFEST = Path("plugins/install.yaml")
DEFAULT_IMAGE_TAG = "contextforge-plugin:latest"  # TBD: add plugin name and version
DEFAULT_IMAGE_BUILDER = "docker"
DEFAULT_BUILD_CONTEXT = "."
DEFAULT_CONTAINERFILE_PATH = Path("docker/Dockerfile")
DEFAULT_VCS_REF = "main"
DEFAULT_INSTALLER = "uv pip install"

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
    installer: Annotated[str, typer.Option("--installer", "-c", help="The install command to install plugins.")] = DEFAULT_INSTALLER,
):
    typer.echo(f"Installing plugin packages from {install_manifest.name}")
    data = yaml.safe_load(install_manifest)
    manifest = InstallManifest.model_validate(data)
    for pkg in manifest.packages:
        typer.echo(f"Installing plugin package {pkg.package} from {pkg.repository}")
        repository = os.path.expandvars(pkg.repository)
        cmd = installer.split(" ")
        if pkg.extras:
            cmd.append(f"{pkg.package}[{','.join(pkg.extras)}]@{repository}")
        else:
            cmd.append(f"{pkg.package}@{repository}")
        subprocess.run(cmd)


@app.command(help="Builds an MCP server to serve plugins as tools")
def package(
    image_tag: Annotated[str, typer.Option("--image_tag", "-t", help="The container image tag to generated container.")] = DEFAULT_IMAGE_TAG,
    containerfile: Annotated[Path, typer.Option("--containerfile", "-c", help="The Dockerfile used to build the container.")] = DEFAULT_CONTAINERFILE_PATH,
    builder: Annotated[str, typer.Option("--builder", "-b", help="The container builder, compatible with docker build.")] = DEFAULT_IMAGE_BUILDER,
    build_context: Annotated[Path, typer.Option("--build_context", "-p", help="The container builder context, specified as a path.")] = DEFAULT_BUILD_CONTEXT,
):
    typer.echo("Building MCP server image")
    cmd = builder.split(" ")
    cmd.extend(["-f", containerfile, "-t", image_tag, build_context])
    subprocess.run(cmd)


def main() -> None:  # noqa: D401 - imperative mood is fine here
    app()


if __name__ == "__main__":  # pragma: no cover - executed only when run directly
    main()
