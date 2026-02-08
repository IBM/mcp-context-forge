# -*- coding: utf-8 -*-
"""Main CLI for REST API data population.

Usage:
    python -m tests.populate --profile small
    python -m tests.populate --profile medium --dry-run
    python -m tests.populate --profile large --base-url http://localhost:8080
"""

# Standard
import argparse
import asyncio
import json
import logging
import os
from pathlib import Path
import sys
import time
from typing import Any, Dict

# Third-Party
from faker import Faker
from rich.console import Console
from rich.panel import Panel
import yaml

# Local
from .api_client import APIClient
from .populators import (
    A2AAgentPopulator,
    GatewayPopulator,
    PromptPopulator,
    RBACPopulator,
    ResourcePopulator,
    ServerPopulator,
    TeamPopulator,
    TokenPopulator,
    ToolPopulator,
    UserPopulator,
)
from .utils.progress import MultiProgressTracker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Populator registry: name -> class
POPULATORS = {
    "users": UserPopulator,
    "teams": TeamPopulator,
    "rbac": RBACPopulator,
    "gateways": GatewayPopulator,
    "tools": ToolPopulator,
    "resources": ResourcePopulator,
    "prompts": PromptPopulator,
    "servers": ServerPopulator,
    "a2a_agents": A2AAgentPopulator,
    "tokens": TokenPopulator,
}


def load_config(profile: str) -> Dict[str, Any]:
    """Load YAML configuration for a profile."""
    config_dir = Path(__file__).parent / "configs"
    config_path = config_dir / f"{profile}.yaml"

    if not config_path.exists():
        raise FileNotFoundError(f"Profile config not found: {config_path}")

    with open(config_path) as f:
        return yaml.safe_load(f)


def generate_admin_token() -> str:
    """Generate an admin JWT token for bootstrapping.

    Uses the same utility as the gateway to ensure token compatibility.
    """
    try:
        # First-Party
        from mcpgateway.utils.create_jwt_token import _create_jwt_token

        token = _create_jwt_token(
            data={"sub": "admin@example.com", "username": "admin@example.com"},
            expires_in_minutes=10080,  # 7 days
            user_data={"email": "admin@example.com", "full_name": "Admin", "is_admin": True},
            teams=None,  # null teams + is_admin = admin bypass
        )
        return token
    except ImportError:
        # Fallback: use env var
        token = os.environ.get("MCPGATEWAY_BEARER_TOKEN", "")
        if not token:
            raise RuntimeError("Cannot generate admin token. Either:\n" "  1. Run from the project root with mcpgateway installed, or\n" "  2. Set MCPGATEWAY_BEARER_TOKEN environment variable")
        return token


async def run_population(config: Dict[str, Any], base_url: str, dry_run: bool = False) -> Dict[str, Any]:
    """Run the full population pipeline."""
    console = Console()
    profile_name = config.get("profile", {}).get("name", "unknown")

    # Setup
    faker_seed = config.get("global", {}).get("random_seed", 42)
    faker = Faker()
    Faker.seed(faker_seed)

    # Generate admin token
    admin_token = os.environ.get("MCPGATEWAY_BEARER_TOKEN") or generate_admin_token()

    # Create API client
    concurrency_cfg = config.get("concurrency", {})
    client = APIClient(
        base_url=base_url,
        admin_token=admin_token,
        max_connections=concurrency_cfg.get("max_connections", 100),
        max_concurrent=concurrency_cfg.get("max_concurrent", 50),
        max_retries=concurrency_cfg.get("max_retries", 3),
        retry_base_delay=concurrency_cfg.get("retry_base_delay", 1.0),
        timeout=concurrency_cfg.get("timeout", 30.0),
    )

    # Shared data store for cross-populator references
    existing_data: Dict[str, Any] = {}

    # Get population order from config
    pop_order = config.get("population_order", list(POPULATORS.keys()))

    # Initialize progress tracker
    tracker = MultiProgressTracker(console=console)

    # Create populator instances
    populator_instances = {}
    for name in pop_order:
        if name not in POPULATORS:
            logger.warning(f"Unknown populator: {name}, skipping")
            continue

        cls = POPULATORS[name]
        instance = cls(
            client=client,
            config=config,
            faker=faker,
            existing_data=existing_data,
            progress_tracker=tracker,
            dry_run=dry_run,
        )
        populator_instances[name] = instance
        tracker.add_task(name, instance.get_count(), name)

    # Print plan
    console.print(
        Panel(
            f"[bold]Profile:[/bold] {profile_name}\n"
            f"[bold]Target:[/bold] {base_url}\n"
            f"[bold]Dry Run:[/bold] {dry_run}\n"
            f"[bold]Populators:[/bold] {len(populator_instances)}\n"
            f"[bold]Total Entities:[/bold] {tracker.total_records:,}",
            title=f"[bold cyan]REST API Population - {profile_name}[/bold cyan]",
            border_style="cyan",
        )
    )

    if dry_run:
        console.print("\n[yellow]DRY RUN - No requests will be sent[/yellow]\n")

    # Run populators in dependency order
    results: Dict[str, Any] = {}
    start_time = time.time()

    with tracker.live_display():
        for name in pop_order:
            if name not in populator_instances:
                continue

            instance = populator_instances[name]
            try:
                result = await instance.run()
                results[name] = result
            except Exception as exc:
                logger.error(f"Populator {name} failed: {exc}", exc_info=True)
                results[name] = {"created": 0, "errors": 1, "exception": str(exc)}

        # Pass actual results so the final summary shows correct numbers
        tracker.set_results(results)

    total_duration = time.time() - start_time

    # Close client
    await client.close()

    # Build report
    total_created = sum(r.get("created", 0) for r in results.values())
    total_errors = sum(r.get("errors", 0) for r in results.values())

    report = {
        "profile": profile_name,
        "base_url": base_url,
        "dry_run": dry_run,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "duration_seconds": round(total_duration, 2),
        "total_created": total_created,
        "total_errors": total_errors,
        "requests_per_second": round(total_created / total_duration, 2) if total_duration > 0 else 0,
        "client_stats": client.get_stats(),
        "populators": {name: {k: v for k, v in r.items() if k != "ids"} for name, r in results.items()},
    }

    # Save report
    report_path = config.get("reporting", {}).get("output_file") or config.get("global", {}).get("output_report")
    if report_path:
        report_file = Path(report_path)
        report_file.parent.mkdir(parents=True, exist_ok=True)
        with open(report_file, "w") as f:
            json.dump(report, f, indent=2, default=str)
        console.print(f"\n[dim]Report saved to: {report_file}[/dim]")

    # Print summary
    console.print(
        Panel(
            (
                f"[bold]Profile:[/bold] {profile_name}\n"
                f"[bold]Duration:[/bold] {total_duration:.2f}s\n"
                f"[bold]Created:[/bold] [green]{total_created:,}[/green]\n"
                f"[bold]Errors:[/bold] [red]{total_errors:,}[/red]\n"
                f"[bold]Rate:[/bold] [cyan]{total_created / total_duration:,.0f} req/s[/cyan]"
                if total_duration > 0
                else ""
            ),
            title="[bold green]Population Complete[/bold green]",
            border_style="green",
        )
    )

    return report


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Populate MCP Gateway with test data via REST API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m tests.populate --profile small
  python -m tests.populate --profile medium --base-url http://gateway:4444
  python -m tests.populate --profile small --dry-run
  python -m tests.populate --profile large --base-url http://localhost:8080
        """,
    )

    parser.add_argument(
        "--profile",
        type=str,
        choices=["small", "medium", "large"],
        default="small",
        help="Population profile (default: small)",
    )
    parser.add_argument(
        "--config",
        type=str,
        help="Custom config YAML path (overrides --profile)",
    )
    parser.add_argument(
        "--base-url",
        type=str,
        default=os.environ.get("MCPGATEWAY_BASE_URL", "http://localhost:8080"),
        help="Gateway base URL (default: http://localhost:8080)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would be created without making requests",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default=None,
        help="Override log level",
    )

    args = parser.parse_args()

    # Load config
    if args.config:
        with open(args.config) as f:
            config = yaml.safe_load(f)
    else:
        config = load_config(args.profile)

    # Set log level
    log_level = args.log_level or config.get("global", {}).get("log_level", "INFO")
    logging.getLogger().setLevel(getattr(logging, log_level))

    # Run
    try:
        report = asyncio.run(run_population(config, args.base_url, dry_run=args.dry_run))
        sys.exit(0 if report.get("total_errors", 0) == 0 else 1)
    except KeyboardInterrupt:
        print("\nInterrupted by user")
        sys.exit(130)
    except Exception as exc:
        logger.error(f"Population failed: {exc}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
