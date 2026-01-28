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
from pathlib import Path
import sys
from typing import List, Optional

# Third-Party
import orjson
from pydantic import ValidationError
import uvicorn

# First-Party
from mcpgateway import __version__
from mcpgateway.config import Settings

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


def _handle_validate_config(path: str = ".env") -> None:
    """
    Validate the application's environment configuration file.

    Attempts to load settings from the specified .env file using Pydantic.
    If validation fails, prints the errors and exits with code 1.
    On success, prints a confirmation message.

    Args:
        path (str): Path to the .env file to validate. Defaults to ".env".

    Raises:
        SystemExit: Exits with code 1 if the configuration is invalid.

    Examples:
        >>> _handle_validate_config(".env.example")
        ✅ Configuration in .env.example is valid
    """

    try:
        Settings(_env_file=path)
    except ValidationError as exc:
        print(f"❌ Invalid configuration in {path}", file=sys.stderr)
        print(exc.json(indent=2), file=sys.stderr)
        raise SystemExit(1)

    print(f"✅ Configuration in {path} is valid")


def _handle_config_schema(output: Optional[str] = None) -> None:
    """
    Export the JSON schema for MCP Gateway Settings.

    This function serializes the Pydantic Settings model into a JSON Schema
    suitable for validation or documentation purposes.

    Args:
        output (Optional[str]): Optional file path to write the schema.
            If None, prints to stdout.

    Examples:
        >>> # Print schema to stdout (output truncated for doctest)
        >>> _handle_config_schema()  # doctest: +ELLIPSIS
        {...

        >>> # Write schema to a file (creates 'schema.json'), skip doctest
        >>> _handle_config_schema("schema.json")  # doctest: +SKIP
        ✅ Schema written to schema.json
    """
    schema = Settings.model_json_schema(mode="validation")
    data = orjson.dumps(schema, option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS).decode()

    if output:
        path = Path(output)
        path.write_text(data, encoding="utf-8")
        print(f"✅ Schema written to {path}")
    else:
        print(data)


def _handle_support_bundle(
    output_dir: Optional[str] = None,
    log_lines: int = 1000,
    include_logs: bool = True,
    include_env: bool = True,
    include_system: bool = True,
) -> None:
    """
    Generate a support bundle containing diagnostics and logs.

    Creates a ZIP file with version info, system diagnostics, configuration,
    and logs - all automatically sanitized to remove sensitive data like
    passwords, tokens, and API keys.

    Args:
        output_dir (Optional[str]): Directory for bundle output (default: /tmp)
        log_lines (int): Number of log lines to include (default: 1000, 0 = all)
        include_logs (bool): Include log files (default: True)
        include_env (bool): Include environment config (default: True)
        include_system (bool): Include system info (default: True)

    Raises:
        SystemExit: If bundle generation fails

    Examples:
        >>> # Generate bundle with default settings
        >>> _handle_support_bundle()  # doctest: +SKIP
        ✅ Support bundle created: /tmp/mcpgateway-support-2025-01-09-120000.zip

        >>> # Generate bundle with custom settings
        >>> _handle_support_bundle(output_dir="/tmp", log_lines=500)  # doctest: +SKIP
        ✅ Support bundle created: /tmp/mcpgateway-support-2025-01-09-120000.zip
    """
    # First-Party
    from mcpgateway.services.support_bundle_service import SupportBundleConfig, SupportBundleService  # pylint: disable=import-outside-toplevel

    try:
        config = SupportBundleConfig(
            include_logs=include_logs,
            include_env=include_env,
            include_system_info=include_system,
            log_tail_lines=log_lines,
            output_dir=Path(output_dir) if output_dir else None,
        )

        service = SupportBundleService()
        bundle_path = service.generate_bundle(config)

        print(f"✅ Support bundle created: {bundle_path}")
        print(f"📦 Bundle size: {bundle_path.stat().st_size / 1024:.2f} KB")
        print()
        print("⚠️  Security Notice:")
        print("   The bundle has been sanitized, but please review before sharing.")
        print("   Sensitive data (passwords, tokens, secrets) have been redacted.")
    except Exception as exc:
        print(f"❌ Failed to create support bundle: {exc}", file=sys.stderr)
        raise SystemExit(1)


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

    Usage:
        mcpgateway --reload
        mcpgateway --workers 4
        mcpgateway --validate-config [path]
        mcpgateway --config-schema [output]
        mcpgateway --support-bundle [options]

    Flags:
        --validate-config [path]           Validate .env file (default: .env)
        --config-schema [output]           Print or write JSON schema for Settings
        --support-bundle                   Generate support bundle for troubleshooting
            --output-dir [path]            Output directory (default: /tmp)
            --log-lines [n]                Number of log lines (default: 1000, 0 = all)
            --no-logs                      Exclude log files
            --no-env                       Exclude environment config
            --no-system                    Exclude system info
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

    # Handle config-related flags
    if len(sys.argv) > 1:
        cmd = sys.argv[1]

        if cmd == "--validate-config":
            env_path = sys.argv[2] if len(sys.argv) > 2 else ".env"
            _handle_validate_config(env_path)
            return

        if cmd == "--config-schema":
            output = sys.argv[2] if len(sys.argv) > 2 else None
            _handle_config_schema(output)
            return

        if cmd == "--support-bundle":
            # Parse support bundle options
            output_dir = None
            log_lines = 1000
            include_logs = True
            include_env = True
            include_system = True

            i = 2
            while i < len(sys.argv):
                arg = sys.argv[i]
                if arg == "--output-dir" and i + 1 < len(sys.argv):
                    output_dir = sys.argv[i + 1]
                    i += 2
                elif arg == "--log-lines" and i + 1 < len(sys.argv):
                    log_lines = int(sys.argv[i + 1])
                    i += 2
                elif arg == "--no-logs":
                    include_logs = False
                    i += 1
                elif arg == "--no-env":
                    include_env = False
                    i += 1
                elif arg == "--no-system":
                    include_system = False
                    i += 1
                else:
                    i += 1

            _handle_support_bundle(
                output_dir=output_dir,
                log_lines=log_lines,
                include_logs=include_logs,
                include_env=include_env,
                include_system=include_system,
            )
            return

    # Discard the program name and inspect the rest.
    user_args = sys.argv[1:]
    uvicorn_argv = _insert_defaults(user_args)

    # Uvicorn's `main()` uses sys.argv - patch it in and run.
    sys.argv = ["mcpgateway", *uvicorn_argv]
    uvicorn.main()  # pylint: disable=no-value-for-parameter


if __name__ == "__main__":  # pragma: no cover - executed only when run directly
    main()
