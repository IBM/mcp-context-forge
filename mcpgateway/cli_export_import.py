# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/cli_export_import.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Export/Import CLI Commands.
This module provides CLI commands for exporting and importing MCP Gateway configuration.
It implements the export/import CLI functionality according to the specification including:
- Complete configuration export with filtering options
- Configuration import with conflict resolution strategies
- Dry-run validation for imports
- Cross-environment key rotation support
- Progress reporting and status tracking
"""

# Standard
import argparse
import asyncio
import base64
from datetime import datetime
import logging
import os
from pathlib import Path
import sys
from typing import Any, Dict, Optional

# Third-Party
import httpx
import orjson

# First-Party
from mcpgateway import __version__
from mcpgateway.config import settings

logger = logging.getLogger(__name__)


class CLIError(Exception):
    """Base class for CLI-related errors."""


class AuthenticationError(CLIError):
    """Raised when authentication fails."""


async def get_auth_token() -> Optional[str]:
    """Get authentication token from environment or config.

    Returns:
        Authentication token string or None if not configured
    """
    # Try environment variable first
    token = os.getenv("MCPGATEWAY_BEARER_TOKEN")
    if token:
        return token

    # Fallback to basic auth if configured
    if settings.basic_auth_user and settings.basic_auth_password:
        creds = base64.b64encode(f"{settings.basic_auth_user}:{settings.basic_auth_password}".encode()).decode()
        return f"Basic {creds}"

    return None


async def make_authenticated_request(method: str, url: str, json_data: Optional[Dict[str, Any]] = None, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Make an authenticated HTTP request to the gateway API.

    Args:
        method: HTTP method (GET, POST, etc.)
        url: URL path for the request
        json_data: Optional JSON data for request body
        params: Optional query parameters

    Returns:
        JSON response from the API

    Raises:
        AuthenticationError: If no authentication is configured
        CLIError: If the API request fails
    """
    token = await get_auth_token()
    if not token:
        raise AuthenticationError("No authentication configured. Set MCPGATEWAY_BEARER_TOKEN environment variable or configure BASIC_AUTH_USER/BASIC_AUTH_PASSWORD.")

    headers = {"Content-Type": "application/json"}
    if token.startswith("Basic "):
        headers["Authorization"] = token
    else:
        headers["Authorization"] = f"Bearer {token}"

    gateway_url = f"http://{settings.host}:{settings.port}"
    full_url = f"{gateway_url}{url}"

    # First-Party
    from mcpgateway.services.http_client_service import get_isolated_http_client  # pylint: disable=import-outside-toplevel

    async with get_isolated_http_client(timeout=300.0, headers=headers, connect_timeout=300.0, write_timeout=300.0, pool_timeout=300.0) as client:
        try:
            response = await client.request(method=method, url=full_url, json=json_data, params=params)
            if response.status_code >= 400:
                error_text = response.text
                raise CLIError(f"API request failed ({response.status_code}): {error_text}")

            return response.json()

        except httpx.HTTPError as e:
            raise CLIError(f"Failed to connect to gateway at {gateway_url}: {str(e)}")


async def export_command(args: argparse.Namespace) -> None:
    """Execute the export command.

    Args:
        args: Parsed command line arguments
    """
    try:
        print(f"Exporting configuration from gateway at http://{settings.host}:{settings.port}")

        # Build API parameters
        params = {}
        if args.types:
            params["types"] = args.types
        if args.exclude_types:
            params["exclude_types"] = args.exclude_types
        if args.tags:
            params["tags"] = args.tags
        if args.include_inactive:
            params["include_inactive"] = "true"
        if not args.include_dependencies:
            params["include_dependencies"] = "false"

        # Make export request
        export_data = await make_authenticated_request("GET", "/export", params=params)

        # Determine output file
        if args.output:
            output_file = Path(args.output)
        else:
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            output_file = Path(f"mcpgateway-export-{timestamp}.json")

        # Write export data
        output_file.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(output_file.write_bytes, orjson.dumps(export_data, option=orjson.OPT_INDENT_2))

        # Print summary
        metadata = export_data.get("metadata", {})
        entity_counts = metadata.get("entity_counts", {})
        total_entities = sum(entity_counts.values())

        print("✅ Export completed successfully!")
        print(f"📁 Output file: {output_file}")
        print(f"📊 Exported {total_entities} total entities:")
        for entity_type, count in entity_counts.items():
            if count > 0:
                print(f"   • {entity_type}: {count}")

        if args.verbose:
            print("\n🔍 Export details:")
            print(f"   • Version: {export_data.get('version')}")
            print(f"   • Exported at: {export_data.get('exported_at')}")
            print(f"   • Exported by: {export_data.get('exported_by')}")
            print(f"   • Source: {export_data.get('source_gateway')}")

    except Exception as e:
        print(f"❌ Export failed: {str(e)}", file=sys.stderr)
        sys.exit(1)


async def import_command(args: argparse.Namespace) -> None:
    """Execute the import command.

    Args:
        args: Parsed command line arguments
    """
    try:
        input_file = Path(args.input_file)
        if not input_file.exists():
            print(f"❌ Input file not found: {input_file}", file=sys.stderr)
            sys.exit(1)

        print(f"Importing configuration from {input_file}")

        # Load import data
        content = await asyncio.to_thread(input_file.read_bytes)
        import_data = orjson.loads(content)

        # Build request data
        request_data = {
            "import_data": import_data,
            "conflict_strategy": args.conflict_strategy,
            "dry_run": args.dry_run,
        }

        if args.rekey_secret:
            request_data["rekey_secret"] = args.rekey_secret

        if args.include:
            # Parse include parameter: "tool:tool1,tool2;server:server1"
            selected_entities = {}
            for selection in args.include.split(";"):
                if ":" in selection:
                    entity_type, entity_list = selection.split(":", 1)
                    entities = [e.strip() for e in entity_list.split(",") if e.strip()]
                    selected_entities[entity_type] = entities
            request_data["selected_entities"] = selected_entities

        # Make import request
        result = await make_authenticated_request("POST", "/import", json_data=request_data)

        # Print results
        status = result.get("status", "unknown")
        progress = result.get("progress", {})

        if args.dry_run:
            print("🔍 Dry-run validation completed!")
        else:
            print(f"✅ Import {status}!")

        print("📊 Results:")
        print(f"   • Total entities: {progress.get('total', 0)}")
        print(f"   • Processed: {progress.get('processed', 0)}")
        print(f"   • Created: {progress.get('created', 0)}")
        print(f"   • Updated: {progress.get('updated', 0)}")
        print(f"   • Skipped: {progress.get('skipped', 0)}")
        print(f"   • Failed: {progress.get('failed', 0)}")

        # Show warnings if any
        warnings = result.get("warnings", [])
        if warnings:
            print(f"\n⚠️  Warnings ({len(warnings)}):")
            for warning in warnings[:5]:  # Show first 5 warnings
                print(f"   • {warning}")
            if len(warnings) > 5:
                print(f"   • ... and {len(warnings) - 5} more warnings")

        # Show errors if any
        errors = result.get("errors", [])
        if errors:
            print(f"\n❌ Errors ({len(errors)}):")
            for error in errors[:5]:  # Show first 5 errors
                print(f"   • {error}")
            if len(errors) > 5:
                print(f"   • ... and {len(errors) - 5} more errors")

        if args.verbose:
            print("\n🔍 Import details:")
            print(f"   • Import ID: {result.get('import_id')}")
            print(f"   • Started at: {result.get('started_at')}")
            print(f"   • Completed at: {result.get('completed_at')}")

        # Exit with error code if there were failures
        if progress.get("failed", 0) > 0:
            sys.exit(1)

    except Exception as e:
        print(f"❌ Import failed: {str(e)}", file=sys.stderr)
        sys.exit(1)


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser for export/import commands.

    Returns:
        Configured argument parser
    """
    parser = argparse.ArgumentParser(prog="mcpgateway", description="MCP Gateway configuration export/import tool")

    parser.add_argument("--version", "-V", action="version", version=f"mcpgateway {__version__}")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Export command
    export_parser = subparsers.add_parser("export", help="Export gateway configuration")
    export_parser.add_argument("--output", "--out", "-o", help="Output file path (default: mcpgateway-export-YYYYMMDD-HHMMSS.json)")
    export_parser.add_argument("--types", "--type", help="Comma-separated entity types to include (tools,gateways,servers,prompts,resources,roots)")
    export_parser.add_argument("--exclude-types", help="Comma-separated entity types to exclude")
    export_parser.add_argument("--tags", help="Comma-separated tags to filter by")
    export_parser.add_argument("--include-inactive", action="store_true", help="Include inactive entities in export")
    export_parser.add_argument("--no-dependencies", action="store_true", help="Don't include dependent entities")
    export_parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    export_parser.set_defaults(func=export_command, include_dependencies=True)

    # Import command
    import_parser = subparsers.add_parser("import", help="Import gateway configuration")
    import_parser.add_argument("input_file", help="Input file containing export data")
    import_parser.add_argument("--conflict-strategy", choices=["skip", "update", "rename", "fail"], default="update", help="How to handle naming conflicts (default: update)")
    import_parser.add_argument("--dry-run", action="store_true", help="Validate but don't make changes")
    import_parser.add_argument("--rekey-secret", help="New encryption secret for cross-environment imports")
    import_parser.add_argument("--include", help="Selective import: entity_type:name1,name2;entity_type2:name3")
    import_parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    import_parser.set_defaults(func=import_command)

    return parser


def main_with_subcommands() -> None:
    """Main CLI entry point with export/import subcommands support."""
    parser = create_parser()

    # Check if we have export/import commands
    if len(sys.argv) > 1 and sys.argv[1] in ["export", "import"]:
        args = parser.parse_args()

        if hasattr(args, "func"):
            # Handle no-dependencies flag
            if hasattr(args, "include_dependencies"):
                args.include_dependencies = not getattr(args, "no_dependencies", False)

            # Run the async command
            try:
                asyncio.run(args.func(args))
            except KeyboardInterrupt:
                print("\n❌ Operation cancelled by user", file=sys.stderr)
                sys.exit(1)
        else:
            parser.print_help()
            sys.exit(1)
    else:
        # Fall back to the original uvicorn-based CLI
        # First-Party
        from mcpgateway.cli import main  # pylint: disable=import-outside-toplevel,cyclic-import

        main()


if __name__ == "__main__":
    main_with_subcommands()
