# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/tools/cli.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Fred Araujo

mcpplugins CLI ─ command line tools for authoring and packaging plugins
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
import logging
from pathlib import Path
import shutil
import subprocess  # nosec B404 # Safe: Used only for git commands with hardcoded args
from typing import Optional

# Third-Party
import typer
from typing_extensions import Annotated

# First-Party
from mcpgateway.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration defaults
# ---------------------------------------------------------------------------
DEFAULT_TEMPLATE_URL = "https://github.com/IBM/mcp-context-forge.git"
DEFAULT_AUTHOR_NAME = "<changeme>"
DEFAULT_AUTHOR_EMAIL = "<changeme>"
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
# Utility functions
# ---------------------------------------------------------------------------


def command_exists(command_name: str) -> bool:
    """Check if a given command-line utility exists and is executable.

    Args:
        command_name: The name of the command to check (e.g., "ls", "git").

    Returns:
        True if the command exists and is executable, False otherwise.
    """
    return shutil.which(command_name) is not None


def git_user_name() -> str:
    """Return the current git user name from the environment.

    Returns:
        The git user name configured in the user's environment.

    Examples:
        >>> user_name = git_user_name()
        >>> isinstance(user_name, str)
        True
    """
    try:
        res = subprocess.run(["git", "config", "user.name"], stdout=subprocess.PIPE, check=False)  # nosec B607 B603 # Safe: hardcoded git command
        return res.stdout.strip().decode() if not res.returncode else DEFAULT_AUTHOR_NAME
    except Exception:
        return DEFAULT_AUTHOR_NAME


def git_user_email() -> str:
    """Return the current git user email from the environment.

    Returns:
        The git user email configured in the user's environment.

    Examples:
        >>> user_name = git_user_email()
        >>> isinstance(user_name, str)
        True
    """
    try:
        res = subprocess.run(["git", "config", "user.email"], stdout=subprocess.PIPE, check=False)  # nosec B607 B603 # Safe: hardcoded git command
        return res.stdout.strip().decode() if not res.returncode else DEFAULT_AUTHOR_EMAIL
    except Exception:
        return DEFAULT_AUTHOR_EMAIL


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
@app.command(help="Creates a new plugin project from template.")
def bootstrap(
    destination: Annotated[Path, typer.Option("--destination", "-d", help="The directory in which to bootstrap the plugin project.")] = DEFAULT_PROJECT_DIR,
    template_url: Annotated[str, typer.Option("--template_url", "-u", help="The URL to the plugins copier template.")] = DEFAULT_TEMPLATE_URL,
    vcs_ref: Annotated[str, typer.Option("--vcs_ref", "-r", help="The version control system tag/branch/commit to use for the template.")] = DEFAULT_VCS_REF,
    answers_file: Optional[Annotated[typer.FileText, typer.Option("--answers_file", "-a", help="The answers file to be used for bootstrapping.")]] = None,
    defaults: Annotated[bool, typer.Option("--defaults", help="Bootstrap with defaults.")] = False,
    dry_run: Annotated[bool, typer.Option("--dry_run", help="Run but do not make any changes.")] = False,
) -> None:
    """Boostrap a new plugin project from a template.

    Args:
        destination: The directory in which to bootstrap the plugin project.
        template_url: The URL to the plugins copier template.
        vcs_ref: The version control system tag/branch/commit to use for the template.
        answers_file: The copier answers file that can be used to skip interactive mode.
        defaults: Bootstrap with defaults.
        dry_run: Run but do not make any changes.

    Raises:
        Exit: If copier is not installed.
    """
    try:
        # Third-Party
        from copier import run_copy  # pylint: disable=import-outside-toplevel
    except ImportError:
        logger.error("copier is not installed. Install with: pip install mcp-contextforge-gateway[templating]")
        raise typer.Exit(1)

    try:
        if command_exists("git"):
            run_copy(
                src_path=template_url,
                dst_path=destination,
                answers_file=answers_file,
                defaults=defaults,
                vcs_ref=vcs_ref,
                data={"default_author_name": git_user_name(), "default_author_email": git_user_email()},
                pretend=dry_run,
            )
        else:
            logger.warning("A git client was not found in the environment to copy remote template.")
    except Exception:
        logger.exception("An error was caught while copying template.")


@app.callback()
def callback() -> None:  # pragma: no cover
    """This function exists to force 'bootstrap' to be a subcommand."""


# @app.command(help="Installs plugins into a Python environment.")
# def install(
#     install_manifest: Annotated[typer.FileText, typer.Option("--install_manifest", "-i", help="The install manifest describing which plugins to install.")] = DEFAULT_INSTALL_MANIFEST,
#     installer: Annotated[str, typer.Option("--installer", "-c", help="The install command to install plugins.")] = DEFAULT_INSTALLER,
# ):
#     typer.echo(f"Installing plugin packages from {install_manifest.name}")
#     data = yaml.safe_load(install_manifest)
#     manifest = InstallManifest.model_validate(data)
#     for pkg in manifest.packages:
#         typer.echo(f"Installing plugin package {pkg.package} from {pkg.repository}")
#         repository = os.path.expandvars(pkg.repository)
#         cmd = installer.split(" ")
#         if pkg.extras:
#             cmd.append(f"{pkg.package}[{','.join(pkg.extras)}]@{repository}")
#         else:
#             cmd.append(f"{pkg.package}@{repository}")
#         subprocess.run(cmd)


# @app.command(help="Builds an MCP server to serve plugins as tools.")
# def package(
#     image_tag: Annotated[str, typer.Option("--image_tag", "-t", help="The container image tag to generated container.")] = DEFAULT_IMAGE_TAG,
#     containerfile: Annotated[Path, typer.Option("--containerfile", "-c", help="The Dockerfile used to build the container.")] = DEFAULT_CONTAINERFILE_PATH,
#     builder: Annotated[str, typer.Option("--builder", "-b", help="The container builder, compatible with docker build.")] = DEFAULT_IMAGE_BUILDER,
#     build_context: Annotated[Path, typer.Option("--build_context", "-p", help="The container builder context, specified as a path.")] = DEFAULT_BUILD_CONTEXT,
# ):
#     typer.echo("Building MCP server image")
#     cmd = builder.split(" ")
#     cmd.extend(["-f", containerfile, "-t", image_tag, build_context])
#     subprocess.run(cmd)


def main() -> None:  # noqa: D401 - imperative mood is fine here
    """Entry point for the *mcpplugins* console script.

    Processes command line arguments, handles version requests, and forwards
    all other arguments to Uvicorn with sensible defaults injected.

    Environment Variables:
        PLUGINS_CLI_COMPLETION: Enable auto-completion for plugins CLI (default: false)
        PLUGINS_CLI_MARKUP_MODE: Set markup mode for plugins CLI (default: rich)
            Valid options:
                rich: use rich markup
                markdown: allow markdown in help strings
                disabled: disable markup
            If unset (commented out), uses "rich" if rich is detected, otherwise disables it.
    """
    app()


if __name__ == "__main__":  # pragma: no cover - executed only when run directly
    main()
