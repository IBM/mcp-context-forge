# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/cli.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

mcpgateway CLI ─ a thin wrapper around Uvicorn
This module is exposed as a **console-script** via:

    [project.scripts]
    mcpgateway = "mcpgateway.cli:main"

so that a user can simply type `mcpgateway ...` instead of the longer
`uvicorn mcpgateway.main:app ...`.

Features
─────────
* Injects the default FastAPI application path (``mcpgateway.main:app``)
  when the user doesn't supply one explicitly.
* Adds sensible default host/port (127.0.0.1:4444) unless the user passes
  ``--host``/``--port`` or overrides them via the environment variables
  ``MCG_HOST`` and ``MCG_PORT``.
* Forwards *all* remaining arguments verbatim to Uvicorn's own CLI, so
  `--reload`, `--workers`, etc. work exactly the same.

Typical usage
─────────────
```console
$ mcpgateway --reload                 # dev server on 127.0.0.1:4444
$ mcpgateway --workers 4              # production-style multiprocess
$ mcpgateway 127.0.0.1:8000 --reload  # explicit host/port keeps defaults out
$ mcpgateway mypkg.other:app          # run a different ASGI callable
```
"""

# Future
from __future__ import annotations

# Standard
import os
import sys
from typing import List

# Third-Party
import uvicorn

# First-Party
from mcpgateway import __version__

# ---------------------------------------------------------------------------
# Configuration defaults (overridable via environment variables)
# ---------------------------------------------------------------------------
DEFAULT_APP = "mcpgateway.main:app"  # dotted path to FastAPI instance
DEFAULT_HOST = os.getenv("MCG_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.getenv("MCG_PORT", "4444"))

# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------


def _needs_app(arg_list: List[str]) -> bool:
    """Return *True* when the CLI invocation has *no* positional APP path.

    According to Uvicorn's argument grammar, the **first** non-flag token
    is taken as the application path. We therefore look at the first
    element of *arg_list* (if any) - if it *starts* with a dash it must be
    an option, hence the app path is missing and we should inject ours.

    Args:
        arg_list (List[str]): List of arguments

    Returns:
        bool: Returns *True* when the CLI invocation has *no* positional APP path

    Examples:
        >>> _needs_app([])
        True
        >>> _needs_app(["--reload"])
        True
        >>> _needs_app(["myapp.main:app"])
        False
    """

    return len(arg_list) == 0 or arg_list[0].startswith("-")


def _insert_defaults(raw_args: List[str]) -> List[str]:
    """Return a *new* argv with defaults sprinkled in where needed.

    Args:
        raw_args (List[str]): List of input arguments to cli

    Returns:
        List[str]: List of arguments

    Examples:
        >>> result = _insert_defaults([])
        >>> result[0]
        'mcpgateway.main:app'
        >>> result = _insert_defaults(["myapp.main:app", "--reload"])
        >>> result[0]
        'myapp.main:app'
    """

    args = list(raw_args)  # shallow copy - we'll mutate this

    # 1️⃣  Ensure an application path is present.
    if _needs_app(args):
        args.insert(0, DEFAULT_APP)

    # 2️⃣  Supply host/port if neither supplied nor UNIX domain socket.
    if "--uds" not in args:
        if "--host" not in args and "--http" not in args:
            args.extend(["--host", DEFAULT_HOST])
        if "--port" not in args:
            args.extend(["--port", str(DEFAULT_PORT)])

    return args


# ---------------------------------------------------------------------------
# Public entry-point
# ---------------------------------------------------------------------------


def main() -> None:  # noqa: D401 - imperative mood is fine here
    """Entry point for the *mcpgateway* console script (delegates to Uvicorn).

    Processes command line arguments, handles version requests, and forwards
    all other arguments to Uvicorn with sensible defaults injected.

    Also supports export/import subcommands for configuration management.

    Environment Variables:
        MCG_HOST: Default host (default: "127.0.0.1")
        MCG_PORT: Default port (default: "4444")
    """

    # Check for export/import commands first
    if len(sys.argv) > 1 and sys.argv[1] in ["export", "import"]:
        # Avoid cyclic import by importing only when needed
        # First-Party
        from mcpgateway.cli_export_import import main_with_subcommands  # pylint: disable=import-outside-toplevel,cyclic-import

        main_with_subcommands()
        return

    # Check for version flag
    if "--version" in sys.argv or "-V" in sys.argv:
        print(f"mcpgateway {__version__}")
        return

    # Discard the program name and inspect the rest.
    user_args = sys.argv[1:]
    uvicorn_argv = _insert_defaults(user_args)

    # Uvicorn's `main()` uses sys.argv - patch it in and run.
    sys.argv = ["mcpgateway", *uvicorn_argv]
    uvicorn.main()  # pylint: disable=no-value-for-parameter


if __name__ == "__main__":  # pragma: no cover - executed only when run directly
    main()
